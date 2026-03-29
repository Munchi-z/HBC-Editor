"""
HBCE — Hybrid Controls Editor
core/app.py — Application bootstrap

HBCEApp orchestrates startup sequence:
  1. Initialize logging
  2. Load config
  3. Initialize database
  4. Apply theme
  5. Check license
  6. Show login dialog
  7. Launch main window
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.logger import get_logger
from core.config import Config
from data.db import Database
from ui.theme_engine import ThemeEngine
from ui.login_dialog import LoginDialog
from ui.main_window import MainWindow
from licensing.activator import LicenseActivator

logger = get_logger(__name__)


class HBCEApp:
    """
    Top-level application controller.
    Owns the startup sequence and holds references to core singletons.
    """

    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.config = Config()
        self.db = None
        self.theme_engine = None
        self.current_user = None
        self.main_window = None

    def start(self) -> int:
        """
        Run the full startup sequence.
        Returns the QApplication exit code.
        """
        try:
            logger.info("=" * 60)
            logger.info("HBCE starting up")
            logger.info("=" * 60)

            # Step 1: Initialize database
            self._init_database()

            # Step 2: Apply theme (before any windows open)
            self._apply_theme()

            # Step 3: License check
            if not self._check_license():
                logger.warning("License check failed — exiting")
                return 1

            # Step 4: Login
            user = self._show_login()
            if user is None:
                logger.info("Login cancelled — exiting")
                return 0

            self.current_user = user
            logger.info(f"User logged in: {user['username']} ({user['role']})")

            # Step 5: Launch main window
            self._launch_main_window()

            return self.qt_app.exec()

        except Exception as e:
            logger.exception(f"Fatal startup error: {e}")
            QMessageBox.critical(
                None,
                "HBCE Startup Error",
                f"A fatal error occurred during startup:\n\n{e}\n\n"
                f"Please check the log file and contact support.",
            )
            return 1

    def _init_database(self):
        logger.info("Initializing database...")
        self.db = Database(self.config.db_path)
        self.db.initialize()
        logger.info(f"Database ready: {self.config.db_path}")

    def _apply_theme(self):
        logger.info("Loading theme...")
        self.theme_engine = ThemeEngine(self.config)
        self.theme_engine.apply_theme(self.qt_app)
        logger.info(f"Theme applied: {self.config.get('theme', 'dark_default')}")

    def _check_license(self) -> bool:
        logger.info("Checking license...")
        activator = LicenseActivator(self.config, self.db)
        valid = activator.check_or_activate()
        if valid:
            logger.info("License valid")
        return valid

    def _show_login(self) -> dict | None:
        logger.info("Showing login dialog...")
        dialog = LoginDialog(self.db)
        if dialog.exec():
            return dialog.get_user()
        return None

    def _launch_main_window(self):
        logger.info("Launching main window...")
        self.main_window = MainWindow(
            config=self.config,
            db=self.db,
            theme_engine=self.theme_engine,
            current_user=self.current_user,
        )
        self.main_window.show()
        logger.info("Main window shown — HBCE running")
