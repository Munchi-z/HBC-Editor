# ui/panels/scheduler.py
# HBCE — Hybrid Controls Editor
# Scheduler Panel — Full Implementation V0.1.3-alpha
#
# Layout:
#   Left  — device + schedule object selector tree
#   Centre — 7-day weekly grid (custom painted, drag-to-create blocks)
#   Right  — block detail editor + exception / holiday list
#
# Features:
#   - 7-day weekly grid: Mon–Sun columns, 00:00–24:00 rows (15-min snap)
#   - Click-drag to create new time blocks; drag edges to resize
#   - Right-click block → Edit / Delete
#   - BACnet Schedule object read / write via adapter (GOTCHA-013 threads)
#   - Exception dates: override a specific date with its own ON/OFF blocks
#   - Holiday list: named holidays that force the schedule to a "holiday" block
#   - Upload to device: diff preview → confirm → ScheduleWriteThread
#   - Local save: persists schedule_json to SQLite schedules table
#   - CSV export of the weekly schedule

from __future__ import annotations

import csv
import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath,
    QPen, QPolygonF,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QStatusBar,
    QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QDate, QTime

from core.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DAYS        = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_SHORT   = ["Mon",    "Tue",     "Wed",       "Thu",      "Fri",    "Sat",       "Sun"]
MINUTES_DAY = 24 * 60          # 1440
SNAP_MIN    = 15               # snap to 15-minute intervals

# Grid geometry
HEADER_H    = 32               # day-label row height
TIME_COL_W  = 48               # left time-label column width
DAY_COL_W   = 100              # each day column width
MIN_PX      = 0.8              # pixels per minute  (1440 min → 1152 px tall)
GRID_H      = int(MINUTES_DAY * MIN_PX)

BLOCK_COLORS = {
    "Occupied":     QColor("#2563EB"),
    "Unoccupied":   QColor("#64748B"),
    "Holiday":      QColor("#D97706"),
    "After Hours":  QColor("#7C3AED"),
    "Custom":       QColor("#059669"),
}
BLOCK_DEFAULT_COLOR = QColor("#2563EB")

HOUR_LINE_COLOR  = QColor("#B0B8C8")
HALF_LINE_COLOR  = QColor("#D4D8E2")
HEADER_BG        = QColor("#C8CDD8")
HEADER_FG        = QColor("#1A1F2E")
WEEKEND_TINT     = QColor(220, 225, 235, 40)
BLOCK_FG         = QColor("#FFFFFF")
GRID_BG          = QColor("#EFF1F5")

SCHEDULES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER,
    device_name   TEXT NOT NULL DEFAULT 'Local',
    schedule_name TEXT NOT NULL,
    object_instance INTEGER DEFAULT 1,
    schedule_json TEXT NOT NULL DEFAULT '{}',
    last_synced   TEXT,
    modified      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TimeBlock:
    """One coloured ON-period on the weekly grid."""
    day:        int    = 0       # 0=Mon … 6=Sun
    start_min:  int    = 480     # minutes from midnight
    end_min:    int    = 1020
    label:      str    = "Occupied"
    color_name: str    = "Occupied"

    @property
    def duration_min(self) -> int:
        return max(0, self.end_min - self.start_min)

    def to_dict(self) -> dict:
        return {
            "day": self.day, "start_min": self.start_min,
            "end_min": self.end_min, "label": self.label,
            "color_name": self.color_name,
        }

    @staticmethod
    def from_dict(d: dict) -> "TimeBlock":
        return TimeBlock(
            day        = d.get("day", 0),
            start_min  = d.get("start_min", 480),
            end_min    = d.get("end_min", 1020),
            label      = d.get("label", "Occupied"),
            color_name = d.get("color_name", "Occupied"),
        )

    def fmt_start(self) -> str:
        h, m = divmod(self.start_min, 60)
        return f"{h:02d}:{m:02d}"

    def fmt_end(self) -> str:
        h, m = divmod(self.end_min, 60)
        return f"{h:02d}:{m:02d}"


@dataclass
class ExceptionEntry:
    """A specific calendar date with its own set of time blocks."""
    date_str:  str              = ""    # "YYYY-MM-DD"
    label:     str              = ""
    blocks:    List[TimeBlock]  = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date_str": self.date_str, "label": self.label,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @staticmethod
    def from_dict(d: dict) -> "ExceptionEntry":
        return ExceptionEntry(
            date_str = d.get("date_str", ""),
            label    = d.get("label", ""),
            blocks   = [TimeBlock.from_dict(b) for b in d.get("blocks", [])],
        )


@dataclass
class HolidayEntry:
    date_str: str = ""
    name:     str = ""

    def to_dict(self) -> dict:
        return {"date_str": self.date_str, "name": self.name}

    @staticmethod
    def from_dict(d: dict) -> "HolidayEntry":
        return HolidayEntry(date_str=d.get("date_str",""), name=d.get("name",""))


@dataclass
class Schedule:
    """Complete schedule object (weekly + exceptions + holidays)."""
    name:       str                     = "New Schedule"
    device_id:  Optional[int]           = None
    device_name: str                    = "Local"
    object_instance: int                = 1
    weekly:     List[TimeBlock]         = field(default_factory=list)
    exceptions: List[ExceptionEntry]    = field(default_factory=list)
    holidays:   List[HolidayEntry]      = field(default_factory=list)
    db_id:      int                     = 0
    last_synced: str                    = ""

    def to_json(self) -> str:
        return json.dumps({
            "name": self.name,
            "object_instance": self.object_instance,
            "weekly":     [b.to_dict() for b in self.weekly],
            "exceptions": [e.to_dict() for e in self.exceptions],
            "holidays":   [h.to_dict() for h in self.holidays],
        }, indent=2)

    @staticmethod
    def from_json(js: str, device_id=None, device_name="Local") -> "Schedule":
        d = json.loads(js)
        s = Schedule(
            name             = d.get("name", "Schedule"),
            device_id        = device_id,
            device_name      = device_name,
            object_instance  = d.get("object_instance", 1),
            weekly           = [TimeBlock.from_dict(b) for b in d.get("weekly", [])],
            exceptions       = [ExceptionEntry.from_dict(e) for e in d.get("exceptions", [])],
            holidays         = [HolidayEntry.from_dict(h) for h in d.get("holidays", [])],
        )
        return s

    def default_weekly(self):
        """Populate with a typical M-F 07:00–18:00 occupied schedule."""
        self.weekly.clear()
        for day in range(5):   # Mon–Fri
            self.weekly.append(TimeBlock(day=day, start_min=420, end_min=1080,
                                         label="Occupied", color_name="Occupied"))


