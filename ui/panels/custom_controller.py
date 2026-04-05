# ui/panels/custom_controller.py
# HBCE — Hybrid Controls Editor
# Custom Controller Panel — Placeholder V0.1.9a-alpha
#
# Reserved for future: drag-and-drop custom BACnet/Modbus controller config,
# hardware I/O mapping, and virtual device simulation.

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.logger import get_logger

logger = get_logger(__name__)


class CustomControllerPanel(QWidget):
    """
    🛠 Custom Controller Panel — Coming Soon.
    Placeholder widget so the panel can be navigated to without crashing.
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user or {}
        self._build_ui()
        logger.debug("CustomControllerPanel initialized (placeholder)")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Dark background matching the rest of the app
        self.setStyleSheet("background: #13131F;")

        icon = QLabel("🛠")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 48pt; background: transparent;")
        root.addWidget(icon)

        title = QLabel("Custom Controller")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #C0C0D0; background: transparent; margin-top: 8px;")
        root.addWidget(title)

        badge = QLabel("Coming Soon")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "color: #5C8AFF; background: #1a1a35; border: 1px solid #3a3a6a; "
            "border-radius: 10px; padding: 4px 16px; font-size: 9pt; "
            "font-weight: bold; margin: 8px 0;"
        )
        badge.setFixedWidth(120)
        root.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)

        desc = QLabel(
            "Drag-and-drop custom BACnet / Modbus controller\n"
            "configuration, hardware I/O mapping, and\n"
            "virtual device simulation."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #505060; font-size: 9pt; background: transparent; margin-top: 4px;")
        desc.setWordWrap(True)
        root.addWidget(desc)
