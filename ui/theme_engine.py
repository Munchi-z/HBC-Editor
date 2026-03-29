"""
HBCE — Hybrid Controls Editor
ui/theme_engine.py — Theme engine

Handles:
  - Dark / Light mode toggle
  - User-customizable accent, background, text, border colors
  - Font family + size
  - QSS generation and application
  - Saving/loading user theme from config
"""

import json
import os
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QColorDialog, QGroupBox,
    QFormLayout, QDialogButtonBox, QFrame,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

from core.logger import get_logger

logger = get_logger(__name__)


# ─── Built-in theme palettes ─────────────────────────────────────────────────

DARK_DEFAULT = {
    "mode": "dark",
    "bg_primary":    "#1E1E2E",
    "bg_secondary":  "#2A2A3E",
    "bg_panel":      "#252535",
    "bg_input":      "#1A1A28",
    "accent":        "#00AAFF",
    "accent_hover":  "#0088CC",
    "accent_press":  "#006699",
    "text_primary":  "#E0E0E0",
    "text_secondary":"#A0A0B0",
    "text_disabled": "#606070",
    "border":        "#3A3A5C",
    "border_focus":  "#00AAFF",
    "success":       "#00CC88",
    "warning":       "#FFAA00",
    "error":         "#FF4455",
    "font_family":   "Segoe UI",
    "font_size":     10,
}

LIGHT_DEFAULT = {
    "mode": "light",
    "bg_primary":    "#F5F5F5",
    "bg_secondary":  "#EBEBEB",
    "bg_panel":      "#FFFFFF",
    "bg_input":      "#FFFFFF",
    "accent":        "#0078D4",
    "accent_hover":  "#006ABE",
    "accent_press":  "#005BA8",
    "text_primary":  "#1A1A1A",
    "text_secondary":"#555555",
    "text_disabled": "#AAAAAA",
    "border":        "#CCCCCC",
    "border_focus":  "#0078D4",
    "success":       "#00875A",
    "warning":       "#C86400",
    "error":         "#D32F2F",
    "font_family":   "Segoe UI",
    "font_size":     10,
}


# ─── QSS template ────────────────────────────────────────────────────────────

