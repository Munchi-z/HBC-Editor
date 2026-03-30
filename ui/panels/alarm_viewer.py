"""
HBCE — Hybrid Controls Editor
ui/panels/alarm_viewer.py — 🔔 Alarm Viewer

View and acknowledge active alarms from all devices.

STATUS: V0.0.4-alpha STUB — Full implementation in subsequent build steps.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from core.logger import get_logger

logger = get_logger(__name__)


class AlarmViewerPanel(QWidget):
    """
    🔔 Alarm Viewer
    View and acknowledge active alarms from all devices.
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.current_user = current_user
        self._build_ui()
        logger.debug(f"AlarmViewerPanel initialized")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Panel header
        header_layout = QHBoxLayout()

        title_label = QLabel("🔔 Alarm Viewer")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Description
        desc_label = QLabel("View and acknowledge active alarms from all devices.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #808090; font-size: 10pt;")
        layout.addWidget(desc_label)

        # Coming soon notice (remove when panel is implemented)
        notice_frame = QFrame()
        notice_layout = QVBoxLayout(notice_frame)
        notice_layout.setContentsMargins(24, 24, 24, 24)

        notice_icon = QLabel("🚧")
        notice_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice_font = QFont()
        notice_font.setPointSize(32)
        notice_icon.setFont(notice_font)
        notice_layout.addWidget(notice_icon)

        notice_text = QLabel("Coming in V0.0.4-alpha — full build in progress.")
        notice_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice_text.setStyleSheet("color: #808090; font-size: 11pt;")
        notice_layout.addWidget(notice_text)

        layout.addWidget(notice_frame)
        layout.addStretch()