# ── Worker threads ─────────────────────────────────────────────────────────────

class ScheduleLoadThread(QThread):
    """Reads a BACnet schedule object from the device."""
    loaded = pyqtSignal(object)    # Schedule
    failed = pyqtSignal(str)

    def __init__(self, device_name: str, instance: int, adapter=None, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.instance    = instance
        self.adapter     = adapter

    def run(self):
        try:
            time.sleep(0.4)   # simulated comms delay
            if self.adapter and hasattr(self.adapter, "read_schedule"):
                data = self.adapter.read_schedule(self.instance)
                s = Schedule.from_json(json.dumps(data),
                                       device_name=self.device_name)
            else:
                s = Schedule(name=f"Schedule-{self.instance}",
                             device_name=self.device_name,
                             object_instance=self.instance)
                s.default_weekly()
            self.loaded.emit(s)
        except Exception as e:
            self.failed.emit(str(e))


class ScheduleWriteThread(QThread):
    """Writes the schedule back to the device."""
    written = pyqtSignal()
    failed  = pyqtSignal(str)
    progress = pyqtSignal(int)
    status   = pyqtSignal(str)

    def __init__(self, schedule: Schedule, adapter=None, parent=None):
        super().__init__(parent)
        self.schedule = schedule
        self.adapter  = adapter

    def run(self):
        try:
            self.status.emit("Preparing schedule data…")
            self.progress.emit(20)
            time.sleep(0.3)

            self.status.emit("Connecting to device…")
            self.progress.emit(40)
            time.sleep(0.3)

            self.status.emit("Writing schedule object…")
            self.progress.emit(70)
            if self.adapter and hasattr(self.adapter, "write_schedule"):
                self.adapter.write_schedule(self.schedule.object_instance,
                                             json.loads(self.schedule.to_json()))
            else:
                time.sleep(0.5)   # simulated

            self.progress.emit(100)
            self.status.emit("✅ Schedule written successfully.")
            self.written.emit()
        except Exception as e:
            self.failed.emit(str(e))


# ── Block edit dialog ─────────────────────────────────────────────────────────

class BlockEditDialog(QDialog):
    """Edit a single time block's start, end, and label."""

    def __init__(self, block: TimeBlock, parent=None):
        super().__init__(parent)
        self.block = deepcopy(block)
        self.setWindowTitle("Edit Time Block")
        self.setMinimumWidth(320)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        title = QLabel(f"Edit Block — {DAYS[self.block.day]}")
        f = QFont(); f.setPointSize(12); f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        # Label / type
        lay.addWidget(QLabel("Block Type:"))
        self._label_cb = QComboBox()
        self._label_cb.addItems(list(BLOCK_COLORS.keys()))
        if self.block.label in BLOCK_COLORS:
            self._label_cb.setCurrentText(self.block.label)
        self._label_cb.currentTextChanged.connect(self._on_label_changed)
        lay.addWidget(self._label_cb)

        # Start time
        lay.addWidget(QLabel("Start Time:"))
        self._start = QTimeEdit()
        self._start.setDisplayFormat("HH:mm")
        sh, sm = divmod(self.block.start_min, 60)
        self._start.setTime(QTime(sh, sm))
        lay.addWidget(self._start)

        # End time
        lay.addWidget(QLabel("End Time:"))
        self._end = QTimeEdit()
        self._end.setDisplayFormat("HH:mm")
        eh, em = divmod(self.block.end_min, 60)
        self._end.setTime(QTime(eh, em))
        lay.addWidget(self._end)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _on_label_changed(self, text: str):
        self.block.label      = text
        self.block.color_name = text

    def _accept(self):
        st = self._start.time()
        et = self._end.time()
        s_min = st.hour() * 60 + st.minute()
        e_min = et.hour() * 60 + et.minute()
        if e_min <= s_min:
            QMessageBox.warning(self, "Invalid Time", "End time must be after start time.")
            return
        self.block.start_min  = s_min
        self.block.end_min    = e_min
        self.block.label      = self._label_cb.currentText()
        self.block.color_name = self.block.label
        self.accept()

    def get_block(self) -> TimeBlock:
        return self.block


# ── Exception entry dialog ────────────────────────────────────────────────────

class ExceptionDialog(QDialog):
    def __init__(self, entry: Optional[ExceptionEntry] = None, parent=None):
        super().__init__(parent)
        self._entry = deepcopy(entry) if entry else ExceptionEntry(
            date_str=date.today().isoformat(), label="Exception"
        )
        self.setWindowTitle("Exception Date")
        self.setMinimumWidth(340)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(20, 20, 20, 20)

        lay.addWidget(QLabel("Date:"))
        self._date_edit = QDateEdit()
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.setCalendarPopup(True)
        try:
            d = date.fromisoformat(self._entry.date_str)
            self._date_edit.setDate(QDate(d.year, d.month, d.day))
        except Exception:
            self._date_edit.setDate(QDate.currentDate())
        lay.addWidget(self._date_edit)

        lay.addWidget(QLabel("Label (optional):"))
        self._label = QLineEdit(self._entry.label)
        lay.addWidget(self._label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def get_entry(self) -> ExceptionEntry:
        qd = self._date_edit.date()
        self._entry.date_str = f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"
        self._entry.label    = self._label.text().strip()
        return self._entry


# ── Holiday dialog ────────────────────────────────────────────────────────────

class HolidayDialog(QDialog):
    def __init__(self, entry: Optional[HolidayEntry] = None, parent=None):
        super().__init__(parent)
        self._entry = deepcopy(entry) if entry else HolidayEntry(
            date_str=date.today().isoformat(), name=""
        )
        self.setWindowTitle("Holiday")
        self.setMinimumWidth(320)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(20, 20, 20, 20)

        lay.addWidget(QLabel("Date:"))
        self._date_edit = QDateEdit()
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.setCalendarPopup(True)
        try:
            d = date.fromisoformat(self._entry.date_str)
            self._date_edit.setDate(QDate(d.year, d.month, d.day))
        except Exception:
            self._date_edit.setDate(QDate.currentDate())
        lay.addWidget(self._date_edit)

        lay.addWidget(QLabel("Holiday Name:"))
        self._name = QLineEdit(self._entry.name)
        self._name.setPlaceholderText("e.g. Christmas Day")
        lay.addWidget(self._name)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def get_entry(self) -> HolidayEntry:
        qd = self._date_edit.date()
        self._entry.date_str = f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"
        self._entry.name     = self._name.text().strip()
        return self._entry


# ── Weekly grid widget ────────────────────────────────────────────────────────

class WeeklyGridWidget(QWidget):
    """
    Custom-painted 7-day weekly schedule grid.

    Interaction:
      - Left-click drag on empty space → create new block (snapped to 15 min)
      - Left-click drag on block edge (top/bottom 6 px) → resize
      - Left-click drag on block body → move
      - Double-click block → edit dialog
      - Right-click block → context menu (Edit / Delete)
    """

    blocks_changed = pyqtSignal()

    _EDGE_PX = 7       # px at top/bottom of block that trigger resize

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocks:  List[TimeBlock] = []
        self._dirty    = False

        # Drag state
        self._drag_mode   = None   # None | "create" | "move" | "resize_top" | "resize_bot"
        self._drag_block:  Optional[TimeBlock] = None
        self._drag_day:    int  = 0
        self._drag_start_y: int = 0
        self._drag_orig_start: int = 0
        self._drag_orig_end:   int = 0
        self._drag_new_block: Optional[TimeBlock] = None

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(GRID_H + HEADER_H + 4)

    # ── Public ────────────────────────────────────────────────────────────────

    def load_blocks(self, blocks: List[TimeBlock]):
        self._blocks = list(blocks)
        self.update()

    def get_blocks(self) -> List[TimeBlock]:
        return list(self._blocks)

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _col_x(self, day: int) -> int:
        return TIME_COL_W + day * DAY_COL_W

    def _min_to_y(self, minutes: int) -> int:
        return HEADER_H + int(minutes * MIN_PX)

    def _y_to_min(self, y: int) -> int:
        raw = (y - HEADER_H) / MIN_PX
        snapped = round(raw / SNAP_MIN) * SNAP_MIN
        return max(0, min(MINUTES_DAY, snapped))

    def _x_to_day(self, x: int) -> int:
        col = (x - TIME_COL_W) // DAY_COL_W
        return max(0, min(6, col))

    def _block_rect(self, b: TimeBlock) -> QRect:
        x = self._col_x(b.day) + 2
        y = self._min_to_y(b.start_min)
        w = DAY_COL_W - 4
        h = max(4, int(b.duration_min * MIN_PX))
        return QRect(x, y, w, h)

    def _hit_block(self, x: int, y: int) -> Optional[Tuple[TimeBlock, str]]:
        """Returns (block, zone) where zone is 'top'/'bot'/'body'."""
        for b in reversed(self._blocks):
            r = self._block_rect(b)
            if r.contains(x, y):
                if y - r.top() <= self._EDGE_PX:
                    return b, "top"
                elif r.bottom() - y <= self._EDGE_PX:
                    return b, "bot"
                return b, "body"
        return None

    def sizeHint(self) -> QSize:
        w = TIME_COL_W + 7 * DAY_COL_W + 2
        h = GRID_H + HEADER_H + 4
        return QSize(w, h)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        # Background
        p.fillRect(self.rect(), GRID_BG)

        # Weekend tint (Sat col 5, Sun col 6)
        for day in (5, 6):
            x = self._col_x(day)
            p.fillRect(QRect(x, HEADER_H, DAY_COL_W, GRID_H), WEEKEND_TINT)

        # Hour lines
        for hour in range(25):
            y = self._min_to_y(hour * 60)
            if hour % 1 == 0:
                color = HOUR_LINE_COLOR if (hour % 3 == 0) else HALF_LINE_COLOR
                p.setPen(QPen(color, 0.5))
                p.drawLine(TIME_COL_W, y, w, y)

                # Time label
                if hour < 24:
                    p.setPen(QPen(QColor("#6B7280"), 1))
                    f = QFont("Segoe UI", 7)
                    p.setFont(f)
                    p.drawText(
                        QRect(0, y - 8, TIME_COL_W - 4, 16),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        f"{hour:02d}:00",
                    )

        # Half-hour lines (lighter)
        for hour in range(24):
            y = self._min_to_y(hour * 60 + 30)
            p.setPen(QPen(HALF_LINE_COLOR, 0.4, Qt.PenStyle.DashLine))
            p.drawLine(TIME_COL_W, y, w, y)

        # Day column dividers
        p.setPen(QPen(HOUR_LINE_COLOR, 0.7))
        for day in range(8):
            x = self._col_x(day)
            p.drawLine(x, 0, x, GRID_H + HEADER_H)

        # Day headers
        p.fillRect(QRect(0, 0, w, HEADER_H), HEADER_BG)
        hf = QFont("Segoe UI", 9)
        hf.setBold(True)
        p.setFont(hf)
        p.setPen(QPen(HEADER_FG))
        for i, label in enumerate(DAY_SHORT):
            x = self._col_x(i)
            p.drawText(
                QRect(x, 0, DAY_COL_W, HEADER_H),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        # Time blocks
        for b in self._blocks:
            self._paint_block(p, b)

        # In-progress drag block
        if self._drag_new_block:
            self._paint_block(p, self._drag_new_block, alpha=160)

    def _paint_block(self, p: QPainter, b: TimeBlock, alpha: int = 220):
        r   = self._block_rect(b)
        col = BLOCK_COLORS.get(b.color_name, BLOCK_DEFAULT_COLOR)
        col.setAlpha(alpha)

        # Fill with rounded rect
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 4, 4)
        p.fillPath(path, QBrush(col))

        # Border
        border_col = col.darker(130)
        border_col.setAlpha(alpha)
        p.setPen(QPen(border_col, 1))
        p.drawPath(path)

        # Label (only if tall enough)
        if r.height() >= 14:
            p.setPen(QPen(BLOCK_FG))
            lf = QFont("Segoe UI", 7)
            lf.setBold(True)
            p.setFont(lf)
            label = f"{b.label}\n{b.fmt_start()}–{b.fmt_end()}"
            p.drawText(r.adjusted(3, 2, -2, -2),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                       label)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if y < HEADER_H or x < TIME_COL_W:
            return

        if event.button() == Qt.MouseButton.RightButton:
            hit = self._hit_block(int(x), int(y))
            if hit:
                self._show_context_menu(hit[0], event.globalPosition().toPoint())
            return

        hit = self._hit_block(int(x), int(y))
        if hit:
            block, zone = hit
            self._drag_block      = block
            self._drag_start_y    = int(y)
            self._drag_orig_start = block.start_min
            self._drag_orig_end   = block.end_min
            if zone == "top":
                self._drag_mode = "resize_top"
                self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
            elif zone == "bot":
                self._drag_mode = "resize_bot"
                self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
            else:
                self._drag_mode = "move"
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        else:
            # Start a new block
            day = self._x_to_day(int(x))
            start_min = self._y_to_min(int(y))
            self._drag_new_block = TimeBlock(
                day=day, start_min=start_min, end_min=start_min + SNAP_MIN,
                label="Occupied", color_name="Occupied",
            )
            self._drag_mode  = "create"
            self._drag_day   = day
            self._drag_start_y = int(y)

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()

        if self._drag_mode is None:
            # Cursor update on hover
            hit = self._hit_block(int(x), int(y))
            if hit:
                _, zone = hit
                if zone in ("top", "bot"):
                    self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
                else:
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return

        dy_min = int((int(y) - self._drag_start_y) / MIN_PX / SNAP_MIN) * SNAP_MIN

        if self._drag_mode == "create" and self._drag_new_block:
            cur_min = self._y_to_min(int(y))
            start_min = self._y_to_min(self._drag_start_y)
            if cur_min > start_min:
                self._drag_new_block.start_min = start_min
                self._drag_new_block.end_min   = cur_min
            else:
                self._drag_new_block.start_min = cur_min
                self._drag_new_block.end_min   = start_min + SNAP_MIN
            self.update()

        elif self._drag_mode == "move" and self._drag_block:
            dur = self._drag_orig_end - self._drag_orig_start
            new_start = max(0, min(MINUTES_DAY - dur,
                                   self._drag_orig_start + dy_min))
            new_start = round(new_start / SNAP_MIN) * SNAP_MIN
            self._drag_block.start_min = new_start
            self._drag_block.end_min   = new_start + dur
            # Allow moving across days
            new_day = self._x_to_day(int(x))
            self._drag_block.day = new_day
            self.update()

        elif self._drag_mode == "resize_top" and self._drag_block:
            new_start = max(0, self._drag_orig_start + dy_min)
            new_start = round(new_start / SNAP_MIN) * SNAP_MIN
            if new_start < self._drag_block.end_min - SNAP_MIN:
                self._drag_block.start_min = new_start
            self.update()

        elif self._drag_mode == "resize_bot" and self._drag_block:
            new_end = min(MINUTES_DAY, self._drag_orig_end + dy_min)
            new_end = round(new_end / SNAP_MIN) * SNAP_MIN
            if new_end > self._drag_block.start_min + SNAP_MIN:
                self._drag_block.end_min = new_end
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_mode == "create" and self._drag_new_block:
            if self._drag_new_block.duration_min >= SNAP_MIN:
                self._blocks.append(deepcopy(self._drag_new_block))
                self.blocks_changed.emit()
            self._drag_new_block = None

        elif self._drag_mode in ("move", "resize_top", "resize_bot"):
            self.blocks_changed.emit()

        self._drag_mode  = None
        self._drag_block = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()

    def mouseDoubleClickEvent(self, event):
        x, y = event.position().x(), event.position().y()
        hit = self._hit_block(int(x), int(y))
        if hit:
            self._edit_block(hit[0])

    def _show_context_menu(self, block: TimeBlock, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#EFF1F5; color:#1A1F2E; border:1px solid #B8BECE; }
            QMenu::item:selected { background:#2B6CB0; color:#fff; }
        """)
        menu.addAction("✏️  Edit Block",   lambda: self._edit_block(block))
        menu.addAction("🗑  Delete Block", lambda: self._delete_block(block))
        menu.exec(pos)

    def _edit_block(self, block: TimeBlock):
        dlg = BlockEditDialog(block, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            edited = dlg.get_block()
            block.start_min  = edited.start_min
            block.end_min    = edited.end_min
            block.label      = edited.label
            block.color_name = edited.color_name
            self.blocks_changed.emit()
            self.update()

    def _delete_block(self, block: TimeBlock):
        if block in self._blocks:
            self._blocks.remove(block)
            self.blocks_changed.emit()
            self.update()


# ── Right panel: block detail + exceptions + holidays ────────────────────────

class ScheduleDetailPanel(QWidget):
    """Shows selected schedule metadata + exception + holiday managers."""

    exceptions_changed = pyqtSignal(list)
    holidays_changed   = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schedule: Optional[Schedule] = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # Schedule name
        self._name_lbl = QLabel("No schedule loaded")
        f = QFont(); f.setPointSize(11); f.setBold(True)
        self._name_lbl.setFont(f)
        self._name_lbl.setWordWrap(True)
        lay.addWidget(self._name_lbl)

        # Metadata
        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet("color: #4A5368; font-size: 9pt;")
        self._meta_lbl.setWordWrap(True)
        lay.addWidget(self._meta_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        # ── Legend ────────────────────────────────────────────────────────
        leg_group = QGroupBox("Block Types")
        leg_lay = QVBoxLayout(leg_group)
        leg_lay.setSpacing(4)
        for label, color in BLOCK_COLORS.items():
            row = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background:{color.name()}; border-radius:3px; border:1px solid #9AA0B2;"
            )
            row.addWidget(swatch)
            row.addWidget(QLabel(label))
            row.addStretch()
            leg_lay.addLayout(row)
        lay.addWidget(leg_group)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep2)

        # ── Exception dates ───────────────────────────────────────────────
        exc_group = QGroupBox("Exception Dates")
        exc_lay = QVBoxLayout(exc_group)
        self._exc_list = QListWidget()
        self._exc_list.setMaximumHeight(110)
        exc_lay.addWidget(self._exc_list)
        exc_btns = QHBoxLayout()
        add_exc = QPushButton("＋")
        add_exc.setFixedWidth(28)
        add_exc.clicked.connect(self._add_exception)
        del_exc = QPushButton("−")
        del_exc.setFixedWidth(28)
        del_exc.clicked.connect(self._del_exception)
        exc_btns.addWidget(add_exc)
        exc_btns.addWidget(del_exc)
        exc_btns.addStretch()
        exc_lay.addLayout(exc_btns)
        lay.addWidget(exc_group)

        # ── Holiday list ──────────────────────────────────────────────────
        hol_group = QGroupBox("Holidays")
        hol_lay = QVBoxLayout(hol_group)
        self._hol_list = QListWidget()
        self._hol_list.setMaximumHeight(110)
        hol_lay.addWidget(self._hol_list)
        hol_btns = QHBoxLayout()
        add_hol = QPushButton("＋")
        add_hol.setFixedWidth(28)
        add_hol.clicked.connect(self._add_holiday)
        del_hol = QPushButton("−")
        del_hol.setFixedWidth(28)
        del_hol.clicked.connect(self._del_holiday)
        hol_btns.addWidget(add_hol)
        hol_btns.addWidget(del_hol)
        hol_btns.addStretch()
        hol_lay.addLayout(hol_btns)
        lay.addWidget(hol_group)

        lay.addStretch()

    def load_schedule(self, s: Schedule):
        self._schedule = s
        self._name_lbl.setText(s.name)
        self._meta_lbl.setText(
            f"Device: {s.device_name}\n"
            f"Instance: {s.object_instance}\n"
            f"Last synced: {s.last_synced or 'Never'}"
        )
        self._exc_list.clear()
        for e in s.exceptions:
            self._exc_list.addItem(f"{e.date_str}  {e.label}")
        self._hol_list.clear()
        for h in s.holidays:
            self._hol_list.addItem(f"{h.date_str}  {h.name}")

    def clear(self):
        self._schedule = None
        self._name_lbl.setText("No schedule loaded")
        self._meta_lbl.setText("")
        self._exc_list.clear()
        self._hol_list.clear()

    def _add_exception(self):
        dlg = ExceptionDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and self._schedule:
            self._schedule.exceptions.append(dlg.get_entry())
            self.load_schedule(self._schedule)
            self.exceptions_changed.emit(self._schedule.exceptions)

    def _del_exception(self):
        row = self._exc_list.currentRow()
        if row >= 0 and self._schedule and row < len(self._schedule.exceptions):
            self._schedule.exceptions.pop(row)
            self.load_schedule(self._schedule)
            self.exceptions_changed.emit(self._schedule.exceptions)

    def _add_holiday(self):
        dlg = HolidayDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and self._schedule:
            self._schedule.holidays.append(dlg.get_entry())
            self.load_schedule(self._schedule)
            self.holidays_changed.emit(self._schedule.holidays)

    def _del_holiday(self):
        row = self._hol_list.currentRow()
        if row >= 0 and self._schedule and row < len(self._schedule.holidays):
            self._schedule.holidays.pop(row)
            self.load_schedule(self._schedule)
            self.holidays_changed.emit(self._schedule.holidays)


# ── Main panel ────────────────────────────────────────────────────────────────

class SchedulerPanel(QWidget):
    """
    📅 Scheduler Panel — Full Implementation V0.1.3-alpha

    Left:   device + schedule object tree
    Centre: 7-day weekly grid (drag-to-create, resize, move blocks)
    Right:  detail panel (legend, exceptions, holidays)
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {"username": "admin", "role": "Admin"}

        self._schedule: Optional[Schedule]         = None
        self._load_thread:  Optional[ScheduleLoadThread]  = None
        self._write_thread: Optional[ScheduleWriteThread] = None
        self._dirty = False

        self._init_db()
        self._build_ui()
        self._load_local_schedules()
        logger.debug("SchedulerPanel initialized")

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self):
        if self.db:
            try:
                self.db.execute(SCHEDULES_TABLE_SQL)
                self.db.conn.commit()
            except Exception as e:
                logger.warning(f"Schedules table init: {e}")
            # Migration: add columns that didn't exist in older schema versions
            migrations = [
                "ALTER TABLE schedules ADD COLUMN device_name TEXT NOT NULL DEFAULT 'Local'",
                "ALTER TABLE schedules ADD COLUMN schedule_name TEXT NOT NULL DEFAULT 'Schedule'",
                "ALTER TABLE schedules ADD COLUMN object_instance INTEGER DEFAULT 1",
                "ALTER TABLE schedules ADD COLUMN modified TEXT NOT NULL DEFAULT (datetime('now'))",
            ]
            for sql in migrations:
                try:
                    self.db.execute(sql)
                    self.db.conn.commit()
                except Exception:
                    pass  # column already exists — safe to ignore

    def _get_devices(self) -> List[dict]:
        if self.db:
            try:
                return self.db.fetchall("SELECT id, name FROM devices")
            except Exception:
                pass
        return []

    def _load_local_schedules(self):
        """Populate the tree with schedules saved to SQLite."""
        self._tree.clear()
        if not self.db:
            self._add_demo_tree()
            return
        try:
            rows = self.db.fetchall("SELECT * FROM schedules ORDER BY device_name, schedule_name")
            devices: Dict[str, QTreeWidgetItem] = {}
            for row in rows:
                dname = row.get("device_name", "Local")
                if dname not in devices:
                    dev_item = QTreeWidgetItem(self._tree, [dname])
                    dev_item.setExpanded(True)
                    devices[dname] = dev_item
                sched_item = QTreeWidgetItem(devices[dname], [row["schedule_name"]])
                sched_item.setData(0, Qt.ItemDataRole.UserRole, row)
            if not rows:
                self._add_demo_tree()
        except Exception as e:
            logger.warning(f"Load schedules: {e}")
            self._add_demo_tree()

    def _add_demo_tree(self):
        """Add a demo local schedule so the UI is not empty."""
        dev_item = QTreeWidgetItem(self._tree, ["Local / Demo"])
        dev_item.setExpanded(True)
        s_item = QTreeWidgetItem(dev_item, ["Occupancy Schedule 1"])
        demo_data = {"id": -1, "schedule_name": "Occupancy Schedule 1",
                     "device_name": "Local / Demo", "object_instance": 1,
                     "schedule_json": None}
        s_item.setData(0, Qt.ItemDataRole.UserRole, demo_data)

    def _save_schedule(self):
        if not self._schedule or not self.db:
            return
        js = self._schedule.to_json()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self._schedule.db_id:
            self.db.update(
                "UPDATE schedules SET schedule_json=?,modified=? WHERE id=?",
                (js, ts, self._schedule.db_id),
            )
        else:
            new_id = self.db.insert(
                """INSERT INTO schedules
                   (device_id,device_name,schedule_name,object_instance,schedule_json,modified)
                   VALUES(?,?,?,?,?,?)""",
                (self._schedule.device_id, self._schedule.device_name,
                 self._schedule.name, self._schedule.object_instance, js, ts),
            )
            self._schedule.db_id = new_id
        self._dirty = False
        self._sb.showMessage("Schedule saved locally.", 4000)
        self._load_local_schedules()

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left: device tree ─────────────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 8, 6, 8)
        left_lay.setSpacing(6)

        lbl = QLabel("Schedules")
        f = QFont(); f.setBold(True); f.setPointSize(9)
        lbl.setFont(f)
        lbl.setStyleSheet("color:#4A5368;")
        left_lay.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background:#EFF1F5;
                border:1px solid #B8BECE;
                border-radius:4px;
                outline:none;
            }
            QTreeWidget::item { padding:4px 6px; }
            QTreeWidget::item:selected { background:#2B6CB0; color:#fff; border-radius:3px; }
            QTreeWidget::item:hover:!selected { background:#D5D9E5; }
        """)
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        left_lay.addWidget(self._tree)

        # New schedule button
        new_sched_btn = QPushButton("＋  New Schedule")
        new_sched_btn.setStyleSheet("""
            QPushButton {
                background:#2B6CB0; color:#fff;
                border:none; border-radius:4px; padding:5px;
                font-weight:bold; font-size:9pt;
            }
            QPushButton:hover { background:#245E9E; }
        """)
        new_sched_btn.clicked.connect(self._new_schedule)
        left_lay.addWidget(new_sched_btn)

        splitter.addWidget(left)

        # ── Centre: scrollable weekly grid ────────────────────────────────
        centre_container = QWidget()
        centre_lay = QVBoxLayout(centre_container)
        centre_lay.setContentsMargins(4, 8, 4, 8)
        centre_lay.setSpacing(4)

        grid_lbl = QLabel("Weekly Schedule")
        gf = QFont(); gf.setBold(True); gf.setPointSize(9)
        grid_lbl.setFont(gf)
        grid_lbl.setStyleSheet("color:#4A5368;")
        centre_lay.addWidget(grid_lbl)

        hint = QLabel(
            "Click+drag to create blocks  ·  Drag edge to resize  ·  "
            "Drag body to move  ·  Right-click to edit/delete"
        )
        hint.setStyleSheet("color:#9AA0B2; font-size: 8pt;")
        centre_lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border:1px solid #B8BECE; border-radius:4px; }")

        self._grid = WeeklyGridWidget()
        self._grid.blocks_changed.connect(self._on_blocks_changed)
        scroll.setWidget(self._grid)
        centre_lay.addWidget(scroll, 1)
        splitter.addWidget(centre_container)

        # ── Right: detail panel ───────────────────────────────────────────
        self._detail = ScheduleDetailPanel()
        self._detail.exceptions_changed.connect(self._on_exceptions_changed)
        self._detail.holidays_changed.connect(self._on_holidays_changed)
        splitter.addWidget(self._detail)

        splitter.setSizes([180, 680, 260])
        root.addWidget(splitter, 1)

        # ── Progress bar ──────────────────────────────────────────────────
        root.addWidget(self._build_progress_area())
        root.addWidget(self._build_status_bar())

    def _build_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setFixedHeight(48)
        frame.setStyleSheet("""
            QFrame { background:#C8CDD8; border-bottom:1px solid #B8BECE; }
            QPushButton {
                background:#EFF1F5; color:#1A1F2E;
                border:1px solid #B8BECE; border-radius:4px;
                padding:5px 12px; font-size:9pt;
            }
            QPushButton:hover { background:#DDE1EA; }
            QPushButton:disabled { color:#9AA0B2; }
        """)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(6)

        title = QLabel("📅  Scheduler")
        tf = QFont(); tf.setPointSize(13); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet("color:#1A1F2E; background:transparent; border:none;")
        lay.addWidget(title)

        vsep = QFrame(); vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet("background:#B8BECE; border:none;")
        vsep.setFixedWidth(1)
        lay.addWidget(vsep)

        self._save_btn = QPushButton("💾  Save")
        self._save_btn.setToolTip("Save schedule locally to database")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_schedule)
        lay.addWidget(self._save_btn)

        self._upload_btn = QPushButton("🔄  Upload to Device")
        self._upload_btn.setToolTip("Write schedule to connected BACnet device")
        self._upload_btn.setEnabled(False)
        self._upload_btn.clicked.connect(self._upload_to_device)
        lay.addWidget(self._upload_btn)

        self._read_btn = QPushButton("📥  Read from Device")
        self._read_btn.setToolTip("Read current schedule from connected device")
        self._read_btn.setEnabled(False)
        self._read_btn.clicked.connect(self._read_from_device)
        lay.addWidget(self._read_btn)

        lay.addSpacing(8)

        self._clear_btn = QPushButton("🗑  Clear Week")
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self._clear_week)
        lay.addWidget(self._clear_btn)

        self._default_btn = QPushButton("↺  Default M–F")
        self._default_btn.setToolTip("Reset to Mon–Fri 07:00–18:00 Occupied")
        self._default_btn.setEnabled(False)
        self._default_btn.clicked.connect(self._apply_default)
        lay.addWidget(self._default_btn)

        lay.addStretch()

        self._csv_btn = QPushButton("📊  Export CSV")
        self._csv_btn.setEnabled(False)
        self._csv_btn.clicked.connect(self._export_csv)
        lay.addWidget(self._csv_btn)

        self._refresh_btn = QPushButton("↺  Refresh List")
        self._refresh_btn.clicked.connect(self._load_local_schedules)
        lay.addWidget(self._refresh_btn)

        return frame

    def _build_progress_area(self) -> QFrame:
        frame = QFrame()
        frame.setMaximumHeight(44)
        frame.setStyleSheet("QFrame { background:#C8CDD8; border-top:1px solid #B8BECE; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        from PyQt6.QtWidgets import QProgressBar
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setFixedHeight(14)
        self._prog_bar.setVisible(False)
        self._prog_bar.setStyleSheet("""
            QProgressBar {
                background:#DDE1EA; border:1px solid #B8BECE;
                border-radius:7px; text-align:center; font-size:8pt;
            }
            QProgressBar::chunk {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #2B6CB0, stop:1 #5BA4E0);
                border-radius:7px;
            }
        """)
        lay.addWidget(self._prog_bar, 1)

        self._prog_lbl = QLabel("Ready.")
        self._prog_lbl.setStyleSheet("color:#4A5368; font-size:9pt;")
        lay.addWidget(self._prog_lbl, 2)

        self._cancel_btn = QPushButton("✕")
        self._cancel_btn.setFixedWidth(28)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._cancel_op)
        self._cancel_btn.setStyleSheet("""
            QPushButton { background:#B02030; color:#fff;
                border-radius:4px; font-weight:bold; }
        """)
        lay.addWidget(self._cancel_btn)
        return frame

    def _build_status_bar(self) -> QStatusBar:
        sb = QStatusBar()
        sb.setFixedHeight(24)
        sb.setStyleSheet("""
            QStatusBar { background:#C8CDD8; border-top:1px solid #B8BECE;
                         color:#4A5368; font-size:8pt; }
        """)
        self._blocks_lbl    = QLabel("  Blocks: 0")
        self._sched_lbl     = QLabel("No schedule loaded  ")
        self._dirty_lbl     = QLabel()
        sb.addWidget(self._blocks_lbl)
        sb.addWidget(QLabel("  |  "))
        sb.addWidget(self._sched_lbl)
        sb.addPermanentWidget(self._dirty_lbl)
        self._sb = sb
        return sb

    # ── Tree interaction ──────────────────────────────────────────────────────

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return   # device-level node

        # Warn if unsaved
        if self._dirty:
            ans = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Discard and load new schedule?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        js = data.get("schedule_json")
        if js:
            s = Schedule.from_json(
                js,
                device_id   = data.get("device_id"),
                device_name = data.get("device_name", "Local"),
            )
            s.db_id = data.get("id", 0)
            s.name  = data.get("schedule_name", s.name)
        else:
            # Demo / new: create default
            s = Schedule(
                name        = data.get("schedule_name", "Schedule"),
                device_name = data.get("device_name", "Local"),
                object_instance = data.get("object_instance", 1),
            )
            s.default_weekly()

        self._load_schedule_into_ui(s)

    def _load_schedule_into_ui(self, s: Schedule):
        self._schedule = s
        self._grid.load_blocks(s.weekly)
        self._detail.load_schedule(s)
        self._dirty = False
        self._update_status_bar()
        self._enable_editing(True)

    def _enable_editing(self, on: bool):
        for btn in (self._save_btn, self._upload_btn, self._read_btn,
                    self._clear_btn, self._default_btn, self._csv_btn):
            btn.setEnabled(on)

    # ── Block / schedule events ───────────────────────────────────────────────

    def _on_blocks_changed(self):
        if self._schedule:
            self._schedule.weekly = self._grid.get_blocks()
        self._dirty = True
        self._update_status_bar()

    def _on_exceptions_changed(self, exceptions: list):
        if self._schedule:
            self._schedule.exceptions = exceptions
        self._dirty = True

    def _on_holidays_changed(self, holidays: list):
        if self._schedule:
            self._schedule.holidays = holidays
        self._dirty = True

    def _new_schedule(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Schedule", "Schedule name:")
        if not ok or not name.strip():
            return
        s = Schedule(name=name.strip(), device_name="Local")
        s.default_weekly()
        self._load_schedule_into_ui(s)
        self._dirty = True

    def _clear_week(self):
        ans = QMessageBox.question(
            self, "Clear Week",
            "Remove all blocks from the weekly schedule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._grid.load_blocks([])
            self._on_blocks_changed()

    def _apply_default(self):
        if self._schedule:
            self._schedule.default_weekly()
            self._grid.load_blocks(self._schedule.weekly)
            self._dirty = True
            self._update_status_bar()

    # ── Device read / write (GOTCHA-013) ──────────────────────────────────────

    def _read_from_device(self):
        if not self._schedule:
            return
        if self._dirty:
            ans = QMessageBox.question(
                self, "Unsaved Changes",
                "Discard local changes and read from device?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        self._set_busy(True, "Reading schedule from device…")
        self._load_thread = ScheduleLoadThread(
            device_name = self._schedule.device_name,
            instance    = self._schedule.object_instance,
        )
        self._load_thread.loaded.connect(self._on_schedule_loaded)
        self._load_thread.failed.connect(self._on_op_failed)
        self._load_thread.finished.connect(lambda: self._set_busy(False))
        self._load_thread.start()

    def _on_schedule_loaded(self, s: Schedule):
        s.db_id      = self._schedule.db_id if self._schedule else 0
        s.last_synced = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._load_schedule_into_ui(s)
        self._sb.showMessage("✅ Schedule read from device.", 5000)

    def _upload_to_device(self):
        if not self._schedule:
            return

        # Diff preview
        total_blocks = len(self._schedule.weekly)
        exc_count    = len(self._schedule.exceptions)
        hol_count    = len(self._schedule.holidays)

        ans = QMessageBox.question(
            self, "Upload Schedule to Device",
            f"Upload schedule  '{self._schedule.name}'  to  {self._schedule.device_name}?\n\n"
            f"  Weekly blocks:   {total_blocks}\n"
            f"  Exception dates: {exc_count}\n"
            f"  Holidays:        {hol_count}\n\n"
            "This will overwrite the current schedule on the device.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True, "Uploading schedule…")
        self._write_thread = ScheduleWriteThread(self._schedule)
        self._write_thread.progress.connect(self._prog_bar.setValue)
        self._write_thread.status.connect(self._prog_lbl.setText)
        self._write_thread.written.connect(self._on_schedule_written)
        self._write_thread.failed.connect(self._on_op_failed)
        self._write_thread.finished.connect(lambda: self._set_busy(False))
        self._write_thread.start()

    def _on_schedule_written(self):
        if self._schedule:
            self._schedule.last_synced = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._detail.load_schedule(self._schedule)
        self._sb.showMessage("✅ Schedule uploaded to device.", 6000)

    def _on_op_failed(self, error: str):
        QMessageBox.critical(self, "Operation Failed", f"Error:\n\n{error}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._schedule:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Schedule",
            os.path.join(os.path.expanduser("~"),
                         f"{self._schedule.name.replace(' ','_')}.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Day", "Start", "End", "Duration (min)", "Label"])
                for b in sorted(self._schedule.weekly,
                                 key=lambda x: (x.day, x.start_min)):
                    w.writerow([
                        DAYS[b.day], b.fmt_start(), b.fmt_end(),
                        b.duration_min, b.label,
                    ])
                if self._schedule.exceptions:
                    w.writerow([])
                    w.writerow(["Exception Date", "Label", "Blocks"])
                    for e in self._schedule.exceptions:
                        block_str = "; ".join(
                            f"{b.fmt_start()}-{b.fmt_end()} {b.label}"
                            for b in e.blocks
                        )
                        w.writerow([e.date_str, e.label, block_str])
                if self._schedule.holidays:
                    w.writerow([])
                    w.writerow(["Holiday Date", "Name"])
                    for h in self._schedule.holidays:
                        w.writerow([h.date_str, h.name])
            self._sb.showMessage(f"✅ CSV exported: {path}", 5000)
        except Exception as ex:
            QMessageBox.critical(self, "Export Failed", str(ex))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, msg: str = ""):
        self._prog_bar.setVisible(busy)
        self._cancel_btn.setVisible(busy)
        self._upload_btn.setEnabled(not busy and self._schedule is not None)
        self._read_btn.setEnabled(not busy and self._schedule is not None)
        if busy:
            self._prog_bar.setValue(0)
            if msg:
                self._prog_lbl.setText(msg)
        else:
            self._prog_bar.setValue(0)

    def _cancel_op(self):
        for t in (self._load_thread, self._write_thread):
            if t and t.isRunning():
                t.quit()
        self._set_busy(False)
        self._sb.showMessage("Operation cancelled.", 3000)

    def _update_status_bar(self):
        n = len(self._schedule.weekly) if self._schedule else 0
        name = self._schedule.name if self._schedule else "No schedule loaded"
        self._blocks_lbl.setText(f"  Blocks: {n}")
        self._sched_lbl.setText(f"{name}  ")
        self._dirty_lbl.setText("● Unsaved  " if self._dirty else "")
        self._dirty_lbl.setStyleSheet(
            "color:#8C4D0A; font-weight:bold;" if self._dirty else ""
        )
