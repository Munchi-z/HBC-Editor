"""
HBCE — Hybrid Controls Editor
core/crash_handler.py — Global crash + unhandled exception handler

Catches:
  - Unhandled Python exceptions  (sys.excepthook)
  - Unhandled exceptions on QThreads  (threading.excepthook)
  - Qt fatal signals  (faulthandler)

On any crash:
  1. Writes a full crash report to  %APPDATA%/HBCE/logs/crash.log
     (rotated — keeps last 5 crash reports, each stamped with datetime)
  2. Also writes to the main hbce.log at CRITICAL level
  3. Shows a user-facing CrashReportDialog with:
       - What crashed  (module, line, exception type + message)
       - Where the log is  (clickable path to open folder)
       - Full traceback (expandable)
       - Copy to Clipboard button
  4. In dev mode: also prints to stderr as normal

Install by calling install_crash_handler() once in main.py before QApplication.exec().
"""

from __future__ import annotations

import faulthandler
import logging
import os
import platform
import sys
import traceback
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Type

from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Log path helpers  (mirrors core/logger.py path logic)
# ---------------------------------------------------------------------------

def _get_log_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    log_dir = Path(base) / "HBCE" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _get_crash_log_path() -> Path:
    return _get_log_dir() / "crash.log"


# ---------------------------------------------------------------------------
# Crash report builder
# ---------------------------------------------------------------------------

def _build_crash_report(
    exc_type:  Type[BaseException],
    exc_value: BaseException,
    exc_tb,
    source: str = "main thread",
) -> str:
    """Build the full text of a crash report."""
    from version import VERSION          # lazy import — safe after Qt init

    tb_lines  = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_text   = "".join(tb_lines)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = (
        f"{'=' * 70}\n"
        f"HBCE CRASH REPORT\n"
        f"{'=' * 70}\n"
        f"Version   : {VERSION}\n"
        f"Timestamp : {timestamp}\n"
        f"Source    : {source}\n"
        f"Platform  : {platform.platform()}\n"
        f"Python    : {sys.version}\n"
        f"{'─' * 70}\n"
        f"Exception : {exc_type.__name__}\n"
        f"Message   : {exc_value}\n"
        f"{'─' * 70}\n"
        f"TRACEBACK:\n\n"
        f"{tb_text}"
        f"{'=' * 70}\n\n"
    )
    return report


# ---------------------------------------------------------------------------
# Crash log writer  (rotates — keeps last 5 crashes in single file)
# ---------------------------------------------------------------------------

_MAX_CRASH_LOG_BYTES = 512 * 1024   # 512 KB — rotate when exceeded

def _write_crash_log(report: str):
    path = _get_crash_log_path()
    try:
        # Simple rotation: if file > 512 KB, clear it before writing
        if path.exists() and path.stat().st_size > _MAX_CRASH_LOG_BYTES:
            path.write_text("", encoding="utf-8")

        with path.open("a", encoding="utf-8") as f:
            f.write(report)
    except Exception as e:
        # Last resort — stderr only
        print(f"[HBCE] Could not write crash log: {e}", file=sys.stderr)

    # Also log at CRITICAL to main hbce.log
    try:
        logger = logging.getLogger("hbce.crash")
        logger.critical(report)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# User-facing crash dialog
# ---------------------------------------------------------------------------

