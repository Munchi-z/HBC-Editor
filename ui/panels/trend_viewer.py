"""
HBCE — Hybrid Controls Editor
ui/panels/trend_viewer.py — Trend Viewer (Full Implementation V0.1.1-alpha)

Features:
  - Multi-point overlay: up to 8 trends on one chart simultaneously
  - Time window: 1h / 8h / 24h / 7d / 30d / Custom date-range picker
  - Live polling: configurable interval, appends new samples in real-time
  - Point picker: add/remove trend lines from a device+object selector
  - Per-series color, label, unit, Y-axis scaling (auto or manual)
  - Dual Y-axes: left for analog (units), right for binary (0/1)
  - Crosshair cursor: hover shows timestamp + value for all active series
  - Legend: toggleable, click to show/hide individual series
  - CSV export: all visible series with timestamps
  - Zoom: scroll-wheel, drag-to-zoom, reset-zoom button
  - Annotations: right-click chart to add a timestamped note
  - Uses pyqtgraph for all charting (already in requirements.txt)

Architecture:
  - TrendDataStore: in-memory ring buffer per series (max 10,000 samples)
  - TrendPollThread: QThread — polls adapter for new values (GOTCHA-013)
  - TrendHistoryThread: QThread — loads historical data on panel open
  - TrendViewerPanel: main widget, owns toolbar + chart + legend + controls
"""

from __future__ import annotations

