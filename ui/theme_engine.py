"""
HBCE — Hybrid Controls Editor
ui/theme_engine.py — Theme engine (updated V0.0.2-alpha)

Changes:
  - Panel headers more prominent (gradient bar, larger title, accent underline)
  - DashCard styling refined
  - Sidebar header button styles added
  - All other V0.0.1 features retained
"""

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


# ── Built-in palettes ─────────────────────────────────────────────────────────

DARK_DEFAULT = {
    "mode":            "dark",
    "bg_primary":      "#12121e",
    "bg_secondary":    "#1e1e32",
    "bg_panel":        "#1a1a2e",
    "bg_input":        "#12121e",
    "accent":          "#00AAFF",
    "accent_hover":    "#0088CC",
    "accent_press":    "#006699",
    "text_primary":    "#E0E0F0",
    "text_secondary":  "#808090",
    "text_disabled":   "#404050",
    "border":          "#2a2a4e",
    "border_focus":    "#00AAFF",
    "success":         "#00CC88",
    "warning":         "#FFAA00",
    "error":           "#FF4455",
    "font_family":     "Segoe UI",
    "font_size":       10,
}

LIGHT_DEFAULT = {
    "mode":            "light",
    "bg_primary":      "#F0F0F5",
    "bg_secondary":    "#E4E4EE",
    "bg_panel":        "#FFFFFF",
    "bg_input":        "#FFFFFF",
    "accent":          "#0078D4",
    "accent_hover":    "#006ABE",
    "accent_press":    "#005BA8",
    "text_primary":    "#1A1A2E",
    "text_secondary":  "#505060",
    "text_disabled":   "#AAAAAA",
    "border":          "#CCCCDD",
    "border_focus":    "#0078D4",
    "success":         "#00875A",
    "warning":         "#C86400",
    "error":           "#D32F2F",
    "font_family":     "Segoe UI",
    "font_size":       10,
}


