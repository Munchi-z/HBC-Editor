"""
HBCE License Portal — Layer 1
portal/app.py — Flask application entry point

Layer 1: Simple Flask + SQLite key issuance and activation.
Deploy on a $5/mo VPS (DigitalOcean, Linode, etc.).
Run: python app.py   (development)
     gunicorn -w 1 app:app   (production — single worker for SQLite safety)

GOTCHA-010: SQLite is NOT safe for concurrent writes with multiple workers.
            Keep gunicorn at -w 1 for Layer 1.
            Migrate to PostgreSQL when moving to Layer 2 (Stripe).

Endpoints:
  POST /activate  — activate a license key (called by HBCE app)
  POST /validate  — validate a JWT token (called by HBCE app on launch)
  GET  /admin     — admin UI to generate and view license keys
  POST /admin/generate — generate a new key (admin only)
"""

import os
import json
import sqlite3
import hashlib
import secrets
import string
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("HBCE_PORTAL_SECRET", "CHANGE_THIS_SECRET_IN_PRODUCTION")

DB_PATH = os.environ.get("HBCE_PORTAL_DB", "portal.db")
ADMIN_PASSWORD = os.environ.get("HBCE_ADMIN_PASSWORD", "change_me_admin")

# License expiry durations
TIER_EXPIRY_DAYS = {
    "SOLO":   365,    # annual by default
    "PRO":    365,
    "ENT":    365,
    "TRIAL":  30,
}


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS license_keys (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT NOT NULL UNIQUE,
                tier        TEXT NOT NULL,
                billing     TEXT NOT NULL DEFAULT 'annual',
                machine_id  TEXT,
                activated   TEXT,
                expiry      TEXT,
                notes       TEXT,
                created     TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS activations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT NOT NULL,
                machine_id  TEXT NOT NULL,
                version     TEXT,
                os_info     TEXT,
                ip_address  TEXT,
                timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
    print(f"Portal DB initialized: {DB_PATH}")


# ── Key Generation ────────────────────────────────────────────────────────────

def generate_key(tier: str, billing: str = "annual") -> str:
    """Generate a new HBCE license key. Format: HBCE-TIER-XXXXXXXXXXXXXXXX"""
    tier = tier.upper()
    charset = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(charset) for _ in range(16))
    return f"HBCE-{tier}-{random_part}"


def generate_jwt(key: str, machine_id: str, tier: str, expiry: datetime) -> str:
    """
    Generate a simple signed token.
    Layer 1: HMAC-SHA256 based. Layer 2: upgrade to proper JWT library.
    """
    import hmac
    secret = app.secret_key.encode()
    payload = f"{key}|{machine_id}|{tier}|{expiry.isoformat()}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    token_data = json.dumps({
        "key": key,
        "machine_id": machine_id,
        "tier": tier,
        "expiry": expiry.isoformat(),
        "sig": sig,
    })
    import base64
    return base64.b64encode(token_data.encode()).decode()


def verify_jwt(token: str) -> dict | None:
    """Verify and decode a token. Returns payload dict or None."""
    import hmac
    import base64
    try:
        token_data = base64.b64decode(token.encode()).decode()
        payload = json.loads(token_data)
        secret = app.secret_key.encode()
        check = f"{payload['key']}|{payload['machine_id']}|{payload['tier']}|{payload['expiry']}"
        expected_sig = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(payload["sig"], expected_sig):
            return None
        return payload
    except Exception:
        return None


# ── Auth decorator for admin routes ──────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ── API Endpoints (called by HBCE app) ───────────────────────────────────────

