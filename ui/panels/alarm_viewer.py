# ui/panels/alarm_viewer.py
# HBCE — Hybrid Controls Editor
# Alarm Viewer Panel — V0.0.8-alpha  (visual redesign: stripe + pill style)
#
# Visual approach:
#   - Near-black rows with very subtle priority tinting (no eye-fatiguing full-row color)
#   - 4 px left accent stripe in vivid priority color  (communicates urgency instantly)
#   - Priority column: small colored pill badge
#   - State column: colored dot + label
#   - Active P1/P2 rows: slightly elevated brightness only
#   - Cleared rows: dimmed text, italic
#   - Font: 9 pt — compact, dense data view
#   All rendering done via AlarmRowDelegate (QStyledItemDelegate)

from __future__ import annotations

import csv
import io
import os
import time
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QRectF,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QTimer,
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
from PyQt6.QtWidgets import QStyle
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Priority definitions
# ---------------------------------------------------------------------------

class AlarmPriority(IntEnum):
    LIFE_SAFETY   = 1
    CRITICAL      = 2
    HIGH          = 3
    MEDIUM_HIGH   = 4
    MEDIUM        = 5
    MEDIUM_LOW    = 6
    LOW           = 7
    INFORMATIONAL = 8

PRIORITY_LABELS = {
    1: "Life Safety",
    2: "Critical",
    3: "High",
    4: "Med-High",
    5: "Medium",
    6: "Med-Low",
    7: "Low",
    8: "Info",
}

# ── Left accent stripe colors — vivid, but only 4 px wide ─────────────────
PRIORITY_STRIPE = {
    1: QColor("#C62828"),   # deep red
    2: QColor("#BF360C"),   # burnt orange
    3: QColor("#E65100"),   # orange
    4: QColor("#F9A825"),   # amber
    5: QColor("#9E9D24"),   # olive
    6: QColor("#1565C0"),   # blue
    7: QColor("#2E7D32"),   # green
    8: QColor("#546E7A"),   # blue-grey
}

# ── Pill badge colors — muted versions of stripe colors ───────────────────
PRIORITY_PILL_BG = {
    1: QColor("#7B0000"),
    2: QColor("#6D1F00"),
    3: QColor("#6D2F00"),
    4: QColor("#7B5800"),
    5: QColor("#4A4700"),
    6: QColor("#0D3B7A"),
    7: QColor("#1B4D1F"),
    8: QColor("#2C3E45"),
}

# ── Row background — very subtle priority tint ────────────────────────────
PRIORITY_ROW_BG = {
    1: QColor("#231818"),
    2: QColor("#211710"),
    3: QColor("#201A0E"),
    4: QColor("#1F1D0C"),
    5: QColor("#191B0C"),
    6: QColor("#0E1620"),
    7: QColor("#0E1A10"),
    8: QColor("#151C20"),
}

ROW_BG_ALT       = QColor("#161D21")   # alternating neutral row
ROW_BG_CLEARED   = QColor("#121619")   # cleared rows — dimmer
ROW_BG_SELECTED  = QColor("#2A3D47")
FG_NORMAL        = QColor("#D8DEE1")
FG_CLEARED       = QColor("#5A6469")   # dimmed text for cleared
FG_ACTIVE_HI     = QColor("#FFFFFF")   # P1/P2 active
STRIPE_WIDTH     = 4
ROW_HEIGHT       = 22
TABLE_FONT_SIZE  = 9


class AlarmState:
    ACTIVE       = "Active"
    ACKNOWLEDGED = "Acknowledged"
    CLEARED      = "Cleared"