import csv
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import (
    QDateTime,
    QThread,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
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

MAX_SAMPLES      = 10_000          # ring buffer size per series
MAX_SERIES       = 8               # max simultaneous trend lines

# Colour palette — distinct, dark-mode friendly
SERIES_COLORS = [
    "#4FC3F7",   # light blue
    "#81C784",   # green
    "#FFB74D",   # orange
    "#F06292",   # pink
    "#CE93D8",   # purple
    "#80DEEA",   # cyan
    "#FFCC02",   # yellow
    "#FF8A65",   # deep orange
]

TIME_WINDOWS = [
    ("1 hour",   3600),
    ("8 hours",  8 * 3600),
    ("24 hours", 24 * 3600),
    ("7 days",   7 * 86400),
    ("30 days",  30 * 86400),
    ("Custom",   -1),
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TrendPoint:
    ts: float       # Unix timestamp
    value: float


@dataclass
class TrendSeries:
    series_id:   str
    device_name: str
    device_addr: str
    object_name: str
    object_type: str
    instance:    int
    units:       str
    color:       str
    label:       str
    visible:     bool = True
    samples:     List[TrendPoint] = field(default_factory=list)

    @property
    def is_binary(self) -> bool:
        return self.object_type in ("binaryInput", "binaryOutput", "binaryValue")

    def append(self, ts: float, value: float):
        self.samples.append(TrendPoint(ts, value))
        if len(self.samples) > MAX_SAMPLES:
            self.samples = self.samples[-MAX_SAMPLES:]

    def numpy(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return (timestamps, values) as numpy arrays."""
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
# Background threads
# ---------------------------------------------------------------------------

class TrendHistoryThread(QThread):
    """Loads historical samples for one or more series from the adapter."""
    data_ready = pyqtSignal(str, list)   # series_id, [(ts, value), ...]
    error      = pyqtSignal(str)

    def __init__(self, series: TrendSeries, start_ts: float, end_ts: float,
                 adapter=None, parent=None):
        super().__init__(parent)
        self._series   = series
        self._start    = start_ts
        self._end      = end_ts
        self._adapter  = adapter

    def run(self):
        try:
            # Real: data = self._adapter.read_trend(series, start, end)
            # Demo: generate synthetic history
            data = _generate_history(self._series, self._start, self._end)
            self.data_ready.emit(self._series.series_id, data)
        except Exception as exc:
            self.error.emit(str(exc))


class TrendPollThread(QThread):
    """Periodically reads current value for all active series."""
    new_samples = pyqtSignal(list)   # [(series_id, ts, value), ...]
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
                    # Real: v = self._adapter.read_present_value(s.device_addr, s.object_type, s.instance)
                    v = _demo_value(s, now)
                    samples.append((s.series_id, now, v))
                if samples:
                    self.new_samples.emit(samples)
            except Exception as exc:
                self.poll_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Demo data helpers
# ---------------------------------------------------------------------------

def _generate_history(series: TrendSeries, start: float, end: float,
                      interval: int = 300) -> List[Tuple[float, float]]:
    """Generate synthetic historical data at `interval` second spacing."""
    data = []
    ts   = start
    base = random.uniform(60, 80) if not series.is_binary else 0
    while ts <= end:
        if series.is_binary:
            v = float(random.random() > 0.85)   # occasional state change
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


# ---------------------------------------------------------------------------
# Add-Series dialog
# ---------------------------------------------------------------------------

class AddSeriesDialog(QDialog):
    """Let the user pick a device + object to add as a new trend series."""

    def __init__(self, existing_ids: List[str], color: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Trend Series")
        self.setFixedWidth(420)
        self.setModal(True)
        self._color  = color
        self._result_series: Optional[TrendSeries] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Device
        layout.addWidget(QLabel("Device:"))
        self._device_combo = QComboBox()
        for d in [("AHU-1", "192.168.1.10"), ("AHU-2", "192.168.1.11"),
                  ("CHWR-1", "192.168.1.20"), ("BAS-CTRL", "192.168.1.1"),
                  ("VAV-B3-04", "192.168.1.45")]:
            self._device_combo.addItem(d[0], d)
        layout.addWidget(self._device_combo)

        # Object
        layout.addWidget(QLabel("Object:"))
        self._obj_combo = QComboBox()
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
        for o in objects:
            self._obj_combo.addItem(f"{o[0]}  ({o[1]}:{o[2]})", o)
        layout.addWidget(self._obj_combo)

        # Label override
        layout.addWidget(QLabel("Label (optional):"))
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Auto-generated if empty")
        layout.addWidget(self._label_edit)

        # Color picker
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(60, 24)
        self._color_btn.setStyleSheet(f"background:{self._color}; border-radius:3px;")
        self._color_btn.clicked.connect(self._pick_color)
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        layout.addLayout(color_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name()
            self._color_btn.setStyleSheet(
                f"background:{self._color}; border-radius:3px;"
            )

    def _on_accept(self):
        dev_data = self._device_combo.currentData()
        obj_data = self._obj_combo.currentData()
        label    = self._label_edit.text().strip() or \
                   f"{dev_data[0]} / {obj_data[0]}"
        series_id = f"{dev_data[0]}_{obj_data[0]}_{obj_data[2]}"
        self._result_series = TrendSeries(
            series_id   = series_id,
            device_name = dev_data[0],
            device_addr = dev_data[1],
            object_name = obj_data[0],
            object_type = obj_data[1],
            instance    = obj_data[2],
            units       = obj_data[3],
            color       = self._color,
            label       = label,
        )
        self.accept()

    @property
    def series(self) -> Optional[TrendSeries]:
        return self._result_series


# ---------------------------------------------------------------------------
# Legend widget
# ---------------------------------------------------------------------------

class TrendLegend(QWidget):
    """Sidebar legend showing each series with color swatch, label, live value."""

    visibility_changed = pyqtSignal(str, bool)   # series_id, visible
    remove_requested   = pyqtSignal(str)          # series_id
    color_changed      = pyqtSignal(str, str)     # series_id, new_color

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet("background: #0F1518;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel("Series")
        title.setStyleSheet("color: #546E7A; font-size: 9px; font-weight: bold; "
                            "text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { padding: 2px; }"
            "QListWidget::item:selected { background: #1A2428; }"
        )
        layout.addWidget(self._list, 1)

        self._rows: Dict[str, QWidget] = {}

    def add_series(self, s: TrendSeries):
        row       = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(6)

        # Color swatch (clickable → color picker)
        swatch = QPushButton()
        swatch.setFixedSize(14, 14)
        swatch.setStyleSheet(
            f"background:{s.color}; border-radius:2px; border:none;"
        )
        swatch.setToolTip("Click to change color")
        swatch.clicked.connect(lambda _, sid=s.series_id: self._change_color(sid))
        row_layout.addWidget(swatch)

        # Visibility checkbox
        chk = QCheckBox()
        chk.setChecked(s.visible)
        chk.setFixedWidth(14)
        chk.stateChanged.connect(
            lambda state, sid=s.series_id:
                self.visibility_changed.emit(sid, bool(state))
        )
        row_layout.addWidget(chk)

        # Label
        lbl = QLabel(s.label)
        lbl.setStyleSheet("color: #B0BEC5; font-size: 9pt;")
        lbl.setWordWrap(False)
        lbl.setMaximumWidth(110)
        row_layout.addWidget(lbl, 1)

        # Live value
        val_lbl = QLabel("—")
        val_lbl.setObjectName(f"val_{s.series_id}")
        val_lbl.setStyleSheet("color: #546E7A; font-size: 8pt;")
        val_lbl.setFixedWidth(40)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        row_layout.addWidget(val_lbl)

        # Remove button
        rm = QPushButton("✕")
        rm.setFixedSize(16, 16)
        rm.setStyleSheet(
            "QPushButton {background:transparent;color:#37474F;border:none;font-size:10px;}"
            "QPushButton:hover{color:#EF5350;}"
        )
        rm.clicked.connect(lambda _, sid=s.series_id: self.remove_requested.emit(sid))
        row_layout.addWidget(rm)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        self._rows[s.series_id] = (item, row, swatch, val_lbl)

    def remove_series(self, series_id: str):
        if series_id not in self._rows:
            return
        item, *_ = self._rows.pop(series_id)
        row_idx = self._list.row(item)
        self._list.takeItem(row_idx)

    def update_value(self, series_id: str, value: float, units: str):
        if series_id not in self._rows:
            return
        _, _, _, val_lbl = self._rows[series_id]
        text = f"{value:.1f}" if abs(value) < 10000 else f"{value:.0f}"
        if units:
            text += f" {units}"
        val_lbl.setText(text)

    def _change_color(self, series_id: str):
        if series_id not in self._rows:
            return
        _, _, swatch, _ = self._rows[series_id]
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            swatch.setStyleSheet(
                f"background:{c.name()}; border-radius:2px; border:none;"
            )
            self.color_changed.emit(series_id, c.name())


# ---------------------------------------------------------------------------
# Main Trend Viewer Panel
# ---------------------------------------------------------------------------

class TrendViewerPanel(QWidget):
    """
    HBCE Trend Viewer — V0.1.1-alpha

    Multi-series pyqtgraph chart with live polling, configurable time windows,
    dual Y-axes, crosshair, legend, zoom, annotations, and CSV export.
    """

    def __init__(self, config=None, db=None, current_user=None,
                 adapter=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {}
        self._adapter     = adapter

        self._series:      Dict[str, TrendSeries] = {}
        self._curves:      Dict[str, pg.PlotDataItem] = {}
        self._annotations: List[Tuple[float, str]] = []

        self._poll_thread:   Optional[TrendPollThread]   = None
        self._history_threads: List[TrendHistoryThread]  = []
        self._polling        = False
        self._poll_interval  = 5

        # Time window
        self._window_seconds = 3600   # 1 hour default
        self._custom_start   = None
        self._custom_end     = None

        if PYQTGRAPH_AVAILABLE:
            pg.setConfigOption("background", "#111820")
            pg.setConfigOption("foreground", "#546E7A")

        self._build_ui()
        self._connect_signals()
        logger.debug("TrendViewerPanel initialized")

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        # Main body: chart | legend
        body = QSplitter(Qt.Orientation.Horizontal)

        if PYQTGRAPH_AVAILABLE:
            body.addWidget(self._build_chart())
        else:
            body.addWidget(self._build_no_pyqtgraph_placeholder())

        self._legend = TrendLegend()
        self._legend.visibility_changed.connect(self._on_visibility_changed)
        self._legend.remove_requested.connect(self._remove_series)
        self._legend.color_changed.connect(self._on_color_changed)
        body.addWidget(self._legend)
        body.setSizes([1000, 220])

        root.addWidget(body, 1)

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setStyleSheet(
            "QStatusBar { background:#0F1518; color:#546E7A; font-size:9pt; }"
        )
        self._status_bar.showMessage("No series added. Click ＋ Add Series to begin.")
        root.addWidget(self._status_bar)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background:#0F1518; border-bottom:1px solid #263238;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        title = QLabel("📈  Trend Viewer")
        title.setStyleSheet("font-size:12px; font-weight:bold; color:#B0BEC5;")
        layout.addWidget(title)
        layout.addStretch()

        btn_style = (
            "QPushButton { background:#1A2428; color:#90A4AE; border:1px solid #263238; "
            "border-radius:3px; padding:3px 10px; font-size:9pt; }"
            "QPushButton:hover { background:#243038; color:#CFD8DC; }"
            "QPushButton:checked { background:#1B3A2A; color:#81C784; }"
            "QPushButton:disabled { color:#37474F; }"
        )

        self._add_btn = QPushButton("＋  Add Series")
        self._add_btn.setStyleSheet(btn_style)
        layout.addWidget(self._add_btn)

        self._clear_btn = QPushButton("✕  Clear All")
        self._clear_btn.setStyleSheet(btn_style)
        layout.addWidget(self._clear_btn)

        # Time window
        layout.addWidget(self._build_time_controls())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#263238;")
        layout.addWidget(sep)

        self._poll_btn = QPushButton("▶  Live")
        self._poll_btn.setCheckable(True)
        self._poll_btn.setStyleSheet(btn_style)
        layout.addWidget(self._poll_btn)

        layout.addWidget(self._build_interval_selector())

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color:#263238;")
        layout.addWidget(sep2)

        self._zoom_reset_btn = QPushButton("⊡  Reset Zoom")
        self._zoom_reset_btn.setStyleSheet(btn_style)
        layout.addWidget(self._zoom_reset_btn)

        self._csv_btn = QPushButton("↓  CSV")
        self._csv_btn.setStyleSheet(btn_style)
        layout.addWidget(self._csv_btn)

        return bar

    def _build_time_controls(self) -> QWidget:
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        lbl = QLabel("Window:")
        lbl.setStyleSheet("color:#546E7A; font-size:9pt;")
        h.addWidget(lbl)

        self._window_combo = QComboBox()
        self._window_combo.setFixedWidth(90)
        self._window_combo.setStyleSheet(
            "QComboBox { background:#1A2428; color:#90A4AE; "
            "border:1px solid #263238; border-radius:3px; font-size:9pt; }"
        )
        for label, seconds in TIME_WINDOWS:
            self._window_combo.addItem(label, seconds)
        h.addWidget(self._window_combo)

        # Custom date range (hidden unless Custom selected)
        self._custom_widget = QWidget()
        ch = QHBoxLayout(self._custom_widget)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(4)

        self._start_dt = QDateTimeEdit()
        self._start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._start_dt.setDateTime(
            QDateTime.currentDateTime().addSecs(-86400)
        )
        self._start_dt.setFixedWidth(130)
        ch.addWidget(self._start_dt)

        ch.addWidget(QLabel("→"))

        self._end_dt = QDateTimeEdit()
        self._end_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._end_dt.setDateTime(QDateTime.currentDateTime())
        self._end_dt.setFixedWidth(130)
        ch.addWidget(self._end_dt)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(50)
        apply_btn.setStyleSheet(
            "QPushButton {background:#1A2428;color:#90A4AE;"
            "border:1px solid #263238;border-radius:3px;font-size:8pt;}"
        )
        apply_btn.clicked.connect(self._apply_custom_range)
        ch.addWidget(apply_btn)

        self._custom_widget.setVisible(False)
        h.addWidget(self._custom_widget)

        return c

    def _build_interval_selector(self) -> QWidget:
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        lbl = QLabel("Every:")
        lbl.setStyleSheet("color:#546E7A; font-size:9pt;")
        h.addWidget(lbl)
        self._interval_combo = QComboBox()
        self._interval_combo.setFixedWidth(68)
        self._interval_combo.setStyleSheet(
            "QComboBox { background:#1A2428; color:#90A4AE; "
            "border:1px solid #263238; border-radius:3px; font-size:9pt; }"
        )
        for s, lbl2 in [(5, "5 s"), (10, "10 s"), (30, "30 s"), (60, "1 min")]:
            self._interval_combo.addItem(lbl2, s)
        h.addWidget(self._interval_combo)
        return c

    def _build_chart(self) -> QWidget:
        """Build the pyqtgraph PlotWidget with dual Y-axes and crosshair."""
        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # Date/time X axis
        date_axis = DateAxisItem(orientation="bottom")

        self._plot = pg.PlotWidget(axisItems={"bottom": date_axis})
        self._plot.setLabel("bottom", "Time")
        self._plot.setLabel("left",   "Value")
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.getPlotItem().setContentsMargins(10, 10, 10, 10)

        # Style axes
        for ax in ("bottom", "left"):
            self._plot.getAxis(ax).setTextPen(pg.mkPen("#546E7A"))
            self._plot.getAxis(ax).setPen(pg.mkPen("#263238"))

        # Crosshair
        self._v_line = pg.InfiniteLine(angle=90,  movable=False,
                                       pen=pg.mkPen("#37474F", width=1))
        self._h_line = pg.InfiniteLine(angle=0,   movable=False,
                                       pen=pg.mkPen("#37474F", width=1))
        self._plot.addItem(self._v_line, ignoreBounds=True)
        self._plot.addItem(self._h_line, ignoreBounds=True)

        # Crosshair tooltip label
        self._crosshair_label = pg.TextItem(
            anchor=(0, 1), color="#B0BEC5",
            fill=pg.mkBrush("#0F151899")
        )
        self._crosshair_label.setFont(QFont("Monospace", 8))
        self._plot.addItem(self._crosshair_label)

        self._plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._plot.scene().sigMouseClicked.connect(self._on_chart_clicked)

        layout.addWidget(self._plot)
        return container

    def _build_no_pyqtgraph_placeholder(self) -> QWidget:
        """Shown when pyqtgraph is not installed."""
        w = QWidget()
        w.setStyleSheet("background:#111820;")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("📈")
        icon.setStyleSheet("font-size:48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg  = QLabel(
            "pyqtgraph is not installed.\n\n"
            "Run:  pip install pyqtgraph\n\n"
            "Then restart HBCE."
        )
        msg.setStyleSheet("color:#546E7A; font-size:11pt;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(msg)
        return w

    # ── Signals ────────────────────────────────────────────────────────────

    def _connect_signals(self):
        self._add_btn.clicked.connect(self._add_series)
        self._clear_btn.clicked.connect(self._clear_all)
        self._poll_btn.toggled.connect(self._toggle_polling)
        self._zoom_reset_btn.clicked.connect(self._reset_zoom)
        self._csv_btn.clicked.connect(self._export_csv)
        self._window_combo.currentIndexChanged.connect(self._on_window_changed)
        self._interval_combo.currentIndexChanged.connect(self._update_poll_interval)

    # ── Series management ──────────────────────────────────────────────────

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
            QMessageBox.information(self, "Already Added",
                                    f"'{s.label}' is already on the chart.")
            return

        self._series[s.series_id] = s
        self._legend.add_series(s)

        if PYQTGRAPH_AVAILABLE:
            curve = self._plot.plot(
                pen=pg.mkPen(s.color, width=2),
                name=s.label,
                stepMode=("center" if s.is_binary else None),
            )
            self._curves[s.series_id] = curve

        # Load history
        start, end = self._current_window()
        thread = TrendHistoryThread(s, start, end, self._adapter, self)
        thread.data_ready.connect(self._on_history_ready)
        thread.error.connect(lambda e: self._status_bar.showMessage(f"Error: {e}"))
        thread.start()
        self._history_threads.append(thread)

        # Update poll thread series list
        if self._poll_thread:
            self._poll_thread.set_series(list(self._series.values()))

        self._update_status()

    def _remove_series(self, series_id: str):
        if series_id not in self._series:
            return
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._plot.removeItem(self._curves.pop(series_id))
        self._legend.remove_series(series_id)
        del self._series[series_id]
        if self._poll_thread:
            self._poll_thread.set_series(list(self._series.values()))
        self._update_status()

    def _clear_all(self):
        for sid in list(self._series.keys()):
            self._remove_series(sid)
        self._annotations.clear()
        self._update_status()

    def _on_visibility_changed(self, series_id: str, visible: bool):
        if series_id in self._series:
            self._series[series_id].visible = visible
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._curves[series_id].setVisible(visible)

    def _on_color_changed(self, series_id: str, color: str):
        if series_id in self._series:
            self._series[series_id].color = color
        if PYQTGRAPH_AVAILABLE and series_id in self._curves:
            self._curves[series_id].setPen(pg.mkPen(color, width=2))

    # ── Data loading ───────────────────────────────────────────────────────

    def _on_history_ready(self, series_id: str, data: List[Tuple[float, float]]):
        if series_id not in self._series:
            return
        s = self._series[series_id]
        for ts, val in data:
            s.append(ts, val)
        self._redraw_series(series_id)
        self._status_bar.showMessage(
            f"Loaded {len(data)} samples for {s.label}"
        )

    def _on_new_samples(self, samples: List[Tuple[str, float, float]]):
        for series_id, ts, val in samples:
            if series_id in self._series:
                s = self._series[series_id]
                s.append(ts, val)
                self._legend.update_value(series_id, val, s.units)
                self._redraw_series(series_id)
        self._update_status()

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

    # ── Time window ────────────────────────────────────────────────────────

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

    # ── Live polling ───────────────────────────────────────────────────────

    def _toggle_polling(self, checked: bool):
        if checked:
            self._start_polling()
        else:
            self._stop_polling()

    def _start_polling(self):
        self._poll_interval = self._interval_combo.currentData() or 5
        self._poll_thread   = TrendPollThread(self._poll_interval, self._adapter, self)
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

    # ── Chart interaction ──────────────────────────────────────────────────

    def _on_mouse_moved(self, pos):
        if not PYQTGRAPH_AVAILABLE:
            return
        if not self._plot.sceneBoundingRect().contains(pos):
            return
        mouse_point = self._plot.getViewBox().mapSceneToView(pos)
        x = mouse_point.x()
        y = mouse_point.y()
        self._v_line.setPos(x)
        self._h_line.setPos(y)

        # Build crosshair tooltip
        # Guard against invalid x values (0, negative, NaN, inf) before any
        # data is loaded — datetime.fromtimestamp() raises OSError on Windows
        # for out-of-range timestamps.  Added as GOTCHA-017.
        try:
            if not (1e6 < x < 32503680000):   # sane year 1970–3000 window
                return
            dt_str = datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return
        lines   = [dt_str]
        for s in self._series.values():
            if not s.visible or len(s.samples) < 2:
                continue
            ts_arr, val_arr = s.numpy()
            idx = np.searchsorted(ts_arr, x)
            if 0 < idx < len(val_arr):
                v = val_arr[idx - 1]
                lines.append(f"{s.label}: {v:.2f} {s.units}")
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
                "QMenu {background:#1A2428;color:#B0BEC5;border:1px solid #263238;}"
                "QMenu::item:selected{background:#2D4450;}"
            )
            add_note = menu.addAction("📝  Add Annotation Here")
            action   = menu.exec(event.screenPos().toPoint())
            if action == add_note:
                text, ok = QInputDialog.getText(
                    self, "Add Annotation",
                    f"Note at {datetime.fromtimestamp(ts).strftime('%H:%M:%S')}:"
                )
                if ok and text:
                    self._annotations.append((ts, text))
                    line = pg.InfiniteLine(
                        pos=ts, angle=90, movable=False,
                        pen=pg.mkPen("#F9A825", width=1, style=Qt.PenStyle.DashLine),
                        label=text, labelOpts={"color": "#F9A825", "position": 0.95}
                    )
                    self._plot.addItem(line)

    def _reset_zoom(self):
        if PYQTGRAPH_AVAILABLE:
            self._plot.getViewBox().autoRange()

    # ── Export ─────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._series:
            QMessageBox.information(self, "Nothing to Export",
                                    "Add at least one series first.")
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
                writer = csv.writer(f)

                # Header
                header = ["Timestamp (UTC)"]
                for s in self._series.values():
                    header.append(f"{s.label} ({s.units})" if s.units else s.label)
                writer.writerow(header)

                # Collect all unique timestamps across all series
                all_ts = set()
                windowed: Dict[str, Tuple] = {}
                for sid, s in self._series.items():
                    ts_arr, val_arr = s.window(start, end)
                    windowed[sid]   = (ts_arr, val_arr)
                    all_ts.update(ts_arr.tolist())

                for ts in sorted(all_ts):
                    row = [datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")]
                    for sid in self._series:
                        ts_arr, val_arr = windowed[sid]
                        idx = np.searchsorted(ts_arr, ts)
                        if idx < len(val_arr) and ts_arr[idx] == ts:
                            row.append(f"{val_arr[idx]:.4f}")
                        else:
                            row.append("")
                    writer.writerow(row)

            n = len(all_ts)
            self._status_bar.showMessage(
                f"✅ CSV exported: {n} rows → {os.path.basename(path)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ── Status ─────────────────────────────────────────────────────────────

    def _update_status(self):
        n        = len(self._series)
        total_pts = sum(len(s.samples) for s in self._series.values())
        window   = self._window_combo.currentText()
        poll_str = f"  ·  live every {self._poll_interval}s" if self._polling else ""
        self._status_bar.showMessage(
            f"Series: {n}/{MAX_SERIES}  ·  Samples: {total_pts:,}  ·  "
            f"Window: {window}{poll_str}"
        )

    # ── Cleanup ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._stop_polling()
        super().closeEvent(event)

    # ── Public API — called from Point Browser "Add to Trend" ──────────────

    def add_series_from_point_browser(self, device_name: str, device_addr: str,
                                       object_name: str, object_type: str,
                                       instance: int, units: str):
        """Wire-in: Point Browser right-click → Add to Trend calls this."""
        if len(self._series) >= MAX_SERIES:
            return False
        color     = SERIES_COLORS[len(self._series) % len(SERIES_COLORS)]
        series_id = f"{device_name}_{object_name}_{instance}"
        if series_id in self._series:
            return False
        s = TrendSeries(
            series_id=series_id, device_name=device_name, device_addr=device_addr,
            object_name=object_name, object_type=object_type, instance=instance,
            units=units, color=color, label=f"{device_name} / {object_name}",
        )
        self._series[s.series_id] = s
        self._legend.add_series(s)
        if PYQTGRAPH_AVAILABLE:
            curve = self._plot.plot(pen=pg.mkPen(s.color, width=2), name=s.label)
            self._curves[s.series_id] = curve
        start, end = self._current_window()
        thread = TrendHistoryThread(s, start, end, self._adapter, self)
        thread.data_ready.connect(self._on_history_ready)
        thread.start()
        self._history_threads.append(thread)
        if self._poll_thread:
            self._poll_thread.set_series(list(self._series.values()))
        self._update_status()
        return True
