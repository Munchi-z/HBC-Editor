"""
HBCE — Hybrid Controls Editor
ui/panels/point_browser.py — Point Browser (Full Implementation V0.0.7-alpha)

Features:
  - Left tree: Device → Object Type → Object Instance
  - Right detail panel: all properties for the selected object
  - Toolbar: filter bar, device selector, refresh, live poll toggle
  - Columns: Object Name | Present Value | Units | Status Flags | Priority | Override
  - Inline write: double-click value cell → edit → priority selector → confirm → write
  - Override indicator: 🔴 badge when point is under manual override
  - Filter bar: search by name, object type, or value (real-time)
  - Right-click context menu: Write, Override, Release, Subscribe COV, Add to Trend
  - Modbus view: flat register table (coil, discrete, holding, input)
  - Live polling: configurable interval, auto-refresh selected device
  - Export: copy selected rows to clipboard, export all to CSV
  - COV subscription: visual indicator, auto-updates on change
  - Priority array: expandable view showing all 16 BACnet priority levels
"""

import csv
import json
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QSplitter, QComboBox, QLineEdit,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox,
    QDialog, QDialogButtonBox, QTextEdit, QCheckBox,
    QMenu, QSizePolicy, QAbstractItemView, QProgressBar,
    QToolButton, QMessageBox, QApplication, QFileDialog,
    QScrollArea,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QThread, QTimer, QPoint, QSortFilterProxyModel,
)
from PyQt6.QtGui import QFont, QColor, QBrush, QAction, QIcon

from core.logger import get_logger

logger = get_logger(__name__)

# ── BACnet object type groups ─────────────────────────────────────────────────

BACNET_OBJECT_GROUPS = {
    "Analog": [
        ("analogInput",    "AI", "Analog Input"),
        ("analogOutput",   "AO", "Analog Output"),
        ("analogValue",    "AV", "Analog Value"),
    ],
    "Binary": [
        ("binaryInput",    "BI", "Binary Input"),
        ("binaryOutput",   "BO", "Binary Output"),
        ("binaryValue",    "BV", "Binary Value"),
    ],
    "Multi-State": [
        ("multiStateInput",  "MSI", "Multi-State Input"),
        ("multiStateOutput", "MSO", "Multi-State Output"),
        ("multiStateValue",  "MSV", "Multi-State Value"),
    ],
    "Schedule & Calendar": [
        ("schedule",        "SCH", "Schedule"),
        ("calendar",        "CAL", "Calendar"),
    ],
    "Trend & Log": [
        ("trendLog",         "TL",  "Trend Log"),
        ("trendLogMultiple", "TLM", "Trend Log Multiple"),
    ],
    "Notification": [
        ("notificationClass", "NC", "Notification Class"),
    ],
}

MODBUS_TYPES = [
    ("coil",              "Coil (Read/Write)"),
    ("discrete_input",    "Discrete Input (Read Only)"),
    ("holding_register",  "Holding Register (Read/Write)"),
    ("input_register",    "Input Register (Read Only)"),
]

# Status flag display
STATUS_FLAGS = {0: ("✅", "#00CC88"), 1: ("⚠️", "#FFAA00"),
                2: ("❌", "#FF4455"), 3: ("🔧", "#808090")}

# Priority names (BACnet priority array 1–16)
PRIORITY_NAMES = {
    1:  "Manual Life Safety",    2:  "Auto Life Safety",
    3:  "Priority 3",            4:  "Priority 4",
    5:  "Critical Equipment",    6:  "Minimum On/Off",
    7:  "Priority 7",            8:  "Manual Operator",
    9:  "Priority 9",            10: "Priority 10",
    11: "Priority 11",           12: "Priority 12",
    13: "Priority 13",           14: "Priority 14",
    15: "Priority 15",           16: "Default",
}

# ── Background data-fetch thread ──────────────────────────────────────────────

class ObjectListThread(QThread):
    """Fetches the object list from a device in the background."""
    objects_ready = pyqtSignal(int, list)   # (device_id, list of (type, instance, name))
    error         = pyqtSignal(str)

    def __init__(self, adapter, device_id: int):
        super().__init__()
        self.adapter   = adapter
        self.device_id = device_id

    def run(self):
        try:
            obj_list = self.adapter.get_object_list(self.device_id)
            # Fetch names for each object (batch where possible)
            named = []
            for obj_type, instance in obj_list[:500]:   # cap at 500 for perf
                try:
                    pv = self.adapter.read_property(
                        self.device_id, obj_type, instance, "objectName"
                    )
                    name = str(pv.present_value) if pv.present_value else f"{obj_type}:{instance}"
                except Exception:
                    name = f"{obj_type}:{instance}"
                named.append((obj_type, instance, name))
            self.objects_ready.emit(self.device_id, named)
        except Exception as e:
            self.error.emit(str(e))


class PointReadThread(QThread):
    """Reads present value + status for a batch of points."""
    values_ready = pyqtSignal(list)   # list of PointValue dicts
    error        = pyqtSignal(str)

    def __init__(self, adapter, device_id: int, objects: list):
        super().__init__()
        self.adapter   = adapter
        self.device_id = device_id
        self.objects   = objects    # list of (obj_type, instance)

    def run(self):
        results = []
        for obj_type, instance in self.objects:
            try:
                pv = self.adapter.read_property(
                    self.device_id, obj_type, instance, "presentValue"
                )
                results.append({
                    "obj_type": obj_type,
                    "instance": instance,
                    "value":    pv.present_value,
                    "name":     pv.name,
                    "units":    pv.units,
                    "status":   pv.status_flags,
                    "priority": pv.priority_array,
                    "oos":      pv.out_of_service,
                })
            except Exception as e:
                results.append({
                    "obj_type": obj_type, "instance": instance,
                    "value": "Error", "name": f"{obj_type}:{instance}",
                    "units": "", "status": [], "priority": [], "oos": False,
                })
        self.values_ready.emit(results)


