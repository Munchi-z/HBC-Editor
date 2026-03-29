"""
HBCE — Hybrid Controls Editor
ui/sidebar.py — Left navigation sidebar

Emits panel_selected(int) signal when user clicks a nav item.
Active item is highlighted with accent color.
Role-based items are hidden for Operator.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QSizePolicy, QFrame, QSpacerItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont

from core.logger import get_logger

logger = get_logger(__name__)


NAV_ITEMS = [
    # (panel_index, icon_text, label, roles_allowed)
    (0,  "🏠",  "Dashboard",          ["Admin", "Technician", "Operator"]),
    (1,  "🔌",  "Connect Device",     ["Admin", "Technician"]),
    (2,  "📋",  "Point Browser",      ["Admin", "Technician", "Operator"]),
    (3,  "🔔",  "Alarm Viewer",       ["Admin", "Technician", "Operator"]),
    (4,  "📈",  "Trend Viewer",       ["Admin", "Technician", "Operator"]),
    (5,  "🧠",  "Program Editor",     ["Admin", "Technician"]),
    (6,  "💾",  "Backup / Restore",   ["Admin", "Technician"]),
    (7,  "📅",  "Scheduler",          ["Admin", "Technician"]),
    (8,  "📄",  "Reports",            ["Admin", "Technician", "Operator"]),
    (9,  "🧱",  "Custom Controller",  ["Admin"]),
]


class Sidebar(QWidget):
    """Left navigation panel with role-filtered module buttons."""

    panel_selected = pyqtSignal(int)

    def __init__(self, current_user: dict, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.role = current_user.get("role", "Operator")
        self._buttons = {}      # panel_index → QPushButton
        self._active_index = 0

        self.setObjectName("Sidebar")
        self.setFixedWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)

        # App name / logo area
        logo_label = QLabel("⚡ HBCE")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_font = QFont()
        logo_font.setPointSize(16)
        logo_font.setBold(True)
        logo_label.setFont(logo_font)
        logo_label.setStyleSheet("color: #00AAFF; padding: 8px 0 4px 0;")
        layout.addWidget(logo_label)

        sub_label = QLabel("Hybrid Controls Editor")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setStyleSheet("color: #808090; font-size: 8pt; padding-bottom: 12px;")
        layout.addWidget(sub_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #3A3A5C;")
        layout.addWidget(sep)
        layout.addSpacing(8)

        # Navigation buttons
        for panel_idx, icon, label, allowed_roles in NAV_ITEMS:
            if self.role not in allowed_roles:
                continue  # Hide items this role can't access

            btn = QPushButton(f"  {icon}  {label}")
            btn.setObjectName("SidebarButton")
            btn.setCheckable(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setProperty("active", False)
            btn.clicked.connect(
                lambda checked, idx=panel_idx: self._on_button_clicked(idx)
            )

            self._buttons[panel_idx] = btn
            layout.addWidget(btn)

        # Spacer pushes remaining items to bottom
        layout.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        # Bottom separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("border: 1px solid #3A3A5C;")
        layout.addWidget(sep2)
        layout.addSpacing(4)

        # User info at bottom
        user_label = QLabel(
            f"👤  {self.current_user.get('username', 'User')}\n"
            f"    {self.role}"
        )
        user_label.setStyleSheet("color: #808090; font-size: 8pt; padding: 4px;")
        layout.addWidget(user_label)

        # Set initial active state
        self.set_active(0)

    def _on_button_clicked(self, panel_index: int):
        self.set_active(panel_index)
        self.panel_selected.emit(panel_index)
        logger.debug(f"Sidebar: panel {panel_index} selected")

    def set_active(self, panel_index: int):
        """Highlight the active navigation button."""
        # Clear previous active
        if self._active_index in self._buttons:
            btn = self._buttons[self._active_index]
            btn.setProperty("active", False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self._active_index = panel_index

        # Set new active
        if panel_index in self._buttons:
            btn = self._buttons[panel_index]
            btn.setProperty("active", True)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