# State dot colors
STATE_DOT = {
    AlarmState.ACTIVE:       QColor("#EF5350"),   # red dot
    AlarmState.ACKNOWLEDGED: QColor("#FFA726"),   # amber dot
    AlarmState.CLEARED:      QColor("#546E7A"),   # grey dot
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AlarmRecord:
    alarm_id:    int
    timestamp:   datetime
    device_name: str
    device_addr: str
    object_name: str
    object_type: str
    instance:    int
    description: str
    priority:    int
    state:       str = AlarmState.ACTIVE
    acked_by:    Optional[str] = None
    acked_at:    Optional[datetime] = None
    cleared_at:  Optional[datetime] = None
    category:    str = "General"
    units:       str = ""
    from_value:  str = ""
    to_value:    str = ""
    notes:       str = ""

    @property
    def priority_label(self) -> str:
        return PRIORITY_LABELS.get(self.priority, f"P{self.priority}")

    @property
    def age_str(self) -> str:
        delta = datetime.now() - self.timestamp
        s = int(delta.total_seconds())
        if s < 60:    return f"{s}s"
        elif s < 3600: return f"{s // 60}m"
        elif s < 86400: return f"{s // 3600}h"
        else:          return f"{s // 86400}d"


# ---------------------------------------------------------------------------
# Table columns
# ---------------------------------------------------------------------------

ALARM_COLUMNS   = ["", "Timestamp", "Age", "Device", "Object",
                   "Description", "Priority", "State", "Category", "Acked By"]
COL_STRIPE      = 0   # zero-width spacer — stripe drawn by delegate on this col
COL_TIMESTAMP   = 1
COL_AGE         = 2
COL_DEVICE      = 3
COL_OBJECT      = 4
COL_DESCRIPTION = 5
COL_PRIORITY    = 6
COL_STATE       = 7
COL_CATEGORY    = 8
COL_ACKED_BY    = 9


# ---------------------------------------------------------------------------
# Qt table model
# ---------------------------------------------------------------------------

class AlarmTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[AlarmRecord] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(ALARM_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ALARM_COLUMNS[section]
        return QVariant()

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._data)):
            return QVariant()

        alarm = self._data[index.row()]
        col   = index.column()

        # Delegate handles all visual rendering — model only provides text + record
        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell_text(alarm, col)

        if role == Qt.ItemDataRole.UserRole:
            return alarm

        # Minimal font hint — delegate overrides most of this
        if role == Qt.ItemDataRole.FontRole:
            f = QFont()
            f.setPointSize(TABLE_FONT_SIZE)
            if alarm.state == AlarmState.CLEARED:
                f.setItalic(True)
            if alarm.state == AlarmState.ACTIVE and alarm.priority <= 2:
                f.setBold(True)
            return f

        return QVariant()

    def _cell_text(self, alarm: AlarmRecord, col: int) -> str:
        if   col == COL_STRIPE:      return ""
        elif col == COL_TIMESTAMP:   return alarm.timestamp.strftime("%Y-%m-%d %H:%M")
        elif col == COL_AGE:         return alarm.age_str
        elif col == COL_DEVICE:      return alarm.device_name
        elif col == COL_OBJECT:      return alarm.object_name
        elif col == COL_DESCRIPTION: return alarm.description
        elif col == COL_PRIORITY:    return f"P{alarm.priority}  {alarm.priority_label}"
        elif col == COL_STATE:       return alarm.state
        elif col == COL_CATEGORY:    return alarm.category
        elif col == COL_ACKED_BY:    return alarm.acked_by or ""
        return ""

    # ── Mutations ──────────────────────────────────────────────────────────

    def load_alarms(self, alarms: List[AlarmRecord]):
        self.beginResetModel()
        self._data = alarms
        self.endResetModel()

    def append_alarm(self, alarm: AlarmRecord):
        row = len(self._data)
        self.beginInsertRows(QModelIndex(), row, row)
        self._data.append(alarm)
        self.endInsertRows()

    def update_alarm(self, alarm_id: int, state: str,
                     acked_by: str = "", acked_at: Optional[datetime] = None):
        for i, rec in enumerate(self._data):
            if rec.alarm_id == alarm_id:
                rec.state    = state
                rec.acked_by = acked_by or rec.acked_by
                rec.acked_at = acked_at or rec.acked_at
                self.dataChanged.emit(self.index(i, 0),
                                      self.index(i, len(ALARM_COLUMNS) - 1))
                return

    def get_alarm(self, alarm_id: int) -> Optional[AlarmRecord]:
        return next((r for r in self._data if r.alarm_id == alarm_id), None)

    def all_alarms(self) -> List[AlarmRecord]:
        return list(self._data)

    def refresh_ages(self):
        if self._data:
            self.dataChanged.emit(self.index(0, COL_AGE),
                                  self.index(len(self._data) - 1, COL_AGE))


# ---------------------------------------------------------------------------
# Custom row delegate — all visual rendering lives here
# ---------------------------------------------------------------------------

class AlarmRowDelegate(QStyledItemDelegate):
    """
    Paints each alarm row with:
      • 4 px left accent stripe  (priority color, vivid)
      • Very subtle priority-tinted row background
      • Cleared rows: dimmed
      • Priority column: rounded pill badge
      • State column: small filled dot + label
      • Everything else: compact 9 pt text, left-padded
    """

    def paint(self, painter: QPainter,
              option: QStyleOptionViewItem, index: QModelIndex):
        # Retrieve the alarm record from col 0 of same row
        alarm_index = index.model().index(index.row(), 0)
        alarm: Optional[AlarmRecord] = alarm_index.data(Qt.ItemDataRole.UserRole)
        if alarm is None:
            super().paint(painter, option, index)
            return

        col      = index.column()
        rect     = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ── Row background ─────────────────────────────────────────────────
        if selected:
            bg = ROW_BG_SELECTED
        elif alarm.state == AlarmState.CLEARED:
            bg = ROW_BG_CLEARED
        else:
            bg = PRIORITY_ROW_BG.get(alarm.priority, QColor("#151C20"))
        painter.fillRect(rect, bg)

        # ── Left accent stripe (column 0 only) ────────────────────────────
        if col == COL_STRIPE:
            stripe_color = PRIORITY_STRIPE.get(alarm.priority, QColor("#546E7A"))
            stripe_rect  = QRect(rect.left(), rect.top(), STRIPE_WIDTH, rect.height())
            painter.fillRect(stripe_rect, stripe_color)
            painter.restore()
            return   # stripe column has no text

        # ── Text foreground ────────────────────────────────────────────────
        if alarm.state == AlarmState.CLEARED:
            fg = FG_CLEARED
        elif alarm.state == AlarmState.ACTIVE and alarm.priority <= 2:
            fg = FG_ACTIVE_HI
        else:
            fg = FG_NORMAL

        # ── Priority pill column ───────────────────────────────────────────
        if col == COL_PRIORITY:
            self._draw_priority_pill(painter, rect, alarm)
            painter.restore()
            return

        # ── State dot + label column ───────────────────────────────────────
        if col == COL_STATE:
            self._draw_state_dot(painter, rect, alarm, fg)
            painter.restore()
            return

        # ── Standard text columns ─────────────────────────────────────────
        font = QFont()
        font.setPointSize(TABLE_FONT_SIZE)
        if alarm.state == AlarmState.CLEARED:
            font.setItalic(True)
        if alarm.state == AlarmState.ACTIVE and alarm.priority <= 2 \
                and col == COL_DESCRIPTION:
            font.setBold(True)

        painter.setFont(font)
        painter.setPen(fg)

        text_rect = rect.adjusted(6, 0, -4, 0)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter
                         | Qt.AlignmentFlag.AlignLeft,
                         text)

        painter.restore()

    # ── Priority pill ──────────────────────────────────────────────────────

    def _draw_priority_pill(self, painter: QPainter,
                             rect: QRect, alarm: AlarmRecord):
        pill_bg = PRIORITY_PILL_BG.get(alarm.priority, QColor("#2C3E45"))
        stripe  = PRIORITY_STRIPE.get(alarm.priority, QColor("#546E7A"))
        label   = f"P{alarm.priority}  {alarm.priority_label}"

        font = QFont()
        font.setPointSize(TABLE_FONT_SIZE - 1)
        font.setBold(True)
        painter.setFont(font)

        fm       = painter.fontMetrics()
        text_w   = fm.horizontalAdvance(label)
        pill_w   = min(text_w + 20, rect.width() - 8)
        pill_h   = min(16, rect.height() - 4)
        pill_x   = rect.left() + 6
        pill_y   = rect.top() + (rect.height() - pill_h) // 2

        pill_rect = QRectF(pill_x, pill_y, pill_w, pill_h)

        # Pill background
        painter.setBrush(QBrush(pill_bg))
        painter.setPen(QPen(stripe, 1.0))
        painter.drawRoundedRect(pill_rect, 3, 3)

        # Pill text
        painter.setPen(QColor("#ECEFF1"))
        painter.drawText(pill_rect.toRect(),
                         Qt.AlignmentFlag.AlignCenter, label)

    # ── State dot ──────────────────────────────────────────────────────────

    def _draw_state_dot(self, painter: QPainter, rect: QRect,
                         alarm: AlarmRecord, fg: QColor):
        dot_color = STATE_DOT.get(alarm.state, QColor("#546E7A"))
        dot_size  = 7
        dot_x     = rect.left() + 8
        dot_y     = rect.top() + (rect.height() - dot_size) // 2

        painter.setBrush(QBrush(dot_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)

        font = QFont()
        font.setPointSize(TABLE_FONT_SIZE)
        if alarm.state == AlarmState.CLEARED:
            font.setItalic(True)
        painter.setFont(font)
        painter.setPen(fg)

        label_rect = rect.adjusted(dot_x - rect.left() + dot_size + 5, 0, -4, 0)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter
                         | Qt.AlignmentFlag.AlignLeft,
                         alarm.state)

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        sh.setHeight(ROW_HEIGHT)
        return sh


