"""
HBCE — Hybrid Controls Editor
ui/sidebar.py — Left navigation sidebar (redesigned V0.0.2-alpha)

Changes from V0.0.1:
  - HBCE logo + header is now the Dashboard home button
  - Tools modules (reports, scheduler, etc.) moved to top menu bar
  - Sidebar now shows device-focused nav only
  - Hex Vortex SVG logo embedded directly
  - Connection status indicator added
  - Collapse/expand toggle added
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QSizePolicy, QFrame, QSpacerItem, QHBoxLayout,
    QToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtCore import QByteArray

from core.logger import get_logger

logger = get_logger(__name__)

# ── SVG logo embedded directly (no file dependency) ──────────────────────────
HEX_VORTEX_SVG = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'>
  <defs><clipPath id='hc'><polygon points='100,18 172,57.5 172,142.5 100,182 28,142.5 28,57.5'/></clipPath></defs>
  <polygon points='100,18 172,57.5 172,142.5 100,182 28,142.5 28,57.5' fill='#10101e' stroke='#3A3A5C' stroke-width='2.5'/>
  <g clip-path='url(#hc)'>
    <path d='M100,100 L136,46 A56,56,0,0,1,168,80 Z' fill='#C04828'/><path d='M100,100 L136,46 A56,56,0,0,1,168,80 Z' fill='#F2A623' opacity='.3'/>
    <path d='M100,100 L154,136 A56,56,0,0,1,120,168 Z' fill='#0C447C'/><path d='M100,100 L154,136 A56,56,0,0,1,120,168 Z' fill='#3B8BD4' opacity='.3'/>
    <path d='M100,100 L64,154 A56,56,0,0,1,32,120 Z' fill='#C04828'/><path d='M100,100 L64,154 A56,56,0,0,1,32,120 Z' fill='#F2A623' opacity='.3'/>
    <path d='M100,100 L46,64 A56,56,0,0,1,80,32 Z' fill='#0C447C'/><path d='M100,100 L46,64 A56,56,0,0,1,80,32 Z' fill='#3B8BD4' opacity='.3'/>
  </g>
  <g stroke='white' stroke-width='1.2' stroke-linecap='round' opacity='.35'>
    <line x1='72' y1='34' x2='128' y2='34'/><line x1='62' y1='46' x2='138' y2='46'/>
    <line x1='62' y1='154' x2='138' y2='154'/><line x1='72' y1='166' x2='128' y2='166'/>
  </g>
  <circle cx='100' cy='100' r='24' fill='#10101e' stroke='#444' stroke-width='2'/>
  <circle cx='100' cy='100' r='15' fill='#1a1a2e'/>
  <path d='M100,85 A15,15,0,0,1,100,115 Z' fill='#E85D24'/>
  <path d='M100,85 A15,15,0,0,0,100,115 Z' fill='#185FA5'/>
  <circle cx='100' cy='18' r='4.5' fill='#F2A623'/>
  <circle cx='172' cy='57.5' r='4.5' fill='#E85D24'/>
  <circle cx='172' cy='142.5' r='4.5' fill='#3B8BD4'/>
  <circle cx='100' cy='182' r='4.5' fill='#185FA5'/>
  <circle cx='28' cy='142.5' r='4.5' fill='#3B8BD4'/>
  <circle cx='28' cy='57.5' r='4.5' fill='#E85D24'/>
  <polygon points='100,18 172,57.5 172,142.5 100,182 28,142.5 28,57.5' fill='none' stroke='white' stroke-width='1.5' opacity='.18'/>
</svg>"""

# ── Sidebar nav items (device-focused only — tools moved to menu bar) ─────────
NAV_ITEMS = [
    (1,  "🔌",  "Connect Device",     ["Admin", "Technician"]),
    (2,  "📋",  "Point Browser",      ["Admin", "Technician", "Operator"]),
    (9,  "🧱",  "Custom Controller",  ["Admin"]),
]