def build_qss(c: dict) -> str:
    """Generate a complete QSS stylesheet from a color dictionary."""
    return f"""
/* ── HBCE Global Stylesheet ── */

QMainWindow, QDialog, QWidget {{
    background-color: {c['bg_primary']};
    color: {c['text_primary']};
    font-family: "{c['font_family']}";
    font-size: {c['font_size']}pt;
}}

/* ── Panels / Frames ── */
QFrame, QGroupBox {{
    background-color: {c['bg_secondary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
}}
QGroupBox::title {{
    color: {c['accent']};
    font-weight: bold;
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {c['accent']};
    color: #FFFFFF;
    border: none;
    border-radius: 5px;
    padding: 6px 16px;
    font-weight: bold;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {c['accent_hover']};
}}
QPushButton:pressed {{
    background-color: {c['accent_press']};
}}
QPushButton:disabled {{
    background-color: {c['border']};
    color: {c['text_disabled']};
}}
QPushButton[flat="true"], QPushButton.secondary {{
    background-color: transparent;
    color: {c['accent']};
    border: 1px solid {c['accent']};
}}
QPushButton[flat="true"]:hover, QPushButton.secondary:hover {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {c['bg_input']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 26px;
    selection-background-color: {c['accent']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1.5px solid {c['border_focus']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    selection-background-color: {c['accent']};
    border: 1px solid {c['border']};
}}

/* ── Tables ── */
QTableWidget, QTableView, QTreeWidget, QTreeView {{
    background-color: {c['bg_panel']};
    alternate-background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    gridline-color: {c['border']};
    border: 1px solid {c['border']};
    border-radius: 4px;
}}
QHeaderView::section {{
    background-color: {c['bg_secondary']};
    color: {c['text_secondary']};
    border: none;
    border-bottom: 2px solid {c['accent']};
    padding: 4px 8px;
    font-weight: bold;
}}
QTableWidget::item:selected, QTableView::item:selected,
QTreeWidget::item:selected, QTreeView::item:selected {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}

/* ── Tab Bar ── */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 0 4px 4px 4px;
    background-color: {c['bg_panel']};
}}
QTabBar::tab {{
    background-color: {c['bg_secondary']};
    color: {c['text_secondary']};
    padding: 6px 16px;
    border: 1px solid {c['border']};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    background-color: {c['bg_panel']};
    color: {c['accent']};
    border-bottom: 2px solid {c['accent']};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background-color: {c['bg_primary']};
    color: {c['text_primary']};
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background-color: {c['bg_secondary']};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {c['accent']};
}}
QScrollBar:horizontal {{
    background-color: {c['bg_secondary']};
    height: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {c['accent']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

/* ── Sidebar ── */
#Sidebar {{
    background-color: {c['bg_secondary']};
    border-right: 1px solid {c['border']};
}}
#SidebarButton {{
    background-color: transparent;
    color: {c['text_secondary']};
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    text-align: left;
    font-size: {c['font_size']}pt;
}}
#SidebarButton:hover {{
    background-color: {c['bg_primary']};
    color: {c['text_primary']};
}}
#SidebarButton[active="true"] {{
    background-color: {c['accent']};
    color: #FFFFFF;
    font-weight: bold;
}}

/* ── Status Bar ── */
QStatusBar {{
    background-color: {c['bg_secondary']};
    color: {c['text_secondary']};
    border-top: 1px solid {c['border']};
    font-size: {max(c['font_size'] - 1, 8)}pt;
}}
QStatusBar::item {{ border: none; }}

/* ── Menu Bar ── */
QMenuBar {{
    background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    border-bottom: 1px solid {c['border']};
}}
QMenuBar::item:selected {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}
QMenu {{
    background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
}}
QMenu::item:selected {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background-color: {c['border']};
}}
QSplitter::handle:hover {{
    background-color: {c['accent']};
}}

/* ── ToolTip ── */
QToolTip {{
    background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    border: 1px solid {c['accent']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {max(c['font_size'] - 1, 8)}pt;
}}

/* ── Progress Bar ── */
QProgressBar {{
    background-color: {c['bg_input']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    text-align: center;
    color: {c['text_primary']};
    height: 16px;
}}
QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 3px;
}}

/* ── CheckBox / RadioButton ── */
QCheckBox, QRadioButton {{
    color: {c['text_primary']};
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {c['border']};
    border-radius: 3px;
    background-color: {c['bg_input']};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}

/* ── Dock Widgets ── */
QDockWidget {{
    color: {c['text_primary']};
    titlebar-close-icon: none;
}}
QDockWidget::title {{
    background-color: {c['bg_secondary']};
    border-bottom: 1px solid {c['border']};
    padding: 4px 8px;
    font-weight: bold;
    color: {c['accent']};
}}
"""


# ─── ThemeEngine class ────────────────────────────────────────────────────────

class ThemeEngine:
    """
    Manages HBCE themes.
    Call apply_theme() after QApplication is created.
    Call open_color_picker() to let the user customize colors.
    """

    def __init__(self, config):
        self.config = config
        self.current_palette = self._load_palette()

    def _load_palette(self) -> dict:
        """Load palette from config, falling back to dark default."""
        mode = self.config.get("theme", "dark_default")
        if mode == "light_default":
            base = dict(LIGHT_DEFAULT)
        else:
            base = dict(DARK_DEFAULT)

        # Apply any user overrides saved in config
        user_keys = [
            "bg_primary", "bg_secondary", "bg_panel", "bg_input",
            "accent", "text_primary", "text_secondary", "border",
            "font_family", "font_size",
        ]
        for key in user_keys:
            cfg_key = f"theme_{key}"
            val = self.config.get(cfg_key)
            if val is not None:
                base[key] = val

        return base

    def apply_theme(self, app: QApplication):
        """Apply the current palette to the entire QApplication."""
        qss = build_qss(self.current_palette)
        app.setStyleSheet(qss)

        font = QFont(
            self.current_palette.get("font_family", "Segoe UI"),
            self.current_palette.get("font_size", 10),
        )
        app.setFont(font)
        logger.debug("Theme applied")

    def toggle_mode(self, app: QApplication):
        """Toggle between dark and light mode."""
        current = self.current_palette.get("mode", "dark")
        if current == "dark":
            self.current_palette = dict(LIGHT_DEFAULT)
            self.config.set_and_save("theme", "light_default")
        else:
            self.current_palette = dict(DARK_DEFAULT)
            self.config.set_and_save("theme", "dark_default")
        self.apply_theme(app)
        logger.info(f"Theme toggled to: {self.current_palette['mode']}")

    def get_color(self, key: str) -> str:
        """Get a color from the current palette by key."""
        return self.current_palette.get(key, "#FFFFFF")

    def open_color_picker(self, app: QApplication, parent=None):
        """Open the user color customization dialog."""
        dialog = ColorPickerDialog(self.current_palette, parent)
        if dialog.exec():
            new_palette = dialog.get_palette()
            self.current_palette.update(new_palette)
            # Save to config
            for key, val in new_palette.items():
                self.config.set(f"theme_{key}", val)
            self.config.save()
            self.apply_theme(app)
            logger.info("User custom theme applied")


