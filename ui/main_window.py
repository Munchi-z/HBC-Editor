"""
HBCE — Hybrid Controls Editor
ui/main_window.py — Main application window (redesigned V0.0.4-alpha)

Changes from V0.0.3-alpha:
  - Dashboard accessed via sidebar logo/header (index 0)
  - Sidebar only shows device panels (Connect, Point Browser, Custom Controller)
  - Tools menu bar now contains: Alarms, Trends, Program Editor,
    Backup/Restore, Scheduler, Reports
  - Panel headers more prominent (styled title bar per panel)
  - Connection status forwarded to sidebar
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QStatusBar, QLabel, QApplication, QMenuBar,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from version import VERSION, APP_FULL_NAME
from core.logger import get_logger
from ui.sidebar import Sidebar

from ui.panels.dashboard        import DashboardPanel
from ui.panels.connection_wizard import ConnectionWizardPanel
from ui.panels.point_browser    import PointBrowserPanel
from ui.panels.alarm_viewer     import AlarmViewerPanel
from ui.panels.trend_viewer     import TrendViewerPanel
from ui.panels.graphic_editor   import GraphicEditorPanel
from ui.panels.backup_restore   import BackupRestorePanel
from ui.panels.scheduler        import SchedulerPanel
from ui.panels.report_builder   import ReportBuilderPanel
from ui.panels.custom_controller import CustomControllerPanel

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """
    HBCE main window.

    Panel index map:
      0  Dashboard          ← sidebar logo/header click
      1  Connect Device     ← sidebar nav
      2  Point Browser      ← sidebar nav
      3  Alarm Viewer       ← Tools menu
      4  Trend Viewer       ← Tools menu
      5  Program Editor     ← Tools menu
      6  Backup / Restore   ← Tools menu
      7  Scheduler          ← Tools menu
      8  Reports            ← Tools menu
      9  Custom Controller  ← sidebar nav (Admin only)
    """

    # Panel index constants
    PANEL_DASHBOARD      = 0
    PANEL_CONNECTION     = 1
    PANEL_POINT_BROWSER  = 2
    PANEL_ALARM_VIEWER   = 3
    PANEL_TREND_VIEWER   = 4
    PANEL_GRAPHIC_EDITOR = 5
    PANEL_BACKUP_RESTORE = 6
    PANEL_SCHEDULER      = 7
    PANEL_REPORT_BUILDER = 8
    PANEL_CUSTOM_CTRL    = 9

    def __init__(self, config, db, theme_engine, current_user):
        super().__init__()
        self.config       = config
        self.db           = db
        self.theme_engine = theme_engine
        self.current_user = current_user

        self._build_ui()
        self._build_menu()
        self._build_statusbar()
        self._restore_window_state()
        logger.debug("MainWindow initialized")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle(
            f"{APP_FULL_NAME}  {VERSION}  —  "
            f"{self.current_user['username']} [{self.current_user['role']}]"
        )
        self.setMinimumSize(1000, 650)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(current_user=self.current_user)
        self.sidebar.panel_selected.connect(self._switch_panel)
        root.addWidget(self.sidebar)

        # Panel stack
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # Add all panels in index order
        panel_classes = [
            (self.PANEL_DASHBOARD,      DashboardPanel),
            (self.PANEL_CONNECTION,     ConnectionWizardPanel),
            (self.PANEL_POINT_BROWSER,  PointBrowserPanel),
            (self.PANEL_ALARM_VIEWER,   AlarmViewerPanel),
            (self.PANEL_TREND_VIEWER,   TrendViewerPanel),
            (self.PANEL_GRAPHIC_EDITOR, GraphicEditorPanel),
            (self.PANEL_BACKUP_RESTORE, BackupRestorePanel),
            (self.PANEL_SCHEDULER,      SchedulerPanel),
            (self.PANEL_REPORT_BUILDER, ReportBuilderPanel),
            (self.PANEL_CUSTOM_CTRL,    CustomControllerPanel),
        ]
        self.panels = {}
        for idx, PanelClass in panel_classes:
            panel = PanelClass(
                config=self.config,
                db=self.db,
                current_user=self.current_user,
            )
            # Give dashboard a reference back to switch panels
            if idx == self.PANEL_DASHBOARD:
                panel.request_panel.connect(self._switch_panel)
            self.panels[idx] = panel
            self.stack.addWidget(panel)

        self.stack.setCurrentIndex(self.PANEL_DASHBOARD)

    # ── Menu bar ──────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        # ── File ──────────────────────────────────────────────────────────
        file_menu = mb.addMenu("&File")

        new_proj = QAction("New Project", self)
        new_proj.setShortcut("Ctrl+N")
        file_menu.addAction(new_proj)

        open_proj = QAction("Open Project…", self)
        open_proj.setShortcut("Ctrl+O")
        file_menu.addAction(open_proj)

        save_proj = QAction("Save Project", self)
        save_proj.setShortcut("Ctrl+S")
        file_menu.addAction(save_proj)

        file_menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # ── View ──────────────────────────────────────────────────────────
        view_menu = mb.addMenu("&View")

        toggle_theme = QAction("Toggle Dark / Light Mode", self)
        toggle_theme.setShortcut("Ctrl+T")
        toggle_theme.triggered.connect(self._toggle_theme)
        view_menu.addAction(toggle_theme)

        custom_colors = QAction("Customize Colors…", self)
        custom_colors.triggered.connect(self._open_color_picker)
        view_menu.addAction(custom_colors)

        view_menu.addSeparator()

        toggle_sidebar = QAction("Toggle Sidebar", self)
        toggle_sidebar.setShortcut("Ctrl+B")
        toggle_sidebar.triggered.connect(
            lambda: self.sidebar.setVisible(not self.sidebar.isVisible())
        )
        view_menu.addAction(toggle_sidebar)

        view_menu.addSeparator()

        # Dashboard layout editor
        edit_dashboard = QAction("Edit Dashboard Layout…", self)
        edit_dashboard.setShortcut("Ctrl+D")
        edit_dashboard.triggered.connect(self._edit_dashboard_layout)
        view_menu.addAction(edit_dashboard)

        # ── Tools — all module panels live here ───────────────────────────
        tools_menu = mb.addMenu("&Tools")

        conn_act = QAction("🔌  Connection Wizard…", self)
        conn_act.setShortcut("Ctrl+W")
        conn_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_CONNECTION)
        )
        tools_menu.addAction(conn_act)

        pb_act = QAction("📋  Point Browser", self)
        pb_act.setShortcut("Ctrl+P")
        pb_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_POINT_BROWSER)
        )
        tools_menu.addAction(pb_act)

        tools_menu.addSeparator()

        alarm_act = QAction("🔔  Alarm Viewer", self)
        alarm_act.setShortcut("Ctrl+A")
        alarm_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_ALARM_VIEWER)
        )
        tools_menu.addAction(alarm_act)

        trend_act = QAction("📈  Trend Viewer", self)
        trend_act.setShortcut("Ctrl+R")
        trend_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_TREND_VIEWER)
        )
        tools_menu.addAction(trend_act)

        tools_menu.addSeparator()

        prog_act = QAction("🧠  Program Editor", self)
        prog_act.setShortcut("Ctrl+E")
        prog_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_GRAPHIC_EDITOR)
        )
        tools_menu.addAction(prog_act)

        sched_act = QAction("📅  Scheduler", self)
        sched_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_SCHEDULER)
        )
        tools_menu.addAction(sched_act)

        tools_menu.addSeparator()

        backup_act = QAction("💾  Backup / Restore", self)
        backup_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_BACKUP_RESTORE)
        )
        tools_menu.addAction(backup_act)

        report_act = QAction("📄  Reports", self)
        report_act.triggered.connect(
            lambda: self._switch_panel(self.PANEL_REPORT_BUILDER)
        )
        tools_menu.addAction(report_act)

        # ── Help ──────────────────────────────────────────────────────────
        help_menu = mb.addMenu("&Help")

        about_act = QAction(f"About {APP_FULL_NAME}", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

        update_act = QAction("Check for Updates…", self)
        update_act.triggered.connect(self._check_updates)
        help_menu.addAction(update_act)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.status_conn = QLabel("  ⚫  Not Connected")
        sb.addWidget(self.status_conn)

        sb.addPermanentWidget(QLabel("  |  "))

        self.status_user = QLabel(
            f"  👤  {self.current_user['username']}  [{self.current_user['role']}]"
        )
        sb.addPermanentWidget(self.status_user)

        sb.addPermanentWidget(QLabel("  |  "))

        sb.addPermanentWidget(QLabel(f"  HBCE {VERSION}  "))

    # ── Panel switching ───────────────────────────────────────────────────────

    def _switch_panel(self, index: int):
        if not self._user_can_access(index):
            self.statusBar().showMessage(
                "⚠  Your role does not have access to this module.", 4000
            )
            return
        self.stack.setCurrentIndex(index)
        self.sidebar.set_active(index)
        logger.debug(f"Switched to panel {index}")

    def _user_can_access(self, panel_index: int) -> bool:
        role = self.current_user.get("role", "Operator")
        if role in ("Admin", "Technician"):
            return True
        # Operator: only dashboard, point browser (read), alarms, trends, reports
        OPERATOR_OK = {
            self.PANEL_DASHBOARD,
            self.PANEL_POINT_BROWSER,
            self.PANEL_ALARM_VIEWER,
            self.PANEL_TREND_VIEWER,
            self.PANEL_REPORT_BUILDER,
        }
        return panel_index in OPERATOR_OK

    # ── Actions ───────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        self.theme_engine.toggle_mode(QApplication.instance())

    def _open_color_picker(self):
        self.theme_engine.open_color_picker(QApplication.instance(), parent=self)

    def _edit_dashboard_layout(self):
        """Tell the dashboard panel to enter layout-edit mode."""
        self._switch_panel(self.PANEL_DASHBOARD)
        dashboard = self.panels.get(self.PANEL_DASHBOARD)
        if dashboard and hasattr(dashboard, "enter_edit_mode"):
            dashboard.enter_edit_mode()

    def _show_about(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self, f"About {APP_FULL_NAME}",
            f"<h2>HBCE — Hybrid Controls Editor</h2>"
            f"<p>Version: <b>{VERSION}</b></p>"
            f"<p>Universal BAS controller configuration, monitoring, and programming.</p>"
            f"<p>Vendors: Johnson Controls Metasys, Trane Tracer, Distech ECLYPSE</p>"
            f"<p>Protocols: BACnet/IP, BACnet MS/TP, USB, Modbus TCP/RTU</p>"
            f"<p><a href='https://github.com/Munchi-z/HBC-Editor'>GitHub</a></p>",
        )

    def _check_updates(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Check for Updates",
            f"You are running HBCE {VERSION}.\n\n"
            f"Visit github.com/Munchi-z/HBC-Editor/releases\n"
            f"to check for newer versions.",
        )

    def set_connection_status(self, connected: bool, device_name: str = ""):
        """Update both status bar and sidebar connection indicator."""
        if connected:
            self.status_conn.setText(f"  🟢  Connected: {device_name}")
        else:
            self.status_conn.setText("  ⚫  Not Connected")
        self.sidebar.set_connection_status(connected, device_name)

    # ── Window state ──────────────────────────────────────────────────────────

    def _restore_window_state(self):
        w = self.config.get("window_width", 1400)
        h = self.config.get("window_height", 900)
        self.resize(w, h)
        if self.config.get("window_maximized", False):
            self.showMaximized()

    def closeEvent(self, event):
        self.config.set("window_maximized", self.isMaximized())
        if not self.isMaximized():
            self.config.set("window_width", self.width())
            self.config.set("window_height", self.height())
        self.config.save()
        logger.info("HBCE closing")
        super().closeEvent(event)
