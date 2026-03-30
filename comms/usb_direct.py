"""
HBCE — Hybrid Controls Editor
comms/usb_direct.py — USB Direct Connection Adapter

Handles direct USB connections to controllers (e.g. Trane UC800 via USB cable).
USB-direct typically presents as a virtual COM port or CDC device.
In many cases this is a Modbus RTU or proprietary protocol over USB-serial.

V0.0.4-alpha: Detects USB serial devices, presents them for selection,
        then delegates to ModbusRTUAdapter or a vendor-specific handler.
"""

import threading
from typing import Any

from comms.base_adapter import (
    BaseCommAdapter, DeviceInfo, PointValue, AlarmRecord, TrendRecord
)
from core.logger import get_logger

logger = get_logger(__name__)


def list_usb_serial_ports() -> list[dict]:
    """
    Return a list of USB serial ports detected on the system.
    Each entry: { 'port': str, 'description': str, 'hwid': str }
    """
    try:
        import serial.tools.list_ports
        ports = []
        for p in serial.tools.list_ports.comports():
            # Filter to likely USB ports (hwid contains "USB")
            if "USB" in (p.hwid or "").upper() or "USB" in (p.description or "").upper():
                ports.append({
                    "port":        p.device,
                    "description": p.description or p.device,
                    "hwid":        p.hwid or "",
                })
        return ports
    except ImportError:
        return []


class USBDirectAdapter(BaseCommAdapter):
    """
    USB direct connection adapter.
    Wraps a Modbus RTU or BACnet MS/TP connection over a USB-serial device.
    The Connection Wizard auto-detects USB COM ports and presents them.
    """

    def __init__(self):
        super().__init__()
        self._delegate = None   # actual adapter handling the protocol
        self._params = {}

    @property
    def protocol_name(self) -> str:
        return "USB Direct"

    @property
    def protocol_id(self) -> str:
        return "usb_direct"

    def get_required_params(self) -> list[dict]:
        usb_ports = list_usb_serial_ports()
        port_options = [p["port"] for p in usb_ports] or ["No USB devices found"]
        port_descriptions = {p["port"]: p["description"] for p in usb_ports}

        return [
            {
                "key":        "port",
                "label":      "USB Device (COM Port)",
                "type":       "combo",
                "options":    port_options,
                "default":    port_options[0],
                "tooltip":    "Select the USB device to connect to. "
                              "If your device is not listed, check that it is plugged in "
                              "and its driver is installed.",
                "required":   True,
                "port_descriptions": port_descriptions,
            },
            {
                "key":      "usb_protocol",
                "label":    "Device Protocol",
                "type":     "combo",
                "options":  ["Modbus RTU", "BACnet MS/TP"],
                "default":  "Modbus RTU",
                "tooltip":  "The protocol your USB-connected controller uses. "
                            "Trane UC800: Modbus RTU. "
                            "Most BACnet controllers: BACnet MS/TP.",
                "required": True,
            },
            {
                "key":      "baud",
                "label":    "Baud Rate",
                "type":     "combo",
                "options":  [9600, 19200, 38400, 57600, 115200],
                "default":  115200,
                "tooltip":  "USB connections typically use 115200 baud. "
                            "Check your controller documentation.",
                "required": True,
            },
            {
                "key":      "unit_id",
                "label":    "Unit / Slave ID",
                "type":     "int",
                "default":  1,
                "tooltip":  "Device unit ID. Usually 1 for direct USB connection.",
                "required": False,
            },
        ]

    def connect(self, params: dict) -> bool:
        self._params = params
        protocol = params.get("usb_protocol", "Modbus RTU")

        logger.info(
            f"USB Direct: connecting via {protocol} "
            f"on {params.get('port')} @ {params.get('baud')} baud"
        )

        if protocol == "Modbus RTU":
            from comms.modbus_rtu import ModbusRTUAdapter
            self._delegate = ModbusRTUAdapter()
            # Map USB params to Modbus RTU params
            rtu_params = {
                "port":    params.get("port"),
                "baud":    params.get("baud", 115200),
                "parity":  "N",
                "stopbits": 1,
                "timeout": 3.0,
                "unit_id": params.get("unit_id", 1),
            }
            result = self._delegate.connect(rtu_params)

        elif protocol == "BACnet MS/TP":
            from comms.bacnet_mstp import BACnetMSTPAdapter
            self._delegate = BACnetMSTPAdapter()
            mstp_params = {
                "port":        params.get("port"),
                "baud":        params.get("baud", 38400),
                "mstp_mac":    127,
                "max_masters": 127,
            }
            result = self._delegate.connect(mstp_params)
        else:
            logger.error(f"USB Direct: unknown protocol '{protocol}'")
            return False

        if result:
            self._connected = True
            logger.info("USB Direct: connected")
        return result

    def disconnect(self) -> None:
        if self._delegate:
            self._delegate.disconnect()
            self._delegate = None
        self._connected = False
        logger.info("USB Direct: disconnected")

    def test_connection(self) -> tuple[bool, str]:
        if self._delegate:
            return self._delegate.test_connection()
        return False, "Not connected"

    def who_is(self, low=0, high=4194303) -> list[DeviceInfo]:
        if self._delegate:
            devices = self._delegate.who_is(low, high)
            for d in devices:
                d.protocol = "USB Direct"
            return devices
        return []

    def get_object_list(self, device_id: int) -> list[tuple[str, int]]:
        if self._delegate:
            return self._delegate.get_object_list(device_id)
        return []

    def read_property(self, device_id, object_type, instance, property_id="presentValue"):
        if self._delegate:
            return self._delegate.read_property(device_id, object_type, instance, property_id)
        return PointValue(object_type=object_type, instance=instance)

    def write_property(self, device_id, object_type, instance, property_id, value, priority=8):
        if self._delegate:
            return self._delegate.write_property(
                device_id, object_type, instance, property_id, value, priority
            )
        return False

    def read_alarm_summary(self, device_id: int) -> list[AlarmRecord]:
        if self._delegate:
            return self._delegate.read_alarm_summary(device_id)
        return []

    def get_trend_log(self, device_id, object_instance, count=100) -> list[TrendRecord]:
        if self._delegate:
            return self._delegate.get_trend_log(device_id, object_instance, count)
        return []