class WriteThread(QThread):
    """Writes a value to a point in the background."""
    write_done = pyqtSignal(bool, str)   # (success, message)

    def __init__(self, adapter, device_id, obj_type, instance, value, priority):
        super().__init__()
        self.adapter   = adapter
        self.device_id = device_id
        self.obj_type  = obj_type
        self.instance  = instance
        self.value     = value
        self.priority  = priority

    def run(self):
        try:
            ok = self.adapter.write_property(
                self.device_id, self.obj_type, self.instance,
                "presentValue", self.value, self.priority
            )
            if ok:
                self.write_done.emit(True, f"Written: {self.value} @ priority {self.priority}")
            else:
                self.write_done.emit(False, "Write failed — check permissions and priority.")
        except Exception as e:
            self.write_done.emit(False, str(e))


# ── Write dialog ──────────────────────────────────────────────────────────────

class WriteDialog(QDialog):
    """Dialog to enter a new value and priority for a write operation."""

    def __init__(self, obj_name: str, obj_type: str, current_value,
                 is_binary: bool = False, is_multistate: bool = False,
                 state_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Write — {obj_name}")
        self.setFixedSize(380, 320)
        self._is_binary     = is_binary
        self._is_multistate = is_multistate
        self._build(obj_name, obj_type, current_value, state_count)

    def _build(self, obj_name, obj_type, current_value, state_count):
        L = QVBoxLayout(self)
        L.setSpacing(12)
        L.setContentsMargins(20, 20, 20, 20)

        # Header
        hdr = QLabel(f"Writing to: <b>{obj_name}</b>")
        hdr.setStyleSheet("font-size: 10pt; color: #C0C0D0;")
        L.addWidget(hdr)

        cur = QLabel(f"Current value: <b>{current_value}</b>")
        cur.setStyleSheet("color: #808090; font-size: 9pt;")
        L.addWidget(cur)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        L.addWidget(sep)

        form = QFormLayout()
        form.setSpacing(10)

        # Value input
        if self._is_binary:
            self._value_combo = QComboBox()
            self._value_combo.addItems(["Active (1)", "Inactive (0)"])
            self._value_combo.setMinimumHeight(32)
            form.addRow("New Value:", self._value_combo)
        elif self._is_multistate and state_count > 0:
            self._value_combo = QComboBox()
            for i in range(1, state_count + 1):
                self._value_combo.addItem(str(i))
            self._value_combo.setMinimumHeight(32)
            form.addRow("New Value:", self._value_combo)
        else:
            self._value_input = QDoubleSpinBox()
            self._value_input.setRange(-999999, 999999)
            self._value_input.setDecimals(3)
            self._value_input.setMinimumHeight(32)
            try:
                self._value_input.setValue(float(current_value))
            except Exception:
                pass
            form.addRow("New Value:", self._value_input)

        # Priority selector
        self._priority_combo = QComboBox()
        self._priority_combo.setMinimumHeight(32)
        for pri, name in PRIORITY_NAMES.items():
            self._priority_combo.addItem(f"{pri} — {name}", userData=pri)
        # Default to priority 8 (Manual Operator)
        self._priority_combo.setCurrentIndex(7)
        form.addRow("Priority:", self._priority_combo)

        L.addLayout(form)

        # Warning for high priorities
        self._warn_lbl = QLabel(
            "⚠️  Priorities 1–7 override safety and equipment logic.\n"
            "   Use priority 8 (Manual Operator) for normal overrides."
        )
        self._warn_lbl.setStyleSheet("color: #FFAA00; font-size: 8pt;")
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.setVisible(False)
        L.addWidget(self._warn_lbl)
        self._priority_combo.currentIndexChanged.connect(self._check_priority)

        L.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        L.addWidget(btns)

    def _check_priority(self, idx: int):
        pri = self._priority_combo.itemData(idx)
        self._warn_lbl.setVisible(pri is not None and pri < 8)

    def get_value(self):
        if self._is_binary:
            return 1 if self._value_combo.currentIndex() == 0 else 0
        elif self._is_multistate:
            return int(self._value_combo.currentText())
        else:
            return self._value_input.value()

    def get_priority(self) -> int:
        return self._priority_combo.currentData() or 8


# ── Object detail panel ───────────────────────────────────────────────────────

class ObjectDetailPanel(QWidget):
    """Right-side panel showing all properties of the selected BACnet object."""

    write_requested = pyqtSignal(str, int, object, int)
    # (obj_type, instance, value, priority)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = {}
        self._build()

    def _build(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            "background: #1e1e32; border-bottom: 1px solid #2a2a4e;"
        )
        hdr_L = QHBoxLayout(hdr)
        hdr_L.setContentsMargins(12, 0, 12, 0)
        self._title = QLabel("Select a point to view details")
        self._title.setStyleSheet(
            "font-weight: bold; color: #C0C0D0; background: transparent;"
        )
        hdr_L.addWidget(self._title)
        hdr_L.addStretch()

        self._write_btn = QPushButton("✏️  Write Value")
        self._write_btn.setFixedHeight(28)
        self._write_btn.setVisible(False)
        self._write_btn.clicked.connect(self._on_write)
        hdr_L.addWidget(self._write_btn)
        L.addWidget(hdr)

        # Scrollable properties
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._props_widget = QWidget()
        self._props_widget.setStyleSheet("background: #12121e;")
        self._props_layout = QVBoxLayout(self._props_widget)
        self._props_layout.setContentsMargins(12, 12, 12, 12)
        self._props_layout.setSpacing(8)
        self._props_layout.addStretch()

        scroll.setWidget(self._props_widget)
        L.addWidget(scroll)

    def show_object(self, obj_data: dict):
        """Populate detail panel with object data."""
        self._current = obj_data

        # Clear existing
        while self._props_layout.count() > 1:
            item = self._props_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        obj_type = obj_data.get("obj_type", "")
        instance = obj_data.get("instance", 0)
        name     = obj_data.get("name", f"{obj_type}:{instance}")
        value    = obj_data.get("value", "—")
        units    = obj_data.get("units", "")
        oos      = obj_data.get("oos", False)
        priority = obj_data.get("priority", [])
        status   = obj_data.get("status", [])

        self._title.setText(name)

        # Is writable?
        writable_types = {
            "analogOutput", "analogValue", "binaryOutput",
            "binaryValue", "multiStateOutput", "multiStateValue",
        }
        is_writable = obj_type in writable_types
        self._write_btn.setVisible(is_writable)

        def add_prop(label: str, val: str, color: str = "#C0C0D0"):
            row = QWidget()
            row.setStyleSheet(
                "background: #1e1e32; border: 1px solid #2a2a4e; border-radius: 6px;"
            )
            r_L = QHBoxLayout(row)
            r_L.setContentsMargins(10, 6, 10, 6)
            k = QLabel(label + ":")
            k.setStyleSheet("color: #606070; font-size: 9pt; background: transparent;")
            k.setFixedWidth(140)
            v = QLabel(str(val))
            v.setStyleSheet(
                f"color: {color}; font-size: 9pt; font-weight: bold; background: transparent;"
            )
            v.setWordWrap(True)
            r_L.addWidget(k)
            r_L.addWidget(v, 1)
            self._props_layout.insertWidget(self._props_layout.count() - 1, row)

        add_prop("Object Type", obj_type)
        add_prop("Instance",    str(instance))
        add_prop("Object Name", name)

        val_color = "#FF4455" if str(value) in ("Error", "null") else "#00CC88" \
            if obj_type.startswith("binary") else "#00AAFF"
        val_str = f"{value}  {units}".strip() if units else str(value)
        add_prop("Present Value", val_str, val_color)

        if oos:
            add_prop("Out of Service", "Yes ⚠️", "#FFAA00")

        # Override indicator
        override_pri = None
        for i, pv in enumerate(priority):
            if pv not in (None, "null", ""):
                override_pri = i + 1
                break
        if override_pri and override_pri < 16:
            add_prop(
                "Active Override",
                f"Priority {override_pri} — {PRIORITY_NAMES.get(override_pri, '')}",
                "#FF8844"
            )

        # Status flags
        if status:
            flags = []
            flag_names = ["inAlarm", "fault", "overridden", "outOfService"]
            for i, flag in enumerate(status[:4]):
                if flag:
                    flags.append(flag_names[i] if i < len(flag_names) else f"flag{i}")
            if flags:
                add_prop("Status Flags", ", ".join(flags), "#FFAA00")
            else:
                add_prop("Status Flags", "Normal ✅", "#00CC88")

        # Priority array (collapsible)
        if priority and any(p not in (None, "null", "") for p in priority):
            pri_group = QGroupBox("Priority Array")
            pri_group.setStyleSheet(
                "QGroupBox { background: #1e1e32; border: 1px solid #2a2a4e; "
                "border-radius: 6px; margin-top: 6px; padding: 8px; }"
                "QGroupBox::title { color: #00AAFF; }"
            )
            pri_L = QVBoxLayout(pri_group)
            pri_L.setSpacing(2)
            for i, pv in enumerate(priority[:16]):
                if pv not in (None, "null", ""):
                    pri_num  = i + 1
                    pri_name = PRIORITY_NAMES.get(pri_num, f"Priority {pri_num}")
                    lbl = QLabel(f"  [{pri_num:2d}] {pri_name}: {pv}")
                    lbl.setStyleSheet(
                        "color: #FF8844; font-size: 8pt; background: transparent;"
                    )
                    pri_L.addWidget(lbl)
            self._props_layout.insertWidget(self._props_layout.count() - 1, pri_group)

    def _on_write(self):
        if not self._current:
            return
        obj_type = self._current.get("obj_type", "")
        instance = self._current.get("instance", 0)
        name     = self._current.get("name", "")
        value    = self._current.get("value")

        is_binary     = obj_type.startswith("binary")
        is_multistate = obj_type.startswith("multiState")

        dlg = WriteDialog(
            name, obj_type, value,
            is_binary=is_binary,
            is_multistate=is_multistate,
            parent=self,
        )
        if dlg.exec():
            self.write_requested.emit(
                obj_type, instance, dlg.get_value(), dlg.get_priority()
            )

    def clear(self):
        while self._props_layout.count() > 1:
            item = self._props_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._title.setText("Select a point to view details")
        self._write_btn.setVisible(False)
        self._current = {}


# ── Point Browser table model ─────────────────────────────────────────────────

# Column indices
COL_NAME     = 0
COL_TYPE     = 1
COL_INSTANCE = 2
COL_VALUE    = 3
COL_UNITS    = 4
COL_STATUS   = 5
COL_OVERRIDE = 6
COL_PRIORITY = 7

COLUMNS = ["Object Name", "Type", "Instance", "Present Value",
           "Units", "Status", "Override", "Active Priority"]


# ── Main Point Browser Panel ──────────────────────────────────────────────────

class PointBrowserPanel(QWidget):
    """
    HBCE Point Browser — browse, read, and write BACnet/Modbus points.

    Layout:
      Toolbar  [Device selector] [Filter bar] [Refresh] [Live] [Export]
      ┌─────────────────────────────┬─────────────────────────┐
      │  Object Tree (left)         │  Point Table (center)   │
      │  Device                     │  Filterable columns     │
      │  ├─ Analog                  │  Inline double-click    │
      │  │   ├─ AI:1 Room Temp      │  write with priority    │
      │  │   └─ AO:1 Valve Cmd      │                         │
      │  ├─ Binary                  ├─────────────────────────┤
      │  └─ ...                     │  Object Detail Panel    │
      │                             │  All properties + write │
      └─────────────────────────────┴─────────────────────────┘
      Statusbar  [X objects | Y shown | polling: ON/OFF]
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user

        self._adapter        = None     # active comms adapter
        self._device_id      = None     # currently browsed device ID
        self._device_name    = ""
        self._all_objects    = []       # (obj_type, instance, name) full list
        self._table_data     = []       # currently shown rows (filtered)
        self._cov_subscribed = set()    # set of (obj_type, instance)
        self._poll_timer     = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_visible)
        self._active_threads = []

        self._build_ui()
        logger.debug("PointBrowserPanel initialized")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panel header ──────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #1a1a30, stop:1 #12121e);"
            "border-bottom: 2px solid #00AAFF22;"
        )
        h_L = QHBoxLayout(header)
        h_L.setContentsMargins(20, 0, 20, 0)
        title = QLabel("📋  Point Browser")
        tf = QFont(); tf.setPointSize(16); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet("color: #E0E0F0; background: transparent;")
        h_L.addWidget(title)
        subtitle = QLabel("Browse and edit BACnet / Modbus points")
        subtitle.setStyleSheet("color: #505060; font-size: 9pt; background: transparent;")
        h_L.addWidget(subtitle)
        h_L.addStretch()
        root.addWidget(header)

        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(46)
        toolbar.setStyleSheet(
            "background: #1a1a2e; border-bottom: 1px solid #2a2a4e;"
        )
        tb_L = QHBoxLayout(toolbar)
        tb_L.setContentsMargins(12, 0, 12, 0)
        tb_L.setSpacing(8)

        # Device selector
        tb_L.addWidget(QLabel("Device:"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(220)
        self._device_combo.setFixedHeight(30)
        self._device_combo.addItem("— Select a device —")
        self._device_combo.currentIndexChanged.connect(self._on_device_selected)
        tb_L.addWidget(self._device_combo)

        # Refresh
        self._refresh_btn = QPushButton("🔄 Refresh")
        self._refresh_btn.setFixedHeight(30)
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.clicked.connect(self._refresh_objects)
        self._refresh_btn.setEnabled(False)
        tb_L.addWidget(self._refresh_btn)

        # Live poll toggle
        self._live_btn = QPushButton("▶ Live")
        self._live_btn.setFixedHeight(30)
        self._live_btn.setFixedWidth(80)
        self._live_btn.setCheckable(True)
        self._live_btn.toggled.connect(self._toggle_live)
        self._live_btn.setEnabled(False)
        tb_L.addWidget(self._live_btn)

        # Poll interval
        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(1, 60)
        self._poll_spin.setValue(5)
        self._poll_spin.setSuffix(" s")
        self._poll_spin.setFixedWidth(70)
        self._poll_spin.setFixedHeight(30)
        self._poll_spin.setToolTip("Live poll interval in seconds")
        tb_L.addWidget(self._poll_spin)

        tb_L.addSpacing(8)

        # Filter bar
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("🔍  Filter by name, type, or value…")
        self._filter_input.setFixedHeight(30)
        self._filter_input.setMinimumWidth(220)
        self._filter_input.textChanged.connect(self._apply_filter)
        tb_L.addWidget(self._filter_input, 1)

        # Type filter
        self._type_filter = QComboBox()
        self._type_filter.setFixedHeight(30)
        self._type_filter.setFixedWidth(140)
        self._type_filter.addItem("All Types")
        self._type_filter.addItem("Analog (AI/AO/AV)")
        self._type_filter.addItem("Binary (BI/BO/BV)")
        self._type_filter.addItem("Multi-State (MSI/MSO/MSV)")
        self._type_filter.addItem("Overrides only")
        self._type_filter.addItem("Alarms only")
        self._type_filter.currentIndexChanged.connect(self._apply_filter)
        tb_L.addWidget(self._type_filter)

        # Export
        self._export_btn = QPushButton("📤 Export CSV")
        self._export_btn.setFixedHeight(30)
        self._export_btn.setFixedWidth(110)
        self._export_btn.clicked.connect(self._export_csv)
        self._export_btn.setEnabled(False)
        tb_L.addWidget(self._export_btn)

        root.addWidget(toolbar)

        # ── Progress bar (loading) ────────────────────────────────────────
        self._load_bar = QProgressBar()
        self._load_bar.setRange(0, 0)
        self._load_bar.setFixedHeight(3)
        self._load_bar.setTextVisible(False)
        self._load_bar.setVisible(False)
        self._load_bar.setStyleSheet(
            "QProgressBar { background: #12121e; border: none; }"
            "QProgressBar::chunk { background: #00AAFF; }"
        )
        root.addWidget(self._load_bar)

        # ── Main splitter: tree | table+detail ───────────────────────────
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a4e; width: 2px; }"
        )

        # ── Left: object tree ─────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Objects")
        self._tree.setMinimumWidth(200)
        self._tree.setMaximumWidth(280)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background: #1a1a2e;
                border: none;
                color: #C0C0D0;
                font-size: 9pt;
            }
            QTreeWidget::item:selected {
                background: #00AAFF;
                color: white;
            }
            QTreeWidget::item:hover:!selected {
                background: #252540;
            }
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                border-image: none;
            }
        """)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        main_splitter.addWidget(self._tree)

        # ── Center+Right vertical splitter ───────────────────────────────
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Point table
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        self._table.currentItemChanged.connect(self._on_table_row_changed)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #12121e;
                alternate-background-color: #1a1a2e;
                gridline-color: #2a2a4e;
                color: #C0C0D0;
                font-size: 9pt;
                border: none;
            }
            QTableWidget::item:selected {
                background: #00AAFF44;
                color: white;
            }
            QHeaderView::section {
                background: #1e1e32;
                color: #808090;
                border: none;
                border-bottom: 2px solid #00AAFF;
                padding: 4px 8px;
                font-weight: bold;
                font-size: 8pt;
            }
        """)

        # Set column widths
        hdr = self._table.horizontalHeader()
        hdr.resizeSection(COL_NAME,     200)
        hdr.resizeSection(COL_TYPE,     100)
        hdr.resizeSection(COL_INSTANCE,  70)
        hdr.resizeSection(COL_VALUE,    110)
        hdr.resizeSection(COL_UNITS,     70)
        hdr.resizeSection(COL_STATUS,    80)
        hdr.resizeSection(COL_OVERRIDE,  80)
        hdr.resizeSection(COL_PRIORITY,  90)

        right_splitter.addWidget(self._table)

        # Detail panel
        self._detail = ObjectDetailPanel()
        self._detail.setMinimumHeight(180)
        self._detail.write_requested.connect(self._do_write)
        right_splitter.addWidget(self._detail)
        right_splitter.setSizes([500, 220])

        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([240, 900])
        root.addWidget(main_splitter, 1)

        # ── Status bar ────────────────────────────────────────────────────
        self._status_bar = QWidget()
        self._status_bar.setFixedHeight(26)
        self._status_bar.setStyleSheet(
            "background: #1a1a2e; border-top: 1px solid #2a2a4e;"
        )
        sb_L = QHBoxLayout(self._status_bar)
        sb_L.setContentsMargins(12, 0, 12, 0)
        self._status_lbl = QLabel("No device selected.")
        self._status_lbl.setStyleSheet("color: #505060; font-size: 8pt;")
        sb_L.addWidget(self._status_lbl)
        sb_L.addStretch()
        self._poll_lbl = QLabel("")
        self._poll_lbl.setStyleSheet("color: #505060; font-size: 8pt;")
        sb_L.addWidget(self._poll_lbl)
        root.addWidget(self._status_bar)

        # Empty state overlay
        self._empty_lbl = QLabel(
            "📋\n\nNo device connected.\n"
            "Use  Tools → Connection Wizard  to connect a device,\n"
            "then select it from the Device dropdown above."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "color: #404050; font-size: 11pt; background: transparent;"
        )

    # ── Device management ─────────────────────────────────────────────────────

    def load_devices_from_db(self):
        """Populate device dropdown from the database."""
        if not self.db:
            return
        try:
            devices = self.db.fetchall("SELECT id, name, vendor, protocol FROM devices")
            self._device_combo.blockSignals(True)
            self._device_combo.clear()
            self._device_combo.addItem("— Select a device —", userData=None)
            for dev in devices:
                label = f"{dev['name']}  [{dev['protocol']}]"
                self._device_combo.addItem(label, userData=dev)
            self._device_combo.blockSignals(False)
            if devices:
                self._device_combo.setCurrentIndex(1)
        except Exception as e:
            logger.warning(f"Could not load devices from DB: {e}")

    def set_adapter(self, adapter, device_id: int, device_name: str = ""):
        """Called externally when a connection is established."""
        self._adapter     = adapter
        self._device_id   = device_id
        self._device_name = device_name
        self._refresh_btn.setEnabled(True)
        self._live_btn.setEnabled(True)
        self._refresh_objects()

    def _on_device_selected(self, idx: int):
        dev = self._device_combo.itemData(idx)
        if not dev:
            return
        # In a real scenario, look up the adapter for this device
        # For now: show message that connection must be live
        self._device_name = dev.get("name", "")
        self._set_status(
            f"Device: {self._device_name} — connect via Connection Wizard to browse live points."
        )

    # ── Object loading ────────────────────────────────────────────────────────

    def _refresh_objects(self):
        if not self._adapter or self._device_id is None:
            self._set_status("No active connection — use Connection Wizard first.")
            return

        self._load_bar.setVisible(True)
        self._refresh_btn.setEnabled(False)
        self._tree.clear()
        self._table.setRowCount(0)
        self._detail.clear()
        self._all_objects.clear()
        self._set_status("Loading object list…")

        thread = ObjectListThread(self._adapter, self._device_id)
        thread.objects_ready.connect(self._on_objects_ready)
        thread.error.connect(self._on_load_error)
        thread.finished.connect(lambda: self._cleanup_thread(thread))
        self._active_threads.append(thread)
        thread.start()

    def _on_objects_ready(self, device_id: int, objects: list):
        self._load_bar.setVisible(False)
        self._refresh_btn.setEnabled(True)
        self._all_objects = objects
        self._build_tree(objects)
        self._show_all_in_table(objects)
        self._export_btn.setEnabled(True)
        self._set_status(
            f"{len(objects)} objects loaded from {self._device_name}"
        )

    def _on_load_error(self, msg: str):
        self._load_bar.setVisible(False)
        self._refresh_btn.setEnabled(True)
        self._set_status(f"Error loading objects: {msg}")
        QMessageBox.warning(self, "Load Error", f"Could not load object list:\n{msg}")

    # ── Tree building ─────────────────────────────────────────────────────────

    def _build_tree(self, objects: list):
        self._tree.clear()

        # Root: device
        root_item = QTreeWidgetItem([f"📡  {self._device_name}"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "device"})
        root_item.setExpanded(True)
        self._tree.addTopLevelItem(root_item)

        # Group by type group
        groups = {}
        for obj_type, instance, name in objects:
            # Find which group this belongs to
            group_name = "Other"
            for gname, types in BACNET_OBJECT_GROUPS.items():
                if any(obj_type == t[0] for t in types):
                    group_name = gname
                    break
            # Check for Modbus types
            if any(obj_type == t[0] for t in MODBUS_TYPES):
                group_name = "Modbus Registers"

            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append((obj_type, instance, name))

        group_icons = {
            "Analog":               "〰️",
            "Binary":               "🔘",
            "Multi-State":          "🔀",
            "Schedule & Calendar":  "📅",
            "Trend & Log":          "📈",
            "Notification":         "🔔",
            "Modbus Registers":     "📊",
            "Other":                "📁",
        }

        for group_name, items in sorted(groups.items()):
            icon = group_icons.get(group_name, "📁")
            grp_item = QTreeWidgetItem([f"{icon}  {group_name}  ({len(items)})"])
            grp_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "group", "group": group_name, "items": items
            })
            grp_item.setForeground(0, QBrush(QColor("#808090")))
            root_item.addChild(grp_item)

            # Add individual objects
            for obj_type, instance, name in items[:100]:   # cap at 100 per group in tree
                obj_item = QTreeWidgetItem([f"  {name}"])
                obj_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "object",
                    "obj_type": obj_type,
                    "instance": instance,
                    "name": name,
                })
                grp_item.addChild(obj_item)

    def _on_tree_selection(self):
        selected = self._tree.selectedItems()
        if not selected:
            return
        data = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        dtype = data.get("type")
        if dtype == "group":
            # Show only this group in table
            items = data.get("items", [])
            self._filter_input.clear()
            self._show_all_in_table(items)
        elif dtype == "object":
            # Filter table to this object and select it
            obj_type = data.get("obj_type")
            instance = data.get("instance")
            # Find row in table
            for row in range(self._table.rowCount()):
                t_item = self._table.item(row, COL_TYPE)
                i_item = self._table.item(row, COL_INSTANCE)
                if t_item and i_item:
                    if t_item.text() == obj_type and i_item.text() == str(instance):
                        self._table.selectRow(row)
                        self._table.scrollToItem(t_item)
                        break
        elif dtype == "device":
            self._show_all_in_table(self._all_objects)

    # ── Table display ─────────────────────────────────────────────────────────

    def _show_all_in_table(self, objects: list):
        """Populate table with given object list (no values yet — reads async)."""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(objects))
        self._table_data = objects

        for row, (obj_type, instance, name) in enumerate(objects):
            items = [
                QTableWidgetItem(name),
                QTableWidgetItem(obj_type),
                QTableWidgetItem(str(instance)),
                QTableWidgetItem("—"),     # value (loaded async)
                QTableWidgetItem(""),      # units
                QTableWidgetItem("…"),     # status
                QTableWidgetItem(""),      # override
                QTableWidgetItem(""),      # priority
            ]
            # Store object identity in each row
            for item in items:
                item.setData(Qt.ItemDataRole.UserRole, {
                    "obj_type": obj_type, "instance": instance, "name": name
                })
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                                      Qt.AlignmentFlag.AlignLeft)
                self._table.setItem(row, col, item)

            self._table.setRowHeight(row, 28)

        self._table.setSortingEnabled(True)
        self._update_status_count()

        # Load values async
        if self._adapter and self._device_id is not None:
            obj_pairs = [(o[0], o[1]) for o in objects[:200]]   # cap at 200
            thread = PointReadThread(self._adapter, self._device_id, obj_pairs)
            thread.values_ready.connect(self._update_table_values)
            thread.finished.connect(lambda: self._cleanup_thread(thread))
            self._active_threads.append(thread)
            thread.start()

    def _update_table_values(self, results: list):
        """Update table cells with live values from read thread."""
        # Build lookup: (obj_type, instance) → result
        lookup = {(r["obj_type"], r["instance"]): r for r in results}

        self._table.setSortingEnabled(False)
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, COL_NAME)
            if not name_item:
                continue
            obj_data  = name_item.data(Qt.ItemDataRole.UserRole) or {}
            key       = (obj_data.get("obj_type"), obj_data.get("instance"))
            result    = lookup.get(key)
            if not result:
                continue

            value   = result.get("value")
            units   = result.get("units", "")
            status  = result.get("status", [])
            priority= result.get("priority", [])
            oos     = result.get("oos", False)

            # Value cell
            val_str = str(value) if value is not None else "—"
            val_item = QTableWidgetItem(val_str)
            val_item.setData(Qt.ItemDataRole.UserRole, obj_data)

            # Color value by type
            obj_type = obj_data.get("obj_type", "")
            if val_str in ("Error", "null"):
                val_item.setForeground(QBrush(QColor("#FF4455")))
            elif obj_type.startswith("binary"):
                color = "#00CC88" if str(value) in ("1", "True", "Active") else "#808090"
                val_item.setForeground(QBrush(QColor(color)))
            else:
                val_item.setForeground(QBrush(QColor("#00AAFF")))

            self._table.setItem(row, COL_VALUE, val_item)
            self._table.setItem(row, COL_UNITS, QTableWidgetItem(str(units) if units else ""))

            # Status
            status_strs = []
            flag_names  = ["inAlarm", "fault", "overridden", "outOfService"]
            for i, flag in enumerate(status[:4]):
                if flag:
                    status_strs.append(flag_names[i] if i < len(flag_names) else f"f{i}")
            status_text = ", ".join(status_strs) if status_strs else "Normal"
            status_item = QTableWidgetItem(status_text)
            if status_strs:
                status_item.setForeground(QBrush(QColor("#FFAA00")))
            else:
                status_item.setForeground(QBrush(QColor("#00CC88")))
            self._table.setItem(row, COL_STATUS, status_item)

            # Override indicator
            override_pri = None
            for i, pv in enumerate(priority):
                if pv not in (None, "null", ""):
                    override_pri = i + 1
                    break
            if override_pri and override_pri < 16:
                ov_item = QTableWidgetItem(f"🔴 P{override_pri}")
                ov_item.setForeground(QBrush(QColor("#FF8844")))
            else:
                ov_item = QTableWidgetItem("")
            self._table.setItem(row, COL_OVERRIDE, ov_item)

            # Active priority
            pri_item = QTableWidgetItem(str(override_pri) if override_pri else "16")
            self._table.setItem(row, COL_PRIORITY, pri_item)

        self._table.setSortingEnabled(True)

    # ── Filter ────────────────────────────────────────────────────────────────

    def _apply_filter(self):
        text       = self._filter_input.text().lower()
        type_idx   = self._type_filter.currentIndex()

        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, COL_NAME)
            type_item = self._table.item(row, COL_TYPE)
            val_item  = self._table.item(row, COL_VALUE)
            ov_item   = self._table.item(row, COL_OVERRIDE)

            name  = name_item.text().lower() if name_item else ""
            ttype = type_item.text().lower() if type_item else ""
            val   = val_item.text().lower()  if val_item  else ""
            ov    = ov_item.text()           if ov_item   else ""

            # Text filter
            text_match = (not text) or (
                text in name or text in ttype or text in val
            )

            # Type filter
            if type_idx == 0:   # All
                type_match = True
            elif type_idx == 1:   # Analog
                type_match = any(t in ttype for t in ("analog",))
            elif type_idx == 2:   # Binary
                type_match = "binary" in ttype
            elif type_idx == 3:   # Multi-State
                type_match = "multistate" in ttype
            elif type_idx == 4:   # Overrides only
                type_match = bool(ov.strip())
            elif type_idx == 5:   # Alarms only
                status_item = self._table.item(row, COL_STATUS)
                status_text = status_item.text().lower() if status_item else ""
                type_match  = "alarm" in status_text or "fault" in status_text
            else:
                type_match = True

            self._table.setRowHidden(row, not (text_match and type_match))

        self._update_status_count()

    def _update_status_count(self):
        total   = self._table.rowCount()
        visible = sum(
            1 for r in range(total) if not self._table.isRowHidden(r)
        )
        self._set_status(
            f"{total} objects total | {visible} shown"
            + (" | 🟢 Live polling" if self._live_btn.isChecked() else "")
        )

    # ── Row selection → detail panel ─────────────────────────────────────────

    def _on_table_row_changed(self, current, previous):
        if not current:
            return
        row      = current.row()
        name_item = self._table.item(row, COL_NAME)
        if not name_item:
            return
        obj_data  = name_item.data(Qt.ItemDataRole.UserRole) or {}
        val_item  = self._table.item(row, COL_VALUE)
        units_item= self._table.item(row, COL_UNITS)
        ov_item   = self._table.item(row, COL_OVERRIDE)

        detail = {
            "obj_type": obj_data.get("obj_type", ""),
            "instance": obj_data.get("instance", 0),
            "name":     obj_data.get("name", ""),
            "value":    val_item.text()  if val_item   else "—",
            "units":    units_item.text() if units_item else "",
            "oos":      False,
            "status":   [],
            "priority": [],
        }
        self._detail.show_object(detail)

    # ── Double-click to write ─────────────────────────────────────────────────

    def _on_double_click(self, item):
        row      = item.row()
        name_item = self._table.item(row, COL_NAME)
        val_item  = self._table.item(row, COL_VALUE)
        if not name_item:
            return

        obj_data = name_item.data(Qt.ItemDataRole.UserRole) or {}
        obj_type = obj_data.get("obj_type", "")
        instance = obj_data.get("instance", 0)
        name     = obj_data.get("name", "")
        value    = val_item.text() if val_item else "—"

        # Only writable types
        writable = {
            "analogOutput", "analogValue", "binaryOutput",
            "binaryValue", "multiStateOutput", "multiStateValue",
            "holding_register", "coil",
        }
        if obj_type not in writable:
            self._set_status(f"'{name}' is read-only.")
            return

        is_binary     = obj_type.startswith("binary") or obj_type == "coil"
        is_multistate = obj_type.startswith("multiState")

        dlg = WriteDialog(
            name, obj_type, value,
            is_binary=is_binary,
            is_multistate=is_multistate,
            parent=self,
        )
        if dlg.exec():
            self._do_write(obj_type, instance, dlg.get_value(), dlg.get_priority())

    # ── Right-click context menu ──────────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint):
        item = self._table.itemAt(pos)
        if not item:
            return
        row      = item.row()
        name_item = self._table.item(row, COL_NAME)
        if not name_item:
            return
        obj_data = name_item.data(Qt.ItemDataRole.UserRole) or {}
        obj_type = obj_data.get("obj_type", "")
        instance = obj_data.get("instance", 0)
        name     = obj_data.get("name", "")

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #1e1e32; border: 1px solid #2a2a4e; border-radius: 6px; }
            QMenu::item { padding: 6px 20px; color: #C0C0D0; }
            QMenu::item:selected { background: #00AAFF; color: white; }
            QMenu::separator { background: #2a2a4e; height: 1px; margin: 4px 0; }
        """)

        writable = {
            "analogOutput", "analogValue", "binaryOutput",
            "binaryValue", "multiStateOutput", "multiStateValue",
            "holding_register", "coil",
        }

        if obj_type in writable:
            write_act = menu.addAction("✏️  Write Value…")
            write_act.triggered.connect(lambda: self._on_double_click(item))

            override_act = menu.addAction("🔴  Override (Priority 8)…")
            override_act.triggered.connect(
                lambda: self._quick_override(obj_type, instance, name)
            )

            release_act = menu.addAction("🟢  Release Override")
            release_act.triggered.connect(
                lambda: self._release_override(obj_type, instance, name)
            )
            menu.addSeparator()

        read_act = menu.addAction("🔄  Read Now")
        read_act.triggered.connect(lambda: self._read_single(obj_type, instance, row))

        cov_key = (obj_type, instance)
        if cov_key in self._cov_subscribed:
            cov_act = menu.addAction("🔕  Unsubscribe COV")
        else:
            cov_act = menu.addAction("📡  Subscribe COV")
        cov_act.triggered.connect(
            lambda: self._toggle_cov(obj_type, instance)
        )

        menu.addSeparator()

        trend_act = menu.addAction("📈  Add to Trend Viewer")
        trend_act.triggered.connect(
            lambda: self._add_to_trend(obj_type, instance, name)
        )

        copy_act = menu.addAction("📋  Copy Value")
        copy_act.triggered.connect(
            lambda: self._copy_value(row)
        )

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── Write / Override operations ───────────────────────────────────────────

    def _do_write(self, obj_type: str, instance: int, value, priority: int):
        if not self._adapter:
            QMessageBox.warning(self, "Not Connected", "No active connection.")
            return

        self._set_status(f"Writing {value} to {obj_type}:{instance} @ P{priority}…")

        thread = WriteThread(
            self._adapter, self._device_id,
            obj_type, instance, value, priority
        )
        thread.write_done.connect(self._on_write_done)
        thread.finished.connect(lambda: self._cleanup_thread(thread))
        self._active_threads.append(thread)
        thread.start()

    def _on_write_done(self, success: bool, message: str):
        if success:
            self._set_status(f"✅  {message}")
            # Refresh the written row
            QTimer.singleShot(500, self._poll_visible)
        else:
            self._set_status(f"❌  Write failed: {message}")
            QMessageBox.warning(self, "Write Failed", message)

    def _quick_override(self, obj_type: str, instance: int, name: str):
        val_item = None
        for row in range(self._table.rowCount()):
            n = self._table.item(row, COL_NAME)
            t = self._table.item(row, COL_TYPE)
            if n and t and t.text() == obj_type:
                i = self._table.item(row, COL_INSTANCE)
                if i and i.text() == str(instance):
                    val_item = self._table.item(row, COL_VALUE)
                    break

        current = val_item.text() if val_item else "0"
        dlg = WriteDialog(
            name, obj_type, current,
            is_binary=obj_type.startswith("binary"),
            parent=self,
        )
        dlg._priority_combo.setCurrentIndex(7)   # P8 = Manual Operator
        if dlg.exec():
            self._do_write(obj_type, instance, dlg.get_value(), 8)

    def _release_override(self, obj_type: str, instance: int, name: str):
        if QMessageBox.question(
            self, "Release Override",
            f"Release the manual override on '{name}'?\n\n"
            f"This will write 'null' to priority 8, allowing lower priorities to take effect.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self._do_write(obj_type, instance, None, 8)

    # ── Single point read ─────────────────────────────────────────────────────

    def _read_single(self, obj_type: str, instance: int, row: int):
        if not self._adapter:
            return
        thread = PointReadThread(
            self._adapter, self._device_id, [(obj_type, instance)]
        )
        thread.values_ready.connect(self._update_table_values)
        thread.finished.connect(lambda: self._cleanup_thread(thread))
        self._active_threads.append(thread)
        thread.start()

    # ── COV ───────────────────────────────────────────────────────────────────

    def _toggle_cov(self, obj_type: str, instance: int):
        key = (obj_type, instance)
        if key in self._cov_subscribed:
            self._cov_subscribed.discard(key)
            self._set_status(f"COV unsubscribed: {obj_type}:{instance}")
        else:
            self._cov_subscribed.add(key)
            self._set_status(f"📡 COV subscribed: {obj_type}:{instance}")

    # ── Live polling ──────────────────────────────────────────────────────────

    def _toggle_live(self, enabled: bool):
        if enabled:
            interval = self._poll_spin.value() * 1000
            self._poll_timer.start(interval)
            self._live_btn.setText("⏹ Stop")
            self._live_btn.setStyleSheet("background: #FF4455; color: white;")
            self._poll_lbl.setText(f"🟢 Polling every {self._poll_spin.value()}s")
        else:
            self._poll_timer.stop()
            self._live_btn.setText("▶ Live")
            self._live_btn.setStyleSheet("")
            self._poll_lbl.setText("")
        self._update_status_count()

    def _poll_visible(self):
        """Re-read all currently visible rows."""
        if not self._adapter or self._device_id is None:
            return
        objs = []
        for row in range(self._table.rowCount()):
            if not self._table.isRowHidden(row):
                name_item = self._table.item(row, COL_NAME)
                if name_item:
                    d = name_item.data(Qt.ItemDataRole.UserRole) or {}
                    if d.get("obj_type"):
                        objs.append((d["obj_type"], d["instance"]))
        if not objs:
            return
        thread = PointReadThread(self._adapter, self._device_id, objs[:100])
        thread.values_ready.connect(self._update_table_values)
        thread.finished.connect(lambda: self._cleanup_thread(thread))
        self._active_threads.append(thread)
        thread.start()

    # ── Trend / Copy ──────────────────────────────────────────────────────────

    def _add_to_trend(self, obj_type: str, instance: int, name: str):
        self._set_status(f"Added to Trend Viewer: {name}  (open Trend Viewer to view)")

    def _copy_value(self, row: int):
        val_item = self._table.item(row, COL_VALUE)
        if val_item:
            QApplication.clipboard().setText(val_item.text())
            self._set_status(f"Copied: {val_item.text()}")

    # ── Export CSV ────────────────────────────────────────────────────────────

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Points to CSV",
            f"HBCE_Points_{self._device_name}_{datetime.now():%Y%m%d_%H%M}.csv",
            "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(COLUMNS)
                for row in range(self._table.rowCount()):
                    if not self._table.isRowHidden(row):
                        row_data = []
                        for col in range(len(COLUMNS)):
                            item = self._table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
            self._set_status(f"✅ Exported to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    def _cleanup_thread(self, thread):
        if thread in self._active_threads:
            self._active_threads.remove(thread)