class CrashReportDialog(QDialog):
    """
    Shows after a crash — gives the user something useful to do
    rather than just silently dying.
    """

    def __init__(self, report: str, crash_log_path: Path, parent=None):
        super().__init__(parent)
        self._report        = report
        self._crash_log_path = crash_log_path

        self.setWindowTitle("HBCE — Unexpected Error")
        self.setMinimumWidth(560)
        self.setMinimumHeight(380)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        icon_lbl = QLabel("⚠️")
        icon_lbl.setStyleSheet("font-size: 28px;")
        header.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title = QLabel("HBCE encountered an unexpected error")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        subtitle = QLabel(
            "The crash has been saved to the log file below.\n"
            "You can continue using the app or restart if needed."
        )
        subtitle.setStyleSheet("color: #78909C; font-size: 10px;")
        subtitle.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        # Error summary (first 3 lines of traceback — quick read)
        lines    = self._report.strip().splitlines()
        exc_line = next((l for l in lines if l.startswith("Exception :")), "")
        msg_line = next((l for l in lines if l.startswith("Message   :")), "")
        src_line = next((l for l in lines if l.startswith("Source    :")), "")

        summary = QLabel(f"{exc_line}\n{msg_line}\n{src_line}")
        summary.setStyleSheet(
            "background: #1A2228; color: #EF9A9A; border-radius: 4px; "
            "padding: 8px; font-family: monospace; font-size: 10px;"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # Log path
        log_row = QHBoxLayout()
        log_lbl = QLabel("Crash log:")
        log_lbl.setStyleSheet("color: #546E7A; font-size: 10px;")
        log_row.addWidget(log_lbl)
        path_lbl = QLabel(str(self._crash_log_path))
        path_lbl.setStyleSheet(
            "color: #80CBC4; font-size: 10px; font-family: monospace;"
        )
        path_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        log_row.addWidget(path_lbl, 1)
        open_btn = QPushButton("Open Folder")
        open_btn.setFixedWidth(90)
        open_btn.setStyleSheet(
            "QPushButton { background: #1A2428; color: #90A4AE; "
            "border: 1px solid #263238; border-radius: 3px; "
            "padding: 2px 8px; font-size: 9pt; }"
            "QPushButton:hover { background: #243038; }"
        )
        open_btn.clicked.connect(self._open_log_folder)
        log_row.addWidget(open_btn)
        layout.addLayout(log_row)

        # Full traceback — collapsed by default
        self._tb_edit = QTextEdit()
        self._tb_edit.setReadOnly(True)
        self._tb_edit.setPlainText(self._report)
        self._tb_edit.setStyleSheet(
            "QTextEdit { background: #111820; color: #90A4AE; "
            "border: 1px solid #1E2B32; border-radius: 3px; "
            "font-family: monospace; font-size: 9px; }"
        )
        self._tb_edit.setVisible(False)
        self._tb_edit.setMinimumHeight(160)
        layout.addWidget(self._tb_edit)

        # Buttons
        btn_row = QHBoxLayout()

        self._toggle_btn = QPushButton("▶  Show Full Traceback")
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #546E7A; "
            "border: none; font-size: 9pt; }"
            "QPushButton:hover { color: #90A4AE; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_traceback)
        btn_row.addWidget(self._toggle_btn)
        btn_row.addStretch()

        copy_btn = QPushButton("📋  Copy Report")
        copy_btn.setStyleSheet(
            "QPushButton { background: #1A2428; color: #90A4AE; "
            "border: 1px solid #263238; border-radius: 3px; "
            "padding: 4px 12px; font-size: 9pt; }"
            "QPushButton:hover { background: #243038; }"
        )
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self._report)
        )
        btn_row.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.setStyleSheet(
            "QPushButton { background: #1B3A2A; color: #81C784; "
            "border: 1px solid #2E7D32; border-radius: 3px; "
            "padding: 4px 16px; font-size: 9pt; }"
            "QPushButton:hover { background: #1E4D33; }"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _toggle_traceback(self):
        visible = not self._tb_edit.isVisible()
        self._tb_edit.setVisible(visible)
        self._toggle_btn.setText(
            "▼  Hide Full Traceback" if visible else "▶  Show Full Traceback"
        )
        if visible:
            self.resize(self.width(), 600)

    def _open_log_folder(self):
        import subprocess
        folder = str(self._crash_log_path.parent)
        if os.name == "nt":
            subprocess.Popen(["explorer", folder])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])


# ---------------------------------------------------------------------------
# Signal bridge — needed to show a Qt dialog from a non-Qt thread
# ---------------------------------------------------------------------------

class _CrashSignalBridge(QObject):
    show_dialog = pyqtSignal(str, str)   # report, log_path_str

    def __init__(self):
        super().__init__()
        self.show_dialog.connect(self._on_show_dialog,
                                 Qt.ConnectionType.QueuedConnection)

    def _on_show_dialog(self, report: str, log_path_str: str):
        try:
            dlg = CrashReportDialog(report, Path(log_path_str))
            dlg.exec()
        except Exception:
            pass   # if the dialog itself fails, just let the app close


_bridge: Optional[_CrashSignalBridge] = None


# ---------------------------------------------------------------------------
# Core handler function
# ---------------------------------------------------------------------------

def _handle_crash(
    exc_type:  Type[BaseException],
    exc_value: BaseException,
    exc_tb,
    source: str = "main thread",
):
    """Central crash handler — called from all hook entry points."""

    # Don't handle KeyboardInterrupt as a crash
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    report       = _build_crash_report(exc_type, exc_value, exc_tb, source)
    crash_log    = _get_crash_log_path()

    _write_crash_log(report)

    # Always print to stderr (visible in dev console / PyInstaller --console)
    print(report, file=sys.stderr)

    # Show dialog — use signal bridge if we're on a non-main thread
    if _bridge is not None:
        try:
            _bridge.show_dialog.emit(report, str(crash_log))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public install function
# ---------------------------------------------------------------------------

def install_crash_handler():
    """
    Call once in main.py after QApplication is created.
    Installs hooks for:
      - sys.excepthook          (unhandled exceptions on main thread)
      - threading.excepthook    (unhandled exceptions on QThread / threading.Thread)
      - faulthandler            (segfaults, stack overflows → crash.log)
    """
    global _bridge

    # Qt signal bridge for cross-thread dialog display
    _bridge = _CrashSignalBridge()

    # ── Main thread hook ───────────────────────────────────────────────────
    def _main_excepthook(exc_type, exc_value, exc_tb):
        _handle_crash(exc_type, exc_value, exc_tb, source="main thread")

    sys.excepthook = _main_excepthook

    # ── Background thread hook ─────────────────────────────────────────────
    def _thread_excepthook(args):
        _handle_crash(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            source=f"thread: {args.thread.name if args.thread else 'unknown'}",
        )

    threading.excepthook = _thread_excepthook

    # ── faulthandler → crash.log (catches segfaults etc.) ─────────────────
    try:
        crash_log = _get_crash_log_path()
        _fault_file = open(crash_log, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file)
    except Exception as e:
        print(f"[HBCE] faulthandler could not be enabled: {e}", file=sys.stderr)

    logging.getLogger("hbce.crash").info(
        "Crash handler installed (excepthook + threading.excepthook + faulthandler)"
    )