class Sidebar(QWidget):
    """
    Left navigation sidebar.
    - Logo + HBCE header acts as Dashboard home button
    - Only device-focused panels remain in sidebar
    - Tools panels accessed via top menu bar
    """

    panel_selected = pyqtSignal(int)   # 0 = dashboard, 1+ = panels

    def __init__(self, current_user: dict, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.role = current_user.get("role", "Operator")
        self._buttons = {}
        self._active_index = 0
        self._collapsed = False

        self.setObjectName("Sidebar")
        self._full_width    = 220
        self._compact_width = 52
        self.setFixedWidth(self._full_width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Logo + title header = Dashboard home button ───────────────────
        self._header_btn = QPushButton()
        self._header_btn.setObjectName("SidebarHeader")
        self._header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_btn.setToolTip("Dashboard — Home")
        self._header_btn.clicked.connect(lambda: self._on_button_clicked(0))
        self._header_btn.setFixedHeight(90)
        self._header_btn.setStyleSheet("""
            QPushButton#SidebarHeader {
                background-color: transparent;
                border: none;
                border-bottom: 1px solid #2a2a3e;
                padding: 0;
            }
            QPushButton#SidebarHeader:hover {
                background-color: rgba(0, 170, 255, 0.08);
            }
            QPushButton#SidebarHeader:pressed {
                background-color: rgba(0, 170, 255, 0.15);
            }
        """)

        # Header inner layout
        header_inner = QWidget()
        header_inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        h_layout = QHBoxLayout(header_inner)
        h_layout.setContentsMargins(10, 8, 10, 8)
        h_layout.setSpacing(10)

        # SVG logo
        self._logo_widget = QSvgWidget()
        self._logo_widget.load(QByteArray(HEX_VORTEX_SVG))
        self._logo_widget.setFixedSize(52, 52)
        self._logo_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        h_layout.addWidget(self._logo_widget)

        # Title text
        self._title_widget = QWidget()
        self._title_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout = QVBoxLayout(self._title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        name_label = QLabel("HBCE")
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet("color: #00AAFF; background: transparent;")
        title_layout.addWidget(name_label)

        sub_label = QLabel("Hybrid Controls Editor")
        sub_label.setStyleSheet("color: #606070; font-size: 8pt; background: transparent;")
        title_layout.addWidget(sub_label)

        h_layout.addWidget(self._title_widget)
        h_layout.addStretch()

        # Stack header inner on top of button using layout trick
        header_container = QWidget()
        header_container.setFixedHeight(90)
        hc_layout = QVBoxLayout(header_container)
        hc_layout.setContentsMargins(0, 0, 0, 0)
        hc_layout.addWidget(self._header_btn)

        # Overlay the inner widget
        header_inner.setParent(self._header_btn)
        header_inner.setGeometry(0, 0, self._full_width, 90)
        header_inner.show()

        layout.addWidget(header_container)

        # ── Collapse/expand toggle ────────────────────────────────────────
        self._toggle_row = QWidget()
        toggle_layout = QHBoxLayout(self._toggle_row)
        toggle_layout.setContentsMargins(8, 4, 8, 4)
        toggle_layout.addStretch()
        self._collapse_btn = QToolButton()
        self._collapse_btn.setText("◀")
        self._collapse_btn.setToolTip("Collapse sidebar")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setStyleSheet("""
            QToolButton { background: transparent; border: none;
                          color: #505060; font-size: 10pt; padding: 2px 4px; }
            QToolButton:hover { color: #00AAFF; }
        """)
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        toggle_layout.addWidget(self._collapse_btn)
        layout.addWidget(self._toggle_row)

        # ── Section label ─────────────────────────────────────────────────
        self._section_label = QLabel("  DEVICES")
        self._section_label.setStyleSheet(
            "color: #404050; font-size: 7pt; font-weight: bold; "
            "letter-spacing: 1px; padding: 8px 12px 4px;"
        )
        layout.addWidget(self._section_label)

        # ── Nav buttons ───────────────────────────────────────────────────
        self._nav_container = QWidget()
        nav_layout = QVBoxLayout(self._nav_container)
        nav_layout.setContentsMargins(8, 0, 8, 0)
        nav_layout.setSpacing(3)

        for panel_idx, icon, label, allowed_roles in NAV_ITEMS:
            if self.role not in allowed_roles:
                continue
            btn = QPushButton(f"  {icon}  {label}")
            btn.setObjectName("SidebarButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setProperty("active", False)
            btn.setToolTip(label)
            btn.clicked.connect(
                lambda checked, idx=panel_idx: self._on_button_clicked(idx)
            )
            self._buttons[panel_idx] = btn
            nav_layout.addWidget(btn)

        layout.addWidget(self._nav_container)

        # ── Spacer ────────────────────────────────────────────────────────
        layout.addSpacerItem(QSpacerItem(
            0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        ))

        # ── Separator ─────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #2a2a3e; margin: 0 8px;")
        layout.addWidget(sep)

        # ── Connection status ─────────────────────────────────────────────
        self._conn_label = QLabel("  ⚫  Not Connected")
        self._conn_label.setStyleSheet(
            "color: #505060; font-size: 8pt; padding: 6px 12px;"
        )
        layout.addWidget(self._conn_label)

        # ── User info ─────────────────────────────────────────────────────
        self._user_label = QLabel(
            f"  👤  {self.current_user.get('username','User')}\n"
            f"       {self.role}"
        )
        self._user_label.setStyleSheet(
            "color: #505060; font-size: 8pt; padding: 4px 12px 10px;"
        )
        layout.addWidget(self._user_label)

        # Set initial active
        self.set_active(0)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_button_clicked(self, panel_index: int):
        self.set_active(panel_index)
        self.panel_selected.emit(panel_index)

    def set_active(self, panel_index: int):
        """Highlight the active nav button. Index 0 = dashboard (header btn)."""
        # Clear previous
        for idx, btn in self._buttons.items():
            btn.setProperty("active", False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self._active_index = panel_index

        # Highlight header if dashboard
        if panel_index == 0:
            self._header_btn.setStyleSheet("""
                QPushButton#SidebarHeader {
                    background-color: rgba(0,170,255,0.12);
                    border: none;
                    border-bottom: 2px solid #00AAFF;
                    border-left: 3px solid #00AAFF;
                    padding: 0;
                }
                QPushButton#SidebarHeader:hover {
                    background-color: rgba(0, 170, 255, 0.18);
                }
            """)
        else:
            self._header_btn.setStyleSheet("""
                QPushButton#SidebarHeader {
                    background-color: transparent;
                    border: none;
                    border-bottom: 1px solid #2a2a3e;
                    padding: 0;
                }
                QPushButton#SidebarHeader:hover {
                    background-color: rgba(0, 170, 255, 0.08);
                }
            """)

        if panel_index in self._buttons:
            btn = self._buttons[panel_index]
            btn.setProperty("active", True)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_connection_status(self, connected: bool, device_name: str = ""):
        """Update the connection indicator at the bottom of the sidebar."""
        if connected:
            self._conn_label.setText(f"  🟢  {device_name}")
            self._conn_label.setStyleSheet(
                "color: #00CC88; font-size: 8pt; padding: 6px 12px;"
            )
        else:
            self._conn_label.setText("  ⚫  Not Connected")
            self._conn_label.setStyleSheet(
                "color: #505060; font-size: 8pt; padding: 6px 12px;"
            )

    def _toggle_collapse(self):
        """Collapse or expand the sidebar."""
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.setFixedWidth(self._compact_width)
            self._title_widget.hide()
            self._section_label.hide()
            self._user_label.hide()
            self._conn_label.hide()
            self._collapse_btn.setText("▶")
            self._collapse_btn.setToolTip("Expand sidebar")
            for btn in self._buttons.values():
                text = btn.text().strip()
                # Show only the emoji
                parts = text.split("  ")
                btn.setText(parts[1] if len(parts) > 1 else text[:2])
        else:
            self.setFixedWidth(self._full_width)
            self._title_widget.show()
            self._section_label.show()
            self._user_label.show()
            self._conn_label.show()
            self._collapse_btn.setText("◀")
            self._collapse_btn.setToolTip("Collapse sidebar")
            for idx, btn in self._buttons.items():
                for item in NAV_ITEMS:
                    if item[0] == idx:
                        btn.setText(f"  {item[1]}  {item[2]}")
                        break