@app.route("/activate", methods=["POST"])
def activate():
    """
    Activate a license key.
    Request JSON: { key, machine_id, version, os }
    Response JSON: { jwt, tier, expiry } or { error }
    """
    data = request.get_json(silent=True) or {}
    key        = data.get("key", "").strip().upper()
    machine_id = data.get("machine_id", "").strip()
    version    = data.get("version", "")
    os_info    = data.get("os", "")

    if not key or not machine_id:
        return jsonify({"error": "Missing key or machine_id"}), 400

    with get_db() as db:
        row = db.execute(
            "SELECT * FROM license_keys WHERE key = ?", (key,)
        ).fetchone()

        if not row:
            return jsonify({"error": "Invalid license key"}), 400

        if row["machine_id"] and row["machine_id"] != machine_id:
            return jsonify({"error": "Key already activated on another machine"}), 409

        tier    = row["tier"]
        billing = row["billing"]
        days    = TIER_EXPIRY_DAYS.get(tier, 365)
        if billing == "monthly":
            days = 31
        expiry = datetime.utcnow() + timedelta(days=days)

        token = generate_jwt(key, machine_id, tier, expiry)

        # Bind to machine
        db.execute(
            "UPDATE license_keys SET machine_id=?, activated=?, expiry=? WHERE key=?",
            (machine_id, datetime.utcnow().isoformat(), expiry.isoformat(), key),
        )
        db.execute(
            """INSERT INTO activations (key, machine_id, version, os_info, ip_address)
               VALUES (?, ?, ?, ?, ?)""",
            (key, machine_id, version, os_info, request.remote_addr),
        )

    return jsonify({
        "jwt":    token,
        "tier":   tier,
        "expiry": expiry.isoformat(),
    })


@app.route("/validate", methods=["POST"])
def validate():
    """
    Validate a cached JWT token.
    Request JSON: { jwt, machine_id, key }
    Response JSON: { valid, tier, expiry } or { valid: false }
    """
    data = request.get_json(silent=True) or {}
    token      = data.get("jwt", "")
    machine_id = data.get("machine_id", "")

    payload = verify_jwt(token)
    if not payload:
        return jsonify({"valid": False, "reason": "Invalid token signature"})

    if payload.get("machine_id") != machine_id:
        return jsonify({"valid": False, "reason": "Machine ID mismatch"})

    try:
        expiry = datetime.fromisoformat(payload["expiry"])
        if datetime.utcnow() > expiry:
            return jsonify({"valid": False, "reason": "License expired"})
    except Exception:
        return jsonify({"valid": False, "reason": "Invalid expiry"})

    # Refresh expiry
    tier  = payload.get("tier", "SOLO")
    new_expiry = datetime.utcnow() + timedelta(days=TIER_EXPIRY_DAYS.get(tier, 365))

    return jsonify({
        "valid":  True,
        "tier":   tier,
        "expiry": new_expiry.isoformat(),
    })


# ── Admin UI ──────────────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    with get_db() as db:
        keys = db.execute(
            "SELECT * FROM license_keys ORDER BY created DESC"
        ).fetchall()
        activations = db.execute(
            "SELECT * FROM activations ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
    return render_template(
        "dashboard.html",
        keys=[dict(k) for k in keys],
        activations=[dict(a) for a in activations],
    )


@app.route("/admin/generate", methods=["POST"])
@admin_required
def admin_generate():
    tier    = request.form.get("tier", "SOLO").upper()
    billing = request.form.get("billing", "annual")
    notes   = request.form.get("notes", "")
    qty     = min(int(request.form.get("qty", 1)), 100)

    generated = []
    with get_db() as db:
        for _ in range(qty):
            key = generate_key(tier, billing)
            db.execute(
                "INSERT INTO license_keys (key, tier, billing, notes) VALUES (?, ?, ?, ?)",
                (key, tier, billing, notes),
            )
            generated.append(key)

    return jsonify({"generated": generated, "count": len(generated)})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("HBCE License Portal — Layer 1")
    print(f"Admin password: {ADMIN_PASSWORD}")
    print("Visit http://localhost:5000/admin to manage licenses")
    app.run(host="0.0.0.0", port=5000, debug=False)
