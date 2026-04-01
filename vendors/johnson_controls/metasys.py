# vendors/johnson_controls/metasys.py
# HBCE — Hybrid Controls Editor
# Johnson Controls Metasys Vendor Profile — V0.1.7-alpha
#
# Covers:
#   NAE / NCE / SNE / SNC field devices
#   FEC / FAC / FX-PCG / VA-9100 controllers
#   MS/TP and BACnet/IP topologies
#
# Metasys-specific knowledge encapsulated here:
#   - Object naming convention: nn:deviceRef/objectRef (Fully Qualified Reference)
#   - Vendor ID: 5 (Johnson Controls)
#   - Proprietary object types: JCI Audit Trail, Energy object
#   - Alarm categories: Life Safety, HVAC, Lighting, Access, Energy
#   - Schedule format: uses WeeklySchedule + SpecialEvents
#   - Priority mapping: JCI Priority 1–16 maps cleanly to BACnet 1–16
#   - Trend log intervals: standard BACnet TrendLog objects

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from comms.base_adapter import (
    BaseCommAdapter, AlarmRecord, DeviceInfo, PointValue, TrendRecord,
)
from data.models import ObjectType, AlarmPriority
from core.logger import get_logger

logger = get_logger(__name__)

# ── Metasys constants ─────────────────────────────────────────────────────────

JCI_VENDOR_ID       = 5
JCI_VENDOR_NAME     = "Johnson Controls"

# Metasys object naming prefix conventions
JCI_OBJECT_PREFIXES = {
    "AI": "analogInput",    "AO": "analogOutput",   "AV": "analogValue",
    "BI": "binaryInput",    "BO": "binaryOutput",   "BV": "binaryValue",
    "MSI":"multiStateInput","MSO":"multiStateOutput","MSV":"multiStateValue",
    "TL": "trendLog",       "SCH":"schedule",        "NC": "notificationClass",
    "PRG":"program",
}

# Metasys alarm category mapping
JCI_ALARM_CATEGORIES = {
    "Life Safety":  AlarmPriority.LIFE_SAFETY,
    "HVAC":         AlarmPriority.HIGH,
    "Lighting":     AlarmPriority.MEDIUM,
    "Access":       AlarmPriority.MED_HIGH,
    "Energy":       AlarmPriority.LOW,
    "General":      AlarmPriority.INFORMATIONAL,
}

# Known JCI controller models and their capabilities
JCI_CONTROLLER_PROFILES = {
    "NAE":   {"type":"network_engine",   "max_objects":10000,"supports_programs":False},
    "NCE":   {"type":"network_engine",   "max_objects":5000, "supports_programs":False},
    "SNE":   {"type":"network_engine",   "max_objects":15000,"supports_programs":False},
    "SNC":   {"type":"network_engine",   "max_objects":15000,"supports_programs":False},
    "FEC":   {"type":"field_controller", "max_objects":500,  "supports_programs":True},
    "FAC":   {"type":"field_controller", "max_objects":500,  "supports_programs":True},
    "VA-9100":{"type":"vav_controller",  "max_objects":150,  "supports_programs":True},
    "FX-PCG":{"type":"field_controller", "max_objects":1000, "supports_programs":True},
}

# ── Metasys-specific data structures ─────────────────────────────────────────

@dataclass
class MetasysObjectRef:
    """Parsed Metasys Fully Qualified Reference (FQR)."""
    site:     str = ""
    device:   str = ""
    object:   str = ""
    property: str = "presentValue"

    @classmethod
    def parse(cls, fqr: str) -> "MetasysObjectRef":
        """Parse  SiteName:DeviceRef/ObjectRef.Property"""
        ref = cls()
        if ":" in fqr:
            ref.site, rest = fqr.split(":", 1)
        else:
            rest = fqr
        if "." in rest:
            rest, ref.property = rest.rsplit(".", 1)
        parts = rest.split("/")
        if len(parts) >= 2:
            ref.device = parts[0]
            ref.object = "/".join(parts[1:])
        else:
            ref.object = rest
        return ref

    def __str__(self) -> str:
        parts = []
        if self.site:   parts.append(f"{self.site}:")
        if self.device: parts.append(f"{self.device}/")
        parts.append(self.object)
        if self.property and self.property != "presentValue":
            parts.append(f".{self.property}")
        return "".join(parts)


