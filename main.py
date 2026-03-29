"""
HBCE — Hybrid Controls Editor
main.py — Application entry point

Run this file to launch HBCE.
For packaged .exe, PyInstaller will target this file.
"""

import sys
import os

# Ensure the HBCE root is on the path (important for PyInstaller builds)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from version import VERSION, APP_NAME, APP_FULL_NAME
from core.app import HBCEApp


def main():
    # Enable high-DPI scaling (important for Windows 10/11)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_FULL_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("HBCE Project")

    # Set app icon (will be replaced with real icon asset)
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icons", "hbce_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Bootstrap the application (theme, DB, license check, login)
    hbce = HBCEApp(app)
    result = hbce.start()

    sys.exit(result)


if __name__ == "__main__":
    main()
