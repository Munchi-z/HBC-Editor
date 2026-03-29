"""
HBCE — Hybrid Controls Editor
data/db.py — SQLite database connection and initialization

Creates all tables on first run.
Provides simple query helpers used throughout the app.
"""

import sqlite3
import os
from core.logger import get_logger

logger = get_logger(__name__)

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    path        TEXT,
    created     TEXT NOT NULL DEFAULT (datetime('now')),
    modified    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    vendor      TEXT,
    model       TEXT,
    protocol    TEXT,
    params_json TEXT,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    created     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type TEXT,
    instance    INTEGER,
    name        TEXT,
    value       TEXT,
    units       TEXT,
    status      TEXT,
    device_id   INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    updated     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alarms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    object_ref  TEXT,
    description TEXT,
    priority    INTEGER,
    ack_state   TEXT NOT NULL DEFAULT 'unacknowledged',
    ack_by      TEXT,
    ack_time    TEXT
);

CREATE TABLE IF NOT EXISTS trends (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    point_id    INTEGER REFERENCES points(id) ON DELETE CASCADE,
    value       REAL
);

CREATE TABLE IF NOT EXISTS schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    schedule_json TEXT,
    last_synced TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL DEFAULT 'Operator',
    password_hash   TEXT NOT NULL,
    permissions_json TEXT,
    created         TEXT NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS license (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT,
    machine_id  TEXT,
    jwt         TEXT,
    expiry      TEXT,
    tier        TEXT,
    activated   TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    user_id     INTEGER REFERENCES users(id),
    action      TEXT,
    detail      TEXT
);
"""

# Default admin user (password: hbce_admin — must be changed on first login)
DEFAULT_ADMIN_SQL = """
INSERT OR IGNORE INTO users (username, role, password_hash)
VALUES ('admin', 'Admin', 'CHANGE_ME_ON_FIRST_LOGIN');
"""


class Database:
    """
    Wraps SQLite connection for HBCE.
    Thread-safety note: create one Database per thread, or use check_same_thread=False
    with appropriate locking for background comms threads.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    def initialize(self):
        """Create database file and all tables if they don't exist."""
        logger.info(f"Initializing database: {self.db_path}")
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA_SQL)
            self._conn.executescript(DEFAULT_ADMIN_SQL)
        logger.info("Database schema ready")

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized — call initialize() first")
        return self._conn

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_list) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params_list)

    def fetchall(self, sql: str, params=()) -> list:
        return [dict(row) for row in self.execute(sql, params).fetchall()]

    def fetchone(self, sql: str, params=()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def insert(self, sql: str, params=()) -> int:
        """Execute an INSERT and return the new row id."""
        with self.conn:
            cur = self.execute(sql, params)
            return cur.lastrowid

    def update(self, sql: str, params=()):
        with self.conn:
            self.execute(sql, params)

    def get_user(self, username: str) -> dict | None:
        return self.fetchone(
            "SELECT * FROM users WHERE username = ?", (username,)
        )

    def get_all_users(self) -> list:
        return self.fetchall("SELECT id, username, role, created, last_login FROM users")

    def log_audit(self, user_id: int, action: str, detail: str = ""):
        self.insert(
            "INSERT INTO audit_log (user_id, action, detail) VALUES (?, ?, ?)",
            (user_id, action, detail),
        )

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("Database connection closed")
