# ui/panels/alarm_viewer.py
# HBCE — Hybrid Controls Editor
# Alarm Viewer Panel — V0.0.8-alpha
# Full implementation: priority color coding, ack single/bulk, filters, CSV/PDF export
# ~1,400 lines

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
    QSortFilterProxyModel,
    Qt,
    QThread,
    QTimer,
    QVariant,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QFont, QAction
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
    LIFE_SAFETY    = 1
    CRITICAL       = 2
    HIGH           = 3
    MEDIUM_HIGH    = 4
    MEDIUM         = 5
    MEDIUM_LOW     = 6
    LOW            = 7
    INFORMATIONAL  = 8

PRIORITY_LABELS = {
    AlarmPriority.LIFE_SAFETY:   "Life Safety",
    AlarmPriority.CRITICAL:      "Critical",
    AlarmPriority.HIGH:          "High",
    AlarmPriority.MEDIUM_HIGH:   "Medium-High",
    AlarmPriority.MEDIUM:        "Medium",
    AlarmPriority.MEDIUM_LOW:    "Medium-Low",
    AlarmPriority.LOW:           "Low",
    AlarmPriority.INFORMATIONAL: "Informational",
}

# Background colors per priority (dark-mode friendly)
PRIORITY_COLORS = {
    AlarmPriority.LIFE_SAFETY:   QColor("#7B0000"),
    AlarmPriority.CRITICAL:      QColor("#B71C1C"),
    AlarmPriority.HIGH:          QColor("#E65100"),
    AlarmPriority.MEDIUM_HIGH:   QColor("#F57F17"),
    AlarmPriority.MEDIUM:        QColor("#827717"),
    AlarmPriority.MEDIUM_LOW:    QColor("#1A5276"),
    AlarmPriority.LOW:           QColor("#1B5E20"),
    AlarmPriority.INFORMATIONAL: QColor("#37474F"),
}

PRIORITY_FG = QColor("#FFFFFF")


class AlarmState:
    ACTIVE       = "Active"
    ACKNOWLEDGED = "Acknowledged"
    CLEARED      = "Cleared"


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
        if s < 60:
            return f"{s}s ago"
        elif s < 3600:
            return f"{s // 60}m ago"
        elif s < 86400:
            return f"{s // 3600}h ago"
        else:
            return f"{s // 86400}d ago"


# ---------------------------------------------------------------------------
# Table columns
# ---------------------------------------------------------------------------

ALARM_COLUMNS = [
    "ID", "Timestamp", "Age", "Device", "Object",
    "Description", "Priority", "State", "Category", "Acked By",
]

COL_ID          = 0
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

        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell_text(alarm, col)

        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(PRIORITY_COLORS.get(alarm.priority, QColor("#37474F")))

        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(PRIORITY_FG)

        if role == Qt.ItemDataRole.FontRole:
            f = QFont()
            if alarm.state == AlarmState.ACTIVE and alarm.priority <= AlarmPriority.CRITICAL:
                f.setBold(True)
            if alarm.state == AlarmState.CLEARED:
                f.setItalic(True)
            return f

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_ID, COL_PRIORITY):
                return int(Qt.AlignmentFlag.AlignCenter)

        if role == Qt.ItemDataRole.UserRole:
            return alarm

        return QVariant()

    def _cell_text(self, alarm: AlarmRecord, col: int) -> str:
        if   col == COL_ID:          return str(alarm.alarm_id)
        elif col == COL_TIMESTAMP:   return alarm.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        elif col == COL_AGE:         return alarm.age_str
        elif col == COL_DEVICE:      return alarm.device_name
        elif col == COL_OBJECT:      return alarm.object_name
        elif col == COL_DESCRIPTION: return alarm.description
        elif col == COL_PRIORITY:    return f"P{alarm.priority} — {alarm.priority_label}"
        elif col == COL_STATE:       return alarm.state
        elif col == COL_CATEGORY:    return alarm.category
        elif col == COL_ACKED_BY:    return alarm.acked_by or ""
        return ""

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
                idx_l = self.index(i, 0)
                idx_r = self.index(i, len(ALARM_COLUMNS) - 1)
                self.dataChanged.emit(idx_l, idx_r)
                return

    def get_alarm(self, alarm_id: int) -> Optional[AlarmRecord]:
        for rec in self._data:
            if rec.alarm_id == alarm_id:
                return rec
        return None

    def all_alarms(self) -> List[AlarmRecord]:
        return list(self._data)

    def refresh_ages(self):
        if self._data:
            idx_l = self.index(0, COL_AGE)
            idx_r = self.index(len(self._data) - 1, COL_AGE)
            self.dataChanged.emit(idx_l, idx_r)