@dataclass
class MetasysDeviceProfile:
    """Detected capabilities of a JCI device."""
    vendor_id:          int    = JCI_VENDOR_ID
    vendor_name:        str    = JCI_VENDOR_NAME
    model_identifier:   str    = ""
    firmware_revision:  str    = ""
    controller_family:  str    = ""
    max_apdu_length:    int    = 1476
    segmentation:       str    = "both"
    supports_programs:  bool   = False
    supports_schedules: bool   = True
    supports_trends:    bool   = True
    supports_alarms:    bool   = True
    protocol_version:   int    = 1
    protocol_revision:  int    = 14
    proprietary_objects: List[Dict] = field(default_factory=list)

    def from_device_info(self, info: DeviceInfo) -> "MetasysDeviceProfile":
        self.firmware_revision = info.firmware
        model = info.model.upper()
        for key, profile in JCI_CONTROLLER_PROFILES.items():
            if key in model:
                self.controller_family  = key
                self.supports_programs  = profile["supports_programs"]
                break
        return self

    def capabilities_summary(self) -> str:
        caps = []
        if self.supports_programs:  caps.append("FBD Programming")
        if self.supports_schedules: caps.append("Schedules")
        if self.supports_trends:    caps.append("Trend Logging")
        if self.supports_alarms:    caps.append("Alarm Management")
        return ", ".join(caps) if caps else "Basic BACnet"


# ═══════════════════════════════════════════════════════════════════════════════
#  Metasys Vendor Profile
# ═══════════════════════════════════════════════════════════════════════════════

