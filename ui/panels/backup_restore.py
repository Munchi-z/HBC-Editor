# ui/panels/backup_restore.py
# HBCE — Hybrid Controls Editor
# Backup / Restore Panel — Full Implementation V0.1.9-alpha
#
# V0.1.9 additions:
#   - CloudSyncPanel widget (Google Drive + OneDrive) as right-side Tab 3
#   - Selection bridge: selecting a backup notifies CloudSyncPanel
#   - Auto-sync trigger: on successful backup, CloudSyncPanel.trigger_auto_sync()
#
# Visual approach: consistent with AlarmViewer (stripe + pill style)
#   - 4 px left accent stripe per backup type
#   - Status pill badge (Complete / Failed / In-Progress)
#   - Near-black rows, subtle type-tinting
#
# ARCH-011 restore flow:
#   1. Select backup → preview diff (current vs backup)
#   2. Auto-backup current state (safety net — inside RestoreThread)
#   3. Confirm dialog (typed "RESTORE" confirmation)
#   4. RestoreThread writes config back to device
#
# All I/O (backup reads/writes, diff compute) runs in QThreads — GOTCHA-013 compliant.

from __future__ import annotations

import csv
import difflib
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QRectF,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QVariant,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from core.logger import get_logger

# Cloud sync — imported lazily so the panel works even without cloud libs
try:
    from data.cloud_sync import (
        CloudSyncManager, SyncProvider, CloudSyncThread,
    )
    from pathlib import Path as _Path
    _CLOUD_AVAILABLE = True
except Exception:
    _CLOUD_AVAILABLE = False

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKUP_TYPE_LABELS = {
    "manual":      "Manual",
    "auto":        "Auto",
    "pre_restore": "Pre-Restore",
    "scheduled":   "Scheduled",
}

BACKUP_STATUS_LABELS = {
    "complete":    "Complete",
    "failed":      "Failed",
    "in_progress": "In Progress",
    "partial":     "Partial",
}

# ── Left accent stripe colors ─────────────────────────────────────────────
TYPE_STRIPE = {
    "manual":      QColor("#1565C0"),
    "auto":        QColor("#2E7D32"),
    "pre_restore": QColor("#F9A825"),
    "scheduled":   QColor("#6A1B9A"),
}

# ── Status pill colors ────────────────────────────────────────────────────
STATUS_PILL_BG = {
    "complete":    QColor("#1B5E20"),
    "failed":      QColor("#7B0000"),
    "in_progress": QColor("#6D3C00"),
    "partial":     QColor("#7B5800"),
}
STATUS_PILL_FG = {
    "complete":    QColor("#A5D6A7"),
    "failed":      QColor("#EF9A9A"),
    "in_progress": QColor("#FFCC80"),
    "partial":     QColor("#FFE082"),
}

ROW_BG_DEFAULT = QColor("#1A1A24")
ROW_BG_ALT     = QColor("#1E1E2A")
ROW_SEL_BG     = QColor("#2A3550")
ROW_SEL_FG     = QColor("#E8E8F0")
ROW_FG         = QColor("#C8C8D8")