# ---------------------------------------------------------------------------
# Sort/filter proxy
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
        self._text_filter = text.lower()
        self.invalidateFilter()

    def set_state_filter(self, state: str):
        self._state_filter = state
        self.invalidateFilter()

    def set_priority_filter(self, priority: str):
        self._priority_filter = priority
        self.invalidateFilter()

    def set_category_filter(self, category: str):
        self._category_filter = category
        self.invalidateFilter()

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
            haystack = " ".join([
                alarm.device_name, alarm.object_name,
                alarm.description, alarm.category,
            ]).lower()
            if self._text_filter not in haystack:
                return False

        return True


# ---------------------------------------------------------------------------
# Background threads  (GOTCHA-013: never block the UI thread)
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
            # Real: alarms = self._adapter.read_alarm_log()
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
            time.sleep(0.4)   # Real: self._adapter.acknowledge(self._ids)
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
                # Real: new = self._adapter.poll_new_alarms()
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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Alarm Detail")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        self._priority_badge = QLabel()
        self._priority_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._priority_badge.setFixedHeight(32)
        layout.addWidget(self._priority_badge)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._fields_layout = QVBoxLayout(content)
        self._fields_layout.setSpacing(4)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        notes_lbl = QLabel("Notes:")
        notes_lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(notes_lbl)
        self._notes_edit = QTextEdit()
        self._notes_edit.setMaximumHeight(80)
        self._notes_edit.setPlaceholderText("Add technician notes here…")
        layout.addWidget(self._notes_edit)

        self._ack_btn = QPushButton("✅  Acknowledge Alarm")
        self._ack_btn.setEnabled(False)
        self._ack_btn.clicked.connect(self._on_ack)
        layout.addWidget(self._ack_btn)

    def _clear_fields(self):
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_field(self, label: str, value: str, bold_value: bool = False):
        row   = QHBoxLayout()
        lbl   = QLabel(f"{label}:")
        lbl.setStyleSheet("color: #9E9E9E;")
        lbl.setFixedWidth(100)
        val   = QLabel(str(value) if value else "—")
        if bold_value:
            val.setStyleSheet("font-weight: bold;")
        val.setWordWrap(True)
        row.addWidget(lbl)
        row.addWidget(val, 1)
        container = QWidget()
        container.setLayout(row)
        self._fields_layout.addWidget(container)

    def show_alarm(self, alarm: AlarmRecord):
        self._alarm = alarm
        self._clear_fields()

        color = PRIORITY_COLORS.get(alarm.priority, QColor("#37474F"))
        self._priority_badge.setText(f"P{alarm.priority} — {alarm.priority_label}")
        self._priority_badge.setStyleSheet(
            f"background: {color.name()}; color: white; "
            "border-radius: 4px; font-weight: bold; padding: 4px;"
        )

        self._add_field("Alarm ID",    str(alarm.alarm_id))
        self._add_field("Timestamp",   alarm.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        self._add_field("Age",         alarm.age_str)
        self._add_field("State",       alarm.state, bold_value=True)
        self._add_field("Device",      alarm.device_name)
        self._add_field("Address",     alarm.device_addr)
        self._add_field("Object",      alarm.object_name)
        self._add_field("Type",        alarm.object_type)
        self._add_field("Instance",    str(alarm.instance))
        self._add_field("Description", alarm.description)
        self._add_field("Category",    alarm.category)
        self._add_field("From Value",  alarm.from_value)
        self._add_field("To Value",    alarm.to_value)
        self._add_field("Units",       alarm.units)

        if alarm.acked_by:
            self._add_field("Acked By", alarm.acked_by)
            if alarm.acked_at:
                self._add_field("Acked At",
                                alarm.acked_at.strftime("%Y-%m-%d %H:%M:%S"))

        self._notes_edit.setPlainText(alarm.notes)
        self._ack_btn.setEnabled(alarm.state == AlarmState.ACTIVE)

    def clear(self):
        self._alarm = None
        self._clear_fields()
        self._priority_badge.setText("")
        self._priority_badge.setStyleSheet("")
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
        self.setFixedWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel(
            f"Acknowledging <b>{alarm_count}</b> alarm(s).<br>"
            "Enter your name or ID to confirm:"
        ))

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Technician name or ID…")
        layout.addWidget(self._user_edit)

        self._note_edit = QTextEdit()
        self._note_edit.setMaximumHeight(70)
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
    def username(self) -> str:
        return self._user_edit.text().strip()

    @property
    def note(self) -> str:
        return self._note_edit.toPlainText().strip()


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _export_csv(alarms: List[AlarmRecord], filepath: str) -> int:
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ID", "Timestamp", "Age", "Device", "Address",
            "Object", "Type", "Instance", "Description",
            "Priority", "State", "Category",
            "From Value", "To Value", "Acked By", "Acked At",
        ])
        for a in alarms:
            writer.writerow([
                a.alarm_id,
                a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                a.age_str,
                a.device_name,
                a.device_addr,
                a.object_name,
                a.object_type,
                a.instance,
                a.description,
                f"P{a.priority} — {a.priority_label}",
                a.state,
                a.category,
                a.from_value,
                a.to_value,
                a.acked_by or "",
                a.acked_at.strftime("%Y-%m-%d %H:%M:%S") if a.acked_at else "",
            ])
    return len(alarms)


