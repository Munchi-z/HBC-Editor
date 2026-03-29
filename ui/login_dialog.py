"""
HBCE — Hybrid Controls Editor
ui/login_dialog.py — Login dialog

Shown at startup before the main window.
Validates username + password against local SQLite users table.
For V0.0.1: default admin account with prompt to set password on first login.
"""

import hashlib
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeyEvent

from version import VERSION, APP_FULL_NAME
from core.logger import get_logger

logger = get_logger(__name__)


def hash_password(password: str) -> str:
    """SHA-256 hash of password. Production: use bcrypt or argon2."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class LoginDialog(QDialog):
    """
    Login dialog shown at HBCE startup.
    Validates against the local users table.
    """

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._user = None
        self._first_login_check()

        self.setWindowTitle(f"{APP_FULL_NAME} — Login")
        self.setFixedSize(380, 420)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        self._build_ui()

    def _first_login_check(self):
        """
        If the admin account still has the default placeholder password,
        force a password setup on first launch.
        """
        admin = self.db.get_user("admin")
        if admin and admin.get("password_hash") == "CHANGE_ME_ON_FIRST_LOGIN":
            self._setup_default_admin()

    def _setup_default_admin(self):
        """Set a real password for the default admin account."""
        from PyQt6.QtWidgets import QInputDialog
        QMessageBox.information(
            None,
            "First Launch — Set Admin Password",
            "Welcome to HBCE!\n\n"
            "This is your first launch. Please set a password for the admin account.\n\n"
            "You can add more users after logging in.",
        )
        while True:
            pw, ok = QInputDialog.getText(
                None,
                "Set Admin Password",
                "Enter a new password for the 'admin' account:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                break
            if len(pw) < 6:
                QMessageBox.warning(None, "Too Short", "Password must be at least 6 characters.")
                continue
            pw2, ok2 = QInputDialog.getText(
                None,
                "Confirm Password",
                "Confirm your new password:",
                QLineEdit.EchoMode.Password,
            )
            if ok2 and pw == pw2:
                self.db.update(
                    "UPDATE users SET password_hash = ? WHERE username = 'admin'",
                    (hash_password(pw),),
                )
                QMessageBox.information(None, "Password Set", "Admin password set successfully!")
                break
            else:
                QMessageBox.warning(None, "Mismatch", "Passwords do not match. Try again.")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        # Logo / app name
        logo = QLabel("⚡ HBCE")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_font = QFont()
        logo_font.setPointSize(24)
        logo_font.setBold(True)
        logo.setFont(logo_font)
        logo.setStyleSheet("color: #00AAFF;")
        layout.addWidget(logo)

        app_name = QLabel(APP_FULL_NAME)
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_name.setStyleSheet("color: #808090; font-size: 10pt;")
        layout.addWidget(app_name)

        ver_label = QLabel(f"Version {VERSION}")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_label.setStyleSheet("color: #606070; font-size: 8pt;")
        layout.addWidget(ver_label)

        layout.addSpacing(8)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        layout.addSpacing(4)

        # Username
        user_label = QLabel("Username")
        user_label.setStyleSheet("font-weight: bold; font-size: 10pt;")
        layout.addWidget(user_label)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        self.username_input.setText("admin")
        self.username_input.setMinimumHeight(36)
        layout.addWidget(self.username_input)

        # Password
        pw_label = QLabel("Password")
        pw_label.setStyleSheet("font-weight: bold; font-size: 10pt;")
        layout.addWidget(pw_label)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumHeight(36)
        self.password_input.returnPressed.connect(self._attempt_login)
        layout.addWidget(self.password_input)

        # Error label (hidden until login fails)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #FF4455; font-size: 9pt;")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        layout.addSpacing(4)

        # Login button
        self.login_btn = QPushButton("Log In")
        self.login_btn.setMinimumHeight(40)
        self.login_btn.clicked.connect(self._attempt_login)
        layout.addWidget(self.login_btn)

        layout.addStretch()

    def _attempt_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            self._show_error("Please enter both username and password.")
            return

        user = self.db.get_user(username)
        if user is None:
            self._show_error("Unknown username.")
            logger.warning(f"Login attempt: unknown user '{username}'")
            return

        expected_hash = user.get("password_hash", "")
        if hash_password(password) != expected_hash:
            self._show_error("Incorrect password.")
            logger.warning(f"Login attempt: wrong password for '{username}'")
            return

        # Success
        self._user = {
            "id":       user["id"],
            "username": user["username"],
            "role":     user["role"],
        }

        # Update last_login
        self.db.update(
            "UPDATE users SET last_login = datetime('now') WHERE id = ?",
            (user["id"],),
        )
        self.db.log_audit(user["id"], "LOGIN", f"Successful login from role {user['role']}")

        logger.info(f"Login successful: {username} ({user['role']})")
        self.accept()

    def _show_error(self, msg: str):
        self.error_label.setText(f"⚠  {msg}")
        self.error_label.setVisible(True)
        self.password_input.clear()
        self.password_input.setFocus()

    def get_user(self) -> dict | None:
        """Returns the authenticated user dict after successful login."""
        return self._user
