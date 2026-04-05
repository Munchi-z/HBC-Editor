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

GOTCHA (GOTCHA-019): Do NOT pass ip= to BAC0.lite() for MS/TP connections.
ip= is BACnet/IP only. On a serial port BAC0 will attempt a network bind
instead of opening the COM port, producing a confusing socket error.
Correct signature: BAC0.lite(port=, baudrate=, mstp_mac=, max_masters=)
"""

import threading
from datetime import datetime
from typing import Any, Optional

from comms.base_adapter import (
    BaseCommAdapter, DeviceInfo, PointValue, AlarmRecord, TrendRecord
)
from comms.bacnet_helpers import _bacnet_ts_to_str, _logdatum_to_float
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
            # BAC0≥22.9 MS/TP (serial) syntax — no ip= kwarg.
            # ip= is BACnet/IP only; passing it on a serial port causes
            # BAC0 to attempt network binding instead of opening the COM port.
            # mstp_mac  — HBCE's own MAC address on the token-passing ring.
            # max_masters — highest MAC polled during token passing;
            #               reducing it speeds up discovery on small networks.
            self._bacnet = BAC0.lite(
                port=port,
                baudrate=baud,
                mstp_mac=mac,
                max_masters=max_mstr,
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
        """
        Read active alarms via BACnet GetAlarmSummary (network-wide).

        Uses the same BAC0.get_alarm_summary() call as BACnet/IP —
        MS/TP and IP share the same BAC0 network object internals.
        See bacnet_ip.py for full implementation notes.

        device_id == 0  →  all devices on the MS/TP bus
        device_id > 0   →  best-effort (BAC0 summary is network-wide)
        """
        if not self._bacnet:
            return []
        now_str = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                raw = self._bacnet.get_alarm_summary()
            if not raw:
                return []
            records: list[AlarmRecord] = []
            for item in raw:
                try:
                    if hasattr(item, "objectIdentifier"):
                        obj_id    = str(item.objectIdentifier)
                        evt_state = str(item.eventState)
                        ack_bits  = getattr(item, "acknowledgedTransitions", None)
                    else:
                        obj_id    = str(item[0])
                        evt_state = str(item[1])
                        ack_bits  = item[2] if len(item) > 2 else None
                    try:
                        acked = bool(ack_bits[0]) if ack_bits is not None else False
                    except (TypeError, IndexError):
                        acked = False
                    evt_lower = evt_state.lower()
                    priority  = 2 if "fault" in evt_lower else (
                                3 if "offnormal" in evt_lower else 5)
                    records.append(AlarmRecord(
                        timestamp   = now_str,
                        device_id   = device_id,
                        object_ref  = obj_id,
                        description = f"{obj_id}  —  eventState: {evt_state}",
                        priority    = priority,
                        ack_state   = "acknowledged" if acked else "unacknowledged",
                    ))
                except (AttributeError, TypeError, IndexError, KeyError):
                    continue
            logger.info(
                f"BACnet MS/TP read_alarm_summary: {len(records)} active alarm(s)"
            )
            return records
        except NotImplementedError:
            logger.debug("BACnet MS/TP: GetAlarmSummary not supported by device")
            return []
        except AttributeError:
            logger.warning(
                "BACnet MS/TP: bacnet.get_alarm_summary() not available — "
                "ensure BAC0>=22.9 is installed"
            )
            return []
        except Exception as e:
            logger.warning(f"BACnet MS/TP read_alarm_summary failed: {e}")
            return []

    def get_trend_log(
        self,
        device_id:       int,
        object_instance: int,
        count:           int = 100,
    ) -> list[TrendRecord]:
        """
        Read the most recent `count` entries from a BACnet TrendLog object.

        Identical logic to BACnet/IP — both use BAC0's read() method.
        MS/TP is slower than IP; BAC0 handles retries internally.
        See bacnet_ip.py for full implementation notes.
        """
        if not self._bacnet:
            return []
        try:
            addr = self._get_address(device_id)
            with self._lock:
                raw = self._bacnet.read(
                    f"{addr} trendLog {object_instance} logBuffer"
                )
            if not raw:
                return []
            records: list[TrendRecord] = []
            for entry in list(raw)[-count:]:
                try:
                    ts_str = _bacnet_ts_to_str(
                        getattr(entry, "timestamp", None)
                    )
                    value  = _logdatum_to_float(
                        getattr(entry, "logDatum", None)
                    )
                    if value is None:
                        continue
                    records.append(TrendRecord(
                        timestamp = ts_str,
                        value     = value,
                        status    = "good",
                    ))
                except (AttributeError, TypeError, ValueError):
                    continue
            logger.info(
                f"BACnet MS/TP get_trend_log: {len(records)} records "
                f"from trendLog:{object_instance}"
            )
            return records
        except Exception as e:
            logger.warning(
                f"BACnet MS/TP get_trend_log failed "
                f"trendLog:{object_instance}: {e}"
            )
            return []

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
