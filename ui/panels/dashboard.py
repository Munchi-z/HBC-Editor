"""
HBCE — Hybrid Controls Editor
ui/panels/dashboard.py — Dashboard panel (full implementation V0.0.4-alpha)

Features:
  - Connected devices quick-connect cards
  - Recent alarms summary widget
  - System stats (CPU, memory, uptime)
  - Recent projects list
  - Quick-action buttons
  - User-editable widget layout (drag to reorder, show/hide widgets)
  - Edit mode toggled via View → Edit Dashboard Layout
"""

import os
import json
import platform
import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QSizePolicy, QToolButton,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox,
    QCheckBox, QMessageBox, QSpacerItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QPoint
from PyQt6.QtGui import QFont, QDrag, QCursor

from core.logger import get_logger

logger = get_logger(__name__)

# ── Widget IDs — used in layout config ───────────────────────────────────────
W_QUICK_ACTIONS  = "quick_actions"
W_DEVICES        = "devices"
W_ALARMS         = "alarms"
W_STATS          = "stats"
W_PROJECTS       = "projects"

DEFAULT_LAYOUT = [
    W_QUICK_ACTIONS,
    W_DEVICES,
    W_ALARMS,
    W_STATS,
    W_PROJECTS,
]


# ── Individual dashboard widget cards ─────────────────────────────────────────

