"""
HBCE — Hybrid Controls Editor
ui/main_window.py — Main application window

The top-level QMainWindow.
Contains: Menu bar, Sidebar navigation, Central panel stack, Status bar.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QLabel, QSizePolicy, QMenuBar, QMenu,
    QStatusBar, QToolButton, QApplication,
)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QAction, QFont

from version import VERSION, APP_FULL_NAME
from core.logger import get_logger
from ui.sidebar import Sidebar

# Panel imports (all stubs at V0.0.1 — fully implemented in later steps)
from ui.panels.dashboard import DashboardPanel
from ui.panels.connection_wizard import ConnectionWizardPanel
from ui.panels.point_browser import PointBrowserPanel
from ui.panels.alarm_viewer import AlarmViewerPanel
from ui.panels.trend_viewer import TrendViewerPanel
from ui.panels.graphic_editor import GraphicEditorPanel
from ui.panels.backup_restore import BackupRestorePanel
from ui.panels.scheduler import SchedulerPanel
from ui.panels.report_builder import ReportBuilderPanel
from ui.panels.custom_controller import CustomControllerPanel

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """
    HBCE main window.
    Sidebar on the left drives which panel is shown in the center stack.
    """

    # Panel index constants — keep in sync with sidebar items
    PANEL_DASHBOARD        = 0
    PANEL_CONNECTION       = 1
    PANEL_POINT_BROWSER    = 2
    PANEL_ALARM_VIEWER     = 3
    PANEL_TREND_VIEWER     = 4
    PANEL_GRAPHIC_EDITOR   = 5
    PANEL_BACKUP_RESTORE   = 6
    PANEL_SCHEDULER        = 7
    PANEL_REPORT_BUILDER   = 8
    PANEL_CUSTOM_CTRL      = 9

    def __init__(self, config, db, theme_engine, current_user):
        super().__init__()
        self.config = config
        self.db = db
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

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(current_user=self.current_user)
        self.sidebar.panel_selected.connect(self._switch_panel)
        root_layout.addWidget(self.sidebar)

        # Panel stack
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        # Instantiate and add all panels
        self.panels = {}
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

        for idx, PanelClass in panel_classes:
            panel = PanelClass(
                config=self.config,
                db=self.db,
                current_user=self.current_user,
            )
            self.panels[idx] = panel
            self.stack.addWidget(panel)

        # Start on dashboard
        self.stack.setCurrentIndex(self.PANEL_DASHBOARD)

    def _build_menu(self):
        """Build the top menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
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

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")
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
        toggle_sidebar.triggered.connect(self._toggle_sidebar)
        view_menu.addAction(toggle_sidebar)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        conn_wizard = QAction("Connection Wizard…", self)
        conn_wizard.triggered.connect(
            lambda: self._switch_panel(self.PANEL_CONNECTION)
        )
        tools_menu.addAction(conn_wizard)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about = QAction(f"About {APP_FULL_NAME}", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

        check_update = QAction("Check for Updates…", self)
        check_update.triggered.connect(self._check_updates)
        help_menu.addAction(check_update)

    def _build_statusbar(self):
        """Build the bottom status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Connection status
        self.status_conn = QLabel("  ⚫  Not Connected")
        self.status_conn.setObjectName("StatusConn")
        self.status_bar.addWidget(self.status_conn)

        self.status_bar.addPermanentWidget(QLabel("  |  "))

        # User / role
        self.status_user = QLabel(
            f"  👤  {self.current_user['username']}  [{self.current_user['role']}]"
        )
        self.status_bar.addPermanentWidget(self.status_user)

        self.status_bar.addPermanentWidget(QLabel("  |  "))

        # Version
        self.status_version = QLabel(f"  HBCE {VERSION}  ")
        self.status_bar.addPermanentWidget(self.status_version)

    # ── Panel Switching ───────────────────────────────────────────────────────

    def _switch_panel(self, index: int):
        """Switch the visible panel in the center stack."""
        # Permission check
        if not self._user_can_access(index):
            self.status_bar.showMessage(
                "⚠  Your role does not have access to this module.", 4000
            )
            return

        self.stack.setCurrentIndex(index)
        self.sidebar.set_active(index)
        logger.debug(f"Switched to panel {index}")

    def _user_can_access(self, panel_index: int) -> bool:
        """
        Check if the current user's role allows access to this panel.
        Operator cannot access graphic editor, backup/restore, scheduler.
        Full permission system wired through DB in later step.
        """
        role = self.current_user.get("role", "Operator")
        if role == "Admin":
            return True
        if role == "Technician":
            return True  # Technicians access all panels for now
        # Operator restrictions
        OPERATOR_BLOCKED = {
            self.PANEL_CONNECTION,
            self.PANEL_GRAPHIC_EDITOR,
            self.PANEL_BACKUP_RESTORE,
            self.PANEL_SCHEDULER,
            self.PANEL_CUSTOM_CTRL,
        }
        return panel_index not in OPERATOR_BLOCKED

    # ── Actions ───────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        self.theme_engine.toggle_mode(QApplication.instance())
        logger.info("Theme toggled")

    def _open_color_picker(self):
        self.theme_engine.open_color_picker(QApplication.instance(), parent=self)

    def _toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def _show_about(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            f"About {APP_FULL_NAME}",
            f"<h2>HBCE — Hybrid Controls Editor</h2>"
            f"<p>Version: <b>{VERSION}</b></p>"
            f"<p>Universal BAS controller configuration, monitoring, and programming tool.</p>"
            f"<p>Supports: Johnson Controls Metasys, Trane Tracer, Distech ECLYPSE, "
            f"and generic BACnet/Modbus devices.</p>"
            f"<p>Protocols: BACnet/IP, BACnet MS/TP, USB, Modbus TCP/RTU</p>",
        )

    def _check_updates(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Check for Updates",
            f"You are running HBCE {VERSION}.\n\n"
            f"To update, visit the HBCE website and download the latest installer.\n"
            f"Updates are installed manually.",
        )

    # ── Window State ──────────────────────────────────────────────────────────

    def _restore_window_state(self):
        w = self.config.get("window_width", 1400)
        h = self.config.get("window_height", 900)
        self.resize(w, h)
        if self.config.get("window_maximized", False):
            self.showMaximized()

    def closeEvent(self, event):
        """Save window state on close."""
        self.config.set("window_maximized", self.isMaximized())
        if not self.isMaximized():
            self.config.set("window_width", self.width())
            self.config.set("window_height", self.height())
        self.config.save()
        logger.info("HBCE closing")
        super().closeEvent(event)

    def set_connection_status(self, connected: bool, device_name: str = ""):
        """Update the connection status in the status bar."""
        if connected:
            self.status_conn.setText(f"  🟢  Connected: {device_name}")
        else:
            self.status_conn.setText("  ⚫  Not Connected")