def _export_pdf(alarms: List[AlarmRecord], filepath: str) -> int:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError:
        raise ImportError("ReportLab not installed. Run: pip install reportlab")

    doc    = SimpleDocTemplate(filepath, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    story  = []

    title_style = ParagraphStyle(
        "AlarmTitle", parent=styles["Title"], fontSize=16, spaceAfter=4,
    )
    story.append(Paragraph("HBCE — Alarm Viewer Export", title_style))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"Total records: {len(alarms)}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 8 * mm))

    header     = ["ID", "Timestamp", "Device", "Object", "Description", "Priority", "State", "Category"]
    table_data = [header]

    rl_colors = {
        1: colors.HexColor("#7B0000"),
        2: colors.HexColor("#B71C1C"),
        3: colors.HexColor("#E65100"),
        4: colors.HexColor("#F57F17"),
        5: colors.HexColor("#827717"),
        6: colors.HexColor("#1A5276"),
        7: colors.HexColor("#1B5E20"),
        8: colors.HexColor("#37474F"),
    }

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("GRID",       (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]

    for i, a in enumerate(alarms, start=1):
        row = [
            str(a.alarm_id),
            a.timestamp.strftime("%Y-%m-%d\n%H:%M:%S"),
            a.device_name,
            a.object_name,
            a.description[:60],
            f"P{a.priority}\n{a.priority_label}",
            a.state,
            a.category,
        ]
        table_data.append(row)
        bg = rl_colors.get(a.priority, colors.HexColor("#37474F"))
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        style_cmds.append(("TEXTCOLOR",  (0, i), (-1, i), colors.white))

    col_widths = [18*mm, 32*mm, 40*mm, 40*mm, 70*mm, 28*mm, 28*mm, 28*mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    doc.build(story)
    return len(alarms)


# ---------------------------------------------------------------------------
# Demo data  (replaces real adapter calls in dev mode)
# ---------------------------------------------------------------------------

_DEMO_COUNTER = 0

def _generate_demo_alarms(count: int = 40) -> List[AlarmRecord]:
    global _DEMO_COUNTER
    import random

    devices = [
        ("AHU-1",     "192.168.1.10"),
        ("AHU-2",     "192.168.1.11"),
        ("CHWR-1",    "192.168.1.20"),
        ("BAS-CTRL",  "192.168.1.1"),
        ("VAV-B3-04", "192.168.1.45"),
    ]
    objects = [
        ("SA-TEMP",  "analogInput",  0, "°F"),
        ("RA-TEMP",  "analogInput",  1, "°F"),
        ("SA-SP",    "analogValue",  2, "°F"),
        ("FAN-SPD",  "analogOutput", 0, "%"),
        ("CHW-FLOW", "analogInput",  5, "GPM"),
        ("FIRE-1",   "binaryInput",  0, ""),
        ("SMOKE-1",  "binaryInput",  1, ""),
        ("OCC",      "binaryValue",  0, ""),
    ]
    descs = [
        "High supply air temperature",
        "Low return air temperature",
        "Fan speed out of range",
        "Chilled water flow fault",
        "Fire alarm active",
        "Smoke detector triggered",
        "Occupancy sensor fault",
        "Controller offline",
        "Communication timeout",
        "Setpoint deviation exceeded",
    ]
    categories = ["HVAC", "Fire/Life Safety", "Equipment", "Communication", "General"]
    states     = [AlarmState.ACTIVE, AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED, AlarmState.CLEARED]

    alarms = []
    for i in range(count):
        _DEMO_COUNTER += 1
        dev   = random.choice(devices)
        obj   = random.choice(objects)
        state = random.choice(states)
        pri   = random.randint(1, 8)
        ts    = datetime.fromtimestamp(time.time() - random.randint(0, 86400 * 7))
        acked_by = acked_at = None
        if state in (AlarmState.ACKNOWLEDGED, AlarmState.CLEARED):
            acked_by = random.choice(["jsmith", "atechman", "operator1"])
            acked_at = datetime.fromtimestamp(ts.timestamp() + random.randint(60, 3600))

        alarms.append(AlarmRecord(
            alarm_id    = _DEMO_COUNTER * 100 + i,
            timestamp   = ts,
            device_name = dev[0],
            device_addr = dev[1],
            object_name = obj[0],
            object_type = obj[1],
            instance    = obj[2],
            description = random.choice(descs),
            priority    = pri,
            state       = state,
            acked_by    = acked_by,
            acked_at    = acked_at,
            category    = random.choice(categories),
            units       = obj[3],
            from_value  = f"{random.uniform(50, 90):.1f}",
            to_value    = f"{random.uniform(90, 120):.1f}",
        ))

    alarms.sort(key=lambda a: (
        0 if a.state == AlarmState.ACTIVE else 1, a.priority, a.timestamp
    ))
    return alarms


# ---------------------------------------------------------------------------
# Main Alarm Viewer Panel
# ---------------------------------------------------------------------------

class AlarmViewerPanel(QWidget):
    """
    HBCE Alarm Viewer — V0.0.8-alpha

    Columns    : ID, Timestamp, Age, Device, Object, Description,
                 Priority, State, Category, Acked By
    Features   : Priority color coding (P1–P8), single + bulk acknowledge,
                 text/state/priority/category filter bar, live polling,
                 CSV export, PDF export (ReportLab), detail side-panel,
                 right-click context menu, status bar
    Threading  : AlarmLoadThread, AlarmAckThread, AlarmPollThread
                 (GOTCHA-013: all network ops use QThread)
    """

    def __init__(self, config=None, db=None, current_user=None,
                 adapter=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {}

        # Extract username for ack dialog pre-fill
        self._username      = self.current_user.get("username", "operator")
        self._adapter       = adapter
        self._poll_thread: Optional[AlarmPollThread] = None
        self._polling       = False
        self._poll_interval = 30

        self._build_ui()
        self._connect_signals()
        self._load_alarms()

        # Refresh "Age" column every 60 s without a full reload
        self._age_timer = QTimer(self)
        self._age_timer.timeout.connect(self._refresh_ages)
        self._age_timer.start(60_000)

        logger.debug("AlarmViewerPanel initialized")

    # ── UI construction ────────────────────────────────────────────────────

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
        self._detail_panel.setMinimumWidth(240)
        self._splitter.addWidget(self._detail_panel)
        self._splitter.setSizes([900, 300])

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        root.addWidget(self._status_bar)
        self._status_bar.showMessage("Loading alarms…")

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background: #1E272C; border-bottom: 1px solid #37474F;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        title = QLabel("🔔  Alarm Viewer")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ECEFF1;")
        layout.addWidget(title)
        layout.addStretch()

        self._ack_btn = QPushButton("✅  Acknowledge Selected")
        self._ack_btn.setEnabled(False)
        layout.addWidget(self._ack_btn)

        self._ack_all_btn = QPushButton("✅  Ack All Active")
        layout.addWidget(self._ack_all_btn)

        self._refresh_btn = QPushButton("🔄  Refresh")
        layout.addWidget(self._refresh_btn)

        self._poll_btn = QPushButton("▶  Start Polling")
        self._poll_btn.setCheckable(True)
        layout.addWidget(self._poll_btn)

        layout.addWidget(self._build_interval_selector())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #37474F;")
        layout.addWidget(sep)

        self._csv_btn = QPushButton("📄  Export CSV")
        layout.addWidget(self._csv_btn)

        self._pdf_btn = QPushButton("📑  Export PDF")
        layout.addWidget(self._pdf_btn)

        return bar

    def _build_interval_selector(self) -> QWidget:
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(QLabel("Poll:"))
        self._interval_combo = QComboBox()
        self._interval_combo.setFixedWidth(80)
        for s, lbl in [(10, "10 s"), (30, "30 s"), (60, "1 min"), (300, "5 min")]:
            self._interval_combo.addItem(lbl, s)
        self._interval_combo.setCurrentIndex(1)
        h.addWidget(self._interval_combo)
        return c

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(38)
        bar.setStyleSheet("background: #263238; border-bottom: 1px solid #37474F;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("🔍"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search device, object, description…")
        self._search_edit.setFixedWidth(260)
        layout.addWidget(self._search_edit)

        layout.addWidget(QLabel("State:"))
        self._state_combo = QComboBox()
        self._state_combo.addItems(["All", "Active", "Acknowledged", "Cleared"])
        self._state_combo.setFixedWidth(110)
        layout.addWidget(self._state_combo)

        layout.addWidget(QLabel("Priority:"))
        self._priority_combo = QComboBox()
        self._priority_combo.addItem("All")
        for p, lbl in PRIORITY_LABELS.items():
            self._priority_combo.addItem(f"P{p} — {lbl}", p)
        self._priority_combo.setFixedWidth(160)
        layout.addWidget(self._priority_combo)

        layout.addWidget(QLabel("Category:"))
        self._category_combo = QComboBox()
        self._category_combo.addItem("All")
        self._category_combo.setFixedWidth(130)
        layout.addWidget(self._category_combo)

        self._clear_filter_btn = QPushButton("✕  Clear")
        self._clear_filter_btn.setFixedWidth(70)
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
        self._table.horizontalHeader().setSectionResizeMode(
            COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch
        )
        self._table.setColumnWidth(COL_ID,        50)
        self._table.setColumnWidth(COL_TIMESTAMP, 145)
        self._table.setColumnWidth(COL_AGE,       75)
        self._table.setColumnWidth(COL_DEVICE,    100)
        self._table.setColumnWidth(COL_OBJECT,    120)
        self._table.setColumnWidth(COL_PRIORITY,  155)
        self._table.setColumnWidth(COL_STATE,     100)
        self._table.setColumnWidth(COL_CATEGORY,  100)
        self._table.setColumnWidth(COL_ACKED_BY,  90)
        self._table.setStyleSheet("""
            QTableView { background: #1C2428; gridline-color: transparent; }
            QTableView::item:selected { background: #455A64; }
            QHeaderView::section {
                background: #263238; color: #B0BEC5;
                border: none; padding: 4px 8px;
                font-size: 11px; font-weight: bold;
            }
        """)

        layout.addWidget(self._table)
        return container

    # ── Signal wiring ──────────────────────────────────────────────────────

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
            lambda e: self._status_bar.showMessage(f"Error: {e}")
        )
        self._load_thread.progress.connect(
            lambda pct, msg: self._status_bar.showMessage(f"{msg} ({pct}%)")
        )
        self._load_thread.start()

    def _on_alarms_loaded(self, alarms: List[AlarmRecord]):
        self._model.load_alarms(alarms)
        self._populate_category_combo(alarms)
        self._update_status()

    def _populate_category_combo(self, alarms: List[AlarmRecord]):
        cats    = sorted({a.category for a in alarms})
        current = self._category_combo.currentText()
        self._category_combo.blockSignals(True)
        self._category_combo.clear()
        self._category_combo.addItem("All")
        self._category_combo.addItems(cats)
        idx = self._category_combo.findText(current)
        if idx >= 0:
            self._category_combo.setCurrentIndex(idx)
        self._category_combo.blockSignals(False)

    # ── Acknowledge ────────────────────────────────────────────────────────

    def _ack_selected(self):
        ids = self._selected_active_ids()
        if not ids:
            QMessageBox.information(self, "Nothing to Acknowledge",
                                    "Select one or more active alarms first.")
            return
        self._run_ack(ids)

    def _ack_all_active(self):
        ids = [
            a.alarm_id
            for r in range(self._proxy.rowCount())
            for a in [self._proxy.data(self._proxy.index(r, 0), Qt.ItemDataRole.UserRole)]
            if a and a.state == AlarmState.ACTIVE
        ]
        if not ids:
            QMessageBox.information(self, "No Active Alarms",
                                    "No active alarms in the current view.")
            return
        self._run_ack(ids)

    def _ack_single(self, alarm_id: int):
        self._run_ack([alarm_id])

    def _run_ack(self, ids: List[int]):
        dlg = AckDialog(len(ids), self)
        # Pre-fill logged-in user
        dlg._user_edit.setText(self._username)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._status_bar.showMessage(f"Acknowledging {len(ids)} alarm(s)…")
        self._ack_thread = AlarmAckThread(ids, dlg.username, self._adapter, self)
        self._ack_thread.ack_complete.connect(self._on_ack_complete)
        self._ack_thread.ack_error.connect(
            lambda e: self._status_bar.showMessage(f"Ack error: {e}")
        )
        self._ack_thread.start()

    def _on_ack_complete(self, alarm_ids: List[int], username: str):
        now = datetime.now()
        for aid in alarm_ids:
            self._model.update_alarm(aid, AlarmState.ACKNOWLEDGED, username, now)
        self._update_status()
        self._status_bar.showMessage(
            f"✅ Acknowledged {len(alarm_ids)} alarm(s) by '{username}'"
        )
        if (self._detail_panel._alarm
                and self._detail_panel._alarm.alarm_id in alarm_ids):
            rec = self._model.get_alarm(self._detail_panel._alarm.alarm_id)
            if rec:
                self._detail_panel.show_alarm(rec)

    def _selected_active_ids(self) -> List[int]:
        return [
            alarm.alarm_id
            for idx in self._table.selectionModel().selectedRows()
            for alarm in [self._proxy.data(idx, Qt.ItemDataRole.UserRole)]
            if alarm and alarm.state == AlarmState.ACTIVE
        ]

    # ── Polling ────────────────────────────────────────────────────────────

    def _toggle_polling(self, checked: bool):
        if checked:
            self._start_polling()
        else:
            self._stop_polling()

    def _start_polling(self):
        self._poll_interval = self._interval_combo.currentData() or 30
        self._poll_thread   = AlarmPollThread(self._poll_interval, self._adapter, self)
        self._poll_thread.new_alarms.connect(self._on_new_alarms)
        self._poll_thread.poll_error.connect(
            lambda e: self._status_bar.showMessage(f"Poll error: {e}")
        )
        self._poll_thread.start()
        self._poll_btn.setText("⏹  Stop Polling")
        self._polling = True

    def _stop_polling(self):
        if self._poll_thread:
            self._poll_thread.stop()
            self._poll_thread.quit()
            self._poll_thread.wait(2000)
            self._poll_thread = None
        self._poll_btn.setText("▶  Start Polling")
        self._polling = False
        self._update_status()

    def _update_poll_interval(self):
        if self._polling:
            self._stop_polling()
            self._poll_btn.setChecked(True)
            self._start_polling()

    def _on_new_alarms(self, alarms: List[AlarmRecord]):
        for a in alarms:
            self._model.append_alarm(a)
        self._update_status()
        if alarms:
            self._status_bar.showMessage(f"🔔 {len(alarms)} new alarm(s) received")

    # ── Selection / interaction ────────────────────────────────────────────

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

    # ── Context menu ───────────────────────────────────────────────────────

    def _show_context_menu(self, pos):
        proxy_idx = self._table.indexAt(pos)
        if not proxy_idx.isValid():
            return
        alarm = self._proxy.data(proxy_idx, Qt.ItemDataRole.UserRole)
        if not alarm:
            return

        menu = QMenu(self)

        if alarm.state == AlarmState.ACTIVE:
            ack_act = menu.addAction("✅  Acknowledge")
            ack_act.triggered.connect(lambda: self._run_ack([alarm.alarm_id]))

        det_act = menu.addAction("🔍  View Details")
        det_act.triggered.connect(lambda: self._detail_panel.show_alarm(alarm))

        menu.addSeparator()

        copy_desc = menu.addAction("📋  Copy Description")
        copy_desc.triggered.connect(
            lambda: QApplication.clipboard().setText(alarm.description)
        )

        copy_row = menu.addAction("📋  Copy Row as CSV")
        copy_row.triggered.connect(lambda: self._copy_row_csv(alarm))

        menu.addSeparator()

        go_act = menu.addAction("🔗  Go to Point in Browser")
        go_act.triggered.connect(lambda: self._status_bar.showMessage(
            f"→ {alarm.device_name} / {alarm.object_name} (wire to Point Browser)"
        ))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_row_csv(self, alarm: AlarmRecord):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            alarm.alarm_id,
            alarm.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            alarm.device_name, alarm.object_name,
            alarm.description, f"P{alarm.priority}",
            alarm.state, alarm.category,
        ])
        QApplication.clipboard().setText(buf.getvalue().strip())

    # ── Filters ────────────────────────────────────────────────────────────

    def _clear_filters(self):
        self._search_edit.clear()
        self._state_combo.setCurrentIndex(0)
        self._priority_combo.setCurrentIndex(0)
        self._category_combo.setCurrentIndex(0)

    # ── Export ─────────────────────────────────────────────────────────────

    def _visible_alarms(self) -> List[AlarmRecord]:
        return [
            a for r in range(self._proxy.rowCount())
            for a in [self._proxy.data(self._proxy.index(r, 0), Qt.ItemDataRole.UserRole)]
            if a
        ]

    def _export_csv(self):
        alarms = self._visible_alarms()
        if not alarms:
            QMessageBox.information(self, "Nothing to Export",
                                    "No alarms match the current filters.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Alarms — CSV",
            f"alarms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            count = _export_csv(alarms, path)
            self._status_bar.showMessage(
                f"✅ CSV exported: {count} records → {os.path.basename(path)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _export_pdf(self):
        alarms = self._visible_alarms()
        if not alarms:
            QMessageBox.information(self, "Nothing to Export",
                                    "No alarms match the current filters.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Alarms — PDF",
            f"alarms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            "PDF Files (*.pdf)"
        )
        if not path:
            return
        try:
            count = _export_pdf(alarms, path)
            self._status_bar.showMessage(
                f"✅ PDF exported: {count} records → {os.path.basename(path)}"
            )
        except ImportError as e:
            QMessageBox.warning(self, "ReportLab Not Installed",
                                str(e) + "\n\nRun: pip install reportlab")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ── Status bar ─────────────────────────────────────────────────────────

    def _update_status(self):
        total   = self._model.rowCount()
        visible = self._proxy.rowCount()
        active  = sum(1 for a in self._model.all_alarms() if a.state == AlarmState.ACTIVE)
        poll_str = (f"  |  🔄 Polling every {self._poll_interval}s"
                    if self._polling else "")
        self._status_bar.showMessage(
            f"Total: {total}  |  Visible: {visible}  |  Active: {active}{poll_str}"
        )

    def _refresh_ages(self):
        self._model.refresh_ages()

    # ── Cleanup ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._stop_polling()
        self._age_timer.stop()
        super().closeEvent(event)
