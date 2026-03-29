"""
HBCE — Hybrid Controls Editor
core/config.py — App-wide configuration manager

Loads and saves settings from a JSON config file.
Provides default values for all settings.
"""

import os
import json
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

# Default config values
DEFAULTS = {
    "theme": "dark_default",
    "theme_accent": "#00AAFF",
    "theme_bg_primary": "#1E1E2E",
    "theme_bg_secondary": "#2A2A3E",
    "theme_text_primary": "#E0E0E0",
    "theme_text_secondary": "#A0A0B0",
    "theme_border": "#3A3A5C",
    "theme_font_family": "Segoe UI",
    "theme_font_size": 10,
    "sidebar_width": 220,
    "window_width": 1400,
    "window_height": 900,
    "window_maximized": False,
    "language": "en_US",
    "units": "imperial",           # imperial or metric
    "bacnet_port": 47808,
    "bacnet_timeout": 3,
    "modbus_timeout": 3,
    "log_level": "INFO",
    "cloud_sync_provider": None,   # None, "google_drive", "onedrive"
    "cloud_sync_enabled": False,
    "recent_projects": [],
    "last_project": None,
}


class Config:
    """
    Manages HBCE application configuration.
    Settings are stored in %APPDATA%/HBCE/config.json on Windows.
    """

    def __init__(self):
        self.app_data_dir = self._get_app_data_dir()
        self.config_path = os.path.join(self.app_data_dir, "config.json")
        self.db_path = os.path.join(self.app_data_dir, "hbce.db")
        self.log_path = os.path.join(self.app_data_dir, "logs", "hbce.log")
        self.themes_dir = os.path.join(self.app_data_dir, "themes")
        self.projects_dir = os.path.join(self.app_data_dir, "projects")

        self._settings = {}
        self._ensure_dirs()
        self._load()

    def _get_app_data_dir(self) -> str:
        """Returns %APPDATA%/HBCE on Windows, ~/.hbce on other platforms."""
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.path.expanduser("~")
        return os.path.join(base, "HBCE")

    def _ensure_dirs(self):
        """Create all required directories if they don't exist."""
        for path in [
            self.app_data_dir,
            os.path.dirname(self.log_path),
            self.themes_dir,
            self.projects_dir,
        ]:
            Path(path).mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Load config from disk, filling in defaults for missing keys."""
        self._settings = dict(DEFAULTS)  # start with defaults
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._settings.update(saved)
                logger.debug(f"Config loaded from {self.config_path}")
            except Exception as e:
                logger.warning(f"Could not load config (using defaults): {e}")

    def save(self):
        """Persist current settings to disk."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
            logger.debug("Config saved")
        except Exception as e:
            logger.error(f"Could not save config: {e}")

    def get(self, key: str, default=None):
        return self._settings.get(key, default)

    def set(self, key: str, value):
        self._settings[key] = value

    def set_and_save(self, key: str, value):
        self.set(key, value)
        self.save()

    def get_all(self) -> dict:
        return dict(self._settings)

    def add_recent_project(self, path: str):
        recents = self._settings.get("recent_projects", [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._settings["recent_projects"] = recents[:10]  # keep last 10
        self.save()
