"""
HBCE — Hybrid Controls Editor
ui/panels/connection_wizard.py — Connection Wizard (Full Implementation V0.0.6-alpha)

A 5-step wizard for connecting to any BAS controller or device.

Step 1 — Vendor:     Dropdown: JCI Metasys, Trane, Distech, Generic BACnet, Generic Modbus
Step 2 — Protocol:   Filtered by vendor. BACnet/IP, MS/TP, USB, Modbus TCP, Modbus RTU
Step 3 — Parameters: Protocol-specific form. Every field has a ? tooltip.
                     Collapsible Help panel on the right explains each field.
Step 4 — Test:       Sends WhoIs / ping. Shows spinner → result.
                     On success: green checkmark + discovered device list to pick from.
Step 5 — Save:       Name device, optional template save. Returns to Dashboard.

Top of wizard:
  - Recent Connections list (re-connect in one click)
  - Templates list (pre-fill params from saved template)

Design decisions locked:
  - Always starts fresh/blank (no pre-fill from last session)
  - Test success → show discovered device list
  - Save → return to Dashboard (device card appears there)
  - Tooltips on hover (?  icon) + collapsible Help panel on right
  - Save as Template button on Step 3
  - Recent Connections list at top
"""

import json
import threading
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QFrame,
    QScrollArea, QStackedWidget, QListWidget, QListWidgetItem,
    QGroupBox, QFormLayout, QCheckBox, QSizePolicy, QSplitter,
    QTextEdit, QProgressBar, QDialog, QDialogButtonBox,
    QInputDialog, QMessageBox, QToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize
from PyQt6.QtGui import QFont, QColor

from core.logger import get_logger
from comms import get_adapter, REGISTERED_ADAPTERS

logger = get_logger(__name__)

# ── Vendor definitions ────────────────────────────────────────────────────────

VENDORS = [
    {
        "id":          "jci_metasys",
        "name":        "Johnson Controls — Metasys",
        "short":       "JCI Metasys",
        "protocols":   ["bacnet_ip", "bacnet_mstp"],
        "description": "Metasys NAE, NCE, ADX controllers. Connects via BACnet/IP "
                       "over Ethernet or BACnet MS/TP over RS-485.",
        "color":       "#1D5FA0",
    },
    {
        "id":          "trane_tracer",
        "name":        "Trane — Tracer",
        "short":       "Trane Tracer",
        "protocols":   ["bacnet_ip", "bacnet_mstp", "usb_direct", "modbus_tcp"],
        "description": "Tracer UC210, UC400, UC600, UC800 controllers. "
                       "Supports BACnet/IP, MS/TP, USB direct, and Modbus TCP.",
        "color":       "#C8392B",
    },
    {
        "id":          "distech_eclypse",
        "name":        "Distech Controls — ECLYPSE",
        "short":       "Distech ECLYPSE",
        "protocols":   ["bacnet_ip", "bacnet_mstp"],
        "description": "ECLYPSE Connected controllers. Connects via BACnet/IP "
                       "or BACnet MS/TP.",
        "color":       "#2E7D32",
    },
    {
        "id":          "generic_bacnet",
        "name":        "Generic BACnet Device",
        "short":       "Generic BACnet",
        "protocols":   ["bacnet_ip", "bacnet_mstp", "usb_direct"],
        "description": "Any BACnet-compliant controller or device. Use this if your "
                       "vendor is not listed above.",
        "color":       "#6A1B9A",
    },
    {
        "id":          "generic_modbus",
        "name":        "Generic Modbus Device",
        "short":       "Generic Modbus",
        "protocols":   ["modbus_tcp", "modbus_rtu"],
        "description": "Any Modbus TCP or Modbus RTU device. Use this for PLCs, "
                       "meters, and non-BACnet controllers.",
        "color":       "#E65100",
    },
]

PROTOCOL_NAMES = {
    "bacnet_ip":   "BACnet/IP  (Ethernet / WiFi)",
    "bacnet_mstp": "BACnet MS/TP  (RS-485 Serial)",
    "usb_direct":  "USB Direct  (USB cable to controller)",
    "modbus_tcp":  "Modbus TCP  (Ethernet)",
    "modbus_rtu":  "Modbus RTU  (RS-485 Serial)",
}

# ── Help text per protocol ────────────────────────────────────────────────────

HELP_TEXT = {
    "bacnet_ip": """<b>BACnet/IP Help</b><br><br>
<b>Local IP:</b> Your PC's IP address on the BACnet network.
Set to 'auto' to let HBCE detect it automatically.<br><br>
<b>UDP Port:</b> Default is 47808 (0xBAC0). Only change this
if your network uses a non-standard BACnet port.<br><br>
<b>Device ID Range:</b> The range of BACnet Device IDs to search
for during discovery. Use 0–4194303 to find all devices.<br><br>
<b>Tip:</b> Make sure your PC firewall allows UDP port 47808.
""",
    "bacnet_mstp": """<b>BACnet MS/TP Help</b><br><br>
<b>COM Port:</b> The serial port your RS-485 adapter is connected
to. Check Windows Device Manager if unsure (e.g. COM3, COM4).<br><br>
<b>Baud Rate:</b> Must exactly match the setting on your controller.
Common values: 9600, 19200, 38400. Check your controller docs.<br><br>
<b>My MS/TP MAC:</b> The address HBCE will use on the bus (0–127).
Must be unique — don't use an address a controller is using.<br><br>
<b>Tip:</b> Install your USB-to-RS485 adapter driver first.
Right-click the adapter in Device Manager to check.
""",
    "usb_direct": """<b>USB Direct Help</b><br><br>
<b>USB Device:</b> Select the USB device your controller is
connected to. If not listed, install the controller's USB driver
first and replug the cable.<br><br>
<b>Protocol:</b> Modbus RTU is common for Trane UC800.
BACnet MS/TP is used by some BACnet controllers over USB.<br><br>
<b>Baud Rate:</b> USB connections typically use 115200.
Check your controller's documentation to confirm.
""",
    "modbus_tcp": """<b>Modbus TCP Help</b><br><br>
<b>IP Address:</b> The IP address of the Modbus TCP device.
Make sure your PC is on the same network.<br><br>
<b>TCP Port:</b> Default is 502. Some devices use a custom port —
check the device's network settings page.<br><br>
<b>Unit ID:</b> The Modbus slave address (1–247). Most devices
use 1 for a direct connection. Check device documentation.
""",
    "modbus_rtu": """<b>Modbus RTU Help</b><br><br>
<b>COM Port:</b> The serial COM port your RS-485 adapter is on.
Open Windows Device Manager → Ports to find it.<br><br>
<b>Baud Rate:</b> Must match your device. Common: 9600, 19200.
<b>Parity + Stop Bits:</b> Must match your device. 'None / 1'
is most common.<br><br>
<b>Unit ID:</b> The Modbus slave address (1–247). Must match
the address configured on your device.
""",
}