# ---------------------------------------------------------------------------
# Filter proxy
# ---------------------------------------------------------------------------

class AlarmFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_filter    = "All"
        self._priority_filter = "All"
        self._category_filter = "All"
        self._text_filter     = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_text_filter(self, text: str):
        self._text_filter = text.lower(); self.invalidateFilter()

    def set_state_filter(self, state: str):
        self._state_filter = state; self.invalidateFilter()

    def set_priority_filter(self, priority: str):
        self._priority_filter = priority; self.invalidateFilter()

    def set_category_filter(self, category: str):
        self._category_filter = category; self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        alarm = model.data(model.index(source_row, 0), Qt.ItemDataRole.UserRole)
        if alarm is None:
            return True

        if self._state_filter != "All" and alarm.state != self._state_filter:
            return False

        if self._priority_filter != "All":
            try:
                p = int(self._priority_filter.split()[0][1:])
                if alarm.priority != p:
                    return False
            except (ValueError, IndexError):
                pass

        if self._category_filter != "All" and alarm.category != self._category_filter:
            return False

        if self._text_filter:
            haystack = " ".join([alarm.device_name, alarm.object_name,
                                 alarm.description, alarm.category]).lower()
            if self._text_filter not in haystack:
                return False

        return True


# ---------------------------------------------------------------------------
# Background threads  (GOTCHA-013)
# ---------------------------------------------------------------------------

class AlarmLoadThread(QThread):
    alarms_loaded = pyqtSignal(list)
    load_error    = pyqtSignal(str)
    progress      = pyqtSignal(int, str)

    def __init__(self, adapter=None, parent=None):
        super().__init__(parent)
        self._adapter = adapter

    def run(self):
        try:
            self.progress.emit(10, "Connecting to device…")
            time.sleep(0.3)
            self.progress.emit(40, "Reading alarm log…")
            time.sleep(0.3)
            self.progress.emit(80, "Parsing records…")
            time.sleep(0.2)
            alarms = _generate_demo_alarms()
            self.progress.emit(100, "Done")
            self.alarms_loaded.emit(alarms)
        except Exception as exc:
            self.load_error.emit(str(exc))


class AlarmAckThread(QThread):
    ack_complete = pyqtSignal(list, str)
    ack_error    = pyqtSignal(str)

    def __init__(self, alarm_ids: List[int], username: str, adapter=None, parent=None):
        super().__init__(parent)
        self._ids      = alarm_ids
        self._username = username
        self._adapter  = adapter

    def run(self):
        try:
            time.sleep(0.4)
            self.ack_complete.emit(self._ids, self._username)
        except Exception as exc:
            self.ack_error.emit(str(exc))


class AlarmPollThread(QThread):
    new_alarms = pyqtSignal(list)
    poll_error = pyqtSignal(str)

    def __init__(self, interval_s: int = 30, adapter=None, parent=None):
        super().__init__(parent)
        self._interval = interval_s
        self._adapter  = adapter
        self._running  = True

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                time.sleep(self._interval)
                if not self._running:
                    break
                import random
                if random.random() < 0.3:
                    self.new_alarms.emit(_generate_demo_alarms(count=1))
            except Exception as exc:
                self.poll_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Detail panel
# ---------------------------------------------------------------------------