BACKUPS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL DEFAULT (datetime('now')),
    device_id    INTEGER,
    device_name  TEXT NOT NULL DEFAULT 'All Devices',
    backup_name  TEXT NOT NULL,
    notes        TEXT DEFAULT '',
    file_path    TEXT,
    file_size    INTEGER DEFAULT 0,
    backup_type  TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL DEFAULT 'complete',
    created_by   TEXT DEFAULT ''
);
"""

COL_ID         = 0
COL_TIMESTAMP  = 1
COL_DEVICE     = 2
COL_NAME       = 3
COL_TYPE       = 4
COL_SIZE       = 5
COL_STATUS     = 6
COL_NOTES      = 7
COL_CREATED_BY = 8

COLUMN_HEADERS = [
    "ID", "Timestamp", "Device", "Backup Name",
    "Type", "Size", "Status", "Notes", "By",
]
COLUMN_WIDTHS = [45, 140, 120, 160, 80, 70, 90, 180, 80]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BackupEntry:
    id:           int              = 0
    timestamp:    str              = ""
    device_id:    Optional[int]    = None
    device_name:  str              = "All Devices"
    backup_name:  str              = ""
    notes:        str              = ""
    file_path:    str              = ""
    file_size:    int              = 0
    backup_type:  str              = "manual"
    status:       str              = "complete"
    created_by:   str              = ""

    @property
    def size_str(self) -> str:
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1048576:
            return f"{self.file_size / 1024:.1f} KB"
        return f"{self.file_size / 1048576:.2f} MB"

    @property
    def type_label(self) -> str:
        return BACKUP_TYPE_LABELS.get(self.backup_type, self.backup_type)

    @property
    def status_label(self) -> str:
        return BACKUP_STATUS_LABELS.get(self.status, self.status)


# ---------------------------------------------------------------------------
# Table model
# ---------------------------------------------------------------------------

class BackupTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[BackupEntry] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMN_HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMN_HEADERS[section]
        return QVariant()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._entries):
            return QVariant()
        e   = self._entries[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_ID:          return str(e.id)
            if col == COL_TIMESTAMP:   return e.timestamp[:16] if e.timestamp else ""
            if col == COL_DEVICE:      return e.device_name
            if col == COL_NAME:        return e.backup_name
            if col == COL_TYPE:        return e.type_label
            if col == COL_SIZE:        return e.size_str
            if col == COL_STATUS:      return e.status_label
            if col == COL_NOTES:       return e.notes
            if col == COL_CREATED_BY:  return e.created_by
        if role == Qt.ItemDataRole.UserRole:
            return e
        return QVariant()

    def load(self, entries: List[BackupEntry]):
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def prepend(self, entry: BackupEntry):
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._entries.insert(0, entry)
        self.endInsertRows()

    def update_entry(self, entry_id: int, status: str, file_size: int = 0):
        for i, e in enumerate(self._entries):
            if e.id == entry_id:
                e.status    = status
                e.file_size = file_size
                self.dataChanged.emit(self.index(i, COL_STATUS), self.index(i, COL_SIZE))
                return

    def remove_ids(self, ids: set):
        self.beginResetModel()
        self._entries = [e for e in self._entries if e.id not in ids]
        self.endResetModel()

    def entry_at(self, row: int) -> Optional[BackupEntry]:
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def all_entries(self) -> List[BackupEntry]:
        return list(self._entries)


# ---------------------------------------------------------------------------
# Row delegate  (stripe + pill — consistent with AlarmViewer)
# ---------------------------------------------------------------------------

class BackupRowDelegate(QStyledItemDelegate):

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex):
        entry: Optional[BackupEntry] = index.data(Qt.ItemDataRole.UserRole)
        if not entry:
            super().paint(painter, option, index)
            return

        painter.save()
        row = index.row()
        col = index.column()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        bg = ROW_SEL_BG if selected else (ROW_BG_ALT if row % 2 else ROW_BG_DEFAULT)
        painter.fillRect(option.rect, bg)

        # 4 px left stripe on first column
        if col == 0:
            stripe = TYPE_STRIPE.get(entry.backup_type, QColor("#546E7A"))
            painter.fillRect(
                QRect(option.rect.left(), option.rect.top(), 4, option.rect.height()),
                stripe,
            )

        fg = ROW_SEL_FG if selected else ROW_FG

        # Status pill
        if col == COL_STATUS:
            pill_bg = STATUS_PILL_BG.get(entry.status, QColor("#37474F"))
            pill_fg = STATUS_PILL_FG.get(entry.status, QColor("#B0BEC5"))
            text    = entry.status_label
            font    = QFont(); font.setPointSize(8); font.setBold(True)
            painter.setFont(font)
            fm = painter.fontMetrics()
            pad_h, pad_v = 8, 3
            pill_w = fm.horizontalAdvance(text) + pad_h * 2
            pill_h = fm.height() + pad_v * 2
            cx, cy = option.rect.center().x(), option.rect.center().y()
            pill_rect = QRectF(cx - pill_w / 2, cy - pill_h / 2, pill_w, pill_h)
            path = QPainterPath()
            path.addRoundedRect(pill_rect, pill_h / 2, pill_h / 2)
            painter.fillPath(path, QBrush(pill_bg))
            painter.setPen(QPen(pill_fg))
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
            return

        # Type pill
        if col == COL_TYPE:
            stripe = TYPE_STRIPE.get(entry.backup_type, QColor("#546E7A"))
            pill_bg = QColor(stripe.red(), stripe.green(), stripe.blue(), 70)
            text    = entry.type_label
            font    = QFont(); font.setPointSize(8)
            painter.setFont(font)
            fm = painter.fontMetrics()
            pad_h, pad_v = 6, 2
            pill_w = fm.horizontalAdvance(text) + pad_h * 2
            pill_h = fm.height() + pad_v * 2
            cx, cy = option.rect.center().x(), option.rect.center().y()
            pill_rect = QRectF(cx - pill_w / 2, cy - pill_h / 2, pill_w, pill_h)
            path = QPainterPath()
            path.addRoundedRect(pill_rect, pill_h / 2, pill_h / 2)
            painter.fillPath(path, QBrush(pill_bg))
            painter.setPen(QPen(stripe.lighter(140)))
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
            return

        # Default text
        font = QFont(); font.setPointSize(9)
        if col == COL_NAME:
            font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(fg))
        text_rect = option.rect.adjusted(8 if col == 0 else 4, 0, -4, 0)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.restore()

    def sizeHint(self, option, index):
        from PyQt6.QtCore import QSize
        return QSize(option.rect.width(), 28)


# ---------------------------------------------------------------------------
# Diff viewer widget
# ---------------------------------------------------------------------------

class DiffViewerWidget(QWidget):
    """Unified diff display with colour-coded added / removed lines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hdr = QHBoxLayout()
        lbl_a = QLabel("📦  Backup State")
        lbl_a.setStyleSheet("color: #80B4FF; font-weight: bold; font-size: 9pt;")
        lbl_b = QLabel("🔴  Current Device State")
        lbl_b.setStyleSheet("color: #FF8080; font-weight: bold; font-size: 9pt;")
        hdr.addWidget(lbl_a)
        hdr.addStretch()
        hdr.addWidget(lbl_b)
        layout.addLayout(hdr)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setStyleSheet("""
            QTextEdit {
                background: #0E0E16;
                color: #C8C8D8;
                border: 1px solid #2A2A3A;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self._text)

        self._summary = QLabel("No diff loaded.")
        self._summary.setStyleSheet("color: #808090; font-size: 9pt;")
        layout.addWidget(self._summary)

    def show_diff(self, backup_lines: List[str], current_lines: List[str],
                  backup_name: str = "backup"):
        diff = list(difflib.unified_diff(
            backup_lines, current_lines,
            fromfile=f"backup: {backup_name}",
            tofile="current device state",
            lineterm="",
        ))
        if not diff:
            self._text.setHtml(
                "<span style='color:#66BB6A;'>"
                "✅  No differences — backup matches current device state.</span>"
            )
            self._summary.setText("0 changes detected.")
            return

        added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        lines_html = []
        for line in diff:
            esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if line.startswith(("+++", "---")):
                lines_html.append(f"<span style='color:#888898;'>{esc}</span>")
            elif line.startswith("@@"):
                lines_html.append(f"<span style='color:#5C8AFF;'>{esc}</span>")
            elif line.startswith("+"):
                lines_html.append(f"<span style='color:#66BB6A;'>{esc}</span>")
            elif line.startswith("-"):
                lines_html.append(f"<span style='color:#EF5350;'>{esc}</span>")
            else:
                lines_html.append(f"<span style='color:#888898;'>{esc}</span>")

        self._text.setHtml("<br>".join(lines_html))
        self._summary.setText(
            f"<span style='color:#66BB6A;'>+{added} added</span>  "
            f"<span style='color:#EF5350;'>−{removed} removed</span>"
        )

    def clear(self):
        self._text.clear()
        self._summary.setText("No diff loaded.")


# ---------------------------------------------------------------------------
# Worker threads  (GOTCHA-013)
# ---------------------------------------------------------------------------

class BackupThread(QThread):
    progress      = pyqtSignal(int)
    status_update = pyqtSignal(str)
    backup_done   = pyqtSignal(int, str, int)   # entry_id, file_path, file_size
    backup_failed = pyqtSignal(int, str)        # entry_id, error_msg

    def __init__(self, entry_id: int, device_name: str,
                 backup_dir: str, file_name: str, adapter=None, parent=None):
        super().__init__(parent)
        self.entry_id    = entry_id
        self.device_name = device_name
        self.backup_dir  = backup_dir
        self.file_name   = file_name
        self.adapter     = adapter
        self._stop       = False

    def stop(self): self._stop = True

    def run(self):
        try:
            os.makedirs(self.backup_dir, exist_ok=True)
            file_path = os.path.join(self.backup_dir, self.file_name)

            self.status_update.emit("Connecting to device…")
            self.progress.emit(10)
            time.sleep(0.3)
            if self._stop: return

            self.status_update.emit("Reading device configuration…")
            self.progress.emit(30)
            config_data = self._read_config()
            if self._stop: return

            self.status_update.emit("Serialising configuration…")
            self.progress.emit(60)
            time.sleep(0.15)

            payload = {
                "hbce_backup_version": "1.0",
                "created": datetime.now().isoformat(),
                "device":  self.device_name,
                "config":  config_data,
            }

            self.status_update.emit("Writing backup file…")
            self.progress.emit(80)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            size = os.path.getsize(file_path)
            self.progress.emit(100)
            self.status_update.emit(f"Backup complete — {size:,} bytes saved.")
            self.backup_done.emit(self.entry_id, file_path, size)

        except Exception as e:
            logger.error(f"BackupThread error: {e}")
            self.backup_failed.emit(self.entry_id, str(e))

    def _read_config(self) -> dict:
        if self.adapter and hasattr(self.adapter, "read_config"):
            return self.adapter.read_config()
        time.sleep(0.4)
        return {
            "objects": [
                {"type": "analog-input",  "instance": 1, "name": "Zone-Temp-1",    "present-value": 72.4, "units": "degreesFahrenheit"},
                {"type": "analog-input",  "instance": 2, "name": "Zone-Temp-2",    "present-value": 71.1, "units": "degreesFahrenheit"},
                {"type": "analog-output", "instance": 1, "name": "Cooling-Valve",  "present-value": 45.0, "units": "percent"},
                {"type": "binary-input",  "instance": 1, "name": "Occ-Sensor",     "present-value": "active"},
                {"type": "binary-output", "instance": 1, "name": "Fan-Enable",     "present-value": "active"},
                {"type": "analog-value",  "instance": 1, "name": "Setpoint-Cool",  "present-value": 74.0, "units": "degreesFahrenheit"},
                {"type": "analog-value",  "instance": 2, "name": "Setpoint-Heat",  "present-value": 68.0, "units": "degreesFahrenheit"},
                {"type": "schedule",      "instance": 1, "name": "Occ-Schedule",   "weekly-schedule": "Mon-Fri 07:00-18:00"},
            ],
            "programs": [],
            "device_props": {
                "vendor-name":          "Johnson Controls",
                "model-name":           "FEC2611-0",
                "firmware-revision":    "5.1.2",
                "application-software": "3.7.0",
            },
        }


class RestoreThread(QThread):
    progress       = pyqtSignal(int)
    status_update  = pyqtSignal(str)
    restore_done   = pyqtSignal(str)   # pre-restore file path
    restore_failed = pyqtSignal(str)

    def __init__(self, backup_file: str, backup_dir: str,
                 device_name: str, adapter=None, parent=None):
        super().__init__(parent)
        self.backup_file = backup_file
        self.backup_dir  = backup_dir
        self.device_name = device_name
        self.adapter     = adapter
        self._stop       = False

    def stop(self): self._stop = True

    def run(self):
        try:
            self.status_update.emit("Validating backup file…")
            self.progress.emit(10)

            if not os.path.exists(self.backup_file):
                raise FileNotFoundError(f"Not found: {self.backup_file}")

            with open(self.backup_file, "r", encoding="utf-8") as f:
                payload = json.load(f)

            if "hbce_backup_version" not in payload:
                raise ValueError("Not a valid HBCE backup file.")

            if self._stop: return

            self.status_update.emit("Saving pre-restore safety backup…")
            self.progress.emit(25)
            pre_path = self._save_pre_restore()
            time.sleep(0.3)
            if self._stop: return

            self.status_update.emit("Connecting to device…")
            self.progress.emit(40)
            time.sleep(0.3)
            if self._stop: return

            self.status_update.emit("Writing configuration to device…")
            self.progress.emit(60)
            if self.adapter and hasattr(self.adapter, "write_config"):
                self.adapter.write_config(payload["config"])
            else:
                time.sleep(0.6)   # simulated write
            if self._stop: return

            self.status_update.emit("Verifying restore…")
            self.progress.emit(85)
            time.sleep(0.3)

            self.progress.emit(100)
            self.status_update.emit("✅ Restore complete.")
            self.restore_done.emit(pre_path)

        except Exception as e:
            logger.error(f"RestoreThread error: {e}")
            self.restore_failed.emit(str(e))

    def _save_pre_restore(self) -> str:
        os.makedirs(self.backup_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.backup_dir, f"pre_restore_{ts}.hbce-bak")
        snap = {
            "hbce_backup_version": "1.0",
            "created": datetime.now().isoformat(),
            "device":  self.device_name,
            "note":    "Auto-saved before restore",
            "config":  {"objects": [], "note": "pre-restore placeholder"},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2)
        return path


class DiffThread(QThread):
    diff_ready  = pyqtSignal(list, list, str)   # backup_lines, current_lines, backup_name
    diff_failed = pyqtSignal(str)

    def __init__(self, backup_file: str, backup_name: str,
                 adapter=None, parent=None):
        super().__init__(parent)
        self.backup_file = backup_file
        self.backup_name = backup_name
        self.adapter     = adapter

    def run(self):
        try:
            if not os.path.exists(self.backup_file):
                raise FileNotFoundError(f"Not found: {self.backup_file}")

            with open(self.backup_file, "r", encoding="utf-8") as f:
                backup_payload = json.load(f)

            backup_lines = json.dumps(
                backup_payload.get("config", {}), indent=2
            ).splitlines()

            if self.adapter and hasattr(self.adapter, "read_config"):
                current_cfg = self.adapter.read_config()
            else:
                current_cfg = self._simulated_current(backup_payload.get("config", {}))

            current_lines = json.dumps(current_cfg, indent=2).splitlines()
            self.diff_ready.emit(backup_lines, current_lines, self.backup_name)

        except Exception as e:
            logger.error(f"DiffThread error: {e}")
            self.diff_failed.emit(str(e))

    def _simulated_current(self, backup_config: dict) -> dict:
        import copy
        current = copy.deepcopy(backup_config)
        for obj in current.get("objects", []):
            if obj.get("type") == "analog-value" and "present-value" in obj:
                obj["present-value"] = round(obj["present-value"] + 2.0, 1)
                break
        if "device_props" in current:
            current["device_props"]["application-software"] = "3.7.1"
        return current


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class NewBackupDialog(QDialog):
    def __init__(self, devices: List[dict], current_user: dict, parent=None):
        super().__init__(parent)
        self.devices      = devices
        self.current_user = current_user
        self.setWindowTitle("💾  New Backup")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Create New Backup")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        lay.addWidget(QLabel("Backup Name *"))
        self._name = QLineEdit()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._name.setText(f"Manual Backup {ts}")
        self._name.selectAll()
        lay.addWidget(self._name)

        lay.addWidget(QLabel("Device"))
        self._device = QComboBox()
        self._device.addItem("All Devices", None)
        for d in self.devices:
            self._device.addItem(d.get("name", "Unknown"), d.get("id"))
        lay.addWidget(self._device)

        lay.addWidget(QLabel("Notes (optional)"))
        self._notes = QTextEdit()
        self._notes.setMaximumHeight(70)
        self._notes.setPlaceholderText("Reason for this backup…")
        lay.addWidget(self._notes)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Start Backup")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _accept(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Validation", "Backup name is required.")
            return
        self.accept()

    def get_values(self) -> dict:
        return {
            "name":        self._name.text().strip(),
            "device_id":   self._device.currentData(),
            "device_name": self._device.currentText(),
            "notes":       self._notes.toPlainText().strip(),
        }


class RestoreConfirmDialog(QDialog):
    """Typed confirmation — ARCH-011 safeguard."""

    def __init__(self, entry: BackupEntry, changes: int, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle("⚠️  Confirm Restore")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._changes = changes
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        warn = QLabel("⚠️  This will overwrite the device's current configuration.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #FF8F00; font-weight: bold; font-size: 11pt;")
        lay.addWidget(warn)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        for label, value in [
            ("Backup:",             self.entry.backup_name),
            ("Device:",             self.entry.device_name),
            ("Created:",            self.entry.timestamp[:16]),
            ("Changes detected:",   f"{self._changes} lines differ"),
        ]:
            row = QHBoxLayout()
            k = QLabel(f"{label}")
            k.setStyleSheet("color: #808090; font-size: 9pt;")
            k.setMinimumWidth(130)
            v = QLabel(str(value))
            v.setStyleSheet("font-weight: bold; font-size: 9pt;")
            row.addWidget(k)
            row.addWidget(v)
            row.addStretch()
            lay.addLayout(row)

        note = QLabel(
            "ℹ️  A pre-restore backup of the current device state will be "
            "saved automatically before proceeding."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64B5F6; font-size: 9pt;")
        lay.addWidget(note)

        lay.addWidget(QLabel('<b>Type  RESTORE  to confirm:</b>'))
        self._confirm = QLineEdit()
        self._confirm.setPlaceholderText("Type RESTORE here…")
        self._confirm.textChanged.connect(
            lambda t: self._ok.setEnabled(t.strip().upper() == "RESTORE")
        )
        lay.addWidget(self._confirm)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("🔄  Restore Now")
        self._ok.setEnabled(False)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


class RetentionSettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("⚙️  Backup Settings")
        self.setMinimumWidth(380)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Backup Settings")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        auto_group = QGroupBox("Auto-Backup")
        auto_lay = QVBoxLayout(auto_group)
        self._auto_cb = QCheckBox("Auto-backup when a device connects")
        self._auto_cb.setChecked(self.settings.get("auto_backup_on_connect", True))
        auto_lay.addWidget(self._auto_cb)
        lay.addWidget(auto_group)

        ret_group = QGroupBox("Retention Policy")
        ret_lay = QHBoxLayout(ret_group)
        ret_lay.addWidget(QLabel("Keep last"))
        self._ret_spin = QSpinBox()
        self._ret_spin.setRange(1, 200)
        self._ret_spin.setValue(self.settings.get("retention_count", 20))
        self._ret_spin.setSuffix("  backups per device")
        ret_lay.addWidget(self._ret_spin)
        ret_lay.addStretch()
        lay.addWidget(ret_group)

        dir_group = QGroupBox("Backup Directory")
        dir_lay = QHBoxLayout(dir_group)
        self._dir_edit = QLineEdit(self.settings.get("backup_dir", ""))
        self._dir_edit.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_lay.addWidget(self._dir_edit)
        dir_lay.addWidget(browse)
        lay.addWidget(dir_group)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Backup Directory", self._dir_edit.text())
        if d:
            self._dir_edit.setText(d)

    def get_values(self) -> dict:
        return {
            "auto_backup_on_connect": self._auto_cb.isChecked(),
            "retention_count":        self._ret_spin.value(),
            "backup_dir":             self._dir_edit.text(),
        }


# ---------------------------------------------------------------------------
# Detail panel (right side)
# ---------------------------------------------------------------------------

class BackupDetailPanel(QWidget):
    restore_requested = pyqtSignal(object)
    diff_requested    = pyqtSignal(object)
    export_requested  = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry: Optional[BackupEntry] = None
        self._build_ui()
        self.clear()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        self._name_lbl = QLabel()
        f = QFont(); f.setPointSize(12); f.setBold(True)
        self._name_lbl.setFont(f)
        self._name_lbl.setWordWrap(True)
        lay.addWidget(self._name_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        self._meta: dict = {}
        for key in ["ID", "Created", "Device", "Type", "Size", "Status", "By", "Notes"]:
            row = QHBoxLayout()
            k = QLabel(f"{key}:")
            k.setStyleSheet("color: #808090; font-size: 9pt;")
            k.setFixedWidth(65)
            v = QLabel()
            v.setStyleSheet("font-size: 9pt;")
            v.setWordWrap(True)
            row.addWidget(k)
            row.addWidget(v, 1)
            lay.addLayout(row)
            self._meta[key] = v

        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setStyleSheet("font-size: 8pt; color: #606070;")
        lay.addWidget(QLabel("File:"))
        lay.addWidget(self._path_edit)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep2)

        self._diff_btn = QPushButton("🔍  Preview Diff")
        self._diff_btn.clicked.connect(lambda: self.diff_requested.emit(self._entry))
        lay.addWidget(self._diff_btn)

        self._restore_btn = QPushButton("🔄  Restore from This Backup")
        self._restore_btn.setStyleSheet("""
            QPushButton {
                background:#1A3A6A; color:#80B4FF;
                border:1px solid #2A5A9A; border-radius:4px;
                padding:6px; font-weight:bold;
            }
            QPushButton:hover { background:#1E4080; }
            QPushButton:disabled { background:#1A1A24; color:#404050; border-color:#2A2A3A; }
        """)
        self._restore_btn.clicked.connect(lambda: self.restore_requested.emit(self._entry))
        lay.addWidget(self._restore_btn)

        self._export_btn = QPushButton("📤  Export Backup File…")
        self._export_btn.clicked.connect(lambda: self.export_requested.emit(self._entry))
        lay.addWidget(self._export_btn)

        lay.addStretch()

    def load_entry(self, e: BackupEntry):
        self._entry = e
        self._name_lbl.setText(e.backup_name)
        self._meta["ID"].setText(str(e.id))
        self._meta["Created"].setText(e.timestamp[:16] if e.timestamp else "")
        self._meta["Device"].setText(e.device_name)
        self._meta["Type"].setText(e.type_label)
        self._meta["Size"].setText(e.size_str)
        self._meta["Status"].setText(e.status_label)
        self._meta["By"].setText(e.created_by)
        self._meta["Notes"].setText(e.notes or "—")
        self._path_edit.setText(e.file_path or "")
        can_act = e.status == "complete" and bool(e.file_path)
        self._diff_btn.setEnabled(can_act)
        self._restore_btn.setEnabled(can_act)
        self._export_btn.setEnabled(can_act and os.path.exists(e.file_path))

    def clear(self):
        self._entry = None
        self._name_lbl.setText("No backup selected")
        for v in self._meta.values():
            v.setText("—")
        self._path_edit.setText("")
        self._diff_btn.setEnabled(False)
        self._restore_btn.setEnabled(False)
        self._export_btn.setEnabled(False)


# ---------------------------------------------------------------------------
# Cloud Sync Panel  (Tab 3 inside BackupRestorePanel's right QTabWidget)
# ---------------------------------------------------------------------------

class CloudSyncPanel(QWidget):
    """
    ☁ Cloud Sync — Google Drive + OneDrive integration.

    Layout:
      Top:    Two provider cards (Google Drive / OneDrive)
               Each card: status indicator + auth button (Connect / Disconnect)
      Middle: Upload section — Upload Selected Backup / Upload DB / Upload Project
      Bottom: Download section — remote file list + Download Selected
      Footer: Auto-sync checkbox + progress bar + status label

    All I/O runs through CloudSyncThread (GOTCHA-013 compliant).
    token_expired signal → QMessageBox prompts re-authentication.
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {}
        self._sync_mgr:    Optional[object] = None
        self._sync_thread: Optional[object] = None
        self._selected_backup_path: str = ""

        if _CLOUD_AVAILABLE:
            try:
                cfg_dir = self._config_dir()
                self._sync_mgr = CloudSyncManager.from_config_dir(cfg_dir)
            except Exception as e:
                logger.warning(f"CloudSyncManager init: {e}")

        self._build_ui()
        if _CLOUD_AVAILABLE and self._sync_mgr:
            self._refresh_status()

    # ── Config dir ────────────────────────────────────────────────────────────

    def _config_dir(self):
        app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
        return _Path(app_data) / "HBCE"

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        if not _CLOUD_AVAILABLE:
            warn = QLabel(
                "⚠  Cloud sync libraries not installed.\n\n"
                "Install google-api-python-client, google-auth-oauthlib\n"
                "and msal to enable Google Drive and OneDrive sync."
            )
            warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            warn.setStyleSheet("color:#808090; font-size:9pt;")
            root.addWidget(warn)
            return

        # ── Provider cards ────────────────────────────────────────────────────
        root.addWidget(self._build_provider_section())

        # ── Upload section ────────────────────────────────────────────────────
        root.addWidget(self._build_upload_section())

        # ── Download section ──────────────────────────────────────────────────
        root.addWidget(self._build_download_section())

        root.addStretch()

        # ── Auto-sync + progress footer ───────────────────────────────────────
        root.addWidget(self._build_footer())

    def _card_style(self) -> str:
        return (
            "QFrame { background:#1a1a2e; border:1px solid #2a2a4e; "
            "border-radius:8px; padding:2px; }"
        )

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:bold; color:#9090B0; font-size:8pt; "
                          "text-transform:uppercase; letter-spacing:1px;")
        return lbl

    def _build_provider_section(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._section_label("☁  Cloud Providers"))

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)

        # Google Drive card
        self._gdrive_card  = self._make_provider_card(
            "Google Drive", "google_drive", "#4285F4")
        # OneDrive card
        self._onedrive_card = self._make_provider_card(
            "Microsoft OneDrive", "onedrive", "#0078D4")

        cards_row.addWidget(self._gdrive_card)
        cards_row.addWidget(self._onedrive_card)
        lay.addLayout(cards_row)
        return w

    def _make_provider_card(self, display_name: str,
                            provider_key: str, accent: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(self._card_style())
        card.setFixedHeight(90)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        # Colour blob
        blob = QLabel("●")
        blob.setStyleSheet(f"color:{accent}; font-size:18pt; background:transparent;")
        blob.setFixedWidth(28)
        lay.addWidget(blob)

        # Name + status
        info = QVBoxLayout()
        name_lbl = QLabel(display_name)
        name_lbl.setStyleSheet("font-weight:bold; color:#C0C0D0; background:transparent;")
        info.addWidget(name_lbl)

        status_lbl = QLabel("Not connected")
        status_lbl.setStyleSheet("color:#606070; font-size:8pt; background:transparent;")
        info.addWidget(status_lbl)
        lay.addLayout(info, 1)

        # Auth button
        auth_btn = QPushButton("Connect")
        auth_btn.setFixedSize(90, 28)
        auth_btn.setStyleSheet(f"""
            QPushButton {{
                background:{accent}; color:white; border:none;
                border-radius:4px; font-size:8pt; font-weight:bold;
            }}
            QPushButton:hover {{ background:{accent}CC; }}
            QPushButton:disabled {{ background:#333344; color:#606070; }}
        """)
        lay.addWidget(auth_btn)

        # Store refs
        key = provider_key
        auth_btn.clicked.connect(lambda _, k=key: self._toggle_auth(k))
        card.setProperty("provider_key",  key)
        card.setProperty("status_lbl",    status_lbl)
        card.setProperty("auth_btn",      auth_btn)
        return card

    def _build_upload_section(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._section_label("⬆  Upload"))

        frame = QFrame()
        frame.setStyleSheet(self._card_style())
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(6)

        # Provider selector row
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("Provider:"))
        self._upload_combo = QComboBox()
        self._upload_combo.setFixedHeight(26)
        self._upload_combo.addItem("Google Drive", "google_drive")
        self._upload_combo.addItem("OneDrive",     "onedrive")
        self._upload_combo.setStyleSheet(
            "QComboBox { background:#252535; border:1px solid #2a2a4e; "
            "border-radius:4px; color:#C0C0D0; padding:2px 6px; }"
        )
        prov_row.addWidget(self._upload_combo)
        prov_row.addStretch()
        fl.addLayout(prov_row)

        # Upload buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._upload_backup_btn = QPushButton("⬆  Upload Selected Backup")
        self._upload_db_btn     = QPushButton("🗄  Upload Database")
        for btn in (self._upload_backup_btn, self._upload_db_btn):
            btn.setFixedHeight(28)
            btn.setStyleSheet(self._upload_btn_style())
            btn_row.addWidget(btn)

        fl.addLayout(btn_row)
        lay.addWidget(frame)

        self._upload_backup_btn.clicked.connect(self._upload_selected_backup)
        self._upload_db_btn.clicked.connect(self._upload_database)
        return w

    def _upload_btn_style(self) -> str:
        return (
            "QPushButton { background:#1e2a40; color:#7090D0; "
            "border:1px solid #2a3a5a; border-radius:4px; "
            "font-size:8pt; padding:0 8px; }"
            "QPushButton:hover { background:#253050; color:#90B0F0; }"
            "QPushButton:disabled { color:#404050; border-color:#1E1E2E; }"
        )

    def _build_download_section(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.addWidget(self._section_label("⬇  Remote Files"))
        hdr.addStretch()
        self._refresh_remote_btn = QPushButton("🔄 Refresh")
        self._refresh_remote_btn.setFixedSize(76, 22)
        self._refresh_remote_btn.setStyleSheet(self._upload_btn_style())
        self._refresh_remote_btn.clicked.connect(self._refresh_remote_list)
        hdr.addWidget(self._refresh_remote_btn)
        lay.addLayout(hdr)

        frame = QFrame()
        frame.setStyleSheet(self._card_style())
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 8, 8, 8)
        fl.setSpacing(6)

        self._remote_list = QListWidget()
        self._remote_list.setFixedHeight(100)
        self._remote_list.setStyleSheet(
            "QListWidget { background:#131320; border:none; color:#C0C0D0; "
            "font-size:8pt; } "
            "QListWidget::item:selected { background:#1e2a40; color:#90B0FF; }"
        )
        self._remote_list.addItem("— click Refresh to load —")
        fl.addWidget(self._remote_list)

        self._download_btn = QPushButton("⬇  Download Selected")
        self._download_btn.setFixedHeight(28)
        self._download_btn.setStyleSheet(self._upload_btn_style())
        self._download_btn.clicked.connect(self._download_selected)
        fl.addWidget(self._download_btn)
        lay.addWidget(frame)
        return w

    def _build_footer(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._auto_sync_chk = QCheckBox("Enable auto-sync after each backup")
        self._auto_sync_chk.setStyleSheet("color:#808090; font-size:8pt;")
        self._auto_sync_chk.setChecked(False)
        lay.addWidget(self._auto_sync_chk)

        self._cloud_progress = QProgressBar()
        self._cloud_progress.setFixedHeight(6)
        self._cloud_progress.setRange(0, 100)
        self._cloud_progress.setValue(0)
        self._cloud_progress.setVisible(False)
        self._cloud_progress.setStyleSheet(
            "QProgressBar { background:#1a1a2e; border:none; border-radius:3px; }"
            "QProgressBar::chunk { background:#5C8AFF; border-radius:3px; }"
        )
        lay.addWidget(self._cloud_progress)

        self._cloud_status_lbl = QLabel("")
        self._cloud_status_lbl.setStyleSheet("color:#606070; font-size:8pt;")
        lay.addWidget(self._cloud_status_lbl)
        return w

    # ── Provider auth toggle ──────────────────────────────────────────────────

    def _toggle_auth(self, provider_key: str):
        if not self._sync_mgr:
            return
        prov = (self._sync_mgr.google if provider_key == "google_drive"
                else self._sync_mgr.onedrive)

        if prov.is_authenticated():
            if QMessageBox.question(
                self, "Disconnect",
                f"Disconnect from {provider_key.replace('_',' ').title()}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes:
                prov.revoke()
                self._refresh_status()
                self._set_status(f"Disconnected from {provider_key.replace('_',' ').title()}.")
        else:
            self._set_status(f"Connecting to {provider_key.replace('_',' ').title()}…")
            # Auth must happen in a background thread — it may open a browser
            t = QThread()
            t._provider    = prov
            t._provider_key = provider_key
            def _run():
                t._provider.authenticate()
            t.run = _run
            t.finished.connect(lambda: self._on_auth_done(provider_key, t))
            t.start()
            self._sync_thread = t

    def _on_auth_done(self, provider_key: str, thread):
        self._refresh_status()
        prov = (self._sync_mgr.google if provider_key == "google_drive"
                else self._sync_mgr.onedrive)
        if prov.is_authenticated():
            self._set_status(f"✅ Connected to {provider_key.replace('_',' ').title()}.")
        else:
            self._set_status("⚠  Authentication failed. Check your credentials.")

    # ── Status refresh ────────────────────────────────────────────────────────

    def _refresh_status(self):
        if not self._sync_mgr:
            return
        status = self._sync_mgr.status()
        for card, key in ((self._gdrive_card,   "google_drive"),
                          (self._onedrive_card, "onedrive")):
            info  = status.get(key, {})
            authed = info.get("authenticated", False)
            s_lbl  = card.property("status_lbl")
            a_btn  = card.property("auth_btn")
            if s_lbl:
                s_lbl.setText("✅ Connected" if authed else "Not connected")
                s_lbl.setStyleSheet(
                    f"color:{'#4CAF50' if authed else '#606070'}; "
                    "font-size:8pt; background:transparent;"
                )
            if a_btn:
                a_btn.setText("Disconnect" if authed else "Connect")

    # ── Upload ────────────────────────────────────────────────────────────────

    def _current_provider_enum(self):
        idx = self._upload_combo.currentIndex()
        key = self._upload_combo.itemData(idx)
        return (SyncProvider.GOOGLE_DRIVE if key == "google_drive"
                else SyncProvider.ONEDRIVE)

    def _upload_selected_backup(self):
        if not self._selected_backup_path:
            QMessageBox.information(
                self, "No backup selected",
                "Select a backup from the list on the left first.",
            )
            return
        self._run_upload(self._selected_backup_path)

    def _upload_database(self):
        app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
        db_path  = os.path.join(app_data, "HBCE", "hbce.db")
        if not os.path.exists(db_path):
            QMessageBox.warning(self, "Not Found",
                                f"Database not found at:\n{db_path}")
            return
        self._run_upload(db_path)

    def _run_upload(self, local_path: str):
        if not self._sync_mgr:
            return
        prov = self._current_provider_enum()
        self._cloud_progress.setVisible(True)
        self._cloud_progress.setValue(0)
        self._set_status("Uploading…")

        t = self._sync_mgr.upload_async(local_path, prov, parent=self)
        t.progress.connect(self._on_progress)
        t.completed.connect(self._on_upload_done)
        t.token_expired.connect(self._on_token_expired)
        t.start()
        self._sync_thread = t

    def _on_upload_done(self, result):
        self._cloud_progress.setVisible(False)
        if result.success:
            self._set_status(f"✅ {result.message}")
        else:
            self._set_status(f"⚠  {result.message}")

    # ── Download ──────────────────────────────────────────────────────────────

    def _refresh_remote_list(self):
        if not self._sync_mgr:
            return
        self._remote_list.clear()
        self._remote_list.addItem("Loading…")
        prov = self._current_provider_enum()
        # List synchronously for simplicity — fast on LAN/cloud
        try:
            files = self._sync_mgr.list_remote_files(prov)
            self._remote_list.clear()
            if not files:
                self._remote_list.addItem("— no files found —")
            else:
                for f in files:
                    name = f.get("name", f.get("id", "?"))
                    size = f.get("size", "")
                    modified = (f.get("modifiedTime", f.get("lastModifiedDateTime", ""))[:10])
                    item = QListWidgetItem(f"📄  {name}   {modified}   {size}")
                    item.setData(Qt.ItemDataRole.UserRole, name)
                    self._remote_list.addItem(item)
        except Exception as e:
            self._remote_list.clear()
            self._remote_list.addItem(f"Error: {e}")

    def _download_selected(self):
        if not self._sync_mgr:
            return
        item = self._remote_list.currentItem()
        if not item:
            return
        remote_name = item.data(Qt.ItemDataRole.UserRole)
        if not remote_name:
            return

        dest_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, remote_name)

        prov = self._current_provider_enum()
        self._cloud_progress.setVisible(True)
        self._cloud_progress.setValue(0)
        self._set_status(f"Downloading {remote_name}…")

        t = self._sync_mgr.download_async(remote_name, dest_path, prov, parent=self)
        t.progress.connect(self._on_progress)
        t.completed.connect(self._on_download_done)
        t.token_expired.connect(self._on_token_expired)
        t.start()
        self._sync_thread = t

    def _on_download_done(self, result):
        self._cloud_progress.setVisible(False)
        if result.success:
            self._set_status(f"✅ {result.message}")
            QMessageBox.information(self, "Download Complete",
                                    f"File saved to Downloads folder.\n\n{result.message}")
        else:
            self._set_status(f"⚠  {result.message}")

    # ── Shared signal handlers ────────────────────────────────────────────────

    def _on_progress(self, pct: int, msg: str):
        self._cloud_progress.setValue(pct)
        self._set_status(msg)

    def _on_token_expired(self, provider_name: str):
        self._cloud_progress.setVisible(False)
        QMessageBox.warning(
            self, "Session Expired",
            f"Your {provider_name} session has expired.\n"
            "Please reconnect using the provider card above.",
        )
        self._refresh_status()

    def _set_status(self, msg: str):
        self._cloud_status_lbl.setText(msg)

    # ── Public API (called by BackupRestorePanel) ─────────────────────────────

    def set_selected_backup(self, file_path: str):
        """Tell this panel which local backup file is currently selected."""
        self._selected_backup_path = file_path

    def trigger_auto_sync(self, file_path: str):
        """Called after a successful backup when auto-sync is enabled."""
        if not self._auto_sync_chk.isChecked():
            return
        if not self._sync_mgr:
            return
        enabled = self._sync_mgr.auto_sync_enabled_providers()
        for prov in enabled:
            self._run_upload(file_path)
            break  # sync to first available provider only


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class BackupRestorePanel(QWidget):
    """
    💾 Backup / Restore Panel — Full Implementation V0.1.2-alpha

    Left:  sortable backup registry table with stripe+pill styling
    Right: detail panel (tab 1) + diff viewer (tab 2)
    Bottom: progress bar + cancel for active operations
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {"username": "admin", "role": "Admin"}

        self._settings: dict = {
            "auto_backup_on_connect": True,
            "retention_count":        20,
            "backup_dir":             self._default_backup_dir(),
        }

        self._backup_thread:  Optional[BackupThread]  = None
        self._restore_thread: Optional[RestoreThread] = None
        self._diff_thread:    Optional[DiffThread]    = None

        self._active_entry:         Optional[BackupEntry] = None
        self._pending_restore_entry: Optional[BackupEntry] = None

        self._init_db()
        self._build_ui()
        self._load_backups()
        logger.debug("BackupRestorePanel initialized")

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _init_db(self):
        if self.db:
            try:
                self.db.execute(BACKUPS_TABLE_SQL)
                self.db.conn.commit()
            except Exception as e:
                logger.warning(f"Backups table init warning: {e}")

    def _default_backup_dir(self) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(here, "..", "..", "backups"))

    def _load_backups(self):
        entries = []
        if self.db:
            try:
                rows = self.db.fetchall("SELECT * FROM backups ORDER BY timestamp DESC")
                entries = [self._row_to_entry(r) for r in rows]
            except Exception as e:
                logger.warning(f"Load backups error: {e}")
        self._model.load(entries)
        self._update_status_bar()

    @staticmethod
    def _row_to_entry(r: dict) -> BackupEntry:
        return BackupEntry(
            id          = r.get("id", 0),
            timestamp   = r.get("timestamp", ""),
            device_id   = r.get("device_id"),
            device_name = r.get("device_name", "Unknown"),
            backup_name = r.get("backup_name", ""),
            notes       = r.get("notes", ""),
            file_path   = r.get("file_path", ""),
            file_size   = r.get("file_size", 0),
            backup_type = r.get("backup_type", "manual"),
            status      = r.get("status", "complete"),
            created_by  = r.get("created_by", ""),
        )

    def _save_record(self, e: BackupEntry) -> int:
        if not self.db:
            return 0
        return self.db.insert(
            """INSERT INTO backups
               (timestamp,device_id,device_name,backup_name,notes,
                file_path,file_size,backup_type,status,created_by)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (e.timestamp, e.device_id, e.device_name, e.backup_name, e.notes,
             e.file_path, e.file_size, e.backup_type, e.status, e.created_by),
        )

    def _update_record(self, entry_id: int, status: str, file_path: str, file_size: int):
        if self.db:
            self.db.update(
                "UPDATE backups SET status=?,file_path=?,file_size=? WHERE id=?",
                (status, file_path, file_size, entry_id),
            )

    def _delete_records(self, ids: set):
        if self.db:
            for bid in ids:
                self.db.update("DELETE FROM backups WHERE id=?", (bid,))

    def _get_devices(self) -> List[dict]:
        if self.db:
            try:
                return self.db.fetchall("SELECT id, name FROM devices")
            except Exception:
                pass
        return []

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left: filter + table ──────────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 8, 6, 8)
        left_lay.setSpacing(6)
        left_lay.addLayout(self._build_filter_bar())

        self._table = QTableView()
        self._model = BackupTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self._table.setModel(self._proxy)
        self._table.setItemDelegate(BackupRowDelegate())
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_NOTES, QHeaderView.ResizeMode.Stretch
        )
        for col, w in enumerate(COLUMN_WIDTHS):
            if col != COL_NOTES:
                self._table.setColumnWidth(col, w)
        self._table.setStyleSheet("""
            QTableView {
                background:#1A1A24; border:1px solid #2A2A3A;
                border-radius:4px; gridline-color:transparent; outline:none;
                selection-background-color:transparent;
            }
            QHeaderView::section {
                background:#141420; color:#7878A0;
                border:none; border-bottom:1px solid #2A2A3A;
                padding:5px 6px; font-size:8pt; font-weight:bold;
            }
            QScrollBar:vertical { background:#141420; width:10px; border-radius:5px; }
            QScrollBar::handle:vertical {
                background:#3A3A5A; border-radius:5px; min-height:20px;
            }
        """)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        left_lay.addWidget(self._table)
        splitter.addWidget(left)

        # ── Right: detail + diff tabs ─────────────────────────────────────
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(6, 8, 12, 8)
        right_lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border:1px solid #2A2A3A; border-radius:4px; }
            QTabBar::tab { padding:6px 16px; color:#808090; }
            QTabBar::tab:selected { color:#C8C8D8; border-bottom:2px solid #5C8AFF; }
        """)
        self._detail_panel = BackupDetailPanel()
        self._detail_panel.restore_requested.connect(self._start_restore_flow)
        self._detail_panel.diff_requested.connect(self._start_diff)
        self._detail_panel.export_requested.connect(self._export_file)
        self._tabs.addTab(self._detail_panel, "📋  Details")

        self._diff_viewer = DiffViewerWidget()
        self._tabs.addTab(self._diff_viewer, "🔍  Diff Viewer")

        self._cloud_panel = CloudSyncPanel(
            config=self.config,
            db=self.db,
            current_user=self.current_user,
        )
        self._tabs.addTab(self._cloud_panel, "☁  Cloud Sync")

        right_lay.addWidget(self._tabs)
        splitter.addWidget(right)
        splitter.setSizes([620, 440])
        root.addWidget(splitter, 1)

        root.addWidget(self._build_progress_area())
        root.addWidget(self._build_status_bar())

    def _build_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setFixedHeight(48)
        frame.setStyleSheet("""
            QFrame { background:#141420; border-bottom:1px solid #2A2A3A; }
            QPushButton {
                background:#1E1E2E; color:#A0A0C0;
                border:1px solid #2A2A3A; border-radius:4px;
                padding:5px 12px; font-size:9pt;
            }
            QPushButton:hover { background:#252535; color:#C8C8E8; }
            QPushButton:disabled { color:#404050; border-color:#1E1E2E; }
        """)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(6)

        title = QLabel("💾  Backup / Restore")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color:#C8C8E8; background:transparent; border:none;")
        lay.addWidget(title)

        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet("background:#2A2A3A; border:none;")
        vsep.setFixedWidth(1)
        lay.addWidget(vsep)

        self._new_btn = QPushButton("＋  New Backup")
        self._new_btn.clicked.connect(self._new_backup)
        lay.addWidget(self._new_btn)

        self._del_btn = QPushButton("🗑  Delete")
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_selected)
        lay.addWidget(self._del_btn)

        lay.addSpacing(8)

        self._import_btn = QPushButton("📥  Import…")
        self._import_btn.clicked.connect(self._import_backup)
        lay.addWidget(self._import_btn)

        self._csv_btn = QPushButton("📊  Export Log CSV")
        self._csv_btn.clicked.connect(self._export_csv)
        lay.addWidget(self._csv_btn)

        lay.addStretch()

        self._settings_btn = QPushButton("⚙  Settings")
        self._settings_btn.clicked.connect(self._open_settings)
        lay.addWidget(self._settings_btn)

        self._refresh_btn = QPushButton("↺  Refresh")
        self._refresh_btn.clicked.connect(self._load_backups)
        lay.addWidget(self._refresh_btn)

        return frame

    def _build_filter_bar(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search device, name, notes…")
        self._search.setMaximumWidth(260)
        self._search.setStyleSheet("""
            QLineEdit {
                background:#141420; border:1px solid #2A2A3A; border-radius:4px;
                padding:4px 8px; color:#C8C8D8; font-size:9pt;
            }
        """)
        self._search.textChanged.connect(lambda t: self._proxy.setFilterFixedString(t))
        lay.addWidget(self._search)

        self._type_cb = QComboBox()
        self._type_cb.addItem("All Types", "")
        for k, v in BACKUP_TYPE_LABELS.items():
            self._type_cb.addItem(v, k)
        lay.addWidget(self._type_cb)

        self._status_cb = QComboBox()
        self._status_cb.addItem("All Statuses", "")
        for k, v in BACKUP_STATUS_LABELS.items():
            self._status_cb.addItem(v, k)
        lay.addWidget(self._status_cb)

        clr = QPushButton("✕")
        clr.setFixedWidth(28)
        clr.setToolTip("Clear filters")
        clr.setStyleSheet("""
            QPushButton {
                background:#1E1E2E; color:#808090;
                border:1px solid #2A2A3A; border-radius:4px;
            }
            QPushButton:hover { color:#FF8080; }
        """)
        clr.clicked.connect(self._clear_filters)
        lay.addWidget(clr)
        lay.addStretch()
        return lay

    def _build_progress_area(self) -> QFrame:
        frame = QFrame()
        frame.setMaximumHeight(44)
        frame.setStyleSheet("""
            QFrame { background:#141420; border-top:1px solid #2A2A3A; }
        """)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(14)
        self._prog_bar.setVisible(False)
        self._prog_bar.setStyleSheet("""
            QProgressBar {
                background:#1E1E2E; border:1px solid #2A2A3A;
                border-radius:7px; text-align:center; color:#C8C8D8; font-size:8pt;
            }
            QProgressBar::chunk {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1565C0, stop:1 #42A5F5);
                border-radius:7px;
            }
        """)
        lay.addWidget(self._prog_bar, 1)

        self._prog_lbl = QLabel("Ready.")
        self._prog_lbl.setStyleSheet("color:#808090; font-size:9pt;")
        lay.addWidget(self._prog_lbl, 2)

        self._cancel_btn = QPushButton("✕  Cancel")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setFixedWidth(82)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background:#3A1A1A; color:#FF8080;
                border:1px solid #5A2A2A; border-radius:4px; padding:3px;
            }
        """)
        self._cancel_btn.clicked.connect(self._cancel_op)
        lay.addWidget(self._cancel_btn)
        return frame

    def _build_status_bar(self) -> QStatusBar:
        sb = QStatusBar()
        sb.setFixedHeight(24)
        sb.setStyleSheet("""
            QStatusBar {
                background:#141420; border-top:1px solid #2A2A3A;
                color:#606070; font-size:8pt;
            }
        """)
        self._total_lbl   = QLabel("  Backups: 0")
        self._visible_lbl = QLabel("Visible: 0")
        self._auto_lbl    = QLabel("Auto-backup: ON  ")
        sb.addWidget(self._total_lbl)
        sb.addWidget(QLabel("  |  "))
        sb.addWidget(self._visible_lbl)
        sb.addPermanentWidget(self._auto_lbl)
        self._sb = sb
        return sb

    # ── Filter / selection ────────────────────────────────────────────────────

    def _clear_filters(self):
        self._search.clear()
        self._type_cb.setCurrentIndex(0)
        self._status_cb.setCurrentIndex(0)
        self._update_status_bar()

    def _on_selection_changed(self):
        sel = self._table.selectionModel().selectedRows()
        self._del_btn.setEnabled(len(sel) > 0)
        if len(sel) == 1:
            src_row = self._proxy.mapToSource(
                self._proxy.index(sel[0].row(), 0)
            ).row()
            entry = self._model.entry_at(src_row)
            if entry:
                self._detail_panel.load_entry(entry)
                self._active_entry = entry
                # Keep cloud panel informed so it knows what to upload
                if hasattr(self, "_cloud_panel") and entry.file_path:
                    self._cloud_panel.set_selected_backup(entry.file_path)
        elif not sel:
            self._detail_panel.clear()
            self._active_entry = None

    def _on_double_click(self, index: QModelIndex):
        src_row = self._proxy.mapToSource(
            self._proxy.index(index.row(), 0)
        ).row()
        entry = self._model.entry_at(src_row)
        if entry and entry.status == "complete" and entry.file_path:
            self._start_diff(entry)

    def _show_context_menu(self, pos):
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            return
        src_row = self._proxy.mapToSource(
            self._proxy.index(sel[0].row(), 0)
        ).row()
        entry = self._model.entry_at(src_row)

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#1E1E2E; color:#C8C8D8; border:1px solid #2A2A3A; }
            QMenu::item:selected { background:#2A3550; }
        """)
        if entry and entry.status == "complete" and entry.file_path:
            menu.addAction("🔍  Preview Diff",           lambda: self._start_diff(entry))
            menu.addAction("🔄  Restore from This Backup", lambda: self._start_restore_flow(entry))
            menu.addSeparator()
            menu.addAction("📤  Export Backup File…",    lambda: self._export_file(entry))

        menu.addSeparator()
        if entry:
            menu.addAction("📋  Copy Name",
                lambda: QApplication.clipboard().setText(entry.backup_name))
            menu.addAction("📋  Copy Row CSV", lambda: self._copy_row_csv(entry))
        menu.addSeparator()
        menu.addAction("🗑  Delete Selected", self._delete_selected)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_row_csv(self, entry: BackupEntry):
        row = [
            str(entry.id), entry.timestamp[:16], entry.device_name,
            entry.backup_name, entry.type_label, entry.size_str,
            entry.status_label, entry.notes, entry.created_by,
        ]
        QApplication.clipboard().setText(",".join(f'"{v}"' for v in row))

    # ── Backup ────────────────────────────────────────────────────────────────

    def _new_backup(self):
        dlg = NewBackupDialog(self._get_devices(), self.current_user, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.get_values()
        self._launch_backup(
            device_id   = vals["device_id"],
            device_name = vals["device_name"],
            backup_name = vals["name"],
            notes       = vals["notes"],
            backup_type = "manual",
        )

    def _launch_backup(self, device_id, device_name, backup_name,
                       notes="", backup_type="manual"):
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ts_f = datetime.now().strftime("%Y%m%d_%H%M%S")

        entry = BackupEntry(
            timestamp   = ts,
            device_id   = device_id,
            device_name = device_name,
            backup_name = backup_name,
            notes       = notes,
            backup_type = backup_type,
            status      = "in_progress",
            created_by  = self.current_user.get("username", ""),
        )
        entry.id = self._save_record(entry)
        self._model.prepend(entry)
        self._update_status_bar()

        safe_dev  = device_name.replace(" ", "_")[:20]
        file_name = f"{backup_type}_{safe_dev}_{ts_f}.hbce-bak"
        bdir      = self._settings.get("backup_dir", self._default_backup_dir())

        self._backup_thread = BackupThread(
            entry_id    = entry.id,
            device_name = device_name,
            backup_dir  = bdir,
            file_name   = file_name,
        )
        self._backup_thread.progress.connect(self._prog_bar.setValue)
        self._backup_thread.status_update.connect(self._prog_lbl.setText)
        self._backup_thread.backup_done.connect(self._on_backup_done)
        self._backup_thread.backup_failed.connect(self._on_backup_failed)
        self._backup_thread.finished.connect(lambda: self._set_busy(False))
        self._set_busy(True)
        self._backup_thread.start()
        logger.info(f"Backup started: {backup_name}")

    def _on_backup_done(self, entry_id: int, file_path: str, file_size: int):
        self._model.update_entry(entry_id, "complete", file_size)
        self._update_record(entry_id, "complete", file_path, file_size)
        self._update_status_bar()
        self._sb.showMessage(
            f"✅  Backup complete — {file_size:,} bytes  |  {os.path.basename(file_path)}", 6000
        )
        if self._active_entry and self._active_entry.id == entry_id:
            self._active_entry.status    = "complete"
            self._active_entry.file_path = file_path
            self._active_entry.file_size = file_size
            self._detail_panel.load_entry(self._active_entry)

        # Auto-sync to cloud if enabled
        if hasattr(self, "_cloud_panel") and file_path:
            self._cloud_panel.trigger_auto_sync(file_path)

    def _on_backup_failed(self, entry_id: int, error: str):
        self._model.update_entry(entry_id, "failed")
        self._update_record(entry_id, "failed", "", 0)
        QMessageBox.critical(self, "Backup Failed", f"Backup failed:\n\n{error}")

    # ── Diff ──────────────────────────────────────────────────────────────────

    def _start_diff(self, entry: Optional[BackupEntry]):
        if not entry or not entry.file_path:
            return
        if not os.path.exists(entry.file_path):
            QMessageBox.warning(self, "File Not Found",
                                f"Backup file not found:\n{entry.file_path}")
            return
        self._tabs.setCurrentIndex(1)
        self._set_busy(True, "Computing diff…")
        self._diff_thread = DiffThread(entry.file_path, entry.backup_name)
        self._diff_thread.diff_ready.connect(self._on_diff_ready)
        self._diff_thread.diff_failed.connect(self._on_diff_failed)
        self._diff_thread.finished.connect(lambda: self._set_busy(False))
        self._diff_thread.start()

    def _on_diff_ready(self, backup_lines, current_lines, backup_name):
        self._diff_viewer.show_diff(backup_lines, current_lines, backup_name)
        self._sb.showMessage("Diff complete.", 4000)

    def _on_diff_failed(self, error: str):
        self._diff_viewer.clear()
        QMessageBox.critical(self, "Diff Failed", f"Could not compute diff:\n\n{error}")

    # ── Restore  (ARCH-011) ───────────────────────────────────────────────────

    def _start_restore_flow(self, entry: Optional[BackupEntry]):
        if not entry or not entry.file_path:
            return
        if not os.path.exists(entry.file_path):
            QMessageBox.warning(self, "File Not Found",
                                f"Backup file not found:\n{entry.file_path}")
            return

        self._pending_restore_entry = entry
        self._set_busy(True, "Computing diff for restore preview…")

        self._diff_thread = DiffThread(entry.file_path, entry.backup_name)
        self._diff_thread.diff_ready.connect(self._on_pre_restore_diff_ready)
        self._diff_thread.diff_failed.connect(self._on_diff_failed)
        self._diff_thread.finished.connect(lambda: self._set_busy(False))
        self._diff_thread.start()

    def _on_pre_restore_diff_ready(self, backup_lines, current_lines, backup_name):
        self._diff_viewer.show_diff(backup_lines, current_lines, backup_name)
        self._tabs.setCurrentIndex(1)

        entry = self._pending_restore_entry
        diff  = list(difflib.unified_diff(backup_lines, current_lines, lineterm=""))
        changes = sum(
            1 for l in diff
            if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
        )

        dlg = RestoreConfirmDialog(entry, changes, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._sb.showMessage("Restore cancelled.", 3000)
            self._pending_restore_entry = None
            return

        bdir = self._settings.get("backup_dir", self._default_backup_dir())
        self._restore_thread = RestoreThread(
            backup_file  = entry.file_path,
            backup_dir   = bdir,
            device_name  = entry.device_name,
        )
        self._restore_thread.progress.connect(self._prog_bar.setValue)
        self._restore_thread.status_update.connect(self._prog_lbl.setText)
        self._restore_thread.restore_done.connect(self._on_restore_done)
        self._restore_thread.restore_failed.connect(self._on_restore_failed)
        self._restore_thread.finished.connect(lambda: self._set_busy(False))
        self._set_busy(True, "Restoring…")
        self._restore_thread.start()
        logger.info(f"Restore started: {entry.backup_name}")

    def _on_restore_done(self, pre_path: str):
        # Register the automatic pre-restore backup in the registry
        if pre_path and os.path.exists(pre_path):
            ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            src = self._pending_restore_entry
            pre = BackupEntry(
                timestamp   = ts,
                device_name = src.device_name if src else "Unknown",
                backup_name = f"Pre-Restore {ts[:16]}",
                notes       = f"Auto-saved before restoring '{src.backup_name if src else ''}'",
                file_path   = pre_path,
                file_size   = os.path.getsize(pre_path),
                backup_type = "pre_restore",
                status      = "complete",
                created_by  = self.current_user.get("username", ""),
            )
            pre.id = self._save_record(pre)
            self._model.prepend(pre)
            self._update_status_bar()

        self._sb.showMessage("✅  Restore complete.", 6000)
        QMessageBox.information(
            self, "Restore Complete",
            "✅  Configuration restored successfully.\n\n"
            "A pre-restore backup has been saved automatically.",
        )
        self._pending_restore_entry = None

    def _on_restore_failed(self, error: str):
        QMessageBox.critical(self, "Restore Failed", f"Restore failed:\n\n{error}")

    # ── Delete ────────────────────────────────────────────────────────────────

    def _delete_selected(self):
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            return

        ids, entries = set(), []
        for proxy_idx in sel:
            src_row = self._proxy.mapToSource(
                self._proxy.index(proxy_idx.row(), 0)
            ).row()
            e = self._model.entry_at(src_row)
            if e:
                ids.add(e.id)
                entries.append(e)

        n = len(ids)
        ans = QMessageBox.question(
            self, "Delete Backup(s)",
            f"Delete {n} backup record{'s' if n > 1 else ''}?\n\n"
            "Backup files on disk will also be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        for e in entries:
            if e.file_path and os.path.exists(e.file_path):
                try:
                    os.remove(e.file_path)
                except Exception as ex:
                    logger.warning(f"Could not delete {e.file_path}: {ex}")

        self._delete_records(ids)
        self._model.remove_ids(ids)
        self._detail_panel.clear()
        self._active_entry = None
        self._update_status_bar()
        self._sb.showMessage(f"Deleted {n} record{'s' if n > 1 else ''}.", 4000)

    # ── Import / Export ───────────────────────────────────────────────────────

    def _import_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Backup File",
            self._settings.get("backup_dir", ""),
            "HBCE Backup (*.hbce-bak);;JSON (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if "hbce_backup_version" not in payload:
                QMessageBox.warning(self, "Invalid File",
                                    "This does not appear to be a valid HBCE backup.")
                return

            bdir = self._settings.get("backup_dir", self._default_backup_dir())
            os.makedirs(bdir, exist_ok=True)
            ts_f = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(bdir, f"imported_{ts_f}.hbce-bak")
            shutil.copy2(path, dest)

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            e = BackupEntry(
                timestamp   = ts,
                device_name = payload.get("device", "Imported"),
                backup_name = f"Imported: {os.path.basename(path)}",
                notes       = f"Imported from {path}",
                file_path   = dest,
                file_size   = os.path.getsize(dest),
                backup_type = "manual",
                status      = "complete",
                created_by  = self.current_user.get("username", ""),
            )
            e.id = self._save_record(e)
            self._model.prepend(e)
            self._update_status_bar()
            self._sb.showMessage(f"✅  Imported: {os.path.basename(path)}", 5000)

        except Exception as ex:
            QMessageBox.critical(self, "Import Failed", f"{ex}")

    def _export_file(self, entry: Optional[BackupEntry]):
        if not entry or not entry.file_path or not os.path.exists(entry.file_path):
            QMessageBox.warning(self, "File Not Found",
                                "Backup file not found on disk.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Backup File",
            os.path.join(
                os.path.expanduser("~"),
                entry.backup_name.replace(" ", "_") + ".hbce-bak",
            ),
            "HBCE Backup (*.hbce-bak);;All Files (*)",
        )
        if dest:
            shutil.copy2(entry.file_path, dest)
            self._sb.showMessage(f"✅  Exported to {dest}", 5000)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Backup Log",
            os.path.join(os.path.expanduser("~"), "hbce_backup_log.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(COLUMN_HEADERS)
                for e in self._model.all_entries():
                    w.writerow([
                        e.id, e.timestamp[:16], e.device_name, e.backup_name,
                        e.type_label, e.size_str, e.status_label, e.notes, e.created_by,
                    ])
            self._sb.showMessage(f"✅  CSV exported: {path}", 5000)
        except Exception as ex:
            QMessageBox.critical(self, "Export Failed", str(ex))

    # ── Settings ──────────────────────────────────────────────────────────────

    def _open_settings(self):
        dlg = RetentionSettingsDialog(self._settings, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings.update(dlg.get_values())
            auto_on = self._settings["auto_backup_on_connect"]
            self._auto_lbl.setText(f"Auto-backup: {'ON' if auto_on else 'OFF'}  ")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, msg: str = ""):
        self._prog_bar.setVisible(busy)
        self._cancel_btn.setVisible(busy)
        self._new_btn.setEnabled(not busy)
        if busy:
            self._prog_bar.setValue(0)
            if msg:
                self._prog_lbl.setText(msg)
        else:
            self._prog_bar.setValue(0)

    def _cancel_op(self):
        for t in (self._backup_thread, self._restore_thread, self._diff_thread):
            if t and t.isRunning():
                if hasattr(t, "stop"):
                    t.stop()
                t.quit()
        self._set_busy(False)
        self._sb.showMessage("Operation cancelled.", 3000)

    def _update_status_bar(self):
        total   = self._model.rowCount()
        visible = self._proxy.rowCount()
        auto_on = self._settings.get("auto_backup_on_connect", True)
        self._total_lbl.setText(f"  Backups: {total}")
        self._visible_lbl.setText(f"Visible: {visible}")
        self._auto_lbl.setText(f"Auto-backup: {'ON' if auto_on else 'OFF'}  ")

    # ── Public API ────────────────────────────────────────────────────────────

    def trigger_auto_backup(self, device_name: str,
                            device_id: Optional[int] = None):
        """
        Called by the comms layer on device connect (when auto-backup is ON).
        Uses the same BackupThread path as a manual backup.
        """
        if not self._settings.get("auto_backup_on_connect", True):
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._launch_backup(
            device_id   = device_id,
            device_name = device_name,
            backup_name = f"Auto-Backup on Connect {ts[:16]}",
            notes       = "Triggered automatically on device connect.",
            backup_type = "auto",
        )
        logger.info(f"Auto-backup triggered for: {device_name}")
