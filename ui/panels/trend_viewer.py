"""
HBCE — Hybrid Controls Editor
ui/panels/trend_viewer.py — Trend Viewer (V0.2.1-alpha redesign)

Three-view Metasys-style layout:
  • Chart  — pyqtgraph multi-series plot  +  bottom series table (vertical splitter)
  • Config — editable settings table  +  series manager with + / − buttons
  • Table  — timestamp × series grid  +  Copy to Clipboard

Public API (unchanged):
  add_series_from_point_browser(device_name, device_addr, object_name,
                                object_type, instance, units) -> bool

Threads (unchanged):
  TrendHistoryThread, TrendPollThread

GOTCHAs honoured:
  GOTCHA-013: all I/O in QThreads — never block UI
  GOTCHA-017: datetime.fromtimestamp() range guard + try/except in _on_mouse_moved
  GOTCHA-018: _build_toolbar() uses lambda wrappers for any deferred-attribute
              access (self._view_stack not yet assigned when toolbar is built)
"""

from __future__ import annotations

import csv
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import (
    QDate, QDateTime, QTime,
    QThread, QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False

from core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SAMPLES = 10_000
MAX_SERIES  = 8

SERIES_COLORS = [
    "#4FC3F7", "#81C784", "#FFB74D", "#F06292",
    "#CE93D8", "#80DEEA", "#FFCC02", "#FF8A65",
]

TIME_WINDOWS = [
    ("1 hour",   3600),
    ("8 hours",  8 * 3600),
    ("24 hours", 24 * 3600),
    ("7 days",   7 * 86400),
    ("30 days",  30 * 86400),
    ("Custom",   -1),
]

PLOT_STYLES       = ["Continuous", "Discrete", "Step"]
_PRECISION_LABELS = ["Ones", "Tenths", "Hundredths"]

_BTN = (
    "QPushButton { background:#1A2428; color:#90A4AE; border:1px solid #263238; "
    "  border-radius:3px; padding:3px 10px; font-size:9pt; }"
    "QPushButton:hover  { background:#243038; color:#CFD8DC; }"
    "QPushButton:checked{ background:#1B3A2A; color:#81C784; }"
    "QPushButton:disabled{ color:#37474F; }"
)
_COMBO = (
    "QComboBox { background:#1A2428; color:#90A4AE; "
    "  border:1px solid #263238; border-radius:3px; font-size:9pt; }"
    "QComboBox::drop-down { border:none; }"
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TrendPoint:
    ts: float
    value: float


@dataclass
class TrendSeries:
    """One trend line.  V0.2.1: added reference + plotting_style fields."""
    series_id:      str
    device_name:    str
    device_addr:    str
    object_name:    str
    object_type:    str
    instance:       int
    units:          str
    color:          str
    label:          str
    visible:        bool = True
    reference:      str  = ""
    plotting_style: str  = "Continuous"
    samples: List[TrendPoint] = field(default_factory=list)

    @property
    def is_binary(self) -> bool:
        return self.object_type in ("binaryInput", "binaryOutput", "binaryValue")

    def append(self, ts: float, value: float):
        self.samples.append(TrendPoint(ts, value))
        if len(self.samples) > MAX_SAMPLES:
            self.samples = self.samples[-MAX_SAMPLES:]

    def numpy(self) -> Tuple[np.ndarray, np.ndarray]:
        if not self.samples:
            return np.array([]), np.array([])
        ts  = np.array([s.ts    for s in self.samples])
        val = np.array([s.value for s in self.samples])
        return ts, val

    def window(self, start_ts: float, end_ts: float) -> Tuple[np.ndarray, np.ndarray]:
        ts, val = self.numpy()
        if ts.size == 0:
            return ts, val
        mask = (ts >= start_ts) & (ts <= end_ts)
        return ts[mask], val[mask]


# ---------------------------------------------------------------------------
# Background threads  (unchanged from V0.2.0)
# ---------------------------------------------------------------------------

class TrendHistoryThread(QThread):
    """Loads historical samples for one series  (GOTCHA-013 compliant)."""
    data_ready = pyqtSignal(str, list)
    error      = pyqtSignal(str)

    def __init__(self, series: TrendSeries, start_ts: float, end_ts: float,
                 adapter=None, parent=None):
        super().__init__(parent)
        self._series  = series
        self._start   = start_ts
        self._end     = end_ts
        self._adapter = adapter

    def run(self):
        try:
            data = _generate_history(self._series, self._start, self._end)
            self.data_ready.emit(self._series.series_id, data)
        except Exception as exc:
            self.error.emit(str(exc))


class TrendPollThread(QThread):
    """Polls present values for all active series at a fixed interval."""
    new_samples = pyqtSignal(list)
    poll_error  = pyqtSignal(str)

    def __init__(self, interval_s: int = 5, adapter=None, parent=None):
        super().__init__(parent)
        self._interval = interval_s
        self._adapter  = adapter
        self._series: List[TrendSeries] = []
        self._running  = True

    def set_series(self, series: List[TrendSeries]):
        self._series = list(series)

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            try:
                samples = []
                now = time.time()
                for s in self._series:
                    if not s.visible:
                        continue
                    v = _demo_value(s, now)
                    samples.append((s.series_id, now, v))
                if samples:
                    self.new_samples.emit(samples)
            except Exception as exc:
                self.poll_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Demo helpers
# ---------------------------------------------------------------------------

def _generate_history(series: TrendSeries, start: float, end: float,
                      interval: int = 300) -> List[Tuple[float, float]]:
    data = []
    ts   = start
    base = random.uniform(60, 80) if not series.is_binary else 0
    while ts <= end:
        if series.is_binary:
            v = float(random.random() > 0.85)
        else:
            base += random.uniform(-1.5, 1.5)
            base  = max(40, min(120, base))
            v     = round(base, 2)
        data.append((ts, v))
        ts += interval
    return data


def _demo_value(series: TrendSeries, ts: float) -> float:
    if series.is_binary:
        return float(random.random() > 0.9)
    seed = hash(series.series_id) % 100
    return round(60 + seed * 0.3 + 10 * abs((ts % 3600) / 3600 - 0.5)
                 + random.uniform(-0.5, 0.5), 2)


def _fmt(value: float, precision: int) -> str:
    return f"{value:.{precision}f}"


# ---------------------------------------------------------------------------
# Add-Series dialog  (extended: Reference + Plot Style)
# ---------------------------------------------------------------------------

class AddSeriesDialog(QDialog):
    def __init__(self, existing_ids: List[str], color: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Trend Series")
        self.setFixedWidth(460)
        self.setModal(True)
        self._color          = color
        self._result_series: Optional[TrendSeries] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Device:"))
        self._device_combo = QComboBox()
        for d in [("AHU-1",     "192.168.1.10"),
                  ("AHU-2",     "192.168.1.11"),
                  ("CHWR-1",    "192.168.1.20"),
                  ("BAS-CTRL",  "192.168.1.1"),
                  ("VAV-B3-04", "192.168.1.45")]:
            self._device_combo.addItem(d[0], d)
        layout.addWidget(self._device_combo)

        layout.addWidget(QLabel("Object:"))
        self._obj_combo = QComboBox()
        for o in [("SA-TEMP",  "analogInput",  0, "°F"),
                  ("RA-TEMP",  "analogInput",  1, "°F"),
                  ("SA-SP",    "analogValue",  2, "°F"),
                  ("FAN-SPD",  "analogOutput", 0, "%"),
                  ("CHW-FLOW", "analogInput",  5, "GPM"),
                  ("FIRE-1",   "binaryInput",  0, ""),
                  ("SMOKE-1",  "binaryInput",  1, ""),
                  ("OCC",      "binaryValue",  0, "")]:
            self._obj_combo.addItem(f"{o[0]}  ({o[1]}:{o[2]})", o)
        layout.addWidget(self._obj_combo)

        layout.addWidget(QLabel("Label (optional):"))
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Auto-generated if empty")
        layout.addWidget(self._label_edit)

        layout.addWidget(QLabel("BACnet Reference (optional):"))
        self._reference_edit = QLineEdit()
        self._reference_edit.setPlaceholderText(
            "e.g.  HOC-ADS1:HOC-SNE2/analogInput,5"
        )
        layout.addWidget(self._reference_edit)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(60, 24)
        self._color_btn.setStyleSheet(f"background:{self._color}; border-radius:3px;")
        self._color_btn.clicked.connect(self._pick_color)
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        layout.addLayout(color_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Plot Style:"))
        self._style_combo = QComboBox()
        self._style_combo.addItems(PLOT_STYLES)
        style_row.addWidget(self._style_combo)
        style_row.addStretch()
        layout.addLayout(style_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name()
            self._color_btn.setStyleSheet(
                f"background:{self._color}; border-radius:3px;"
            )

    def _on_accept(self):
        dev  = self._device_combo.currentData()
        obj  = self._obj_combo.currentData()
        lbl  = self._label_edit.text().strip() or f"{dev[0]} / {obj[0]}"
        ref  = (self._reference_edit.text().strip()
                or f"{dev[1]}:{obj[1]},{obj[2]}")
        sid  = f"{dev[0]}_{obj[0]}_{obj[2]}"
        self._result_series = TrendSeries(
            series_id=sid, device_name=dev[0], device_addr=dev[1],
            object_name=obj[0], object_type=obj[1], instance=obj[2],
            units=obj[3], color=self._color, label=lbl, reference=ref,
            plotting_style=self._style_combo.currentText(),
        )
        self.accept()

    @property
    def series(self) -> Optional[TrendSeries]:
        return self._result_series


# ---------------------------------------------------------------------------
# SeriesBottomTable  (replaces TrendLegend sidebar)
# ---------------------------------------------------------------------------

class SeriesBottomTable(QWidget):
    """
    Bottom panel in Chart view.
    Columns: Show ☑ | Marker ■ | Name | Reference (editable) | Plot Style ▼ | ✕
    Splitter with no fixed row count — user-draggable (user decision c).
    """
    visibility_changed     = pyqtSignal(str, bool)
    color_change_requested = pyqtSignal(str)
    reference_changed      = pyqtSignal(str, str)
    plotting_style_changed = pyqtSignal(str, str)
    remove_requested       = pyqtSignal(str)
    add_requested          = pyqtSignal()

    _C_SHOW  = 0
    _C_MKR   = 1
    _C_NAME  = 2
    _C_REF   = 3
    _C_STYLE = 4
    _C_RM    = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sub-header
        hbar = QWidget()
        hbar.setFixedHeight(26)
        hbar.setStyleSheet(
            "background:#0F1518; border-top:1px solid #263238;"
        )
        hb_lay = QHBoxLayout(hbar)
        hb_lay.setContentsMargins(8, 2, 8, 2)
        lbl = QLabel("Series")
        lbl.setStyleSheet(
            "color:#546E7A; font-size:9px; font-weight:bold;"
        )
        hb_lay.addWidget(lbl)
        hb_lay.addStretch()
        add_btn = QPushButton("＋  Add Series")
        add_btn.setFixedHeight(20)
        add_btn.setStyleSheet(
            "QPushButton{background:#1A2428;color:#81C784;"
            "border:1px solid #263238;border-radius:2px;"
            "font-size:8pt;padding:0 8px;}"
            "QPushButton:hover{background:#243038;}"
        )
        add_btn.clicked.connect(self.add_requested)
        hb_lay.addWidget(add_btn)
        root.addWidget(hbar)

        self._tbl = QTableWidget(0, 6)
        self._tbl.setHorizontalHeaderLabels(
            ["Show", "Mkr", "Name", "Reference", "Plot Style", ""]
        )
        self._tbl.setStyleSheet(
            "QTableWidget{background:#0F1518;color:#B0BEC5;"
            "gridline-color:#1A2428;border:none;font-size:9pt;}"
            "QTableWidget::item{padding:2px 4px;}"
            "QTableWidget::item:selected{background:#1B2A32;}"
            "QTableWidget::item:alternate{background:#111820;}"
            "QHeaderView::section{background:#111820;color:#546E7A;"
            "border:none;border-bottom:1px solid #263238;"
            "font-size:8pt;padding:2px 4px;}"
        )
        self._tbl.setShowGrid(False)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked |
            QTableWidget.EditTrigger.SelectedClicked
        )
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.verticalHeader().setDefaultSectionSize(26)

        hdr = self._tbl.horizontalHeader()
        hdr.setSectionResizeMode(self._C_SHOW,  QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self._C_MKR,   QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self._C_NAME,  QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self._C_REF,   QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self._C_STYLE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self._C_RM,    QHeaderView.ResizeMode.Fixed)
        self._tbl.setColumnWidth(self._C_SHOW,  44)
        self._tbl.setColumnWidth(self._C_MKR,   36)
        self._tbl.setColumnWidth(self._C_STYLE, 118)
        self._tbl.setColumnWidth(self._C_RM,    32)

        self._tbl.itemChanged.connect(self._on_item_changed)
        self._tbl.cellDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._tbl, 1)

    # ── Internal ────────────────────────────────────────────────────────

    def _find_row(self, series_id: str) -> int:
        for r in range(self._tbl.rowCount()):
            item = self._tbl.item(r, self._C_SHOW)
            if item and item.data(Qt.ItemDataRole.UserRole) == series_id:
                return r
        return -1

    def _series_id_at(self, row: int) -> Optional[str]:
        item = self._tbl.item(row, self._C_SHOW)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ── Public ──────────────────────────────────────────────────────────

    def add_series(self, s: TrendSeries):
        row = self._tbl.rowCount()
        self._tbl.insertRow(row)
        self._tbl.blockSignals(True)
        self._fill_row(row, s)
        self._tbl.blockSignals(False)
        self._set_cell_widgets(row, s)

    def remove_series(self, series_id: str):
        row = self._find_row(series_id)
        if row >= 0:
            self._tbl.removeRow(row)

    def update_series(self, s: TrendSeries):
        row = self._find_row(s.series_id)
        if row < 0:
            self.add_series(s)
            return
        self._tbl.blockSignals(True)
        self._fill_row(row, s)
        self._tbl.blockSignals(False)
        # Update only style combo (reference item already updated via _fill_row)
        combo = self._tbl.cellWidget(row, self._C_STYLE)
        if combo:
            combo.blockSignals(True)
            combo.setCurrentText(s.plotting_style)
            combo.blockSignals(False)

    def sync_from_dict(self, series_dict: Dict[str, TrendSeries]):
        for r in range(self._tbl.rowCount() - 1, -1, -1):
            sid = self._series_id_at(r)
            if sid and sid not in series_dict:
                self._tbl.removeRow(r)
        for s in series_dict.values():
            if self._find_row(s.series_id) < 0:
                self._tbl.blockSignals(True)
                row = self._tbl.rowCount()
                self._tbl.insertRow(row)
                self._fill_row(row, s)
                self._tbl.blockSignals(False)
                self._set_cell_widgets(row, s)
            else:
                self.update_series(s)

    def _fill_row(self, row: int, s: TrendSeries):
        # Col 0: Show checkbox
        show = QTableWidgetItem()
        show.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        show.setCheckState(
            Qt.CheckState.Checked if s.visible else Qt.CheckState.Unchecked
        )
        show.setData(Qt.ItemDataRole.UserRole, s.series_id)
        self._tbl.setItem(row, self._C_SHOW, show)

        # Col 1: Marker (colored background, not editable)
        mkr = QTableWidgetItem()
        mkr.setFlags(Qt.ItemFlag.ItemIsEnabled)
        mkr.setBackground(QColor(s.color))
        mkr.setToolTip("Double-click to change color")
        mkr.setData(Qt.ItemDataRole.UserRole, s.series_id)
        self._tbl.setItem(row, self._C_MKR, mkr)

        # Col 2: Name (display only)
        name = QTableWidgetItem(s.label)
        name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._tbl.setItem(row, self._C_NAME, name)

        # Col 3: Reference (inline editable — user decision b)
        ref = QTableWidgetItem(s.reference)
        ref.setData(Qt.ItemDataRole.UserRole, s.series_id)
        ref.setToolTip("Full BACnet object path — editable")
        self._tbl.setItem(row, self._C_REF, ref)

    def _set_cell_widgets(self, row: int, s: TrendSeries):
        # Col 4: Plot Style combo
        combo = QComboBox()
        combo.addItems(PLOT_STYLES)
        combo.setCurrentText(s.plotting_style)
        combo.setStyleSheet(
            "QComboBox{background:#1A2428;color:#90A4AE;border:none;font-size:8pt;}"
        )
        combo.currentTextChanged.connect(
            lambda txt, sid=s.series_id: self.plotting_style_changed.emit(sid, txt)
        )
        self._tbl.setCellWidget(row, self._C_STYLE, combo)

        # Col 5: Remove button
        btn = QPushButton("✕")
        btn.setFixedSize(26, 22)
        btn.setStyleSheet(
            "QPushButton{background:transparent;color:#37474F;border:none;}"
            "QPushButton:hover{color:#EF5350;}"
        )
        btn.clicked.connect(
            lambda _, sid=s.series_id: self.remove_requested.emit(sid)
        )
        self._tbl.setCellWidget(row, self._C_RM, btn)

    def _on_item_changed(self, item: QTableWidgetItem):
        col = item.column()
        sid = item.data(Qt.ItemDataRole.UserRole)
        if not sid:
            return
        if col == self._C_SHOW:
            self.visibility_changed.emit(
                sid, item.checkState() == Qt.CheckState.Checked
            )
        elif col == self._C_REF:
            self.reference_changed.emit(sid, item.text())

    def _on_double_click(self, row: int, col: int):
        if col == self._C_MKR:
            sid = self._series_id_at(row)
            if sid:
                self.color_change_requested.emit(sid)


# ---------------------------------------------------------------------------
# TrendConfigPanel  (Config view)
# ---------------------------------------------------------------------------

class TrendConfigPanel(QWidget):
    refresh_rate_changed    = pyqtSignal(int)
    precision_changed       = pyqtSignal(int)
    date_range_changed      = pyqtSignal(float, float)
    stacked_y_changed       = pyqtSignal(bool)
    add_series_requested    = pyqtSignal()
    remove_series_requested = pyqtSignal(str)
    reference_changed       = pyqtSignal(str, str)
    plotting_style_changed  = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#111820;")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._build_settings_group())
        root.addWidget(self._build_series_group(), 1)

    def _build_settings_group(self) -> QGroupBox:
        grp = QGroupBox("General Settings")
        grp.setStyleSheet(
            "QGroupBox{color:#90A4AE;border:1px solid #263238;"
            "border-radius:4px;margin-top:8px;font-size:9pt;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
        )
        lay = QVBoxLayout(grp)

        self._settings_tbl = QTableWidget(10, 3)
        self._settings_tbl.setHorizontalHeaderLabels(
            ["Attribute", "Value", "Units"]
        )
        self._settings_tbl.setStyleSheet(
            "QTableWidget{background:#0F1518;color:#B0BEC5;"
            "gridline-color:#1A2428;border:none;font-size:9pt;}"
            "QTableWidget::item{padding:3px 6px;}"
            "QTableWidget::item:selected{background:#1B2A32;}"
            "QHeaderView::section{background:#111820;color:#546E7A;"
            "border:none;border-bottom:1px solid #263238;"
            "font-size:8pt;padding:3px 6px;}"
        )
        self._settings_tbl.verticalHeader().setVisible(False)
        self._settings_tbl.verticalHeader().setDefaultSectionSize(30)
        self._settings_tbl.setShowGrid(False)
        self._settings_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hdr = self._settings_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._settings_tbl.setColumnWidth(2, 80)

        self._populate_settings_rows()
        lay.addWidget(self._settings_tbl)

        # Fix height to content
        total_h = (sum(self._settings_tbl.rowHeight(r)
                       for r in range(10))
                   + self._settings_tbl.horizontalHeader().height() + 6)
        self._settings_tbl.setFixedHeight(total_h)
        return grp

    def _attr_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        if text.startswith("—"):
            item.setForeground(QColor("#546E7A"))
        return item

    def _unit_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setForeground(QColor("#546E7A"))
        return item

    def _populate_settings_rows(self):
        now = QDateTime.currentDateTime()
        attrs  = ["Refresh Rate", "Display Precision",
                  "— Range Start —", "Start Date", "Start Time",
                  "— Range End —",   "End Date",   "End Time",
                  "— Chart Display —", "Stacked Y Axis"]
        units  = ["seconds", "", "", "", "", "", "", "", "", ""]
        for r, (a, u) in enumerate(zip(attrs, units)):
            self._settings_tbl.setItem(r, 0, self._attr_item(a))
            self._settings_tbl.setItem(r, 2, self._unit_item(u))
            if a.startswith("—"):
                self._settings_tbl.setRowHeight(r, 22)

        # Row 0: Refresh Rate
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(5, 3600)
        self._refresh_spin.setValue(60)
        self._refresh_spin.setStyleSheet(
            "QSpinBox{background:#1A2428;color:#90A4AE;"
            "border:1px solid #263238;font-size:9pt;}"
        )
        self._refresh_spin.editingFinished.connect(
            lambda: self.refresh_rate_changed.emit(self._refresh_spin.value())
        )
        self._settings_tbl.setCellWidget(0, 1, self._refresh_spin)

        # Row 1: Display Precision
        self._precision_combo = QComboBox()
        self._precision_combo.addItems(_PRECISION_LABELS)
        self._precision_combo.setCurrentIndex(1)
        self._precision_combo.setStyleSheet(_COMBO)
        self._precision_combo.currentIndexChanged.connect(
            lambda idx: self.precision_changed.emit(idx)
        )
        self._settings_tbl.setCellWidget(1, 1, self._precision_combo)

        dt_style = (
            "QDateEdit,QTimeEdit{background:#1A2428;color:#90A4AE;"
            "border:1px solid #263238;font-size:9pt;}"
        )

        # Row 3: Start Date
        self._start_date = QDateEdit(now.addSecs(-86400).date())
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        self._start_date.setCalendarPopup(True)
        self._start_date.setStyleSheet(dt_style)
        self._start_date.dateChanged.connect(self._emit_range)
        self._settings_tbl.setCellWidget(3, 1, self._start_date)

        # Row 4: Start Time
        self._start_time = QTimeEdit(QTime(0, 0, 0))
        self._start_time.setDisplayFormat("hh:mm:ss AP")
        self._start_time.setStyleSheet(dt_style)
        self._start_time.timeChanged.connect(self._emit_range)
        self._settings_tbl.setCellWidget(4, 1, self._start_time)

        # Row 6: End Date
        self._end_date = QDateEdit(now.date())
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        self._end_date.setCalendarPopup(True)
        self._end_date.setStyleSheet(dt_style)
        self._end_date.dateChanged.connect(self._emit_range)
        self._settings_tbl.setCellWidget(6, 1, self._end_date)

        # Row 7: End Time
        self._end_time = QTimeEdit(now.time())
        self._end_time.setDisplayFormat("hh:mm:ss AP")
        self._end_time.setStyleSheet(dt_style)
        self._end_time.timeChanged.connect(self._emit_range)
        self._settings_tbl.setCellWidget(7, 1, self._end_time)

        # Row 9: Stacked Y Axis
        self._stacked_combo = QComboBox()
        self._stacked_combo.addItems(["False", "True"])
        self._stacked_combo.setStyleSheet(_COMBO)
        self._stacked_combo.currentTextChanged.connect(
            lambda txt: self.stacked_y_changed.emit(txt == "True")
        )
        self._settings_tbl.setCellWidget(9, 1, self._stacked_combo)

    def _emit_range(self):
        start_dt = QDateTime(self._start_date.date(), self._start_time.time())
        end_dt   = QDateTime(self._end_date.date(),   self._end_time.time())
        self.date_range_changed.emit(
            float(start_dt.toSecsSinceEpoch()),
            float(end_dt.toSecsSinceEpoch()),
        )

    def _build_series_group(self) -> QGroupBox:
        grp = QGroupBox("Series")
        grp.setStyleSheet(
            "QGroupBox{color:#90A4AE;border:1px solid #263238;"
            "border-radius:4px;margin-top:8px;font-size:9pt;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
        )
        lay = QVBoxLayout(grp)

        btn_row = QHBoxLayout()
        self._cfg_add_btn = QPushButton("＋  Add")
        self._cfg_add_btn.setStyleSheet(_BTN)
        self._cfg_add_btn.clicked.connect(self.add_series_requested)
        self._cfg_rm_btn = QPushButton("−  Remove")
        self._cfg_rm_btn.setStyleSheet(_BTN)
        self._cfg_rm_btn.clicked.connect(self._on_cfg_remove)
        btn_row.addWidget(self._cfg_add_btn)
        btn_row.addWidget(self._cfg_rm_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._series_tbl = QTableWidget(0, 3)
        self._series_tbl.setHorizontalHeaderLabels(
            ["Name", "Reference", "Plot Style"]
        )
        self._series_tbl.setStyleSheet(
            "QTableWidget{background:#0F1518;color:#B0BEC5;"
            "gridline-color:#1A2428;border:none;font-size:9pt;}"
            "QTableWidget::item{padding:3px 6px;}"
            "QTableWidget::item:selected{background:#1B2A32;}"
            "QTableWidget::item:alternate{background:#111820;}"
            "QHeaderView::section{background:#111820;color:#546E7A;"
            "border:none;border-bottom:1px solid #263238;"
            "font-size:8pt;padding:3px 6px;}"
        )
        self._series_tbl.verticalHeader().setVisible(False)
        self._series_tbl.verticalHeader().setDefaultSectionSize(28)
        self._series_tbl.setShowGrid(False)
        self._series_tbl.setAlternatingRowColors(True)
        self._series_tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hdr = self._series_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._series_tbl.setColumnWidth(2, 118)
        self._series_tbl.itemChanged.connect(self._on_series_item_changed)
        lay.addWidget(self._series_tbl, 1)
        return grp

    def _on_cfg_remove(self):
        rows = self._series_tbl.selectionModel().selectedRows()
        if not rows:
            return
        item = self._series_tbl.item(rows[0].row(), 0)
        if item:
            sid = item.data(Qt.ItemDataRole.UserRole)
            if sid:
                self.remove_series_requested.emit(sid)

    def _on_series_item_changed(self, item: QTableWidgetItem):
        if item.column() == 1:
            sid = item.data(Qt.ItemDataRole.UserRole)
            if sid:
                self.reference_changed.emit(sid, item.text())

    def refresh_series(self, series_dict: Dict[str, TrendSeries]):
        self._series_tbl.blockSignals(True)
        self._series_tbl.setRowCount(0)
        for s in series_dict.values():
            row = self._series_tbl.rowCount()
            self._series_tbl.insertRow(row)

            name_item = QTableWidgetItem(s.label)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            name_item.setData(Qt.ItemDataRole.UserRole, s.series_id)
            self._series_tbl.setItem(row, 0, name_item)

            ref_item = QTableWidgetItem(s.reference)
            ref_item.setData(Qt.ItemDataRole.UserRole, s.series_id)
            self._series_tbl.setItem(row, 1, ref_item)

            combo = QComboBox()
            combo.addItems(PLOT_STYLES)
            combo.setCurrentText(s.plotting_style)
            combo.setStyleSheet(_COMBO)
            combo.currentTextChanged.connect(
                lambda txt, sid=s.series_id:
                    self.plotting_style_changed.emit(sid, txt)
            )
            self._series_tbl.setCellWidget(row, 2, combo)
        self._series_tbl.blockSignals(False)

    def get_precision(self) -> int:
        return self._precision_combo.currentIndex()

    def get_refresh_rate(self) -> int:
        return self._refresh_spin.value()


# ---------------------------------------------------------------------------
# TrendTablePanel  (Table view)
# ---------------------------------------------------------------------------

class TrendTablePanel(QWidget):
    """
    Time × Series data table.
    Reads from in-memory series dict only — no network (GOTCHA-013).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#111820;")
        self._series_order: List[str] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setFixedHeight(38)
        top.setStyleSheet(
            "background:#0F1518; border-bottom:1px solid #263238;"
        )
        tl = QHBoxLayout(top)
        tl.setContentsMargins(10, 4, 10, 4)
        title_lbl = QLabel("📋  Trend Data Table")
        title_lbl.setStyleSheet(
            "color:#B0BEC5; font-size:11px; font-weight:bold;"
        )
        tl.addWidget(title_lbl)
        self._row_lbl = QLabel("")
        self._row_lbl.setStyleSheet("color:#546E7A; font-size:9pt;")
        tl.addWidget(self._row_lbl)
        tl.addStretch()
        self._copy_btn = QPushButton("📋  Copy to Clipboard")
        self._copy_btn.setStyleSheet(_BTN)
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        tl.addWidget(self._copy_btn)
        root.addWidget(top)

        self._tbl = QTableWidget(0, 1)
        self._tbl.setHorizontalHeaderLabels(["Time"])
        self._tbl.setStyleSheet(
            "QTableWidget{background:#0F1518;color:#B0BEC5;"
            "gridline-color:#1A2428;border:none;font-size:9pt;}"
            "QTableWidget::item{padding:2px 6px;}"
            "QTableWidget::item:selected{background:#1B2A32;}"
            "QTableWidget::item:alternate{background:#111820;}"
            "QHeaderView::section{background:#111820;color:#546E7A;"
            "border:none;border-bottom:1px solid #263238;"
            "font-size:8pt;padding:3px 6px;}"
        )
        self._tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.verticalHeader().setDefaultSectionSize(22)
        self._tbl.setShowGrid(True)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        root.addWidget(self._tbl, 1)

    def refresh_from_series(self, series_dict: Dict[str, TrendSeries],
                            precision: int, start_ts: float, end_ts: float):
        order = [sid for sid, s in series_dict.items() if s.visible]
        self._series_order = order

        self._tbl.blockSignals(True)
        self._tbl.clear()
        ncols = 1 + len(order)
        self._tbl.setColumnCount(ncols)
        headers = ["Time"]
        for sid in order:
            s = series_dict[sid]
            u = f" ({s.units})" if s.units else ""
            headers.append(f"{s.label} - Present Value{u}")
        self._tbl.setHorizontalHeaderLabels(headers)

        if not order:
            self._tbl.setRowCount(0)
            self._row_lbl.setText("")
            self._tbl.blockSignals(False)
            return

        all_ts: set = set()
        windowed: Dict[str, Tuple] = {}
        for sid in order:
            ts_arr, val_arr = series_dict[sid].window(start_ts, end_ts)
            windowed[sid]   = (ts_arr, val_arr)
            all_ts.update(ts_arr.tolist())

        sorted_ts = sorted(all_ts)
        self._tbl.setRowCount(len(sorted_ts))

        for row, ts in enumerate(sorted_ts):
            try:
                dt_str = (
                    datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    if 1e6 < ts < 32503680000 else str(ts)      # GOTCHA-017
                )
            except (OSError, OverflowError, ValueError):
                dt_str = str(ts)

            ts_item = QTableWidgetItem(dt_str)
            ts_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._tbl.setItem(row, 0, ts_item)

            for col, sid in enumerate(order, start=1):
                ts_arr, val_arr = windowed[sid]
                idx = np.searchsorted(ts_arr, ts)
                if idx < len(val_arr) and ts_arr[idx] == ts:
                    text = _fmt(val_arr[idx], precision)
                else:
                    text = ""
                cell = QTableWidgetItem(text)
                cell.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self._tbl.setItem(row, col, cell)

        self._tbl.blockSignals(False)
        self._row_lbl.setText(
            f"  {len(sorted_ts):,} rows  ·  {len(order)} series"
        )

    def _copy_to_clipboard(self):
        if self._tbl.columnCount() <= 1:
            return
        lines = []
        hdrs = [
            self._tbl.horizontalHeaderItem(c).text()
            for c in range(self._tbl.columnCount())
        ]
        lines.append(",".join(f'"{h}"' for h in hdrs))
        for r in range(self._tbl.rowCount()):
            row_cells = []
            for c in range(self._tbl.columnCount()):
                item = self._tbl.item(r, c)
                row_cells.append(item.text() if item else "")
            lines.append(",".join(row_cells))
        QApplication.clipboard().setText("\n".join(lines))
        self._copy_btn.setText("✅  Copied!")
        QTimer.singleShot(
            1500, lambda: self._copy_btn.setText("📋  Copy to Clipboard")
        )


# ---------------------------------------------------------------------------
# Main Panel
# ---------------------------------------------------------------------------

class TrendViewerPanel(QWidget):
    """
    HBCE Trend Viewer — V0.2.1-alpha (Metasys-style redesign)

    Three views (QStackedWidget):
      0 — Chart  : pyqtgraph + vertical-splitter bottom series table
      1 — Config : settings table + series manager
      2 — Table  : timestamp × series grid + clipboard

    Public API unchanged from V0.2.0:
      add_series_from_point_browser(device_name, device_addr, object_name,
                                    object_type, instance, units) -> bool
    """

    _VIEW_CHART  = 0
    _VIEW_CONFIG = 1
    _VIEW_TABLE  = 2

    def __init__(self, config=None, db=None, current_user=None,
                 adapter=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {}
        self._adapter     = adapter

        self._series:          Dict[str, TrendSeries]  = {}
        self._curves:          Dict[str, object]       = {}
        self._annotations:     List[Tuple[float, str]] = []

        self._poll_thread:     Optional[TrendPollThread]    = None
        self._history_threads: List[TrendHistoryThread]     = []
        self._polling          = False
        self._poll_interval    = 5

        self._window_seconds   = 3600
        self._custom_start     = None
        self._custom_end       = None
        self._display_precision = 1   # Tenths default
        self._stacked_y        = False

        if PYQTGRAPH_AVAILABLE:
            pg.setConfigOption("background", "#111820")
            pg.setConfigOption("foreground", "#546E7A")

        self._build_ui()
        self._connect_signals()
        logger.debug("TrendViewerPanel initialized (V0.2.1-alpha)")

    # ====================================================================
    # Build
    # ====================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Toolbar (GOTCHA-018: toolbar built before _view_stack exists;
        #    connections to _view_stack are made in _connect_signals, not here)
        root.addWidget(self._build_toolbar())

        # 2. Three-view stack
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._build_chart_view())    # 0
        self._view_stack.addWidget(self._build_config_view())   # 1
        self._view_stack.addWidget(self._build_table_view())    # 2
        root.addWidget(self._view_stack, 1)

        # 3. Status bar
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setStyleSheet(
            "QStatusBar{background:#0F1518;color:#546E7A;font-size:9pt;}"
        )
        root.addWidget(self._status_bar)

        self._update_status()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(42)
        bar.setStyleSheet("background:#0F1518; border-bottom:1px solid #263238;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        title = QLabel("📈  Trend Viewer")
        title.setStyleSheet("font-size:12px;font-weight:bold;color:#B0BEC5;")
        layout.addWidget(title)
        layout.addWidget(self._vsep())

        # View toggle buttons
        toggle_ss = (
            "QPushButton{background:#1A2428;color:#90A4AE;"
            "border:1px solid #263238;border-radius:3px;"
            "padding:3px 12px;font-size:9pt;}"
            "QPushButton:hover{background:#243038;color:#CFD8DC;}"
            "QPushButton:checked{background:#1B3050;color:#64B5F6;"
            "border-color:#1E4A80;}"
        )
        self._chart_btn  = QPushButton("📈  Chart")
        self._config_btn = QPushButton("⚙  Config")
        self._table_btn  = QPushButton("📋  Table")
        for btn in (self._chart_btn, self._config_btn, self._table_btn):
            btn.setCheckable(True)
            btn.setStyleSheet(toggle_ss)
            layout.addWidget(btn)
        self._chart_btn.setChecked(True)
        layout.addWidget(self._vsep())

        # Series actions
        self._add_btn = QPushButton("＋  Add Series")
        self._add_btn.setStyleSheet(_BTN)
        layout.addWidget(self._add_btn)
        self._clear_btn = QPushButton("✕  Clear All")
        self._clear_btn.setStyleSheet(_BTN)
        layout.addWidget(self._clear_btn)
        layout.addWidget(self._vsep())

        # Time window
        lbl_w = QLabel("Window:")
        lbl_w.setStyleSheet("color:#546E7A;font-size:9pt;")
        layout.addWidget(lbl_w)
        self._window_combo = QComboBox()
        self._window_combo.setFixedWidth(90)
        self._window_combo.setStyleSheet(_COMBO)
        for lbl2, secs in TIME_WINDOWS:
            self._window_combo.addItem(lbl2, secs)
        layout.addWidget(self._window_combo)

        # Custom range
        self._custom_widget = QWidget()
        cw = QHBoxLayout(self._custom_widget)
        cw.setContentsMargins(0, 0, 0, 0)
        cw.setSpacing(4)
        dt_ss = (
            "QDateTimeEdit{background:#1A2428;color:#90A4AE;"
            "border:1px solid #263238;border-radius:3px;font-size:9pt;}"
        )
        self._start_dt = QDateTimeEdit()
        self._start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._start_dt.setDateTime(QDateTime.currentDateTime().addSecs(-86400))
        self._start_dt.setFixedWidth(130)
        self._start_dt.setStyleSheet(dt_ss)
        cw.addWidget(self._start_dt)
        cw.addWidget(QLabel("→"))
        self._end_dt = QDateTimeEdit()
        self._end_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._end_dt.setDateTime(QDateTime.currentDateTime())
        self._end_dt.setFixedWidth(130)
        self._end_dt.setStyleSheet(dt_ss)
        cw.addWidget(self._end_dt)
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(50)
        apply_btn.setStyleSheet(
            "QPushButton{background:#1A2428;color:#90A4AE;"
            "border:1px solid #263238;border-radius:3px;font-size:8pt;}"
        )
        apply_btn.clicked.connect(self._apply_custom_range)
        cw.addWidget(apply_btn)
        self._custom_widget.setVisible(False)
        layout.addWidget(self._custom_widget)
        layout.addWidget(self._vsep())

        # Live polling
        self._poll_btn = QPushButton("▶  Live")
        self._poll_btn.setCheckable(True)
        self._poll_btn.setStyleSheet(_BTN)
        layout.addWidget(self._poll_btn)
        lbl_e = QLabel("Every:")
        lbl_e.setStyleSheet("color:#546E7A;font-size:9pt;")
        layout.addWidget(lbl_e)
        self._interval_combo = QComboBox()
        self._interval_combo.setFixedWidth(68)
        self._interval_combo.setStyleSheet(_COMBO)
        for secs, lbl3 in [(5,"5 s"),(10,"10 s"),(30,"30 s"),(60,"1 min")]:
            self._interval_combo.addItem(lbl3, secs)
        layout.addWidget(self._interval_combo)
        layout.addWidget(self._vsep())

        # Chart controls
        self._zoom_reset_btn = QPushButton("⊡  Reset Zoom")
        self._zoom_reset_btn.setStyleSheet(_BTN)
        layout.addWidget(self._zoom_reset_btn)
        self._csv_btn = QPushButton("↓  CSV")
        self._csv_btn.setStyleSheet(_BTN)
        layout.addWidget(self._csv_btn)

        return bar

    def _build_chart_view(self) -> QWidget:
        """
        Vertical QSplitter: pyqtgraph on top, SeriesBottomTable below.
        No setSizes() — purely user-draggable (user decision a).
        """
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setStyleSheet(
            "QSplitter::handle{background:#1A2428;height:4px;}"
        )
        if PYQTGRAPH_AVAILABLE:
            splitter.addWidget(self._build_chart())
        else:
            splitter.addWidget(self._build_no_pyqtgraph_placeholder())

        self._bottom_series = SeriesBottomTable()
        splitter.addWidget(self._bottom_series)
        self._chart_splitter = splitter
        return splitter

    def _build_config_view(self) -> QWidget:
        self._config_panel = TrendConfigPanel()
        return self._config_panel

    def _build_table_view(self) -> QWidget:
        self._table_panel = TrendTablePanel()
        return self._table_panel

    def _build_chart(self) -> QWidget:
        container = QWidget()
        from PyQt6.QtWidgets import QStackedLayout
        stack = QStackedLayout(container)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        plot_host = QWidget()
        pl = QVBoxLayout(plot_host)
        pl.setContentsMargins(0, 0, 0, 0)

        date_axis = DateAxisItem(orientation="bottom")
        self._plot = pg.PlotWidget(axisItems={"bottom": date_axis})
        self._plot.setLabel("bottom", "Time")
        self._plot.setLabel("left",   "Value")
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.getPlotItem().setContentsMargins(10, 10, 10, 10)
        for ax in ("bottom", "left"):
            self._plot.getAxis(ax).setTextPen(pg.mkPen("#546E7A"))
            self._plot.getAxis(ax).setPen(pg.mkPen("#263238"))

        self._v_line = pg.InfiniteLine(angle=90,  movable=False,
                                       pen=pg.mkPen("#37474F", width=1))
        self._h_line = pg.InfiniteLine(angle=0,   movable=False,
                                       pen=pg.mkPen("#37474F", width=1))
        self._plot.addItem(self._v_line, ignoreBounds=True)
        self._plot.addItem(self._h_line, ignoreBounds=True)

        self._crosshair_label = pg.TextItem(
            anchor=(0, 1), color="#B0BEC5",
            fill=pg.mkBrush("#0F151899")
        )
        self._crosshair_label.setFont(QFont("Monospace", 8))
        self._plot.addItem(self._crosshair_label)

        self._plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._plot.scene().sigMouseClicked.connect(self._on_chart_clicked)
        pl.addWidget(self._plot)
        stack.addWidget(plot_host)

        # Empty overlay
        self._empty_overlay = QWidget()
        self._empty_overlay.setStyleSheet("background:transparent;")
        self._empty_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        ov = QVBoxLayout(self._empty_overlay)
        ov.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for text, ss in [
            ("📈",
             "font-size:40pt;background:transparent;color:#1E2A30;"),
            ("No trend series added",
             "font-size:13pt;font-weight:bold;color:#2A3A42;background:transparent;"),
            ("Click  ＋ Add Series  in the toolbar to begin,\n"
             "or right-click a point in the Point Browser\n"
             "and choose  'Trend this point'.",
             "font-size:9pt;color:#37474F;background:transparent;margin-top:6px;"),
        ]:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(ss)
            ov.addWidget(lbl)

        stack.addWidget(self._empty_overlay)
        self._empty_overlay.show()
        return container

    def _build_no_pyqtgraph_placeholder(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#111820;")
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("📈")
        icon.setStyleSheet("font-size:48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg = QLabel(
            "pyqtgraph is not installed.\n\n"
            "Run:  pip install pyqtgraph\n\nThen restart HBCE."
        )
        msg.setStyleSheet("color:#546E7A;font-size:11pt;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)
        lay.addWidget(msg)
        return w

    @staticmethod
    def _vsep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#263238;")
        sep.setFixedWidth(1)
        return sep

    # ====================================================================
    # Signal wiring
    # ====================================================================

    def _connect_signals(self):
        # GOTCHA-018 safe: self._view_stack is assigned before _connect_signals.
        # Using lambdas here for explicitness; either form is safe at this point.
        self._chart_btn.clicked.connect(
            lambda: self._switch_view(self._VIEW_CHART)
        )
        self._config_btn.clicked.connect(
            lambda: self._switch_view(self._VIEW_CONFIG)
        )
        self._table_btn.clicked.connect(
            lambda: self._switch_view(self._VIEW_TABLE)
        )

        self._add_btn.clicked.connect(self._add_series)
        self._clear_btn.clicked.connect(self._clear_all)
        self._poll_btn.toggled.connect(self._toggle_polling)
        self._zoom_reset_btn.clicked.connect(self._reset_zoom)
        self._csv_btn.clicked.connect(self._export_csv)
        self._window_combo.currentIndexChanged.connect(self._on_window_changed)
        self._interval_combo.currentIndexChanged.connect(self._update_poll_interval)

        # Bottom series table
        self._bottom_series.visibility_changed.connect(self._on_visibility_changed)
        self._bottom_series.color_change_requested.connect(self._on_color_pick)
        self._bottom_series.reference_changed.connect(self._on_reference_changed)
        self._bottom_series.plotting_style_changed.connect(self._on_plotting_style_changed)
        self._bottom_series.remove_requested.connect(self._remove_series)
        self._bottom_series.add_requested.connect(self._add_series)

        # Config panel
        self._config_panel.refresh_rate_changed.connect(self._on_config_refresh_rate)
        self._config_panel.precision_changed.connect(self._on_config_precision)
        self._config_panel.date_range_changed.connect(self._on_config_date_range)
        self._config_panel.stacked_y_changed.connect(self._on_stacked_y_changed)
        self._config_panel.add_series_requested.connect(self._add_series)
        self._config_panel.remove_series_requested.connect(self._remove_series)
        self._config_panel.reference_changed.connect(self._on_reference_changed)
        self._config_panel.plotting_style_changed.connect(self._on_plotting_style_changed)

    # ====================================================================
    # View switching
    # ====================================================================

    def _switch_view(self, index: int):
        self._view_stack.setCurrentIndex(index)
        self._chart_btn.setChecked(index == self._VIEW_CHART)
        self._config_btn.setChecked(index == self._VIEW_CONFIG)
        self._table_btn.setChecked(index == self._VIEW_TABLE)
        self._zoom_reset_btn.setEnabled(index == self._VIEW_CHART)

        if index == self._VIEW_CONFIG:
            self._config_panel.refresh_series(self._series)
        elif index == self._VIEW_TABLE:
            start, end = self._current_window()
            self._table_panel.refresh_from_series(
                self._series, self._display_precision, start, end
            )

    # ====================================================================
    # Series management
    # ====================================================================

    def _add_series(self):
        if len(self._series) >= MAX_SERIES:
            QMessageBox.information(
                self, "Limit Reached",
                f"Maximum {MAX_SERIES} series per chart.\nRemove one first."
            )
            return
        color = SERIES_COLORS[len(self._series) % len(SERIES_COLORS)]
        dlg   = AddSeriesDialog(list(self._series.keys()), color, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.series:
            return
        s = dlg.series
        if s.series_id in self._series:
            QMessageBox.information(
                self, "Already Added", f"'{s.label}' is already on the chart."
            )
            return

        self._series[s.series_id] = s
        self._bottom_series.add_series(s)
        if PYQTGRAPH_AVAILABLE:
            self._add_curve_for_series(s)

        start, end = self._current_window()
        thread = TrendHistoryThread(s, start, end, self._adapter, self)
        thread.data_ready.connect(self._on_history_ready)
        thread.error.connect(
            lambda e: self._status_bar.showMessage(f"Error: {e}")
        )
        thread.start()
        self._history_threads.append(thread)
        if self._poll_thread:
            self._poll_thread.set_series(list(self._series.values()))
        self._update_status()

    def _remove_series(self, series_id: str):
        if series_id not in self._series:
            return
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._plot.removeItem(self._curves.pop(series_id))
        self._bottom_series.remove_series(series_id)
        del self._series[series_id]
        if self._poll_thread:
            self._poll_thread.set_series(list(self._series.values()))
        self._update_status()

    def _clear_all(self):
        for sid in list(self._series.keys()):
            self._remove_series(sid)
        self._annotations.clear()
        self._update_status()

    def _add_curve_for_series(self, s: TrendSeries):
        if not PYQTGRAPH_AVAILABLE:
            return
        style = s.plotting_style
        if style == "Discrete":
            curve = self._plot.plot(
                pen=None, symbol="o", symbolSize=5,
                symbolBrush=pg.mkBrush(s.color),
                symbolPen=pg.mkPen(None), name=s.label,
            )
        elif style == "Step":
            curve = self._plot.plot(
                pen=pg.mkPen(s.color, width=2),
                stepMode="right", name=s.label,
            )
        else:
            curve = self._plot.plot(
                pen=pg.mkPen(s.color, width=2), name=s.label,
            )
        self._curves[s.series_id] = curve

    # ====================================================================
    # Handlers for bottom-table / config signals
    # ====================================================================

    def _on_visibility_changed(self, series_id: str, visible: bool):
        if series_id in self._series:
            self._series[series_id].visible = visible
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._curves[series_id].setVisible(visible)

    def _on_color_pick(self, series_id: str):
        if series_id not in self._series:
            return
        c = QColorDialog.getColor(QColor(self._series[series_id].color), self)
        if not c.isValid():
            return
        self._series[series_id].color = c.name()
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._curves[series_id].setPen(pg.mkPen(c.name(), width=2))
        self._bottom_series.update_series(self._series[series_id])

    def _on_reference_changed(self, series_id: str, ref: str):
        if series_id in self._series:
            self._series[series_id].reference = ref

    def _on_plotting_style_changed(self, series_id: str, style: str):
        if series_id not in self._series:
            return
        self._series[series_id].plotting_style = style
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._plot.removeItem(self._curves.pop(series_id))
            self._add_curve_for_series(self._series[series_id])
            self._redraw_series(series_id)

    def _on_config_refresh_rate(self, secs: int):
        self._poll_interval = secs
        if self._polling:
            self._stop_polling()
            self._poll_btn.setChecked(True)
            self._start_polling()

    def _on_config_precision(self, index: int):
        self._display_precision = index
        if self._view_stack.currentIndex() == self._VIEW_TABLE:
            start, end = self._current_window()
            self._table_panel.refresh_from_series(
                self._series, self._display_precision, start, end
            )

    def _on_config_date_range(self, start_ts: float, end_ts: float):
        self._custom_start   = start_ts
        self._custom_end     = end_ts
        self._window_seconds = -1
        self._window_combo.blockSignals(True)
        for i in range(self._window_combo.count()):
            if self._window_combo.itemData(i) == -1:
                self._window_combo.setCurrentIndex(i)
                break
        self._custom_widget.setVisible(True)
        self._window_combo.blockSignals(False)
        self._redraw_all()

    def _on_stacked_y_changed(self, stacked: bool):
        self._stacked_y = stacked
        if PYQTGRAPH_AVAILABLE:
            self._plot.getViewBox().enableAutoRange()

    # ====================================================================
    # Live polling
    # ====================================================================

    def _toggle_polling(self, checked: bool):
        if checked:
            self._start_polling()
        else:
            self._stop_polling()

    def _start_polling(self):
        self._poll_interval = self._interval_combo.currentData() or 5
        self._poll_thread   = TrendPollThread(
            self._poll_interval, self._adapter, self
        )
        self._poll_thread.set_series(list(self._series.values()))
        self._poll_thread.new_samples.connect(self._on_new_samples)
        self._poll_thread.poll_error.connect(
            lambda e: self._status_bar.showMessage(f"Poll error: {e}")
        )
        self._poll_thread.start()
        self._poll_btn.setText("⏹  Live")
        self._polling = True
        self._update_status()

    def _stop_polling(self):
        if self._poll_thread:
            self._poll_thread.stop()
            self._poll_thread.quit()
            self._poll_thread.wait(2000)
            self._poll_thread = None
        self._poll_btn.setText("▶  Live")
        self._polling = False
        self._update_status()

    def _update_poll_interval(self):
        if self._polling:
            self._stop_polling()
            self._poll_btn.setChecked(True)
            self._start_polling()

    # ====================================================================
    # Data / redraw
    # ====================================================================

    def _on_history_ready(self, series_id: str, data: List[Tuple[float, float]]):
        if series_id not in self._series:
            return
        s = self._series[series_id]
        for ts, val in data:
            s.append(ts, val)
        self._redraw_series(series_id)
        self._status_bar.showMessage(f"Loaded {len(data)} samples for {s.label}")
        if self._view_stack.currentIndex() == self._VIEW_TABLE:
            start, end = self._current_window()
            self._table_panel.refresh_from_series(
                self._series, self._display_precision, start, end
            )

    def _on_new_samples(self, samples: List[Tuple[str, float, float]]):
        for series_id, ts, val in samples:
            if series_id in self._series:
                self._series[series_id].append(ts, val)
                self._redraw_series(series_id)
        self._update_status()
        if self._view_stack.currentIndex() == self._VIEW_TABLE:
            start, end = self._current_window()
            self._table_panel.refresh_from_series(
                self._series, self._display_precision, start, end
            )

    def _redraw_series(self, series_id: str):
        if not PYQTGRAPH_AVAILABLE or series_id not in self._curves:
            return
        s = self._series[series_id]
        start, end = self._current_window()
        ts, val    = s.window(start, end)
        if ts.size > 0:
            self._curves[series_id].setData(ts, val)

    def _redraw_all(self):
        for sid in self._series:
            self._redraw_series(sid)

    # ====================================================================
    # Time window
    # ====================================================================

    def _current_window(self) -> Tuple[float, float]:
        now = time.time()
        if self._window_seconds == -1 and self._custom_start and self._custom_end:
            return self._custom_start, self._custom_end
        return now - self._window_seconds, now

    def _on_window_changed(self):
        seconds = self._window_combo.currentData()
        self._window_seconds = seconds
        self._custom_widget.setVisible(seconds == -1)
        if seconds != -1:
            self._redraw_all()

    def _apply_custom_range(self):
        self._custom_start = self._start_dt.dateTime().toSecsSinceEpoch()
        self._custom_end   = self._end_dt.dateTime().toSecsSinceEpoch()
        self._redraw_all()

    # ====================================================================
    # Chart interaction
    # ====================================================================

    def _on_mouse_moved(self, pos):
        if not PYQTGRAPH_AVAILABLE:
            return
        if not self._plot.sceneBoundingRect().contains(pos):
            return
        mp = self._plot.getViewBox().mapSceneToView(pos)
        x, y = mp.x(), mp.y()
        self._v_line.setPos(x)
        self._h_line.setPos(y)

        # GOTCHA-017 — guard invalid timestamps before datetime call
        try:
            if not (1e6 < x < 32503680000):
                return
            dt_str = datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return

        lines = [dt_str]
        for s in self._series.values():
            if not s.visible or len(s.samples) < 2:
                continue
            ts_arr, val_arr = s.numpy()
            idx = np.searchsorted(ts_arr, x)
            if 0 < idx < len(val_arr):
                v = val_arr[idx - 1]
                lines.append(
                    f"{s.label}: {_fmt(v, self._display_precision)} {s.units}"
                )
        self._crosshair_label.setText("\n".join(lines))
        self._crosshair_label.setPos(x, y)

    def _on_chart_clicked(self, event):
        if not PYQTGRAPH_AVAILABLE:
            return
        if event.button() == Qt.MouseButton.RightButton:
            pos = self._plot.getViewBox().mapSceneToView(event.scenePos())
            ts  = pos.x()
            menu = QMenu(self)
            menu.setStyleSheet(
                "QMenu{background:#1A2428;color:#B0BEC5;"
                "border:1px solid #263238;}"
                "QMenu::item:selected{background:#2D4450;}"
            )
            add_note = menu.addAction("📝  Add Annotation Here")
            action   = menu.exec(event.screenPos().toPoint())
            if action == add_note:
                try:
                    ts_str = (
                        datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                        if 1e6 < ts < 32503680000 else str(ts)
                    )
                except (OSError, OverflowError, ValueError):
                    ts_str = str(ts)
                text, ok = QInputDialog.getText(
                    self, "Add Annotation", f"Note at {ts_str}:"
                )
                if ok and text:
                    self._annotations.append((ts, text))
                    line = pg.InfiniteLine(
                        pos=ts, angle=90, movable=False,
                        pen=pg.mkPen("#F9A825", width=1,
                                     style=Qt.PenStyle.DashLine),
                        label=text,
                        labelOpts={"color": "#F9A825", "position": 0.95},
                    )
                    self._plot.addItem(line)

    def _reset_zoom(self):
        if PYQTGRAPH_AVAILABLE:
            self._plot.getViewBox().autoRange()

    # ====================================================================
    # CSV Export
    # ====================================================================

    def _export_csv(self):
        if not self._series:
            QMessageBox.information(
                self, "Nothing to Export", "Add at least one series first."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Trend Data — CSV",
            f"trend_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        if not path:
            return
        start, end = self._current_window()
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                hdr = ["Timestamp (UTC)"]
                for s in self._series.values():
                    hdr.append(
                        f"{s.label} ({s.units})" if s.units else s.label
                    )
                w.writerow(hdr)

                all_ts: set = set()
                windowed: Dict[str, Tuple] = {}
                for sid, s in self._series.items():
                    ts_arr, val_arr = s.window(start, end)
                    windowed[sid]   = (ts_arr, val_arr)
                    all_ts.update(ts_arr.tolist())

                for ts in sorted(all_ts):
                    try:
                        dt_str = (
                            datetime.fromtimestamp(ts).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                            if 1e6 < ts < 32503680000 else str(ts)
                        )
                    except (OSError, OverflowError, ValueError):
                        dt_str = str(ts)
                    row = [dt_str]
                    for sid in self._series:
                        ts_arr, val_arr = windowed[sid]
                        idx = np.searchsorted(ts_arr, ts)
                        if idx < len(val_arr) and ts_arr[idx] == ts:
                            row.append(_fmt(val_arr[idx], self._display_precision))
                        else:
                            row.append("")
                    w.writerow(row)

            self._status_bar.showMessage(
                f"✅ CSV exported: {len(all_ts)} rows → {os.path.basename(path)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ====================================================================
    # Status
    # ====================================================================

    def _update_status(self):
        n         = len(self._series)
        total_pts = sum(len(s.samples) for s in self._series.values())
        window    = self._window_combo.currentText()
        poll_str  = f"  ·  live every {self._poll_interval}s" if self._polling else ""
        if n == 0:
            self._status_bar.showMessage(
                "No series added — click  ＋ Add Series  to begin trending."
            )
        else:
            self._status_bar.showMessage(
                f"Series: {n}/{MAX_SERIES}  ·  Samples: {total_pts:,}  ·  "
                f"Window: {window}{poll_str}"
            )
        if hasattr(self, "_empty_overlay"):
            self._empty_overlay.setVisible(n == 0)

    # ====================================================================
    # Cleanup
    # ====================================================================

    def closeEvent(self, event):
        self._stop_polling()
        super().closeEvent(event)

    # ====================================================================
    # Public API  (signature unchanged — V0.2.0 → V0.2.1 compatible)
    # ====================================================================

    def add_series_from_point_browser(self, device_name: str, device_addr: str,
                                       object_name: str, object_type: str,
                                       instance: int, units: str) -> bool:
        """
        Called by Point Browser right-click → 'Trend this point'.
        Returns True if added, False if already present or limit reached.
        """
        if len(self._series) >= MAX_SERIES:
            return False
        color     = SERIES_COLORS[len(self._series) % len(SERIES_COLORS)]
        series_id = f"{device_name}_{object_name}_{instance}"
        if series_id in self._series:
            return False

        s = TrendSeries(
            series_id     = series_id,
            device_name   = device_name,
            device_addr   = device_addr,
            object_name   = object_name,
            object_type   = object_type,
            instance      = instance,
            units         = units,
            color         = color,
            label         = f"{device_name} / {object_name}",
            reference     = f"{device_addr}:{object_type},{instance}",
        )
        self._series[s.series_id] = s
        self._bottom_series.add_series(s)

        if PYQTGRAPH_AVAILABLE:
            self._add_curve_for_series(s)

        start, end = self._current_window()
        thread = TrendHistoryThread(s, start, end, self._adapter, self)
        thread.data_ready.connect(self._on_history_ready)
        thread.start()
        self._history_threads.append(thread)
        if self._poll_thread:
            self._poll_thread.set_series(list(self._series.values()))
        self._update_status()
        return True