class DashCard(QFrame):
    """Base styled card for all dashboard widgets."""

    def __init__(self, title: str, icon: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("DashCard")
        self.setStyleSheet("""
            QFrame#DashCard {
                background-color: #1e1e32;
                border: 1px solid #2a2a4e;
                border-radius: 8px;
            }
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        # Card header bar
        header = QWidget()
        header.setStyleSheet(
            "background-color: #252540; border-radius: 8px 8px 0 0; "
            "border-bottom: 1px solid #2a2a4e;"
        )
        header.setFixedHeight(36)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 0, 8, 0)
        h_layout.setSpacing(6)

        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet("background: transparent; font-size: 14px;")
            h_layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "background: transparent; color: #C0C0D0; "
            "font-size: 10pt; font-weight: bold;"
        )
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()

        self._root.addWidget(header)

        # Content area
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 10, 12, 12)
        self._content_layout.setSpacing(6)
        self._root.addWidget(self._content)

    def content_layout(self):
        return self._content_layout


class QuickActionsCard(DashCard):
    """Quick-action buttons for common tasks."""

    action_requested = pyqtSignal(int)   # emits panel index

    ACTIONS = [
        (1,  "🔌", "Connect Device",   "#0C447C", "#3B8BD4"),
        (2,  "📋", "Browse Points",    "#0C4428", "#1D9E75"),
        (3,  "🔔", "Alarm Viewer",     "#4A1B0C", "#D85A30"),
        (4,  "📈", "Trend Viewer",     "#26215C", "#7F77DD"),
        (5,  "🧠", "Program Editor",   "#2C2C2A", "#888780"),
        (8,  "📄", "Reports",          "#0C2044", "#378ADD"),
    ]

    def __init__(self, parent=None):
        super().__init__("Quick Actions", "⚡", parent)
        grid = QGridLayout()
        grid.setSpacing(8)

        for i, (panel_idx, icon, label, bg, hover) in enumerate(self.ACTIONS):
            btn = QPushButton(f"{icon}  {label}")
            btn.setMinimumHeight(44)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg};
                    color: #D0D0E0;
                    border: 1px solid {hover}44;
                    border-radius: 6px;
                    font-size: 9pt;
                    font-weight: bold;
                    text-align: left;
                    padding-left: 10px;
                }}
                QPushButton:hover {{
                    background-color: {hover}55;
                    border: 1px solid {hover};
                    color: white;
                }}
                QPushButton:pressed {{
                    background-color: {hover}88;
                }}
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, idx=panel_idx: self.action_requested.emit(idx)
            )
            grid.addWidget(btn, i // 3, i % 3)

        self.content_layout().addLayout(grid)


class DevicesCard(DashCard):
    """Connected devices quick-connect list."""

    connect_requested = pyqtSignal(int)  # panel index

    def __init__(self, db=None, parent=None):
        super().__init__("Connected Devices", "🔌", parent)
        self.db = db
        self._build()

    def _build(self):
        cl = self.content_layout()

        # No device placeholder
        self._empty_label = QLabel("No devices connected.\nUse 'Connect Device' to add one.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #505060; font-size: 9pt; padding: 16px;")
        cl.addWidget(self._empty_label)

        # Quick connect button
        btn = QPushButton("🔌  Connect New Device…")
        btn.setMinimumHeight(36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.connect_requested.emit(1))
        cl.addWidget(btn)

    def refresh(self, devices: list):
        """Update with list of connected device dicts."""
        # Clear existing device rows (keep last button)
        while self.content_layout().count() > 2:
            item = self.content_layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not devices:
            self._empty_label.show()
            return

        self._empty_label.hide()
        for dev in devices:
            row = QFrame()
            row.setStyleSheet(
                "background:#252540; border:1px solid #2a2a4e; border-radius:6px;"
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)

            dot = QLabel("🟢")
            row_layout.addWidget(dot)

            name = QLabel(dev.get("name", "Unknown"))
            name.setStyleSheet("color:#E0E0F0; font-weight:bold; background:transparent;")
            row_layout.addWidget(name)

            proto = QLabel(dev.get("protocol", ""))
            proto.setStyleSheet("color:#707080; font-size:8pt; background:transparent;")
            row_layout.addWidget(proto)
            row_layout.addStretch()

            self.content_layout().insertWidget(
                self.content_layout().count() - 1, row
            )


class AlarmsCard(DashCard):
    """Recent alarms summary."""

    def __init__(self, db=None, parent=None):
        super().__init__("Recent Alarms", "🔔", parent)
        self.db = db
        self._build()

    def _build(self):
        cl = self.content_layout()
        self._rows = []

        # Header row
        hdr = QWidget()
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(0, 0, 0, 4)
        for txt, stretch in [("Time", 0), ("Device", 1), ("Description", 2), ("Pri", 0), ("State", 0)]:
            lbl = QLabel(txt)
            lbl.setStyleSheet(
                "color:#606070; font-size:8pt; font-weight:bold; background:transparent;"
            )
            hdr_l.addWidget(lbl, stretch)
        cl.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border:1px solid #2a2a4e;")
        cl.addWidget(sep)

        self._no_alarms = QLabel("No active alarms.")
        self._no_alarms.setStyleSheet("color:#505060; font-size:9pt; padding:8px;")
        self._no_alarms.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self._no_alarms)

    def refresh(self, alarms: list):
        """Update with alarm records from DB."""
        # Remove old rows
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()

        if not alarms:
            self._no_alarms.show()
            return

        self._no_alarms.hide()
        PRIORITY_COLORS = {1: "#FF4455", 2: "#FF8844", 3: "#FFAA00"}

        for alarm in alarms[:8]:   # show max 8
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 2, 0, 2)

            pri = alarm.get("priority", 3)
            col = PRIORITY_COLORS.get(pri, "#808090")

            time_lbl  = QLabel(alarm.get("timestamp", "")[-8:])   # HH:MM:SS
            dev_lbl   = QLabel(alarm.get("object_ref", "")[:12])
            desc_lbl  = QLabel(alarm.get("description", "")[:30])
            pri_lbl   = QLabel(str(pri))
            state_lbl = QLabel(alarm.get("ack_state", "")[:4])

            for lbl, stretch in [(time_lbl,0),(dev_lbl,1),(desc_lbl,2),(pri_lbl,0),(state_lbl,0)]:
                lbl.setStyleSheet(
                    f"color:{col}; font-size:8pt; background:transparent;"
                )
                row_l.addWidget(lbl, stretch)

            self.content_layout().addWidget(row)
            self._rows.append(row)


class StatsCard(DashCard):
    """System stats — CPU, memory, uptime."""

    def __init__(self, parent=None):
        super().__init__("System Status", "📊", parent)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(3000)   # update every 3s
        self._refresh()

    def _build(self):
        cl = self.content_layout()
        self._stat_labels = {}

        stats = [
            ("cpu",    "CPU Usage",     "—"),
            ("mem",    "Memory Usage",  "—"),
            ("uptime", "System Uptime", "—"),
            ("os",     "OS",            platform.system() + " " + platform.release()),
        ]

        grid = QGridLayout()
        grid.setSpacing(6)

        for i, (key, label, value) in enumerate(stats):
            key_lbl = QLabel(label + ":")
            key_lbl.setStyleSheet(
                "color:#707080; font-size:9pt; background:transparent;"
            )
            val_lbl = QLabel(value)
            val_lbl.setStyleSheet(
                "color:#C0C0D0; font-size:9pt; font-weight:bold; background:transparent;"
            )
            grid.addWidget(key_lbl, i, 0)
            grid.addWidget(val_lbl, i, 1)
            self._stat_labels[key] = val_lbl

        cl.addLayout(grid)

    def _refresh(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.datetime.now() - boot_time
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            mins = remainder // 60

            self._stat_labels["cpu"].setText(f"{cpu:.1f}%")
            self._stat_labels["mem"].setText(
                f"{mem.percent:.1f}%  ({mem.used // (1024**3):.1f} / "
                f"{mem.total // (1024**3):.1f} GB)"
            )
            self._stat_labels["uptime"].setText(f"{hours}h {mins}m")

            cpu_color = "#FF4455" if cpu > 80 else "#FFAA00" if cpu > 60 else "#00CC88"
            self._stat_labels["cpu"].setStyleSheet(
                f"color:{cpu_color}; font-size:9pt; font-weight:bold; background:transparent;"
            )
        except ImportError:
            self._stat_labels["cpu"].setText("Install psutil for live stats")
            self._timer.stop()


class ProjectsCard(DashCard):
    """Recent projects list."""

    open_requested = pyqtSignal(str)   # path

    def __init__(self, config=None, parent=None):
        super().__init__("Recent Projects", "📁", parent)
        self.config = config
        self._build()
        self.refresh()

    def _build(self):
        cl = self.content_layout()
        self._rows = []
        self._no_projects = QLabel("No recent projects.")
        self._no_projects.setStyleSheet("color:#505060; font-size:9pt; padding:8px;")
        self._no_projects.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self._no_projects)

        new_btn = QPushButton("📂  New Project…")
        new_btn.setMinimumHeight(32)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cl.addWidget(new_btn)

    def refresh(self):
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()

        recents = []
        if self.config:
            recents = self.config.get("recent_projects", [])

        if not recents:
            self._no_projects.show()
            return

        self._no_projects.hide()
        for path in recents[:5]:
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 2, 0, 2)

            name = QLabel("📄  " + os.path.basename(path))
            name.setStyleSheet("color:#C0C0D0; font-size:9pt; background:transparent;")
            row_l.addWidget(name, 1)

            open_btn = QPushButton("Open")
            open_btn.setFixedWidth(54)
            open_btn.setFixedHeight(24)
            open_btn.setStyleSheet("font-size:8pt; padding:0;")
            open_btn.clicked.connect(lambda checked, p=path: self.open_requested.emit(p))
            row_l.addWidget(open_btn)

            self.content_layout().insertWidget(
                self.content_layout().count() - 1, row
            )
            self._rows.append(row)


# ── Dashboard panel ───────────────────────────────────────────────────────────

class DashboardPanel(QWidget):
    """
    HBCE Dashboard — home screen.
    Widgets can be reordered by the user via the Edit Dashboard Layout dialog.
    """

    request_panel = pyqtSignal(int)   # ask main window to switch panels

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user

        self._layout_config = self._load_layout()
        self._edit_mode     = False
        self._cards         = {}

        self._build_ui()
        self._start_refresh_timer()
        logger.debug("DashboardPanel initialized")

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panel header ──────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #1a1a30, stop:1 #12121e);"
            "border-bottom: 2px solid #00AAFF22;"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 0, 16, 0)

        title_lbl = QLabel("Dashboard")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet("color: #E0E0F0; background: transparent;")
        h_layout.addWidget(title_lbl)

        user = self.current_user.get("username","") if self.current_user else ""
        greet_lbl = QLabel(f"Welcome back, {user}")
        greet_lbl.setStyleSheet("color: #606070; font-size: 9pt; background: transparent;")
        h_layout.addWidget(greet_lbl)
        h_layout.addStretch()

        # Edit layout button
        self._edit_btn = QPushButton("✏️  Edit Layout")
        self._edit_btn.setFixedHeight(30)
        self._edit_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #3a3a5c;
                border-radius: 5px;
                color: #808090;
                font-size: 9pt;
                padding: 0 10px;
            }
            QPushButton:hover { border-color: #00AAFF; color: #00AAFF; }
        """)
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(self.enter_edit_mode)
        h_layout.addWidget(self._edit_btn)

        root.addWidget(header)

        # ── Scrollable widget area ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._canvas = QWidget()
        self._canvas.setStyleSheet("background: #12121e;")
        self._canvas_layout = QVBoxLayout(self._canvas)
        self._canvas_layout.setContentsMargins(16, 16, 16, 16)
        self._canvas_layout.setSpacing(12)

        scroll.setWidget(self._canvas)
        root.addWidget(scroll)

        self._rebuild_widgets()

    def _rebuild_widgets(self):
        """Build or rebuild widgets in the current layout order."""
        # Clear existing
        while self._canvas_layout.count():
            item = self._canvas_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        # Two-column grid
        grid = QGridLayout()
        grid.setSpacing(12)

        widget_factories = {
            W_QUICK_ACTIONS: self._make_quick_actions,
            W_DEVICES:       self._make_devices,
            W_ALARMS:        self._make_alarms,
            W_STATS:         self._make_stats,
            W_PROJECTS:      self._make_projects,
        }

        # Full-width widgets (span 2 columns)
        FULL_WIDTH = {W_QUICK_ACTIONS}

        row, col = 0, 0
        for widget_id in self._layout_config:
            factory = widget_factories.get(widget_id)
            if not factory:
                continue
            card = factory()
            if card is None:
                continue
            self._cards[widget_id] = card
            if widget_id in FULL_WIDTH:
                grid.addWidget(card, row, 0, 1, 2)
                row += 1
                col = 0
            else:
                grid.addWidget(card, row, col)
                col += 1
                if col >= 2:
                    col = 0
                    row += 1

        # Fill last column if odd number
        if col == 1:
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            grid.addWidget(spacer, row, 1)

        self._canvas_layout.addLayout(grid)
        self._canvas_layout.addStretch()

    def _make_quick_actions(self) -> DashCard:
        card = QuickActionsCard()
        card.action_requested.connect(self.request_panel.emit)
        return card

    def _make_devices(self) -> DashCard:
        card = DevicesCard(db=self.db)
        card.connect_requested.connect(self.request_panel.emit)
        return card

    def _make_alarms(self) -> DashCard:
        card = AlarmsCard(db=self.db)
        self._refresh_alarms(card)
        return card

    def _make_stats(self) -> DashCard:
        return StatsCard()

    def _make_projects(self) -> DashCard:
        card = ProjectsCard(config=self.config)
        return card

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _start_refresh_timer(self):
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._refresh_timer.start(10000)   # refresh every 10s

    def _periodic_refresh(self):
        if W_ALARMS in self._cards:
            self._refresh_alarms(self._cards[W_ALARMS])
        if W_PROJECTS in self._cards:
            self._cards[W_PROJECTS].refresh()

    def _refresh_alarms(self, card: AlarmsCard):
        if self.db:
            try:
                alarms = self.db.fetchall(
                    "SELECT * FROM alarms WHERE ack_state='unacknowledged' "
                    "ORDER BY timestamp DESC LIMIT 8"
                )
                card.refresh(alarms)
            except Exception as e:
                logger.warning(f"Dashboard alarm refresh failed: {e}")

    # ── Layout editing ─────────────────────────────────────────────────────────

    def enter_edit_mode(self):
        """Open the layout editor dialog."""
        dialog = DashboardLayoutEditor(self._layout_config, parent=self)
        if dialog.exec():
            self._layout_config = dialog.get_layout()
            self._save_layout()
            self._rebuild_widgets()

    def _load_layout(self) -> list:
        if self.config:
            saved = self.config.get("dashboard_layout")
            if saved and isinstance(saved, list):
                return saved
        return list(DEFAULT_LAYOUT)

    def _save_layout(self):
        if self.config:
            self.config.set_and_save("dashboard_layout", self._layout_config)


# ── Layout editor dialog ──────────────────────────────────────────────────────

WIDGET_NAMES = {
    W_QUICK_ACTIONS: "⚡  Quick Actions",
    W_DEVICES:       "🔌  Connected Devices",
    W_ALARMS:        "🔔  Recent Alarms",
    W_STATS:         "📊  System Status",
    W_PROJECTS:      "📁  Recent Projects",
}


class DashboardLayoutEditor(QDialog):
    """
    Dialog to reorder and show/hide dashboard widgets.
    Users drag items in the list to reorder, or uncheck to hide.
    """

    def __init__(self, current_layout: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Dashboard Layout")
        self.setMinimumSize(380, 360)
        self._layout = list(current_layout)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        desc = QLabel(
            "Drag items to reorder. Uncheck to hide a widget.\n"
            "Changes apply immediately after clicking OK."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #808090; font-size: 9pt;")
        root.addWidget(desc)

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setStyleSheet("""
            QListWidget { border: 1px solid #2a2a4e; border-radius:6px; background:#1e1e32; }
            QListWidget::item { padding: 8px; color: #C0C0D0; }
            QListWidget::item:selected { background:#252550; }
        """)

        # Add all widgets — checked if in current layout
        all_ids = list(WIDGET_NAMES.keys())
        ordered = self._layout + [w for w in all_ids if w not in self._layout]

        for widget_id in ordered:
            item = QListWidgetItem(WIDGET_NAMES.get(widget_id, widget_id))
            item.setData(Qt.ItemDataRole.UserRole, widget_id)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if widget_id in self._layout
                else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)

        root.addWidget(self._list)

        # Reset button
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setStyleSheet("background:transparent; color:#808090; border:1px solid #3a3a5c; padding:4px;")
        reset_btn.clicked.connect(self._reset)
        root.addWidget(reset_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _reset(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            widget_id = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(
                Qt.CheckState.Checked
                if widget_id in DEFAULT_LAYOUT
                else Qt.CheckState.Unchecked
            )

    def get_layout(self) -> list:
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result