def build_qss(c: dict) -> str:
    """Generate complete QSS from a color palette dict."""
    fs   = c["font_size"]
    fs_s = max(fs - 1, 8)

    return f"""
/* ── HBCE Global Stylesheet V0.0.2-alpha ── */

QMainWindow, QDialog, QWidget {{
    background-color: {c['bg_primary']};
    color: {c['text_primary']};
    font-family: "{c['font_family']}";
    font-size: {fs}pt;
}}

/* ── Frames / Groups ── */
QFrame {{
    background-color: {c['bg_secondary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    background: transparent;
    border-radius: 0;
}}
QGroupBox {{
    background-color: {c['bg_secondary']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    margin-top: 8px;
    padding-top: 4px;
}}
QGroupBox::title {{
    color: {c['accent']};
    font-weight: bold;
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}

/* ── Prominent panel headers ── */
QLabel#PanelTitle {{
    color: {c['text_primary']};
    font-size: {fs + 6}pt;
    font-weight: bold;
    background: transparent;
    border: none;
}}
QWidget#PanelHeader {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['bg_secondary']}, stop:1 {c['bg_primary']});
    border-bottom: 2px solid {c['accent']}44;
    border-radius: 0;
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
QPushButton:hover  {{ background-color: {c['accent_hover']}; }}
QPushButton:pressed {{ background-color: {c['accent_press']}; }}
QPushButton:disabled {{
    background-color: {c['border']};
    color: {c['text_disabled']};
}}
QPushButton[flat="true"] {{
    background-color: transparent;
    color: {c['accent']};
    border: 1px solid {c['accent']};
}}
QPushButton[flat="true"]:hover {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QPlainTextEdit,
QSpinBox, QDoubleSpinBox, QComboBox {{
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
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    selection-background-color: {c['accent']};
    border: 1px solid {c['border']};
}}

/* ── Tables / Trees ── */
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

/* ── Tabs ── */
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
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {c['accent']}; }}
QScrollBar:horizontal {{
    background-color: {c['bg_secondary']};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {c['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}

/* ── Sidebar ── */
QWidget#Sidebar {{
    background-color: {c['bg_secondary']};
    border-right: 1px solid {c['border']};
    border-radius: 0;
}}
QPushButton#SidebarButton {{
    background-color: transparent;
    color: {c['text_secondary']};
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    text-align: left;
    font-size: {fs}pt;
    min-height: 38px;
}}
QPushButton#SidebarButton:hover {{
    background-color: {c['bg_primary']};
    color: {c['text_primary']};
}}
QPushButton#SidebarButton[active="true"] {{
    background-color: {c['accent']};
    color: #FFFFFF;
    font-weight: bold;
}}

/* ── Status bar ── */
QStatusBar {{
    background-color: {c['bg_secondary']};
    color: {c['text_secondary']};
    border-top: 1px solid {c['border']};
    font-size: {fs_s}pt;
}}
QStatusBar::item {{ border: none; }}

/* ── Menu bar ── */
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
    border-radius: 4px;
}}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}
QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: 4px 8px;
}}

/* ── Splitter ── */
QSplitter::handle {{ background-color: {c['border']}; }}
QSplitter::handle:hover {{ background-color: {c['accent']}; }}

/* ── ToolTip ── */
QToolTip {{
    background-color: {c['bg_secondary']};
    color: {c['text_primary']};
    border: 1px solid {c['accent']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {fs_s}pt;
}}

/* ── Progress bar ── */
QProgressBar {{
    background-color: {c['bg_input']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    text-align: center;
    color: {c['text_primary']};
    height: 14px;
}}
QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 3px;
}}

/* ── Checkbox / Radio ── */
QCheckBox, QRadioButton {{
    color: {c['text_primary']};
    spacing: 6px;
    background: transparent;
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

/* ── List widget ── */
QListWidget {{
    background-color: {c['bg_panel']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{ padding: 6px 10px; }}
QListWidget::item:selected {{
    background-color: {c['accent']};
    color: #FFFFFF;
    border-radius: 4px;
}}
QListWidget::item:hover:!selected {{
    background-color: {c['bg_secondary']};
}}

/* ── Dock widgets ── */
QDockWidget {{ color: {c['text_primary']}; }}
QDockWidget::title {{
    background-color: {c['bg_secondary']};
    border-bottom: 1px solid {c['border']};
    padding: 4px 8px;
    font-weight: bold;
    color: {c['accent']};
}}

/* ── Scroll area ── */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


class ThemeEngine:
    def __init__(self, config):
        self.config = config
        self.current_palette = self._load_palette()

    def _load_palette(self) -> dict:
        mode = self.config.get("theme", "dark_default")
        base = dict(LIGHT_DEFAULT if mode == "light_default" else DARK_DEFAULT)
        for key in ["bg_primary","bg_secondary","bg_panel","bg_input","accent",
                    "text_primary","text_secondary","border","font_family","font_size"]:
            val = self.config.get(f"theme_{key}")
            if val is not None:
                base[key] = val
        return base

    def apply_theme(self, app: QApplication):
        app.setStyleSheet(build_qss(self.current_palette))
        font = QFont(
            self.current_palette.get("font_family","Segoe UI"),
            self.current_palette.get("font_size", 10),
        )
        app.setFont(font)
        logger.debug("Theme applied")

    def toggle_mode(self, app: QApplication):
        if self.current_palette.get("mode","dark") == "dark":
            self.current_palette = dict(LIGHT_DEFAULT)
            self.config.set_and_save("theme","light_default")
        else:
            self.current_palette = dict(DARK_DEFAULT)
            self.config.set_and_save("theme","dark_default")
        self.apply_theme(app)

    def get_color(self, key: str) -> str:
        return self.current_palette.get(key,"#FFFFFF")

    def open_color_picker(self, app: QApplication, parent=None):
        dialog = ColorPickerDialog(self.current_palette, parent)
        if dialog.exec():
            new_palette = dialog.get_palette()
            self.current_palette.update(new_palette)
            for key, val in new_palette.items():
                self.config.set(f"theme_{key}", val)
            self.config.save()
            self.apply_theme(app)


class ColorPickerDialog(QDialog):
    EDITABLE = [
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

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Theme Colors")
        self.setMinimumWidth(420)
        self._palette = dict(palette)
        self._swatches = {}
        self._build_ui()

    def _build_ui(self):
        L = QVBoxLayout(self)
        L.setSpacing(12)

        row = QHBoxLayout()
        row.addWidget(QLabel("Base Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Dark","Light"])
        self.mode_combo.setCurrentText("Dark" if self._palette.get("mode","dark")=="dark" else "Light")
        self.mode_combo.currentTextChanged.connect(self._on_mode)
        row.addWidget(self.mode_combo)
        row.addStretch()
        L.addLayout(row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        L.addWidget(sep)

        grp = QGroupBox("Colors")
        form = QFormLayout(grp)
        form.setSpacing(8)
        for key, label in self.EDITABLE:
            hrow = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(24,24)
            swatch.setStyleSheet(
                f"background:{self._palette.get(key,'#888')};"
                f"border:1px solid #555;border-radius:3px;"
            )
            self._swatches[key] = swatch
            btn = QPushButton("Choose…")
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda _, k=key: self._pick(k))
            hrow.addWidget(swatch)
            hrow.addWidget(btn)
            hrow.addStretch()
            form.addRow(label+":", hrow)
        L.addWidget(grp)

        fgrp = QGroupBox("Font")
        fform = QFormLayout(fgrp)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8,18)
        self.font_spin.setValue(self._palette.get("font_size",10))
        fform.addRow("Size (pt):", self.font_spin)
        L.addWidget(fgrp)

        reset = QPushButton("Reset to Default")
        reset.setProperty("flat",True)
        reset.clicked.connect(lambda: self._on_mode(self.mode_combo.currentText()))
        L.addWidget(reset)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        L.addWidget(btns)

    def _pick(self, key: str):
        color = QColorDialog.getColor(QColor(self._palette.get(key,"#888")), self)
        if color.isValid():
            self._palette[key] = color.name()
            self._swatches[key].setStyleSheet(
                f"background:{color.name()};border:1px solid #555;border-radius:3px;"
            )

    def _on_mode(self, mode_text: str):
        base = dict(LIGHT_DEFAULT if mode_text=="Light" else DARK_DEFAULT)
        self._palette.update(base)
        for key, sw in self._swatches.items():
            sw.setStyleSheet(
                f"background:{self._palette.get(key,'#888')};"
                f"border:1px solid #555;border-radius:3px;"
            )

    def get_palette(self) -> dict:
        self._palette["font_size"] = self.font_spin.value()
        self._palette["mode"] = self.mode_combo.currentText().lower()
        return self._palette