class MetasysVendorProfile:
    """
    Johnson Controls Metasys vendor knowledge layer.

    Used by the Connection Wizard and all panels to apply
    Metasys-specific translations on top of the generic BACnet adapter.
    Does NOT subclass BaseCommAdapter — it wraps one.
    """

    VENDOR_ID   = JCI_VENDOR_ID
    VENDOR_NAME = JCI_VENDOR_NAME
    VENDOR_KEY  = "johnson_controls"
    DISPLAY_NAME = "Johnson Controls Metasys"

    SUPPORTED_PROTOCOLS = ["bacnet_ip", "bacnet_mstp", "usb_direct"]

    CONNECTION_TEMPLATES = [
        {
            "name":        "NAE/NCE — BACnet/IP (typical)",
            "protocol_id": "bacnet_ip",
            "params":      {"port": 47808, "device_id_low": 1, "device_id_high": 4194303},
            "description": "Network Automation Engine on BACnet/IP. Most common.",
        },
        {
            "name":        "FEC/FAC — BACnet MS/TP",
            "protocol_id": "bacnet_mstp",
            "params":      {"baud_rate": 76800, "mac_address": 1},
            "description": "Field Equipment Controller on RS-485 MS/TP bus.",
        },
        {
            "name":        "VA-9100 — BACnet MS/TP (VAV)",
            "protocol_id": "bacnet_mstp",
            "params":      {"baud_rate": 38400, "mac_address": 1},
            "description": "Variable Air Volume controller on MS/TP.",
        },
    ]

    def __init__(self, adapter: Optional[BaseCommAdapter] = None):
        self.adapter = adapter
        self._device_profiles: Dict[int, MetasysDeviceProfile] = {}

    # ── Device identification ─────────────────────────────────────────────────

    @classmethod
    def is_metasys_device(cls, device_info: DeviceInfo) -> bool:
        return device_info.vendor == JCI_VENDOR_NAME or \
               str(getattr(device_info, "vendor_id", None)) == str(JCI_VENDOR_ID)

    def get_device_profile(self, device_id: int) -> MetasysDeviceProfile:
        if device_id not in self._device_profiles:
            self._device_profiles[device_id] = MetasysDeviceProfile()
        return self._device_profiles[device_id]

    # ── Object naming ─────────────────────────────────────────────────────────

    @staticmethod
    def format_object_name(obj_type_str: str, instance: int,
                           raw_name: str = "") -> str:
        """
        Return a Metasys-style display name for a BACnet object.
        Falls back to raw BACnet name if provided.
        """
        if raw_name:
            return raw_name
        short = ObjectType.from_str(obj_type_str).short()
        return f"{short}-{instance}"

    @staticmethod
    def parse_fqr(fqr: str) -> MetasysObjectRef:
        return MetasysObjectRef.parse(fqr)

    # ── Alarm enrichment ──────────────────────────────────────────────────────

    @staticmethod
    def enrich_alarm(alarm: AlarmRecord,
                     raw: dict) -> AlarmRecord:
        """
        Add Metasys-specific alarm metadata from a raw BACnet alarm dict.
        Maps JCI alarm categories to HBCE AlarmPriority.
        """
        category = raw.get("messageText","General")
        # JCI encodes category in the message text field
        for cat, pri in JCI_ALARM_CATEGORIES.items():
            if cat.lower() in category.lower():
                alarm.category = cat
                alarm.priority = pri
                break
        else:
            alarm.category = "General"
        alarm.device_name = raw.get("sourceName","")
        alarm.event_type  = raw.get("eventType","")
        return alarm

    # ── Schedule translation ──────────────────────────────────────────────────

    @staticmethod
    def bacnet_schedule_to_hbce(raw: dict) -> dict:
        """
        Convert a raw BACnet WeeklySchedule dict (as returned by BAC0)
        to HBCE schedule JSON format.
        """
        blocks = []
        day_map = {
            "monday":0,"tuesday":1,"wednesday":2,"thursday":3,
            "friday":4,"saturday":5,"sunday":6,
        }
        weekly = raw.get("weeklySchedule", {})
        for day_name, day_idx in day_map.items():
            for entry in weekly.get(day_name, []):
                time_str = entry.get("time","00:00")
                value    = entry.get("value", False)
                try:
                    hh, mm = map(int, time_str.split(":"))
                    start_min = hh * 60 + mm
                except Exception:
                    start_min = 0
                blocks.append({
                    "day": day_idx,
                    "start_min": start_min,
                    "end_min":   start_min + 60,   # Metasys uses start+duration
                    "value":     value,
                    "label":     "",
                })
        return {
            "blocks":       blocks,
            "exceptions":   raw.get("exceptionSchedule",[]),
            "holidays":     [],
            "default_value": raw.get("scheduleDefault", False),
        }

    @staticmethod
    def hbce_schedule_to_bacnet(hbce_sched: dict) -> dict:
        """Convert HBCE schedule JSON back to BACnet WeeklySchedule format."""
        day_names = ["monday","tuesday","wednesday","thursday",
                     "friday","saturday","sunday"]
        weekly: Dict[str, List] = {d: [] for d in day_names}
        for b in hbce_sched.get("blocks", []):
            day = b.get("day", 0)
            if 0 <= day <= 6:
                sm = b.get("start_min", 0)
                hh, mm = divmod(sm, 60)
                weekly[day_names[day]].append({
                    "time":  f"{hh:02d}:{mm:02d}",
                    "value": b.get("value", False),
                })
        return {
            "weeklySchedule":   weekly,
            "exceptionSchedule": hbce_sched.get("exceptions",[]),
            "scheduleDefault":   hbce_sched.get("default_value", False),
        }

    # ── Connection parameter hints ─────────────────────────────────────────────

    @staticmethod
    def get_troubleshooting_tips() -> List[str]:
        return [
            "Ensure the NAE/NCE is accessible on the same BACnet/IP network.",
            "BACnet/IP default port is 47808 (0xBAC0). Check firewall rules.",
            "For MS/TP: verify RS-485 baud rate matches device (typically 76800 for FEC).",
            "VAV controllers (VA-9100): use 38400 baud on MS/TP.",
            "If WhoIs returns no devices, check BBMD/foreign-device registration.",
            "Metasys devices require BACnet protocol enabled in the Site Director.",
            "Use Device ID range 1–4194303 for a full WhoIs sweep.",
        ]

    # ── Repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<MetasysVendorProfile adapter={self.adapter!r}>"