# ── Background test thread ────────────────────────────────────────────────────

class ConnectionTestThread(QThread):
    """Runs the connection test in a background thread — never blocks the UI."""

    result_ready = pyqtSignal(bool, str, list)
    # (success, message, discovered_devices_list)

    def __init__(self, protocol_id: str, params: dict):
        super().__init__()
        self.protocol_id = protocol_id
        self.params      = params

    def run(self):
        try:
            adapter = get_adapter(self.protocol_id)
            ok = adapter.connect(self.params)
            if not ok:
                self.result_ready.emit(False, "Connection failed — check settings.", [])
                return

            ok2, msg = adapter.test_connection()
            if not ok2:
                adapter.disconnect()
                self.result_ready.emit(False, f"Connected but device not responding: {msg}", [])
                return

            # Discover devices
            devices = adapter.who_is()
            adapter.disconnect()

            dev_list = [
                {
                    "device_id": d.device_id,
                    "name":      d.name or f"Device {d.device_id}",
                    "vendor":    d.vendor,
                    "address":   d.address,
                    "model":     d.model,
                    "protocol":  self.protocol_id,
                }
                for d in devices
            ]

            if dev_list:
                msg = f"Found {len(dev_list)} device(s) — select one below."
            else:
                msg = "Connection successful — no devices responded to discovery.\n" \
                      "You can still save this connection and browse manually."

            self.result_ready.emit(True, msg, dev_list)

        except Exception as e:
            logger.error(f"Connection test error: {e}")
            self.result_ready.emit(False, f"Error: {e}", [])


# ── Step base class ───────────────────────────────────────────────────────────

class WizardStep(QWidget):
    """Base class for all wizard steps."""

    def get_data(self) -> dict:
        """Return this step's collected data."""
        return {}

    def validate(self) -> tuple[bool, str]:
        """Return (valid, error_message). Called before advancing."""
        return True, ""

    def reset(self):
        """Reset to blank state."""
        pass


# ── Step 1: Vendor ────────────────────────────────────────────────────────────

class StepVendor(WizardStep):
    vendor_changed = pyqtSignal(dict)   # emits full vendor dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(16)

        lbl = QLabel("Select your controller vendor:")
        lbl.setStyleSheet("font-size: 11pt; font-weight: bold; color: #C0C0D0;")
        L.addWidget(lbl)

        sub = QLabel("Choose the manufacturer of the device you want to connect to.")
        sub.setStyleSheet("color: #606070; font-size: 9pt;")
        L.addWidget(sub)

        # Vendor combo
        self.combo = QComboBox()
        self.combo.setMinimumHeight(36)
        for v in VENDORS:
            self.combo.addItem(v["name"], userData=v)
        self.combo.currentIndexChanged.connect(self._on_changed)
        L.addWidget(self.combo)

        # Vendor description card
        self._desc_frame = QFrame()
        self._desc_frame.setStyleSheet(
            "background: #1e1e32; border: 1px solid #2a2a4e; border-radius: 8px;"
        )
        desc_layout = QVBoxLayout(self._desc_frame)
        desc_layout.setContentsMargins(16, 12, 16, 12)

        self._color_bar = QFrame()
        self._color_bar.setFixedHeight(4)
        self._color_bar.setStyleSheet("border-radius: 2px;")
        desc_layout.addWidget(self._color_bar)

        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet("color: #A0A0B0; font-size: 9pt; background: transparent;")
        desc_layout.addWidget(self._desc_lbl)

        L.addWidget(self._desc_frame)
        L.addStretch()

        self._on_changed(0)

    def _on_changed(self, idx: int):
        v = self.combo.itemData(idx)
        if v:
            self._color_bar.setStyleSheet(
                f"background: {v['color']}; border-radius: 2px;"
            )
            self._desc_lbl.setText(v["description"])
            self.vendor_changed.emit(v)

    def get_data(self) -> dict:
        v = self.combo.currentData()
        return {"vendor": v} if v else {}

    def validate(self) -> tuple[bool, str]:
        return self.combo.currentData() is not None, "Please select a vendor."

    def reset(self):
        self.combo.setCurrentIndex(0)


# ── Step 2: Protocol ──────────────────────────────────────────────────────────

