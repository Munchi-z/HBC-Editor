"""
HBCE — Hybrid Controls Editor
comms/bacnet_mstp.py — BACnet MS/TP (RS-485 Serial) Adapter

Uses BAC0 with a serial port for BACnet MS/TP over RS-485.
Requires a USB-to-RS485 adapter (e.g. USB485-STISO or similar).

GOTCHA (GOTCHA-002): MS/TP MUST have correct COM port + baud rate.
Wrong settings cause BAC0 to hang or hard-crash.
Always validate port + baud before attempting connection.

GOTCHA (GOTCHA-004): RS-485 USB adapters need a driver.
Silently fails on Windows if driver not installed.
HBCE detects adapter presence and prompts for driver install.
"""

import threading
from typing import Any

from comms.base_adapter import (
    BaseCommAdapter, DeviceInfo, PointValue, AlarmRecord, TrendRecord
)
from core.logger import get_logger

logger = get_logger(__name__)

# Standard BACnet MS/TP baud rates
VALID_BAUDS = [9600, 19200, 38400, 57600, 76800]


class BACnetMSTPAdapter(BaseCommAdapter):
    """BACnet MS/TP adapter via RS-485 serial using BAC0."""

    def __init__(self):
        super().__init__()
        self._bacnet = None
        self._lock = threading.Lock()
        self._params = {}

    @property
    def protocol_name(self) -> str:
        return "BACnet MS/TP (RS-485)"

    @property
    def protocol_id(self) -> str:
        return "bacnet_mstp"

    def get_required_params(self) -> list[dict]:
        return [
            {
                "key":      "port",
                "label":    "COM Port",
                "type":     "comport",       # Connection Wizard renders a dropdown
                "default":  "COM1",
                "tooltip":  "The serial COM port your RS-485 adapter is connected to. "
                            "Check Device Manager if unsure (e.g. COM3, COM4).",
                "required": True,
            },
            {
                "key":      "baud",
                "label":    "Baud Rate",
                "type":     "combo",
                "options":  VALID_BAUDS,
                "default":  38400,
                "tooltip":  "Must match the baud rate configured on the controller. "
                            "Common values: 9600, 19200, 38400. Check controller docs.",
                "required": True,
            },
            {
                "key":      "mstp_mac",
                "label":    "My MS/TP MAC Address",
                "type":     "int",
                "default":  127,
                "tooltip":  "The MS/TP MAC address HBCE will use on the bus (0–127). "
                            "Must be unique — do not use an address already taken by a controller.",
                "required": True,
            },
            {
                "key":      "max_masters",
                "label":    "Max Masters",
                "type":     "int",
                "default":  127,
                "tooltip":  "Highest MS/TP MAC address to poll. "
                            "Reduce to speed up token passing on small networks.",
                "required": False,
            },
        ]

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, params: dict) -> bool:
        port     = params.get("port", "COM1")
        baud     = int(params.get("baud", 38400))
        mac      = int(params.get("mstp_mac", 127))
        max_mstr = int(params.get("max_masters", 127))

        # Pre-flight validation
        ok, msg = self._validate_port(port)
        if not ok:
            logger.error(f"BACnet MS/TP: {msg}")
            return False

        if baud not in VALID_BAUDS:
            logger.error(f"BACnet MS/TP: invalid baud rate {baud}. Use one of {VALID_BAUDS}")
            return False

        try:
            import BAC0
            logger.info(
                f"BACnet MS/TP: connecting port={port} baud={baud} "
                f"mac={mac} max_masters={max_mstr}"
            )
            self._bacnet = BAC0.lite(
                port=port,
                baudrate=baud,
                ip=f"127.0.0.1",    # local loopback — BAC0 MS/TP mode
            )
            self._params = params
            self._connected = True
            logger.info("BACnet MS/TP: connected")
            return True

        except ImportError:
            logger.error("BAC0 not installed. Run: pip install BAC0")
            return False
        except Exception as e:
            logger.error(f"BACnet MS/TP connect failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        try:
            if self._bacnet:
                self._bacnet.disconnect()
                self._bacnet = None
            self._connected = False
            logger.info("BACnet MS/TP: disconnected")
        except Exception as e:
            logger.warning(f"BACnet MS/TP disconnect error: {e}")

    def test_connection(self) -> tuple[bool, str]:
        if not self._connected or not self._bacnet:
            return False, "Not connected"
        try:
            devices = self.who_is()
            if devices:
                return True, f"Found {len(devices)} device(s) on MS/TP bus"
            return True, "Connected to MS/TP bus — no devices responded (check baud rate)"
        except Exception as e:
            return False, str(e)

    # ── Discovery ─────────────────────────────────────────────────────────────

    def who_is(self, low: int = 0, high: int = 4194303) -> list[DeviceInfo]:
        if not self._bacnet:
            return []
        try:
            import time
            with self._lock:
                self._bacnet.whois(f"{low} {high}")
            time.sleep(3)  # MS/TP is slower than IP — give it more time
            devices = []
            for dev_id, dev_info in self._bacnet.devices.items():
                devices.append(DeviceInfo(
                    device_id=dev_id,
                    name=str(dev_info.get("name", f"Device {dev_id}")),
                    vendor=str(dev_info.get("vendorName", "Unknown")),
                    address=str(dev_info.get("address", "")),
                    protocol="BACnet MS/TP",
                ))
            return devices
        except Exception as e:
            logger.error(f"BACnet MS/TP WhoIs failed: {e}")
            return []

    def get_object_list(self, device_id: int) -> list[tuple[str, int]]:
        # Delegates same logic as BACnet/IP — share via base or copy
        if not self._bacnet:
            return []
        try:
            addr = self._get_address(device_id)
            with self._lock:
                obj_list = self._bacnet.read(
                    f"{addr} device {device_id} objectList"
                )
            return [(str(o[0]), int(o[1])) for o in obj_list]
        except Exception as e:
            logger.error(f"BACnet MS/TP get_object_list failed: {e}")
            return []

    def read_property(
        self, device_id, object_type, instance, property_id="presentValue"
    ) -> PointValue:
        pv = PointValue(object_type=object_type, instance=instance)
        if not self._bacnet:
            return pv
        try:
            addr = self._get_address(device_id)
            with self._lock:
                value = self._bacnet.read(
                    f"{addr} {object_type} {instance} {property_id}"
                )
            pv.present_value = value
            try:
                with self._lock:
                    pv.name = self._bacnet.read(
                        f"{addr} {object_type} {instance} objectName"
                    )
            except Exception:
                pv.name = f"{object_type}:{instance}"
            return pv
        except Exception as e:
            logger.warning(f"BACnet MS/TP read failed {object_type}:{instance}: {e}")
            return pv

    def write_property(
        self, device_id, object_type, instance, property_id, value, priority=8
    ) -> bool:
        if not self._bacnet:
            return False
        try:
            addr = self._get_address(device_id)
            with self._lock:
                self._bacnet.write(
                    f"{addr} {object_type} {instance} {property_id} {value} - {priority}"
                )
            return True
        except Exception as e:
            logger.error(f"BACnet MS/TP write failed: {e}")
            return False

    def read_alarm_summary(self, device_id: int) -> list[AlarmRecord]:
        return []  # Stub — V0.0.4-alpha

    def get_trend_log(self, device_id, object_instance, count=100) -> list[TrendRecord]:
        return []  # Stub — V0.0.4-alpha

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_address(self, device_id: int) -> str:
        if not self._bacnet:
            raise RuntimeError("Not connected")
        dev = self._bacnet.devices.get(device_id)
        if dev:
            return str(dev.get("address", ""))
        raise ValueError(f"Device {device_id} not in cache — run WhoIs first")

    @staticmethod
    def _validate_port(port: str) -> tuple[bool, str]:
        """
        Check if the COM port exists on this machine before connecting.
        Prevents BAC0 hard-crash on invalid port. (Fixes GOTCHA-002/GOTCHA-004)
        """
        try:
            import serial.tools.list_ports
            available = [p.device for p in serial.tools.list_ports.comports()]
            if port not in available:
                available_str = ", ".join(available) if available else "none found"
                return (
                    False,
                    f"COM port '{port}' not found. Available ports: {available_str}\n"
                    f"If your RS-485 adapter is connected, install its driver first.",
                )
            return True, "OK"
        except ImportError:
            # pyserial not installed — can't validate, proceed anyway
            return True, "OK (pyserial not available for port validation)"

    @staticmethod
    def list_available_ports() -> list[str]:
        """Return list of available COM port names for Connection Wizard dropdown."""
        try:
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()]
        except ImportError:
            return []
