"""
HBCE — Hybrid Controls Editor
core/logger.py — Logging configuration

Sets up file + console logging.
Call get_logger(__name__) in any module to get a named logger.
"""

import logging
import os
from pathlib import Path


_initialized = False
_log_path = None


def _init_logging(log_path: str = None, level: str = "INFO"):
    global _initialized, _log_path

    if _initialized:
        return

    # Determine log file path
    if log_path is None:
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.path.expanduser("~")
        log_dir = os.path.join(base, "HBCE", "logs")
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_path = os.path.join(log_dir, "hbce.log")

    _log_path = log_path

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Root logger
    root = logging.getLogger("hbce")
    root.setLevel(log_level)

    # Formatter
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (rotating would be better in production — simple for now)
    try:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(log_level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        print(f"Warning: could not open log file {log_path}: {e}")

    # Console handler (shows in dev; hidden in .exe since console=False)
    ch = logging.StreamHandler()
    ch.setLevel(log_level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger under the 'hbce' hierarchy.
    Auto-initializes logging on first call.

    Usage:
        from core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Hello from this module")
    """
    _init_logging()
    # Strip leading package name if it starts with 'hbce.'
    clean_name = name.replace("__main__", "main")
    return logging.getLogger(f"hbce.{clean_name}")