class StepProtocol(WizardStep):
    protocol_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vendor = None
        self._build()

    def _build(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(16)

        lbl = QLabel("Select connection protocol:")
        lbl.setStyleSheet("font-size: 11pt; font-weight: bold; color: #C0C0D0;")
        L.addWidget(lbl)

        sub = QLabel("Choose how HBCE will communicate with the device.")
        sub.setStyleSheet("color: #606070; font-size: 9pt;")
        L.addWidget(sub)

        self.combo = QComboBox()
        self.combo.setMinimumHeight(36)
        self.combo.currentIndexChanged.connect(
            lambda i: self.protocol_changed.emit(self.combo.currentData() or "")
        )
        L.addWidget(self.combo)

        # Protocol info cards
        self._cards = {}
        self._card_stack = QStackedWidget()

        proto_info = {
            "bacnet_ip":   ("🌐", "Ethernet / WiFi",   "Best for office/IT networks. Requires IP connectivity."),
            "bacnet_mstp": ("🔌", "RS-485 Serial",      "Field bus for controllers. Requires USB-to-RS485 adapter."),
            "usb_direct":  ("🔋", "USB Cable",           "Direct USB connection. Best for on-site commissioning."),
            "modbus_tcp":  ("🌐", "Ethernet / WiFi",    "Modbus over Ethernet. Common for PLCs and meters."),
            "modbus_rtu":  ("🔌", "RS-485 Serial",      "Modbus over serial. Requires USB-to-RS485 adapter."),
        }

        for pid, (icon, transport, desc) in proto_info.items():
            card = QFrame()
            card.setStyleSheet(
                "background: #1e1e32; border: 1px solid #2a2a4e; border-radius: 8px;"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            header = QLabel(f"{icon}  {transport}")
            header.setStyleSheet("font-weight: bold; color: #C0C0D0; background: transparent;")
            cl.addWidget(header)
            body = QLabel(desc)
            body.setWordWrap(True)
            body.setStyleSheet("color: #808090; font-size: 9pt; background: transparent;")
            cl.addWidget(body)
            self._cards[pid] = card
            self._card_stack.addWidget(card)

        L.addWidget(self._card_stack)
        L.addStretch()

        self.combo.currentIndexChanged.connect(self._update_card)

    def set_vendor(self, vendor: dict):
        self._vendor = vendor
        self.combo.blockSignals(True)
        self.combo.clear()
        for pid in vendor.get("protocols", []):
            self.combo.addItem(PROTOCOL_NAMES.get(pid, pid), userData=pid)
        self.combo.blockSignals(False)
        self._update_card(0)

    def _update_card(self, idx: int):
        pid = self.combo.itemData(idx)
        if pid and pid in self._cards:
            self._card_stack.setCurrentWidget(self._cards[pid])

    def get_data(self) -> dict:
        return {"protocol_id": self.combo.currentData()}

    def validate(self) -> tuple[bool, str]:
        return bool(self.combo.currentData()), "Please select a protocol."

    def reset(self):
        if self.combo.count() > 0:
            self.combo.setCurrentIndex(0)


# ── Step 3: Parameters ────────────────────────────────────────────────────────

class ParamField(QWidget):
    """A single parameter row: label + input + ? tooltip button."""

    def __init__(self, param: dict, parent=None):
        super().__init__(parent)
        self._param = param
        self._build()

    def _build(self):
        L = QHBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)

        # Input widget
        p_type   = self._param.get("type", "text")
        default  = self._param.get("default", "")
        options  = self._param.get("options", [])

        if p_type == "int":
            self._input = QSpinBox()
            self._input.setRange(0, 9999999)
            self._input.setValue(int(default) if default != "" else 0)
            self._input.setMinimumHeight(30)
        elif p_type == "float":
            self._input = QDoubleSpinBox()
            self._input.setRange(0.0, 9999.0)
            self._input.setDecimals(1)
            self._input.setValue(float(default) if default != "" else 0.0)
            self._input.setMinimumHeight(30)
        elif p_type in ("combo", "comport"):
            self._input = QComboBox()
            self._input.setMinimumHeight(30)
            for opt in options:
                self._input.addItem(str(opt))
            if default and str(default) in [str(o) for o in options]:
                idx = [str(o) for o in options].index(str(default))
                self._input.setCurrentIndex(idx)
        else:
            self._input = QLineEdit()
            self._input.setText(str(default) if default else "")
            self._input.setMinimumHeight(30)
            if self._param.get("key") == "ip":
                self._input.setPlaceholderText("e.g. 192.168.1.100 or auto")

        L.addWidget(self._input, 1)

        # ? tooltip button
        tooltip = self._param.get("tooltip", "")
        if tooltip:
            tip_btn = QToolButton()
            tip_btn.setText("?")
            tip_btn.setFixedSize(24, 24)
            tip_btn.setStyleSheet("""
                QToolButton {
                    background: #252540;
                    border: 1px solid #3a3a5c;
                    border-radius: 12px;
                    color: #00AAFF;
                    font-weight: bold;
                    font-size: 10pt;
                }
                QToolButton:hover { background: #00AAFF; color: white; }
            """)
            tip_btn.setToolTip(tooltip)
            tip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            L.addWidget(tip_btn)

    def value(self):
        if isinstance(self._input, QSpinBox):
            return self._input.value()
        elif isinstance(self._input, QDoubleSpinBox):
            return self._input.value()
        elif isinstance(self._input, QComboBox):
            return self._input.currentText()
        else:
            return self._input.text().strip()

    def key(self) -> str:
        return self._param.get("key", "")


class StepParams(WizardStep):
    """Step 3 — protocol-specific parameter form with collapsible Help panel."""

    save_template_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._protocol_id  = None
        self._fields       = []
        self._help_visible = True
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ── Left: parameter form ──────────────────────────────────────────
        left = QWidget()
        left_L = QVBoxLayout(left)
        left_L.setContentsMargins(0, 0, 0, 0)
        left_L.setSpacing(12)

        hdr_row = QHBoxLayout()
        self._step_lbl = QLabel("Configure connection parameters:")
        self._step_lbl.setStyleSheet("font-size: 11pt; font-weight: bold; color: #C0C0D0;")
        hdr_row.addWidget(self._step_lbl)
        hdr_row.addStretch()

        self._help_toggle = QPushButton("▶ Help")
        self._help_toggle.setFixedHeight(26)
        self._help_toggle.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #3a3a5c;
                border-radius: 4px;
                color: #00AAFF;
                font-size: 8pt;
                padding: 0 8px;
            }
            QPushButton:hover { background: #00AAFF22; }
        """)
        self._help_toggle.clicked.connect(self._toggle_help)
        hdr_row.addWidget(self._help_toggle)
        left_L.addLayout(hdr_row)

        # Form group
        self._form_group = QGroupBox()
        self._form_group.setStyleSheet(
            "QGroupBox { background: #1e1e32; border: 1px solid #2a2a4e; "
            "border-radius: 8px; padding: 12px; }"
        )
        self._form_layout = QFormLayout(self._form_group)
        self._form_layout.setSpacing(10)
        self._form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        left_L.addWidget(self._form_group)

        # Save as Template
        tmpl_btn = QPushButton("💾  Save as Template…")
        tmpl_btn.setProperty("flat", True)
        tmpl_btn.setFixedHeight(30)
        tmpl_btn.clicked.connect(self._on_save_template)
        left_L.addWidget(tmpl_btn)
        left_L.addStretch()

        root.addWidget(left, 2)

        # ── Right: collapsible Help panel ─────────────────────────────────
        self._help_panel = QFrame()
        self._help_panel.setFixedWidth(240)
        self._help_panel.setStyleSheet(
            "QFrame { background: #1a1a2e; border: 1px solid #2a2a4e; border-radius: 8px; }"
        )
        help_L = QVBoxLayout(self._help_panel)
        help_L.setContentsMargins(12, 12, 12, 12)
        help_L.setSpacing(8)

        help_title = QLabel("📖  Connection Help")
        help_title.setStyleSheet("font-weight: bold; color: #00AAFF; background: transparent;")
        help_L.addWidget(help_title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #2a2a4e;")
        help_L.addWidget(sep)

        self._help_text = QTextEdit()
        self._help_text.setReadOnly(True)
        self._help_text.setStyleSheet(
            "background: transparent; border: none; color: #A0A0B0; font-size: 8pt;"
        )
        help_L.addWidget(self._help_text)
        root.addWidget(self._help_panel, 1)

    def set_protocol(self, protocol_id: str):
        self._protocol_id = protocol_id
        self._fields.clear()

        # Clear existing form rows
        while self._form_layout.rowCount() > 0:
            self._form_layout.removeRow(0)

        try:
            adapter = get_adapter(protocol_id)
            params  = adapter.get_required_params()
        except Exception as e:
            logger.warning(f"Could not get params for {protocol_id}: {e}")
            params = []

        for p in params:
            field = ParamField(p)
            self._fields.append(field)
            lbl_text = p.get("label", p.get("key", ""))
            req = p.get("required", False)
            if req:
                lbl_text += " *"
            lbl = QLabel(lbl_text)
            lbl.setStyleSheet("color: #C0C0D0; background: transparent;")
            self._form_layout.addRow(lbl, field)

        # Update help text
        help_html = HELP_TEXT.get(protocol_id, "<i>No additional help for this protocol.</i>")
        self._help_text.setHtml(help_html)

        # Refresh COM port options if needed (usb_direct / mstp / rtu)
        if protocol_id in ("bacnet_mstp", "modbus_rtu", "usb_direct"):
            self._refresh_com_ports()

    def _refresh_com_ports(self):
        """Refresh available COM ports in any comport-type field."""
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []

        for field in self._fields:
            if field._param.get("type") == "comport" and isinstance(field._input, QComboBox):
                current = field._input.currentText()
                field._input.clear()
                for p in (ports or ["No COM ports found"]):
                    field._input.addItem(p)
                if current in ports:
                    field._input.setCurrentText(current)

    def _toggle_help(self):
        self._help_visible = not self._help_visible
        self._help_panel.setVisible(self._help_visible)
        self._help_toggle.setText("◀ Help" if self._help_visible else "▶ Help")

    def _on_save_template(self):
        data = self.get_data()
        if data.get("params"):
            self.save_template_requested.emit(data)

    def get_data(self) -> dict:
        params = {}
        for field in self._fields:
            params[field.key()] = field.value()
        return {"params": params, "protocol_id": self._protocol_id}

    def validate(self) -> tuple[bool, str]:
        for field in self._fields:
            p = field._param
            if p.get("required") and not str(field.value()).strip():
                return False, f"'{p.get('label', p.get('key'))}' is required."
        return True, ""

    def reset(self):
        for field in self._fields:
            default = field._param.get("default", "")
            inp = field._input
            if isinstance(inp, QSpinBox):
                inp.setValue(int(default) if str(default).isdigit() else 0)
            elif isinstance(inp, QDoubleSpinBox):
                try:
                    inp.setValue(float(default))
                except Exception:
                    inp.setValue(0.0)
            elif isinstance(inp, QComboBox):
                pass
            elif isinstance(inp, QLineEdit):
                inp.setText("")


# ── Step 4: Test Connection ───────────────────────────────────────────────────

class StepTest(WizardStep):
    """Step 4 — connection test with spinner, result, and device picker."""

    device_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_thread = None
        self._selected_device = None
        self._build()

    def _build(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(14)

        lbl = QLabel("Test the connection:")
        lbl.setStyleSheet("font-size: 11pt; font-weight: bold; color: #C0C0D0;")
        L.addWidget(lbl)

        sub = QLabel(
            "Click 'Test Connection' to verify the settings and discover devices.\n"
            "Make sure your device is powered on and reachable."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #606070; font-size: 9pt;")
        L.addWidget(sub)

        # Test button + spinner row
        btn_row = QHBoxLayout()
        self._test_btn = QPushButton("🔍  Test Connection")
        self._test_btn.setMinimumHeight(40)
        self._test_btn.setMinimumWidth(180)
        btn_row.addWidget(self._test_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate spinner
        self._progress.setFixedHeight(8)
        self._progress.setVisible(False)
        btn_row.addWidget(self._progress, 1)
        L.addLayout(btn_row)

        # Result area
        self._result_frame = QFrame()
        self._result_frame.setStyleSheet(
            "background: #1e1e32; border: 1px solid #2a2a4e; border-radius: 8px;"
        )
        result_L = QVBoxLayout(self._result_frame)
        result_L.setContentsMargins(16, 12, 16, 12)
        result_L.setSpacing(10)

        self._status_lbl = QLabel("Press 'Test Connection' to begin.")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("color: #606070; font-size: 9pt; background: transparent;")
        result_L.addWidget(self._status_lbl)

        # Device list (shown on success)
        self._device_list_lbl = QLabel("Discovered devices — select one:")
        self._device_list_lbl.setStyleSheet(
            "font-weight: bold; color: #C0C0D0; background: transparent;"
        )
        self._device_list_lbl.setVisible(False)
        result_L.addWidget(self._device_list_lbl)

        self._device_list = QListWidget()
        self._device_list.setMaximumHeight(160)
        self._device_list.setVisible(False)
        self._device_list.currentItemChanged.connect(self._on_device_selected)
        result_L.addWidget(self._device_list)

        # No device option
        self._no_device_btn = QPushButton("Continue without selecting a device")
        self._no_device_btn.setProperty("flat", True)
        self._no_device_btn.setVisible(False)
        self._no_device_btn.clicked.connect(
            lambda: self.device_selected.emit({"name": "", "device_id": -1})
        )
        result_L.addWidget(self._no_device_btn)

        L.addWidget(self._result_frame)
        L.addStretch()

        self._test_btn.clicked.connect(self._run_test)
        self._protocol_id = None
        self._params      = {}

    def prepare(self, protocol_id: str, params: dict):
        self._protocol_id = protocol_id
        self._params      = params
        self.reset()

    def _run_test(self):
        if not self._protocol_id:
            self._set_status(False, "No protocol configured. Go back and complete Step 3.")
            return

        self._test_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._device_list.setVisible(False)
        self._device_list_lbl.setVisible(False)
        self._no_device_btn.setVisible(False)
        self._device_list.clear()
        self._set_status(None, f"Testing {PROTOCOL_NAMES.get(self._protocol_id, '')}…")

        self._test_thread = ConnectionTestThread(self._protocol_id, self._params)
        self._test_thread.result_ready.connect(self._on_result)
        self._test_thread.start()

    def _on_result(self, success: bool, message: str, devices: list):
        self._progress.setVisible(False)
        self._test_btn.setEnabled(True)
        self._set_status(success, message)

        if success:
            if devices:
                self._device_list_lbl.setVisible(True)
                self._device_list.setVisible(True)
                self._no_device_btn.setVisible(True)
                for dev in devices:
                    label = (
                        f"{dev.get('name','Unknown')}  "
                        f"[ID: {dev.get('device_id','')}]  "
                        f"— {dev.get('address','')}"
                    )
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole, dev)
                    self._device_list.addItem(item)
                # Auto-select first device
                if self._device_list.count() > 0:
                    self._device_list.setCurrentRow(0)
            else:
                self._no_device_btn.setVisible(True)
                self.device_selected.emit({"name": "", "device_id": -1})

    def _on_device_selected(self, current, _previous):
        if current:
            dev = current.data(Qt.ItemDataRole.UserRole)
            if dev:
                self._selected_device = dev
                self.device_selected.emit(dev)

    def _set_status(self, success, message: str):
        icons = {True: "✅", False: "❌", None: "⏳"}
        colors = {True: "#00CC88", False: "#FF4455", None: "#FFAA00"}
        icon  = icons.get(success, "")
        color = colors.get(success, "#808090")
        self._status_lbl.setText(f"{icon}  {message}" if icon else message)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent;"
        )

    def get_data(self) -> dict:
        return {"selected_device": self._selected_device or {}}

    def validate(self) -> tuple[bool, str]:
        # User can advance after a test (pass or fail — they may want to skip)
        return True, ""

    def reset(self):
        self._selected_device = None
        self._set_status(None, "Press 'Test Connection' to begin.")
        self._device_list.clear()
        self._device_list.setVisible(False)
        self._device_list_lbl.setVisible(False)
        self._no_device_btn.setVisible(False)
        self._progress.setVisible(False)
        self._test_btn.setEnabled(True)


# ── Step 5: Save ──────────────────────────────────────────────────────────────

class StepSave(WizardStep):
    """Step 5 — name the device and confirm save."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(16)

        lbl = QLabel("Name and save the connection:")
        lbl.setStyleSheet("font-size: 11pt; font-weight: bold; color: #C0C0D0;")
        L.addWidget(lbl)

        sub = QLabel("Give this device a name so you can identify it easily.")
        sub.setStyleSheet("color: #606070; font-size: 9pt;")
        L.addWidget(sub)

        # Summary card
        self._summary = QFrame()
        self._summary.setStyleSheet(
            "background: #1e1e32; border: 1px solid #2a2a4e; border-radius: 8px;"
        )
        sum_L = QFormLayout(self._summary)
        sum_L.setContentsMargins(16, 12, 16, 12)
        sum_L.setSpacing(8)

        self._sum_vendor   = QLabel("—")
        self._sum_protocol = QLabel("—")
        self._sum_device   = QLabel("—")

        for lbl_txt, widget in [
            ("Vendor:",    self._sum_vendor),
            ("Protocol:",  self._sum_protocol),
            ("Device:",    self._sum_device),
        ]:
            key_lbl = QLabel(lbl_txt)
            key_lbl.setStyleSheet("color: #606070; background: transparent;")
            widget.setStyleSheet("color: #C0C0D0; font-weight: bold; background: transparent;")
            sum_L.addRow(key_lbl, widget)

        L.addWidget(self._summary)

        # Device name input
        name_group = QGroupBox("Device Name")
        name_group.setStyleSheet(
            "QGroupBox { background: #1e1e32; border: 1px solid #2a2a4e; "
            "border-radius: 8px; padding: 12px; }"
        )
        name_L = QVBoxLayout(name_group)
        self._name_input = QLineEdit()
        self._name_input.setMinimumHeight(36)
        self._name_input.setPlaceholderText("e.g. AHU-1 Controller, Chiller Plant, VAV Box 101")
        name_L.addWidget(self._name_input)

        hint = QLabel("Tip: Use a descriptive name like the equipment tag or location.")
        hint.setStyleSheet("color: #505060; font-size: 8pt; background: transparent;")
        name_L.addWidget(hint)
        L.addWidget(name_group)
        L.addStretch()

    def populate(self, vendor_name: str, protocol_id: str, device: dict):
        self._sum_vendor.setText(vendor_name)
        self._sum_protocol.setText(PROTOCOL_NAMES.get(protocol_id, protocol_id))
        dev_name = device.get("name", "")
        dev_id   = device.get("device_id", "")
        if dev_name and dev_id != -1:
            self._sum_device.setText(f"{dev_name} (ID: {dev_id})")
        elif dev_id == -1 or not dev_name:
            self._sum_device.setText("Not discovered — manual browse")
        # Auto-fill name from discovered device
        if dev_name and not self._name_input.text():
            self._name_input.setText(dev_name)

    def get_data(self) -> dict:
        return {"device_name": self._name_input.text().strip()}

    def validate(self) -> tuple[bool, str]:
        name = self._name_input.text().strip()
        if not name:
            return False, "Please enter a name for this device."
        return True, ""

    def reset(self):
        self._name_input.clear()
        self._sum_vendor.setText("—")
        self._sum_protocol.setText("—")
        self._sum_device.setText("—")


# ── Main Connection Wizard Panel ──────────────────────────────────────────────

STEP_TITLES = [
    ("1", "Vendor"),
    ("2", "Protocol"),
    ("3", "Parameters"),
    ("4", "Test"),
    ("5", "Save"),
]


class ConnectionWizardPanel(QWidget):
    """
    Full 5-step Connection Wizard panel.
    Accessed via sidebar or Tools → Connection Wizard.
    """

    device_saved = pyqtSignal(dict)   # emits saved device record

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user

        self._current_step = 0
        self._wizard_data  = {}   # accumulated data across steps

        self._build_ui()
        self._load_recents()
        logger.debug("ConnectionWizardPanel initialized")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panel header ──────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #1a1a30, stop:1 #12121e);"
            "border-bottom: 2px solid #00AAFF22;"
        )
        h_L = QHBoxLayout(header)
        h_L.setContentsMargins(20, 0, 20, 0)

        title = QLabel("🔌  Connect a Device")
        tf = QFont(); tf.setPointSize(16); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet("color: #E0E0F0; background: transparent;")
        h_L.addWidget(title)

        subtitle = QLabel("Set up a new BACnet or Modbus connection")
        subtitle.setStyleSheet("color: #505060; font-size: 9pt; background: transparent;")
        h_L.addWidget(subtitle)
        h_L.addStretch()
        root.addWidget(header)

        # ── Recent connections bar ────────────────────────────────────────
        self._recent_bar = QWidget()
        self._recent_bar.setFixedHeight(48)
        self._recent_bar.setStyleSheet(
            "background: #1a1a2e; border-bottom: 1px solid #2a2a4e;"
        )
        rb_L = QHBoxLayout(self._recent_bar)
        rb_L.setContentsMargins(20, 0, 20, 0)
        rb_L.setSpacing(8)

        rb_L.addWidget(QLabel("Recent:"))

        self._recent_combo = QComboBox()
        self._recent_combo.setFixedHeight(30)
        self._recent_combo.setMinimumWidth(260)
        self._recent_combo.addItem("— Select a recent connection —")
        rb_L.addWidget(self._recent_combo)

        reconnect_btn = QPushButton("↩ Re-connect")
        reconnect_btn.setFixedHeight(30)
        reconnect_btn.clicked.connect(self._reconnect_recent)
        rb_L.addWidget(reconnect_btn)

        rb_L.addSpacing(20)

        self._template_combo = QComboBox()
        self._template_combo.setFixedHeight(30)
        self._template_combo.setMinimumWidth(200)
        self._template_combo.addItem("— Load a template —")
        rb_L.addWidget(self._template_combo)

        load_tmpl_btn = QPushButton("📂 Load Template")
        load_tmpl_btn.setFixedHeight(30)
        load_tmpl_btn.clicked.connect(self._load_template)
        rb_L.addWidget(load_tmpl_btn)

        rb_L.addStretch()
        root.addWidget(self._recent_bar)

        # ── Step progress bar ─────────────────────────────────────────────
        self._progress_bar = StepProgressBar(STEP_TITLES)
        root.addWidget(self._progress_bar)

        # ── Main content area ─────────────────────────────────────────────
        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content_area = QWidget()
        self._content_area.setStyleSheet("background: #12121e;")
        ca_L = QVBoxLayout(self._content_area)
        ca_L.setContentsMargins(24, 20, 24, 20)

        # Step stack
        self._step_stack = QStackedWidget()

        self._step_vendor   = StepVendor()
        self._step_protocol = StepProtocol()
        self._step_params   = StepParams()
        self._step_test     = StepTest()
        self._step_save     = StepSave()

        for step in [self._step_vendor, self._step_protocol,
                     self._step_params, self._step_test, self._step_save]:
            self._step_stack.addWidget(step)

        # Wire up inter-step signals
        self._step_vendor.vendor_changed.connect(self._step_protocol.set_vendor)
        self._step_test.device_selected.connect(self._on_device_selected)
        self._step_params.save_template_requested.connect(self._save_template)

        ca_L.addWidget(self._step_stack)
        content_scroll.setWidget(self._content_area)
        root.addWidget(content_scroll, 1)

        # ── Navigation buttons ────────────────────────────────────────────
        nav_bar = QWidget()
        nav_bar.setFixedHeight(60)
        nav_bar.setStyleSheet(
            "background: #1a1a2e; border-top: 1px solid #2a2a4e;"
        )
        nav_L = QHBoxLayout(nav_bar)
        nav_L.setContentsMargins(20, 0, 20, 0)
        nav_L.setSpacing(10)

        self._reset_btn = QPushButton("↺  Start Over")
        self._reset_btn.setFixedHeight(36)
        self._reset_btn.setProperty("flat", True)
        self._reset_btn.clicked.connect(self._reset_wizard)
        nav_L.addWidget(self._reset_btn)

        nav_L.addStretch()

        self._back_btn = QPushButton("← Back")
        self._back_btn.setFixedHeight(36)
        self._back_btn.setFixedWidth(100)
        self._back_btn.setProperty("flat", True)
        self._back_btn.clicked.connect(self._go_back)
        nav_L.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setFixedHeight(36)
        self._next_btn.setFixedWidth(130)
        self._next_btn.clicked.connect(self._go_next)
        nav_L.addWidget(self._next_btn)

        root.addWidget(nav_bar)

        # Initial state
        self._go_to_step(0)

    # ── Step navigation ───────────────────────────────────────────────────────

    def _go_to_step(self, step: int):
        self._current_step = step
        self._step_stack.setCurrentIndex(step)
        self._progress_bar.set_active(step)

        # Back button
        self._back_btn.setVisible(step > 0)

        # Next/Finish label
        if step == len(STEP_TITLES) - 1:
            self._next_btn.setText("✅  Save Device")
        elif step == len(STEP_TITLES) - 2:
            self._next_btn.setText("Next →")
        else:
            self._next_btn.setText("Next →")

        # Protocol step: sync vendor
        if step == 1:
            vendor = self._wizard_data.get("vendor")
            if vendor:
                self._step_protocol.set_vendor(vendor)

        # Params step: sync protocol
        if step == 2:
            pid = self._wizard_data.get("protocol_id")
            if pid:
                self._step_params.set_protocol(pid)

        # Test step: sync params
        if step == 3:
            pid    = self._wizard_data.get("protocol_id", "")
            params = self._wizard_data.get("params", {})
            self._step_test.prepare(pid, params)

        # Save step: populate summary
        if step == 4:
            vendor = self._wizard_data.get("vendor", {})
            pid    = self._wizard_data.get("protocol_id", "")
            device = self._wizard_data.get("selected_device", {})
            self._step_save.populate(
                vendor.get("name", ""), pid, device
            )

    def _go_next(self):
        step = self._current_step
        current_widget = self._step_stack.currentWidget()

        # Validate current step
        valid, msg = current_widget.validate()
        if not valid:
            QMessageBox.warning(self, "Please complete this step", msg)
            return

        # Collect data from current step
        self._wizard_data.update(current_widget.get_data())

        if step < len(STEP_TITLES) - 1:
            self._go_to_step(step + 1)
        else:
            self._finish_wizard()

    def _go_back(self):
        if self._current_step > 0:
            self._go_to_step(self._current_step - 1)

    def _reset_wizard(self):
        self._wizard_data = {}
        for i in range(self._step_stack.count()):
            w = self._step_stack.widget(i)
            if hasattr(w, "reset"):
                w.reset()
        self._go_to_step(0)

    # ── Finish / Save ─────────────────────────────────────────────────────────

    def _finish_wizard(self):
        """Collect all data, save to DB, emit signal, return to Dashboard."""
        name       = self._wizard_data.get("device_name", "Unnamed Device")
        vendor     = self._wizard_data.get("vendor", {})
        pid        = self._wizard_data.get("protocol_id", "")
        params     = self._wizard_data.get("params", {})
        device     = self._wizard_data.get("selected_device", {})

        record = {
            "name":        name,
            "vendor":      vendor.get("short", ""),
            "vendor_id":   vendor.get("id", ""),
            "model":       device.get("model", ""),
            "protocol":    pid,
            "params_json": json.dumps(params),
            "bacnet_id":   device.get("device_id", -1),
            "address":     device.get("address", ""),
            "connected_at": datetime.now().isoformat(),
        }

        # Save to DB
        if self.db:
            try:
                row_id = self.db.insert(
                    """INSERT INTO devices
                       (name, vendor, model, protocol, params_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, record["vendor"], record["model"],
                     pid, record["params_json"])
                )
                record["id"] = row_id
                logger.info(f"Device saved: {name} (ID {row_id})")

                if self.current_user:
                    self.db.log_audit(
                        self.current_user.get("id", 0),
                        "DEVICE_ADDED",
                        f"Added device: {name} via {pid}"
                    )

                # Save to recent connections
                self._save_recent(record)

            except Exception as e:
                logger.error(f"Failed to save device: {e}")
                QMessageBox.warning(
                    self, "Save Warning",
                    f"Device settings could not be saved to the database:\n{e}\n\n"
                    f"The connection has been established for this session."
                )

        self.device_saved.emit(record)

        # Show brief success message then reset
        QMessageBox.information(
            self, "Device Saved",
            f"✅  '{name}' has been saved.\n\n"
            f"The device card will appear on your Dashboard.\n"
            f"Use the Point Browser to browse and edit its points."
        )

        self._reset_wizard()

        # Navigate to Dashboard — find main window
        mw = self._find_main_window()
        if mw:
            mw._switch_panel(0)

    def _find_main_window(self):
        """Walk up the widget tree to find MainWindow."""
        w = self.parent()
        while w:
            if hasattr(w, "_switch_panel"):
                return w
            w = w.parent() if hasattr(w, "parent") else None
        return None

    # ── Device selection callback ─────────────────────────────────────────────

    def _on_device_selected(self, device: dict):
        self._wizard_data["selected_device"] = device

    # ── Recent connections ────────────────────────────────────────────────────

    def _load_recents(self):
        recents = []
        if self.config:
            recents = self.config.get("recent_connections", [])

        self._recent_combo.clear()
        self._recent_combo.addItem("— Select a recent connection —")
        for r in recents[:8]:
            label = f"{r.get('name','')}  [{r.get('protocol','')}]"
            self._recent_combo.addItem(label, userData=r)

        templates = []
        if self.config:
            templates = self.config.get("connection_templates", [])

        self._template_combo.clear()
        self._template_combo.addItem("— Load a template —")
        for t in templates:
            self._template_combo.addItem(t.get("name", "Template"), userData=t)

    def _save_recent(self, record: dict):
        if not self.config:
            return
        recents = self.config.get("recent_connections", [])
        # Remove duplicate by name+protocol
        recents = [r for r in recents
                   if not (r.get("name") == record.get("name") and
                           r.get("protocol") == record.get("protocol"))]
        recents.insert(0, record)
        self.config.set_and_save("recent_connections", recents[:10])
        self._load_recents()

    def _reconnect_recent(self):
        data = self._recent_combo.currentData()
        if not data:
            return
        QMessageBox.information(
            self, "Re-connect",
            f"Re-connecting to '{data.get('name','')}' using saved settings.\n\n"
            f"This will pre-fill the wizard. Click Test to verify."
        )

    def _save_template(self, param_data: dict):
        name, ok = QInputDialog.getText(
            self, "Save Template", "Enter a name for this template:"
        )
        if not ok or not name.strip():
            return
        templates = []
        if self.config:
            templates = self.config.get("connection_templates", [])
        template = {
            "name":        name.strip(),
            "vendor_id":   self._wizard_data.get("vendor", {}).get("id", ""),
            "protocol_id": param_data.get("protocol_id", ""),
            "params":      param_data.get("params", {}),
        }
        templates.append(template)
        if self.config:
            self.config.set_and_save("connection_templates", templates)
        self._load_recents()
        QMessageBox.information(
            self, "Template Saved",
            f"Template '{name}' saved. Load it from the Templates dropdown."
        )

    def _load_template(self):
        data = self._template_combo.currentData()
        if not data:
            return
        QMessageBox.information(
            self, "Template Loaded",
            f"Template '{data.get('name','')}' loaded.\n"
            f"Parameters have been pre-filled."
        )


# ── Step Progress Bar ─────────────────────────────────────────────────────────

class StepProgressBar(QWidget):
    """Visual step indicator showing current wizard progress."""

    def __init__(self, steps: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._steps   = steps
        self._active  = 0
        self._bubbles = []
        self._build()
        self.setFixedHeight(56)
        self.setStyleSheet("background: #1a1a2e; border-bottom: 1px solid #2a2a4e;")

    def _build(self):
        L = QHBoxLayout(self)
        L.setContentsMargins(24, 8, 24, 8)
        L.setSpacing(0)

        for i, (num, label) in enumerate(self._steps):
            # Bubble
            bubble = QLabel(num)
            bubble.setFixedSize(28, 28)
            bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bubble.setStyleSheet(
                "background: #252540; color: #606070; border-radius: 14px; "
                "font-weight: bold; font-size: 10pt;"
            )
            L.addWidget(bubble)
            self._bubbles.append(bubble)

            # Label
            step_lbl = QLabel(label)
            step_lbl.setStyleSheet("color: #606070; font-size: 8pt; padding: 0 6px;")
            L.addWidget(step_lbl)

            # Connector line
            if i < len(self._steps) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFixedHeight(1)
                line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                line.setStyleSheet("background: #2a2a4e; border: none;")
                L.addWidget(line, 1)

        self.set_active(0)

    def set_active(self, step: int):
        self._active = step
        for i, bubble in enumerate(self._bubbles):
            if i < step:
                bubble.setStyleSheet(
                    "background: #00CC88; color: white; border-radius: 14px; "
                    "font-weight: bold; font-size: 10pt;"
                )
                bubble.setText("✓")
            elif i == step:
                bubble.setStyleSheet(
                    "background: #00AAFF; color: white; border-radius: 14px; "
                    "font-weight: bold; font-size: 10pt;"
                )
                bubble.setText(self._steps[i][0])
            else:
                bubble.setStyleSheet(
                    "background: #252540; color: #606070; border-radius: 14px; "
                    "font-weight: bold; font-size: 10pt;"
                )
                bubble.setText(self._steps[i][0])