# ─── Color Picker Dialog ──────────────────────────────────────────────────────

class ColorPickerDialog(QDialog):
    """
    Dialog that lets the user customize all theme colors.
    Shows a live preview swatch next to each color button.
    """

    EDITABLE_COLORS = [
        ("bg_primary",    "Background (Primary)"),
        ("bg_secondary",  "Background (Secondary)"),
        ("bg_panel",      "Panel Background"),
        ("accent",        "Accent Color"),
        ("text_primary",  "Text (Primary)"),
        ("text_secondary","Text (Secondary)"),
        ("border",        "Borders"),
        ("success",       "Success / Connected"),
        ("warning",       "Warning"),
        ("error",         "Error / Alarm"),
    ]

    def __init__(self, current_palette: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Theme Colors")
        self.setMinimumWidth(420)
        self._palette = dict(current_palette)
        self._swatches = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Mode selector
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Base Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Dark", "Light"])
        self.mode_combo.setCurrentText(
            "Dark" if self._palette.get("mode", "dark") == "dark" else "Light"
        )
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Color rows
        color_group = QGroupBox("Custom Colors")
        form = QFormLayout(color_group)
        form.setSpacing(8)

        for key, label in self.EDITABLE_COLORS:
            row = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(24, 24)
            swatch.setStyleSheet(
                f"background-color: {self._palette.get(key, '#888888')};"
                f"border: 1px solid #555; border-radius: 3px;"
            )
            self._swatches[key] = swatch

            btn = QPushButton("Choose…")
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda checked, k=key: self._pick_color(k))

            row.addWidget(swatch)
            row.addWidget(btn)
            row.addStretch()
            form.addRow(label + ":", row)

        layout.addWidget(color_group)

        # Font settings
        font_group = QGroupBox("Font")
        font_form = QFormLayout(font_group)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 18)
        self.font_size_spin.setValue(self._palette.get("font_size", 10))
        font_form.addRow("Font Size (pt):", self.font_size_spin)
        layout.addWidget(font_group)

        # Reset button
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setProperty("flat", True)
        reset_btn.clicked.connect(self._reset_to_default)
        layout.addWidget(reset_btn)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_color(self, key: str):
        current = QColor(self._palette.get(key, "#888888"))
        color = QColorDialog.getColor(current, self, f"Choose color for {key}")
        if color.isValid():
            hex_color = color.name()
            self._palette[key] = hex_color
            self._swatches[key].setStyleSheet(
                f"background-color: {hex_color};"
                f"border: 1px solid #555; border-radius: 3px;"
            )

    def _on_mode_changed(self, mode_text: str):
        if mode_text == "Dark":
            base = dict(DARK_DEFAULT)
        else:
            base = dict(LIGHT_DEFAULT)
        self._palette.update(base)
        # Update swatches
        for key, swatch in self._swatches.items():
            color = self._palette.get(key, "#888888")
            swatch.setStyleSheet(
                f"background-color: {color};"
                f"border: 1px solid #555; border-radius: 3px;"
            )

    def _reset_to_default(self):
        mode = self.mode_combo.currentText()
        self._on_mode_changed(mode)

    def get_palette(self) -> dict:
        self._palette["font_size"] = self.font_size_spin.value()
        mode = self.mode_combo.currentText().lower()
        self._palette["mode"] = mode
        return self._palette
