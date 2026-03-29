"""
HBCE — Hybrid Controls Editor
licensing/activator.py — License activation and validation

DEV MODE (current default — HBCE_LICENSE_ENABLED = False):
  App runs completely free. No dialogs, no network calls, no key needed.
  Build, test, and use HBCE freely during development.

PRODUCTION MODE (future — flip HBCE_LICENSE_ENABLED = True):
  Deploy portal/app.py to a VPS first, then enable this.
  Users will be prompted to activate a license key on first launch.

*** REMINDER: DigitalOcean portal deployment is ON HOLD.
    When you're ready, ask Claude about:
    "Set up the HBCE Flask portal on DigitalOcean with one-click deploy"
    and flip HBCE_LICENSE_ENABLED = True here at the same time. ***
"""

import hashlib
import platform
import uuid
import os
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  MASTER SWITCH
#  False = dev/hobby mode, no license needed, runs free forever until flipped
#  True  = production mode, requires active key from license portal
# ─────────────────────────────────────────────────────────────────────────────
HBCE_LICENSE_ENABLED = False
# ─────────────────────────────────────────────────────────────────────────────

PORTAL_BASE_URL     = os.environ.get("HBCE_PORTAL_URL", "https://license.hbce.io")
ACTIVATE_ENDPOINT   = f"{PORTAL_BASE_URL}/activate"
VALIDATE_ENDPOINT   = f"{PORTAL_BASE_URL}/validate"
OFFLINE_GRACE_DAYS  = 7


def get_machine_id() -> str:
    """Stable machine fingerprint — only used in production mode."""
    raw = "|".join([platform.node(), str(uuid.getnode()),
                    platform.system(), platform.machine()])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class LicenseActivator:
    """
    Controls HBCE license checking.

    DEV MODE  (HBCE_LICENSE_ENABLED=False): always returns True, zero overhead.
    PROD MODE (HBCE_LICENSE_ENABLED=True):  validates JWT or prompts activation.
    """

    def __init__(self, config, db):
        self.config     = config
        self.db         = db
        self.machine_id = get_machine_id()

    def check_or_activate(self) -> bool:
        if not HBCE_LICENSE_ENABLED:
            logger.info(
                "LICENSE: dev mode — running free. "
                "Flip HBCE_LICENSE_ENABLED=True in licensing/activator.py "
                "when portal is ready. (Reminder: ask about DigitalOcean deploy.)"
            )
            return True

        # ── Production path ───────────────────────────────────────────────────
        record = self.db.fetchone(
            "SELECT * FROM license ORDER BY id DESC LIMIT 1"
        )
        if record and record.get("jwt"):
            if self._is_locally_valid(record):
                logger.info(f"License OK — tier: {record.get('tier','?')}")
                return True
            if self._validate_online(record.get("jwt",""), record.get("key","")):
                return True
        return self._show_activation_dialog()

    def _is_locally_valid(self, record: dict) -> bool:
        try:
            expiry  = datetime.fromisoformat(record["expiry"])
            return datetime.utcnow() < expiry + timedelta(days=OFFLINE_GRACE_DAYS)
        except Exception:
            return False

    def _validate_online(self, jwt: str, key: str) -> bool:
        try:
            import requests
            r = requests.post(VALIDATE_ENDPOINT,
                              json={"jwt": jwt, "machine_id": self.machine_id,
                                    "key": key}, timeout=8)
            if r.status_code == 200 and r.json().get("valid"):
                self.db.update("UPDATE license SET expiry=? WHERE jwt=?",
                               (r.json().get("expiry"), jwt))
                return True
        except Exception as e:
            logger.warning(f"Online validation failed: {e}")
        return False

    def _activate_key(self, key: str) -> tuple[bool, str]:
        from version import VERSION
        try:
            import requests
            r = requests.post(ACTIVATE_ENDPOINT,
                              json={"key": key, "machine_id": self.machine_id,
                                    "version": VERSION,
                                    "os": f"{platform.system()} {platform.release()}"},
                              timeout=12)
            if r.status_code == 200:
                d = r.json()
                self.db.insert(
                    "INSERT INTO license (key,machine_id,jwt,expiry,tier,activated) "
                    "VALUES (?,?,?,?,?,datetime('now'))",
                    (key, self.machine_id, d.get("jwt",""),
                     d.get("expiry",""), d.get("tier","unknown")))
                return True, ""
            if r.status_code == 400: return False, "Invalid license key."
            if r.status_code == 409: return False, "Key already activated on another machine."
            return False, f"Server error ({r.status_code}). Try again later."
        except Exception as e:
            return False, "Could not reach the license server. Check your connection."

    def _show_activation_dialog(self) -> bool:
        dlg = ActivationDialog(self.machine_id)
        if dlg.exec():
            ok, err = self._activate_key(dlg.get_key())
            if ok:
                QMessageBox.information(None, "Activated",
                                        "HBCE license activated! Thank you.")
                return True
            QMessageBox.critical(None, "Activation Failed", err)
        return False


class ActivationDialog(QDialog):
    """License key entry dialog — shown only in production mode."""

    def __init__(self, machine_id: str, parent=None):
        super().__init__(parent)
        self.machine_id = machine_id
        self.setWindowTitle("HBCE — License Activation")
        self.setFixedSize(460, 360)
        self.setWindowFlags(Qt.WindowType.Dialog |
                            Qt.WindowType.WindowCloseButtonHint)
        self._build_ui()

    def _build_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(32, 28, 32, 28)
        L.setSpacing(12)

        hdr = QLabel("HBCE — License Activation")
        f = QFont(); f.setPointSize(14); f.setBold(True)
        hdr.setFont(f); hdr.setStyleSheet("color:#00AAFF;")
        L.addWidget(hdr)

        sub = QLabel("Enter your license key. Internet required for activation.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#A0A0B0; font-size:9pt;")
        L.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        L.addWidget(sep)

        L.addWidget(QLabel("License Key:"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("HBCE-XXXX-XXXXXXXXXXXXXXXX")
        self.key_input.setMinimumHeight(36)
        self.key_input.setMaxLength(40)
        L.addWidget(self.key_input)

        note = QLabel("Format: HBCE-[TIER]-[16 characters]")
        note.setStyleSheet("color:#606070; font-size:8pt;")
        L.addWidget(note)

        row = QHBoxLayout()
        row.addWidget(QLabel("Machine ID:"))
        mid = QLineEdit(self.machine_id)
        mid.setReadOnly(True)
        mid.setStyleSheet("color:#606070; font-size:8pt;")
        row.addWidget(mid)
        cp = QPushButton("Copy"); cp.setFixedWidth(56)
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.machine_id))
        row.addWidget(cp)
        L.addLayout(row)

        btn = QPushButton("Activate License")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self._on_activate)
        L.addWidget(btn)

        buy = QLabel("Don't have a key? Visit hbce.io to purchase.")
        buy.setStyleSheet("color:#606070; font-size:8pt;")
        buy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        L.addWidget(buy)
        L.addStretch()

    def _on_activate(self):
        key = self.key_input.text().strip().upper()
        if not key.startswith("HBCE-") or len(key) < 10:
            QMessageBox.warning(self, "Invalid Format",
                                "Format: HBCE-[TIER]-[16 characters]")
            return
        self.accept()

    def get_key(self) -> str:
        return self.key_input.text().strip().upper()
