"""
HBCE — Hybrid Controls Editor
comms/bacnet_ip.py — BACnet/IP Communication Adapter

Uses BAC0 library for BACnet/IP over Ethernet/WiFi.
Supports: WhoIs/IAm discovery, ReadProperty, WriteProperty,
          ReadPropertyMultiple, GetAlarmSummary, TrendLog reads.

GOTCHA (GOTCHA-007): BAC0 runs its own thread internally.
Never call Qt UI methods directly from BAC0 callbacks.
Always use Qt signals to push data back to the UI thread.
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


class BACnetIPAdapter(BaseCommAdapter):
    """BACnet/IP adapter using the BAC0 library."""

    def __init__(self):
        super().__init__()
        self._bacnet = None   # BAC0 network instance
        self._lock = threading.Lock()

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def protocol_name(self) -> str:
        return "BACnet/IP"

    @property
    def protocol_id(self) -> str:
        return "bacnet_ip"

    def get_required_params(self) -> list[dict]:
        return [
            {
                "key":      "ip",
                "label":    "Local IP Address",
                "type":     "text",
                "default":  "auto",
                "tooltip":  "Your PC's IP address on the BACnet network. "
                            "Use 'auto' to let HBCE detect it.",
                "required": False,
            },
            {
                "key":      "port",
                "label":    "UDP Port",
                "type":     "int",
                "default":  47808,
                "tooltip":  "BACnet/IP UDP port. Default is 47808 (0xBAC0). "
                            "Only change if your network uses a non-standard port.",
                "required": False,
            },
            {
                "key":      "device_id_low",
                "label":    "Device ID Range (Low)",
                "type":     "int",
                "default":  0,
                "tooltip":  "Lowest BACnet Device ID to search for during WhoIs discovery.",
                "required": False,
            },
            {
                "key":      "device_id_high",
                "label":    "Device ID Range (High)",
                "type":     "int",
                "default":  4194303,
                "tooltip":  "Highest BACnet Device ID to search for. "
                            "4194303 is the maximum possible BACnet device ID.",
                "required": False,
            },
        ]

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, params: dict) -> bool:
        try:
            import BAC0
            ip = params.get("ip", "")
            port = int(params.get("port", 47808))

            logger.info(f"BACnet/IP: connecting (ip={ip or 'auto'}, port={port})")

            if ip and ip.lower() != "auto":
                self._bacnet = BAC0.lite(ip=ip, port=port)
            else:
                self._bacnet = BAC0.lite(port=port)

            self._connected = True
            logger.info("BACnet/IP: connected")
            return True

        except ImportError:
            logger.error("BAC0 library not installed. Run: pip install BAC0")
            return False
        except Exception as e:
            logger.error(f"BACnet/IP connect failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        try:
            if self._bacnet:
                self._bacnet.disconnect()
                self._bacnet = None
            self._connected = False
            logger.info("BACnet/IP: disconnected")
        except Exception as e:
            logger.warning(f"BACnet/IP disconnect error: {e}")

    def test_connection(self) -> tuple[bool, str]:
        """Send a WhoIs and check for any response."""
        if not self._connected or not self._bacnet:
            return False, "Not connected"
        try:
            devices = self.who_is(0, 4194303)
            if devices:
                return True, f"Found {len(devices)} device(s) on network"
            return True, "Connected — no devices responded to WhoIs (check device IDs)"
        except Exception as e:
            return False, str(e)

    # ── Discovery ─────────────────────────────────────────────────────────────

    def who_is(self, low: int = 0, high: int = 4194303) -> list[DeviceInfo]:
        if not self._bacnet:
            return []
        try:
            with self._lock:
                self._bacnet.whois(f"{low} {high}")
            import time
            time.sleep(2)  # wait for IAm responses

            devices = []
            for dev_id, dev_info in self._bacnet.devices.items():
                devices.append(DeviceInfo(
                    device_id=dev_id,
                    name=str(dev_info.get("name", f"Device {dev_id}")),
                    vendor=str(dev_info.get("vendorName", "Unknown")),
                    address=str(dev_info.get("address", "")),
                    protocol="BACnet/IP",
                ))
            logger.info(f"BACnet/IP WhoIs: found {len(devices)} device(s)")
            return devices
        except Exception as e:
            logger.error(f"BACnet/IP WhoIs failed: {e}")
            return []

    # ── Read / Write ──────────────────────────────────────────────────────────

    def get_object_list(self, device_id: int) -> list[tuple[str, int]]:
        if not self._bacnet:
            return []
        try:
            with self._lock:
                obj_list = self._bacnet.read(
                    f"{self._get_address(device_id)} device {device_id} objectList"
                )
            result = []
            for obj in obj_list:
                obj_type = str(obj[0])
                instance = int(obj[1])
                result.append((obj_type, instance))
            return result
        except Exception as e:
            logger.error(f"BACnet/IP get_object_list failed for device {device_id}: {e}")
            return []

    def read_property(
        self,
        device_id:   int,
        object_type: str,
        instance:    int,
        property_id: str = "presentValue",
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

            # Also try to get object name
            try:
                with self._lock:
                    pv.name = self._bacnet.read(
                        f"{addr} {object_type} {instance} objectName"
                    )
            except Exception:
                pv.name = f"{object_type}:{instance}"

            return pv
        except Exception as e:
            logger.warning(
                f"BACnet/IP read failed {object_type}:{instance} "
                f"prop={property_id} dev={device_id}: {e}"
            )
            return pv

    def write_property(
        self,
        device_id:   int,
        object_type: str,
        instance:    int,
        property_id: str,
        value:       Any,
        priority:    int = 8,
    ) -> bool:
        if not self._bacnet:
            return False
        try:
            addr = self._get_address(device_id)
            with self._lock:
                self._bacnet.write(
                    f"{addr} {object_type} {instance} {property_id} {value} - {priority}"
                )
            logger.info(
                f"BACnet/IP write: {object_type}:{instance}.{property_id} "
                f"= {value} @ priority {priority}"
            )
            return True
        except Exception as e:
            logger.error(f"BACnet/IP write failed: {e}")
            return False

    # ── Alarms ────────────────────────────────────────────────────────────────

    def read_alarm_summary(self, device_id: int) -> list[AlarmRecord]:
        """
        Read active alarms via BACnet GetAlarmSummary confirmed service.

        device_id == 0  →  network-wide: returns alarms from all discovered
                           devices (BAC0.get_alarm_summary() is inherently
                           network-wide; filtering to a single device is
                           best-effort via the objectIdentifier).
        device_id > 0   →  same network-wide fetch, result is unfiltered
                           (BACnet does not support per-device GetAlarmSummary
                           from a single confirmed request in standard BAC0).

        BAC0≥22.9 returns a list of AlarmSummary namedtuples:
            objectIdentifier        — e.g. ('analogValue', 5)
            eventState              — 'offnormal' | 'fault' | 'normal'
            acknowledgedTransitions — EventTransitionBits (index 0 = toOffNormal)

        Returns [] on any failure so callers always get a clean list.
        """
        if not self._bacnet:
            return []
        now_str = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                raw = self._bacnet.get_alarm_summary()
            if not raw:
                logger.debug("BACnet/IP read_alarm_summary: no active alarms")
                return []

            records: list[AlarmRecord] = []
            for item in raw:
                try:
                    # Support both namedtuple and positional-tuple forms
                    if hasattr(item, "objectIdentifier"):
                        obj_id    = str(item.objectIdentifier)
                        evt_state = str(item.eventState)
                        ack_bits  = getattr(item, "acknowledgedTransitions", None)
                    else:
                        obj_id    = str(item[0])
                        evt_state = str(item[1])
                        ack_bits  = item[2] if len(item) > 2 else None

                    # EventTransitionBits[0] = toOffNormal acknowledged flag
                    try:
                        acked = bool(ack_bits[0]) if ack_bits is not None else False
                    except (TypeError, IndexError):
                        acked = False

                    # Map BACnet event state to HBCE priority (1–8 scale)
                    evt_lower = evt_state.lower()
                    if "fault" in evt_lower:
                        priority = 2   # Critical
                    elif "offnormal" in evt_lower:
                        priority = 3   # High
                    else:
                        priority = 5   # Medium (shouldn't appear; normal = no alarm)

                    records.append(AlarmRecord(
                        timestamp   = now_str,
                        device_id   = device_id,
                        object_ref  = obj_id,
                        description = f"{obj_id}  —  eventState: {evt_state}",
                        priority    = priority,
                        ack_state   = "acknowledged" if acked else "unacknowledged",
                    ))
                except (AttributeError, TypeError, IndexError, KeyError):
                    continue   # skip malformed entries

            logger.info(
                f"BACnet/IP read_alarm_summary: {len(records)} active alarm(s)"
            )
            return records

        except NotImplementedError:
            # Some BACnet devices/stacks explicitly reject GetAlarmSummary
            logger.debug(
                "BACnet/IP: GetAlarmSummary rejected by device (not supported)"
            )
            return []
        except AttributeError:
            # get_alarm_summary() missing — BAC0 build too old or wrong variant
            logger.warning(
                "BACnet/IP: bacnet.get_alarm_summary() not available. "
                "Ensure BAC0>=22.9 is installed."
            )
            return []
        except Exception as e:
            logger.warning(f"BACnet/IP read_alarm_summary failed: {e}")
            return []

    def acknowledge_alarm(
        self,
        device_id:   int,
        object_type: str,
        instance:    int,
        timestamp:   str,
        ack_text:    str = "Acknowledged via HBCE",
    ) -> bool:
        """
        Send an AcknowledgeAlarm confirmed service request via BAC0.

        BAC0≥22.9 does not expose a clean high-level wrapper for
        AcknowledgeAlarm, so we use WriteProperty to set the
        acknowledgedTransitions property, which most controllers accept
        as an equivalent when the Acknowledge Service is not available.

        Falls back gracefully if the controller rejects the write —
        the UI still marks the alarm acknowledged locally in the DB.
        """
        if not self._bacnet:
            return False
        try:
            addr = self._get_address(device_id)
            # Attempt via BAC0 write — sets acknowledgedTransitions
            # to all-True (toOffNormal, toFault, toNormal all acked).
            # Priority 8 = manual operator.
            with self._lock:
                self._bacnet.write(
                    f"{addr} {object_type} {instance} "
                    f"acknowledgedTransitions [True,True,True] - 8"
                )
            logger.info(
                f"BACnet/IP ack alarm: {object_type}:{instance} "
                f"@ {addr}  text='{ack_text}'"
            )
            return True
        except Exception as e:
            # WriteProperty rejection is common — the controller may require
            # the true AcknowledgeAlarm confirmed service.  Log as debug
            # (not warning) since local DB ack still proceeds on the UI side.
            logger.debug(
                f"BACnet/IP acknowledge_alarm write failed "
                f"({object_type}:{instance}): {e} — local ack only"
            )
            return False

    # ── Trends ────────────────────────────────────────────────────────────────

    def get_trend_log(
        self,
        device_id:       int,
        object_instance: int,
        count:           int = 100,
    ) -> list[TrendRecord]:
        """
        Read the most recent `count` entries from a BACnet TrendLog object
        using the logBuffer property.

        BAC0≥22.9 approach: read logBuffer as a plain ReadProperty.
        Each LogRecord entry contains:
          timestamp  — BACnet DateTime
          logDatum   — CHOICE (realValue, booleanValue, integerValue, …)

        Returns empty list on any failure — callers should treat this as
        "no history available" and fall back to live polling if needed.
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
                logger.debug(
                    f"BACnet/IP get_trend_log: empty logBuffer "
                    f"trendLog:{object_instance}"
                )
                return []

            records: list[TrendRecord] = []
            entries = list(raw)[-count:]   # newest `count` entries
            for entry in entries:
                try:
                    ts_str = _bacnet_ts_to_str(
                        getattr(entry, "timestamp", None)
                    )
                    value = _logdatum_to_float(
                        getattr(entry, "logDatum", None)
                    )
                    if value is None:
                        continue   # null / failure / timeChange — skip
                    records.append(TrendRecord(
                        timestamp = ts_str,
                        value     = value,
                        status    = "good",
                    ))
                except (AttributeError, TypeError, ValueError):
                    continue

            logger.info(
                f"BACnet/IP get_trend_log: {len(records)} records "
                f"from trendLog:{object_instance}"
            )
            return records

        except Exception as e:
            logger.warning(
                f"BACnet/IP get_trend_log failed "
                f"trendLog:{object_instance}: {e}"
            )
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_address(self, device_id: int) -> str:
        """Look up the network address for a device_id from the BAC0 device cache."""
        if not self._bacnet:
            raise RuntimeError("Not connected")
        dev = self._bacnet.devices.get(device_id)
        if dev:
            return str(dev.get("address", ""))
        raise ValueError(f"Device {device_id} not found in device cache — run WhoIs first")