class AlarmDetailPanel(QWidget):
    ack_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alarm: Optional[AlarmRecord] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Alarm Detail")
        title.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #B0BEC5;"
        )
        layout.addWidget(title)

        # Priority stripe banner (replaces heavy colored box)
        self._banner = QFrame()
        self._banner.setFixedHeight(28)
        self._banner.setStyleSheet("border-radius: 3px;")
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(10, 0, 10, 0)
        self._banner_label = QLabel()
        self._banner_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #fff;")
        banner_layout.addWidget(self._banner_label)
        layout.addWidget(self._banner)

        scroll   = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content  = QWidget()
        self._fields_layout = QVBoxLayout(content)
        self._fields_layout.setSpacing(3)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        notes_lbl = QLabel("Notes:")
        notes_lbl.setStyleSheet("font-size: 10px; color: #78909C;")
        layout.addWidget(notes_lbl)
        self._notes_edit = QTextEdit()
        self._notes_edit.setMaximumHeight(70)
        self._notes_edit.setPlaceholderText("Technician notes…")
        self._notes_edit.setStyleSheet(
            "QTextEdit { background: #1A2228; border: 1px solid #37474F; "
            "border-radius: 3px; font-size: 9pt; color: #CFD8DC; }"
        )
        layout.addWidget(self._notes_edit)

        self._ack_btn = QPushButton("✅  Acknowledge")
        self._ack_btn.setEnabled(False)
        self._ack_btn.setStyleSheet(
            "QPushButton { background: #1B5E20; color: #fff; border-radius: 3px; "
            "padding: 5px; font-size: 9pt; }"
            "QPushButton:hover { background: #2E7D32; }"
            "QPushButton:disabled { background: #263238; color: #546E7A; }"
        )
        self._ack_btn.clicked.connect(self._on_ack)
        layout.addWidget(self._ack_btn)

    def _clear_fields(self):
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_field(self, label: str, value: str, highlight: bool = False):
        row = QHBoxLayout()
        row.setSpacing(0)
        lbl = QLabel(f"{label}")
        lbl.setFixedWidth(85)
        lbl.setStyleSheet("color: #607D8B; font-size: 9pt;")
        val = QLabel(str(value) if value else "—")
        val.setWordWrap(True)
        color = "#ECEFF1" if highlight else "#B0BEC5"
        val.setStyleSheet(
            f"color: {color}; font-size: 9pt;"
            + (" font-weight: bold;" if highlight else "")
        )
        row.addWidget(lbl)
        row.addWidget(val, 1)
        container = QWidget()
        container.setLayout(row)
        self._fields_layout.addWidget(container)

    def show_alarm(self, alarm: AlarmRecord):
        self._alarm = alarm
        self._clear_fields()

        stripe = PRIORITY_STRIPE.get(alarm.priority, QColor("#546E7A"))
        pill   = PRIORITY_PILL_BG.get(alarm.priority, QColor("#2C3E45"))
        self._banner.setStyleSheet(
            f"background: {pill.name()}; border-left: 4px solid {stripe.name()}; "
            "border-radius: 3px;"
        )
        self._banner_label.setText(
            f"P{alarm.priority} — {PRIORITY_LABELS.get(alarm.priority, '')}  ·  "
            f"{alarm.state}"
        )

        self._add_field("ID",          str(alarm.alarm_id))
        self._add_field("Timestamp",   alarm.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        self._add_field("Age",         alarm.age_str)
        self._add_field("State",       alarm.state, highlight=True)
        self._add_field("Device",      alarm.device_name)
        self._add_field("Address",     alarm.device_addr)
        self._add_field("Object",      alarm.object_name)
        self._add_field("Type",        alarm.object_type)
        self._add_field("Instance",    str(alarm.instance))
        self._add_field("Description", alarm.description, highlight=True)
        self._add_field("Category",    alarm.category)
        self._add_field("From",        alarm.from_value)
        self._add_field("To",          alarm.to_value)
        self._add_field("Units",       alarm.units)
        if alarm.acked_by:
            self._add_field("Acked By",  alarm.acked_by)
            if alarm.acked_at:
                self._add_field("Acked At",
                                alarm.acked_at.strftime("%Y-%m-%d %H:%M:%S"))

        self._notes_edit.setPlainText(alarm.notes)
        self._ack_btn.setEnabled(alarm.state == AlarmState.ACTIVE)

    def clear(self):
        self._alarm = None
        self._clear_fields()
        self._banner_label.setText("")
        self._banner.setStyleSheet("border-radius: 3px; background: #1A2228;")
        self._notes_edit.clear()
        self._ack_btn.setEnabled(False)

    def _on_ack(self):
        if self._alarm:
            self.ack_requested.emit(self._alarm.alarm_id)


# ---------------------------------------------------------------------------
# Acknowledge dialog
# ---------------------------------------------------------------------------

class AckDialog(QDialog):
    def __init__(self, alarm_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acknowledge Alarms")
        self.setFixedWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel(
            f"Acknowledging <b>{alarm_count}</b> alarm(s).<br>"
            "Enter your name or ID to confirm:"
        ))

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Technician name or ID…")
        layout.addWidget(self._user_edit)

        self._note_edit = QTextEdit()
        self._note_edit.setMaximumHeight(60)
        self._note_edit.setPlaceholderText("Optional note…")
        layout.addWidget(self._note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not self._user_edit.text().strip():
            QMessageBox.warning(self, "Required", "Please enter your name or ID.")
            return
        self.accept()

    @property
    def username(self) -> str: return self._user_edit.text().strip()

    @property
    def note(self) -> str: return self._note_edit.toPlainText().strip()


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _export_csv(alarms: List[AlarmRecord], filepath: str) -> int:
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID","Timestamp","Age","Device","Address","Object","Type",
                    "Instance","Description","Priority","State","Category",
                    "From","To","Acked By","Acked At"])
        for a in alarms:
            w.writerow([
                a.alarm_id, a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                a.age_str, a.device_name, a.device_addr, a.object_name,
                a.object_type, a.instance, a.description,
                f"P{a.priority} {a.priority_label}", a.state, a.category,
                a.from_value, a.to_value, a.acked_by or "",
                a.acked_at.strftime("%Y-%m-%d %H:%M:%S") if a.acked_at else "",
            ])
    return len(alarms)


def _export_pdf(alarms: List[AlarmRecord], filepath: str) -> int:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except ImportError:
        raise ImportError("ReportLab not installed. Run: pip install reportlab")

    doc    = SimpleDocTemplate(filepath, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    story  = []

    story.append(Paragraph("HBCE — Alarm Viewer Export",
                            ParagraphStyle("T", parent=styles["Title"],
                                           fontSize=14, spaceAfter=3)))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"Records: {len(alarms)}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    # Stripe colors for PDF rows — muted, left-border style approximated via bg
    rl_pill = {
        1: colors.HexColor("#7B0000"), 2: colors.HexColor("#6D1F00"),
        3: colors.HexColor("#6D2F00"), 4: colors.HexColor("#7B5800"),
        5: colors.HexColor("#4A4700"), 6: colors.HexColor("#0D3B7A"),
        7: colors.HexColor("#1B4D1F"), 8: colors.HexColor("#2C3E45"),
    }
    header = ["ID","Timestamp","Device","Object","Description","Priority","State","Category"]
    table_data = [header]
    style_cmds = [
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#263238")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7),
        ("GRID",       (0,0), (-1,-1), 0.2, colors.HexColor("#37474F")),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1),
         [colors.HexColor("#1A1F22"), colors.HexColor("#161B1E")]),
        ("TEXTCOLOR",  (0,1), (-1,-1), colors.HexColor("#CFD8DC")),
    ]
    for i, a in enumerate(alarms, start=1):
        table_data.append([
            str(a.alarm_id), a.timestamp.strftime("%Y-%m-%d %H:%M"),
            a.device_name, a.object_name, a.description[:55],
            f"P{a.priority} {a.priority_label}", a.state, a.category,
        ])
        # Left cell tinted with priority pill color
        style_cmds.append(
            ("BACKGROUND", (0,i), (0,i), rl_pill.get(a.priority, colors.grey))
        )

    col_widths = [14*mm,30*mm,35*mm,35*mm,72*mm,28*mm,28*mm,26*mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    doc.build(story)
    return len(alarms)


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

_DEMO_COUNTER = 0

def _generate_demo_alarms(count: int = 40) -> List[AlarmRecord]:
    global _DEMO_COUNTER
    import random

    devices = [("AHU-1","192.168.1.10"),("AHU-2","192.168.1.11"),
               ("CHWR-1","192.168.1.20"),("BAS-CTRL","192.168.1.1"),
               ("VAV-B3-04","192.168.1.45")]
    objects = [("SA-TEMP","analogInput",0,"°F"),("RA-TEMP","analogInput",1,"°F"),
               ("SA-SP","analogValue",2,"°F"),("FAN-SPD","analogOutput",0,"%"),
               ("CHW-FLOW","analogInput",5,"GPM"),("FIRE-1","binaryInput",0,""),
               ("SMOKE-1","binaryInput",1,""),("OCC","binaryValue",0,"")]
    descs = ["High supply air temperature","Low return air temperature",
             "Fan speed out of range","Chilled water flow fault",
             "Fire alarm active","Smoke detector triggered",
             "Occupancy sensor fault","Controller offline",
             "Communication timeout","Setpoint deviation exceeded"]
    categories = ["HVAC","Fire/Life Safety","Equipment","Communication","General"]
    states     = [AlarmState.ACTIVE, AlarmState.ACTIVE,
                  AlarmState.ACKNOWLEDGED, AlarmState.CLEARED]

    alarms = []
    for i in range(count):
        _DEMO_COUNTER += 1
        dev   = random.choice(devices)
        obj   = random.choice(objects)
        state = random.choice(states)
        pri   = random.randint(1, 8)
        ts    = datetime.fromtimestamp(time.time() - random.randint(0, 86400*7))
        acked_by = acked_at = None
        if state in (AlarmState.ACKNOWLEDGED, AlarmState.CLEARED):
            acked_by = random.choice(["jsmith","atechman","operator1"])
            acked_at = datetime.fromtimestamp(ts.timestamp() + random.randint(60, 3600))

        alarms.append(AlarmRecord(
            alarm_id=_DEMO_COUNTER * 100 + i, timestamp=ts,
            device_name=dev[0], device_addr=dev[1],
            object_name=obj[0], object_type=obj[1], instance=obj[2],
            description=random.choice(descs), priority=pri, state=state,
            acked_by=acked_by, acked_at=acked_at,
            category=random.choice(categories), units=obj[3],
            from_value=f"{random.uniform(50,90):.1f}",
            to_value=f"{random.uniform(90,120):.1f}",
        ))

    alarms.sort(key=lambda a: (
        0 if a.state == AlarmState.ACTIVE else 1, a.priority, a.timestamp
    ))
    return alarms


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class AlarmViewerPanel(QWidget):
    """
    HBCE Alarm Viewer — V0.0.8-alpha (visual redesign)

    Visual: stripe + pill approach — no full-row saturation.
    All other features identical to original V0.0.8 implementation.
    """

    def __init__(self, config=None, db=None, current_user=None,
                 adapter=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {}
        self._username      = self.current_user.get("username", "operator")
        self._adapter       = adapter
        self._poll_thread: Optional[AlarmPollThread] = None
        self._polling       = False
        self._poll_interval = 30

        self._build_ui()
        self._connect_signals()
        self._load_alarms()

        self._age_timer = QTimer(self)
        self._age_timer.timeout.connect(self._refresh_ages)
        self._age_timer.start(60_000)

        logger.debug("AlarmViewerPanel initialized (redesign)")

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_filter_bar())

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self._splitter, 1)
        self._splitter.addWidget(self._build_table_widget())

        self._detail_panel = AlarmDetailPanel()
        self._detail_panel.ack_requested.connect(self._ack_single)
        self._detail_panel.setMinimumWidth(230)
        self._detail_panel.setStyleSheet("background: #111820;")
        self._splitter.addWidget(self._detail_panel)
        self._splitter.setSizes([870, 290])

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setStyleSheet(
            "QStatusBar { background: #0F1518; color: #607D8B; font-size: 9pt; }"
        )
        root.addWidget(self._status_bar)
        self._status_bar.showMessage("Loading alarms…")

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(
            "background: #0F1518; border-bottom: 1px solid #263238;"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        title = QLabel("🔔  Alarm Viewer")
        title.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #B0BEC5;"
        )
        layout.addWidget(title)
        layout.addStretch()

        btn_style = (
            "QPushButton { background: #1A2428; color: #90A4AE; border: 1px solid #263238; "
            "border-radius: 3px; padding: 3px 10px; font-size: 9pt; }"
            "QPushButton:hover { background: #243038; color: #CFD8DC; }"
            "QPushButton:checked { background: #1B3A2A; color: #81C784; }"
            "QPushButton:disabled { color: #37474F; }"
        )

        self._ack_btn = QPushButton("✅  Acknowledge Selected")
        self._ack_btn.setEnabled(False)
        self._ack_btn.setStyleSheet(btn_style)
        layout.addWidget(self._ack_btn)

        self._ack_all_btn = QPushButton("✅  Ack All Active")
        self._ack_all_btn.setStyleSheet(btn_style)
        layout.addWidget(self._ack_all_btn)

        self._refresh_btn = QPushButton("↺  Refresh")
        self._refresh_btn.setStyleSheet(btn_style)
        layout.addWidget(self._refresh_btn)

        self._poll_btn = QPushButton("▶  Poll")
        self._poll_btn.setCheckable(True)
        self._poll_btn.setStyleSheet(btn_style)
        layout.addWidget(self._poll_btn)

        layout.addWidget(self._build_interval_selector())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #263238;")
        layout.addWidget(sep)

        self._csv_btn = QPushButton("↓ CSV")
        self._csv_btn.setStyleSheet(btn_style)
        layout.addWidget(self._csv_btn)

        self._pdf_btn = QPushButton("↓ PDF")
        self._pdf_btn.setStyleSheet(btn_style)
        layout.addWidget(self._pdf_btn)

        return bar

    def _build_interval_selector(self) -> QWidget:
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        lbl = QLabel("Poll:")
        lbl.setStyleSheet("color: #546E7A; font-size: 9pt;")
        h.addWidget(lbl)
        self._interval_combo = QComboBox()
        self._interval_combo.setFixedWidth(68)
        self._interval_combo.setStyleSheet(
            "QComboBox { background: #1A2428; color: #90A4AE; "
            "border: 1px solid #263238; border-radius: 3px; font-size: 9pt; }"
        )
        for s, lbl in [(10,"10 s"),(30,"30 s"),(60,"1 min"),(300,"5 min")]:
            self._interval_combo.addItem(lbl, s)
        self._interval_combo.setCurrentIndex(1)
        h.addWidget(self._interval_combo)
        return c

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet(
            "background: #111A20; border-bottom: 1px solid #1E2B32;"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(8)

        lbl_style  = "color: #546E7A; font-size: 9pt;"
        edit_style = (
            "QLineEdit { background: #1A2428; color: #B0BEC5; "
            "border: 1px solid #263238; border-radius: 3px; "
            "padding: 2px 6px; font-size: 9pt; }"
        )
        combo_style = (
            "QComboBox { background: #1A2428; color: #B0BEC5; "
            "border: 1px solid #263238; border-radius: 3px; "
            "padding: 2px 4px; font-size: 9pt; }"
        )

        layout.addWidget(QLabel("🔍"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setFixedWidth(200)
        self._search_edit.setStyleSheet(edit_style)
        layout.addWidget(self._search_edit)

        lbl = QLabel("State:"); lbl.setStyleSheet(lbl_style)
        layout.addWidget(lbl)
        self._state_combo = QComboBox()
        self._state_combo.addItems(["All","Active","Acknowledged","Cleared"])
        self._state_combo.setFixedWidth(100)
        self._state_combo.setStyleSheet(combo_style)
        layout.addWidget(self._state_combo)

        lbl2 = QLabel("Priority:"); lbl2.setStyleSheet(lbl_style)
        layout.addWidget(lbl2)
        self._priority_combo = QComboBox()
        self._priority_combo.addItem("All")
        for p, lbl_t in PRIORITY_LABELS.items():
            self._priority_combo.addItem(f"P{p} — {lbl_t}", p)
        self._priority_combo.setFixedWidth(140)
        self._priority_combo.setStyleSheet(combo_style)
        layout.addWidget(self._priority_combo)

        lbl3 = QLabel("Category:"); lbl3.setStyleSheet(lbl_style)
        layout.addWidget(lbl3)
        self._category_combo = QComboBox()
        self._category_combo.addItem("All")
        self._category_combo.setFixedWidth(120)
        self._category_combo.setStyleSheet(combo_style)
        layout.addWidget(self._category_combo)

        self._clear_filter_btn = QPushButton("✕")
        self._clear_filter_btn.setFixedWidth(28)
        self._clear_filter_btn.setToolTip("Clear all filters")
        self._clear_filter_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #546E7A; "
            "border: none; font-size: 11pt; }"
            "QPushButton:hover { color: #90A4AE; }"
        )
        layout.addWidget(self._clear_filter_btn)
        layout.addStretch()
        return bar

    def _build_table_widget(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = AlarmTableModel(self)
        self._proxy = AlarmFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(Qt.ItemDataRole.DisplayRole)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setStyleSheet("""
            QTableView {
                background: #111820;
                gridline-color: transparent;
                selection-background-color: transparent;
            }
            QHeaderView::section {
                background: #0F1518;
                color: #546E7A;
                border: none;
                border-bottom: 1px solid #1E2B32;
                padding: 3px 6px;
                font-size: 9px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QScrollBar:vertical {
                background: #0F1518; width: 8px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #263238; border-radius: 4px;
            }
        """)

        # Apply custom delegate to all columns
        self._delegate = AlarmRowDelegate(self._table)
        self._table.setItemDelegate(self._delegate)

        # Column widths
        self._table.setColumnWidth(COL_STRIPE,     STRIPE_WIDTH + 2)
        self._table.setColumnWidth(COL_TIMESTAMP,  128)
        self._table.setColumnWidth(COL_AGE,        42)
        self._table.setColumnWidth(COL_DEVICE,     88)
        self._table.setColumnWidth(COL_OBJECT,     90)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch
        )
        self._table.setColumnWidth(COL_PRIORITY,   132)
        self._table.setColumnWidth(COL_STATE,      105)
        self._table.setColumnWidth(COL_CATEGORY,   90)
        self._table.setColumnWidth(COL_ACKED_BY,   80)

        # Row height
        self._table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)

        layout.addWidget(self._table)
        return container

    # ── Signals ────────────────────────────────────────────────────────────

    def _connect_signals(self):
        self._ack_btn.clicked.connect(self._ack_selected)
        self._ack_all_btn.clicked.connect(self._ack_all_active)
        self._refresh_btn.clicked.connect(self._load_alarms)
        self._poll_btn.toggled.connect(self._toggle_polling)
        self._csv_btn.clicked.connect(self._export_csv)
        self._pdf_btn.clicked.connect(self._export_pdf)

        self._search_edit.textChanged.connect(self._proxy.set_text_filter)
        self._state_combo.currentTextChanged.connect(self._proxy.set_state_filter)
        self._priority_combo.currentTextChanged.connect(self._proxy.set_priority_filter)
        self._category_combo.currentTextChanged.connect(self._proxy.set_category_filter)
        self._clear_filter_btn.clicked.connect(self._clear_filters)

        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._interval_combo.currentIndexChanged.connect(self._update_poll_interval)

    # ── Load ───────────────────────────────────────────────────────────────

    def _load_alarms(self):
        self._status_bar.showMessage("Loading alarms…")
        self._load_thread = AlarmLoadThread(adapter=self._adapter, parent=self)
        self._load_thread.alarms_loaded.connect(self._on_alarms_loaded)
        self._load_thread.load_error.connect(
            lambda e: self._status_bar.showMessage(f"Error: {e}"))
        self._load_thread.progress.connect(
            lambda pct, msg: self._status_bar.showMessage(f"{msg} ({pct}%)"))
        self._load_thread.start()

    def _on_alarms_loaded(self, alarms: List[AlarmRecord]):
        self._model.load_alarms(alarms)
        cats = sorted({a.category for a in alarms})
        self._category_combo.blockSignals(True)
        cur = self._category_combo.currentText()
        self._category_combo.clear()
        self._category_combo.addItem("All")
        self._category_combo.addItems(cats)
        idx = self._category_combo.findText(cur)
        if idx >= 0: self._category_combo.setCurrentIndex(idx)
        self._category_combo.blockSignals(False)
        self._update_status()

    # ── Acknowledge ────────────────────────────────────────────────────────

    def _ack_selected(self):
        ids = self._selected_active_ids()
        if not ids:
            QMessageBox.information(self, "Nothing to Acknowledge",
                                    "Select one or more active alarms first.")
            return
        self._run_ack(ids)

    def _ack_all_active(self):
        ids = [a.alarm_id for r in range(self._proxy.rowCount())
               for a in [self._proxy.data(self._proxy.index(r, 0),
                                          Qt.ItemDataRole.UserRole)]
               if a and a.state == AlarmState.ACTIVE]
        if not ids:
            QMessageBox.information(self, "No Active Alarms",
                                    "No active alarms in current view.")
            return
        self._run_ack(ids)

    def _ack_single(self, alarm_id: int):
        self._run_ack([alarm_id])

    def _run_ack(self, ids: List[int]):
        dlg = AckDialog(len(ids), self)
        dlg._user_edit.setText(self._username)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._status_bar.showMessage(f"Acknowledging {len(ids)} alarm(s)…")
        self._ack_thread = AlarmAckThread(ids, dlg.username, self._adapter, self)
        self._ack_thread.ack_complete.connect(self._on_ack_complete)
        self._ack_thread.ack_error.connect(
            lambda e: self._status_bar.showMessage(f"Ack error: {e}"))
        self._ack_thread.start()

    def _on_ack_complete(self, alarm_ids: List[int], username: str):
        now = datetime.now()
        for aid in alarm_ids:
            self._model.update_alarm(aid, AlarmState.ACKNOWLEDGED, username, now)
        self._update_status()
        self._status_bar.showMessage(
            f"✅ Acknowledged {len(alarm_ids)} alarm(s) by '{username}'")
        if (self._detail_panel._alarm
                and self._detail_panel._alarm.alarm_id in alarm_ids):
            rec = self._model.get_alarm(self._detail_panel._alarm.alarm_id)
            if rec: self._detail_panel.show_alarm(rec)

    def _selected_active_ids(self) -> List[int]:
        return [a.alarm_id for idx in self._table.selectionModel().selectedRows()
                for a in [self._proxy.data(idx, Qt.ItemDataRole.UserRole)]
                if a and a.state == AlarmState.ACTIVE]

    # ── Polling ────────────────────────────────────────────────────────────

    def _toggle_polling(self, checked: bool):
        if checked: self._start_polling()
        else:       self._stop_polling()

    def _start_polling(self):
        self._poll_interval = self._interval_combo.currentData() or 30
        self._poll_thread   = AlarmPollThread(self._poll_interval, self._adapter, self)
        self._poll_thread.new_alarms.connect(self._on_new_alarms)
        self._poll_thread.poll_error.connect(
            lambda e: self._status_bar.showMessage(f"Poll error: {e}"))
        self._poll_thread.start()
        self._poll_btn.setText("⏹  Poll")
        self._polling = True

    def _stop_polling(self):
        if self._poll_thread:
            self._poll_thread.stop()
            self._poll_thread.quit()
            self._poll_thread.wait(2000)
            self._poll_thread = None
        self._poll_btn.setText("▶  Poll")
        self._polling = False
        self._update_status()

    def _update_poll_interval(self):
        if self._polling:
            self._stop_polling()
            self._poll_btn.setChecked(True)
            self._start_polling()

    def _on_new_alarms(self, alarms: List[AlarmRecord]):
        for a in alarms: self._model.append_alarm(a)
        self._update_status()
        if alarms:
            self._status_bar.showMessage(f"🔔 {len(alarms)} new alarm(s) received")

    # ── Selection ──────────────────────────────────────────────────────────

    def _on_selection_changed(self):
        rows         = self._table.selectionModel().selectedRows()
        active_count = 0
        if len(rows) == 1:
            alarm = self._proxy.data(rows[0], Qt.ItemDataRole.UserRole)
            if alarm:
                self._detail_panel.show_alarm(alarm)
                active_count = 1 if alarm.state == AlarmState.ACTIVE else 0
        elif len(rows) == 0:
            self._detail_panel.clear()
        else:
            active_count = sum(
                1 for r in rows
                if (a := self._proxy.data(r, Qt.ItemDataRole.UserRole))
                and a.state == AlarmState.ACTIVE
            )

        self._ack_btn.setEnabled(active_count > 0)
        self._ack_btn.setText(
            f"✅  Acknowledge ({active_count})" if active_count
            else "✅  Acknowledge Selected"
        )

    def _on_double_click(self, proxy_idx: QModelIndex):
        alarm = self._proxy.data(proxy_idx, Qt.ItemDataRole.UserRole)
        if alarm and alarm.state == AlarmState.ACTIVE:
            self._run_ack([alarm.alarm_id])

    def _show_context_menu(self, pos):
        proxy_idx = self._table.indexAt(pos)
        if not proxy_idx.isValid():
            return
        alarm = self._proxy.data(proxy_idx, Qt.ItemDataRole.UserRole)
        if not alarm:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1A2428; color: #B0BEC5; border: 1px solid #263238; }"
            "QMenu::item:selected { background: #2D4450; }"
        )
        if alarm.state == AlarmState.ACTIVE:
            a = menu.addAction("✅  Acknowledge")
            a.triggered.connect(lambda: self._run_ack([alarm.alarm_id]))

        a2 = menu.addAction("🔍  View Details")
        a2.triggered.connect(lambda: self._detail_panel.show_alarm(alarm))
        menu.addSeparator()

        a3 = menu.addAction("📋  Copy Description")
        a3.triggered.connect(lambda: QApplication.clipboard().setText(alarm.description))

        a4 = menu.addAction("📋  Copy Row CSV")
        a4.triggered.connect(lambda: self._copy_row_csv(alarm))
        menu.addSeparator()

        a5 = menu.addAction("🔗  Go to Point in Browser")
        a5.triggered.connect(lambda: self._status_bar.showMessage(
            f"→ {alarm.device_name} / {alarm.object_name} (wire to Point Browser)"))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_row_csv(self, alarm: AlarmRecord):
        buf = io.StringIO()
        csv.writer(buf).writerow([
            alarm.alarm_id, alarm.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            alarm.device_name, alarm.object_name, alarm.description,
            f"P{alarm.priority}", alarm.state, alarm.category,
        ])
        QApplication.clipboard().setText(buf.getvalue().strip())

    def _clear_filters(self):
        self._search_edit.clear()
        self._state_combo.setCurrentIndex(0)
        self._priority_combo.setCurrentIndex(0)
        self._category_combo.setCurrentIndex(0)

    # ── Export ─────────────────────────────────────────────────────────────

    def _visible_alarms(self) -> List[AlarmRecord]:
        return [a for r in range(self._proxy.rowCount())
                for a in [self._proxy.data(self._proxy.index(r, 0),
                                           Qt.ItemDataRole.UserRole)] if a]

    def _export_csv(self):
        alarms = self._visible_alarms()
        if not alarms:
            QMessageBox.information(self,"Nothing to Export",
                                    "No alarms match current filters."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV",
            f"alarms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)")
        if not path: return
        try:
            n = _export_csv(alarms, path)
            self._status_bar.showMessage(
                f"✅ CSV: {n} records → {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _export_pdf(self):
        alarms = self._visible_alarms()
        if not alarms:
            QMessageBox.information(self,"Nothing to Export",
                                    "No alarms match current filters."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF",
            f"alarms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            "PDF Files (*.pdf)")
        if not path: return
        try:
            n = _export_pdf(alarms, path)
            self._status_bar.showMessage(
                f"✅ PDF: {n} records → {os.path.basename(path)}")
        except ImportError as e:
            QMessageBox.warning(self,"ReportLab Not Installed",
                                str(e)+"\n\nRun: pip install reportlab")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ── Status / cleanup ───────────────────────────────────────────────────

    def _update_status(self):
        total   = self._model.rowCount()
        visible = self._proxy.rowCount()
        active  = sum(1 for a in self._model.all_alarms()
                      if a.state == AlarmState.ACTIVE)
        poll_str = (f"  ·  polling {self._poll_interval}s"
                    if self._polling else "")
        self._status_bar.showMessage(
            f"Total: {total}  ·  Visible: {visible}  ·  Active: {active}{poll_str}")

    def _refresh_ages(self):
        self._model.refresh_ages()

    def closeEvent(self, event):
        self._stop_polling()
        self._age_timer.stop()
        super().closeEvent(event)
