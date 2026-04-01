# vendors/distech/eclypse.py
# HBCE — Hybrid Controls Editor
# Distech Controls ECLYPSE Vendor Profile — V0.1.7-alpha
#
# Covers:
#   EC-BOS (Building Operating System controller)
#   EC-Net / EC-gfxProgram compatible nodes
#   ECLYPSE Connected Thermostat (ECT)
#   EC-Smart-Vue / EC-Smart-Dali
#
# Distech-specific knowledge:
#   Vendor ID: 76 (Distech Controls)
#   Object naming: descriptive with units suffix (e.g. "Zone Temp [°C]")
#   EC-gfxProgram: graphical FBD environment — closest match to HBCE
#   Alarm categories: HVAC, Equipment Fault, IAQ, Comfort
#   Protocol: BACnet/IP primary, BACnet MS/TP on controllers
#   REST API: ECLYPSE devices expose a local REST API (not implemented here)
#   Proprietary: EC-Node-RED flows, Haystack tagging

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from comms.base_adapter import AlarmRecord, DeviceInfo
from data.models import AlarmPriority, ObjectType
from core.logger import get_logger

logger = get_logger(__name__)

# ── Distech constants ─────────────────────────────────────────────────────────

DISTECH_VENDOR_ID   = 76
DISTECH_VENDOR_NAME = "Distech Controls"

DISTECH_ALARM_CATEGORIES = {
    "HVAC":           AlarmPriority.HIGH,
    "Equipment Fault":AlarmPriority.CRITICAL,
    "IAQ":            AlarmPriority.MEDIUM,
    "Comfort":        AlarmPriority.MED_LOW,
    "Energy":         AlarmPriority.LOW,
    "General":        AlarmPriority.INFORMATIONAL,
}

DISTECH_CONTROLLER_PROFILES = {
    "EC-BOS":       {"type":"building_os",   "max_objects":20000,"gfx_programs":True},
    "EC-Smart-Vue": {"type":"room_ctrl",     "max_objects":400,  "gfx_programs":False},
    "EC-Smart-Dali":{"type":"lighting_ctrl", "max_objects":600,  "gfx_programs":False},
    "ECT":          {"type":"thermostat",    "max_objects":200,  "gfx_programs":False},
    "EC-gfx":       {"type":"controller",   "max_objects":1500, "gfx_programs":True},
}

DISTECH_CONNECTION_TEMPLATES = [
    {
        "name":        "EC-BOS — BACnet/IP (primary)",
        "protocol_id": "bacnet_ip",
        "params":      {"port": 47808},
        "description": "ECLYPSE BOS building controller over BACnet/IP.",
    },
    {
        "name":        "EC-Smart-Vue — BACnet MS/TP",
        "protocol_id": "bacnet_mstp",
        "params":      {"baud_rate": 76800, "mac_address": 3},
        "description": "ECLYPSE room controller on MS/TP bus.",
    },
    {
        "name":        "EC-gfxProgram — BACnet/IP",
        "protocol_id": "bacnet_ip",
        "params":      {"port": 47808},
        "description": "EC-gfx graphical FBD controller over BACnet/IP.",
    },
]


@dataclass
class DistechHaystackTag:
    """
    A Haystack marker or value tag used by ECLYPSE for semantic tagging.
    ECLYPSE exposes tags via proprietary BACnet properties.
    """
    tag:   str
    value: Any = True   # True = marker tag; string/number = value tag


@dataclass
class DistechDeviceProfile:
    """Detected capabilities of a Distech device."""
    vendor_id:          int   = DISTECH_VENDOR_ID
    vendor_name:        str   = DISTECH_VENDOR_NAME
    model_identifier:   str   = ""
    firmware_revision:  str   = ""
    controller_family:  str   = ""
    supports_programs:  bool  = False   # EC-gfxProgram = True
    supports_schedules: bool  = True
    supports_trends:    bool  = True
    supports_alarms:    bool  = True
    supports_haystack:  bool  = False
    supports_rest_api:  bool  = False
    haystack_tags:      List[DistechHaystackTag] = field(default_factory=list)

    def from_device_info(self, info: DeviceInfo) -> "DistechDeviceProfile":
        self.firmware_revision = info.firmware
        model = info.model
        for key, profile in DISTECH_CONTROLLER_PROFILES.items():
            if key.lower() in model.lower():
                self.controller_family = key
                self.supports_programs = profile["gfx_programs"]
                break
        # EC-BOS and EC-gfx support REST + Haystack
        if self.controller_family in ("EC-BOS","EC-gfx"):
            self.supports_rest_api  = True
            self.supports_haystack  = True
        return self

    def capabilities_summary(self) -> str:
        caps = []
        if self.supports_programs:  caps.append("FBD Programs")
        if self.supports_schedules: caps.append("Schedules")
        if self.supports_trends:    caps.append("Trends")
        if self.supports_alarms:    caps.append("Alarms")
        if self.supports_haystack:  caps.append("Haystack Tags")
        if self.supports_rest_api:  caps.append("REST API")
        return ", ".join(caps) if caps else "Basic BACnet"


class DistechVendorProfile:
    """
    Distech Controls ECLYPSE vendor knowledge layer.
    Wraps a generic BACnet adapter with ECLYPSE-specific translations.
    """

    VENDOR_ID    = DISTECH_VENDOR_ID
    VENDOR_NAME  = DISTECH_VENDOR_NAME
    VENDOR_KEY   = "distech"
    DISPLAY_NAME = "Distech Controls ECLYPSE"

    SUPPORTED_PROTOCOLS  = ["bacnet_ip", "bacnet_mstp"]
    CONNECTION_TEMPLATES = DISTECH_CONNECTION_TEMPLATES

    def __init__(self, adapter=None):
        self.adapter = adapter
        self._device_profiles: Dict[int, DistechDeviceProfile] = {}

    @classmethod
    def is_distech_device(cls, info: DeviceInfo) -> bool:
        return info.vendor == DISTECH_VENDOR_NAME or \
               str(getattr(info,"vendor_id",None)) == str(DISTECH_VENDOR_ID)

    def get_device_profile(self, device_id: int) -> DistechDeviceProfile:
        if device_id not in self._device_profiles:
            self._device_profiles[device_id] = DistechDeviceProfile()
        return self._device_profiles[device_id]

    @staticmethod
    def format_object_name(obj_type_str: str, instance: int,
                           raw_name: str = "") -> str:
        """
        ECLYPSE names often include units in brackets — preserve them.
        Example: 'Zone Temp [°C]' → keep as-is.
        """
        if raw_name:
            return raw_name
        return f"{ObjectType.from_str(obj_type_str).short()}-{instance}"

    @staticmethod
    def strip_unit_suffix(name: str) -> Tuple[str, str]:
        """
        Split 'Zone Temp [°C]' into ('Zone Temp', '°C').
        Returns (name, unit).
        """
        import re
        m = re.match(r"^(.*?)\s*\[([^\]]+)\]\s*$", name)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return name, ""

    @staticmethod
    def enrich_alarm(alarm: AlarmRecord, raw: dict) -> AlarmRecord:
        msg = raw.get("messageText","")
        for cat, pri in DISTECH_ALARM_CATEGORIES.items():
            if cat.lower() in msg.lower():
                alarm.category = cat
                alarm.priority = pri
                break
        else:
            alarm.category = "General"
        alarm.device_name = raw.get("sourceName","")
        return alarm

    @staticmethod
    def bacnet_schedule_to_hbce(raw: dict) -> dict:
        """ECLYPSE uses standard BACnet WeeklySchedule — same as Trane."""
        blocks = []
        day_names = ["monday","tuesday","wednesday","thursday",
                     "friday","saturday","sunday"]
        for day_idx, day_name in enumerate(day_names):
            for entry in raw.get("weeklySchedule",{}).get(day_name,[]):
                try:
                    hh, mm = map(int, entry.get("time","00:00").split(":"))
                    start_min = hh*60 + mm
                except Exception:
                    start_min = 0
                blocks.append({
                    "day": day_idx, "start_min": start_min,
                    "end_min": start_min+60,
                    "value": entry.get("value",False), "label":"",
                })
        return {
            "blocks":        blocks,
            "exceptions":    raw.get("exceptionSchedule",[]),
            "holidays":      [],
            "default_value": raw.get("scheduleDefault",False),
        }

    @staticmethod
    def hbce_schedule_to_bacnet(hbce: dict) -> dict:
        day_names = ["monday","tuesday","wednesday","thursday",
                     "friday","saturday","sunday"]
        weekly: Dict[str,list] = {d:[] for d in day_names}
        for b in hbce.get("blocks",[]):
            day = b.get("day",0)
            if 0 <= day <= 6:
                hh, mm = divmod(b.get("start_min",0),60)
                weekly[day_names[day]].append({
                    "time":  f"{hh:02d}:{mm:02d}",
                    "value": b.get("value",False),
                })
        return {
            "weeklySchedule":    weekly,
            "exceptionSchedule": hbce.get("exceptions",[]),
            "scheduleDefault":   hbce.get("default_value",False),
        }

    # ── Haystack tag helpers ──────────────────────────────────────────────────

    @staticmethod
    def make_haystack_tags(point_name: str, obj_type_str: str) -> List[dict]:
        """
        Generate Project Haystack tags for a point based on its name and type.
        ECLYPSE uses Haystack for semantic tagging.
        """
        tags: List[dict] = [{"tag":"point","value":True}]
        name_lower = point_name.lower()
        ot = ObjectType.from_str(obj_type_str)

        # Sensor vs cmd
        if ot in (ObjectType.ANALOG_INPUT, ObjectType.BINARY_INPUT):
            tags.append({"tag":"sensor","value":True})
        elif ot in (ObjectType.ANALOG_OUTPUT, ObjectType.BINARY_OUTPUT):
            tags.append({"tag":"cmd","value":True})
        else:
            tags.append({"tag":"sp","value":True})

        # Common semantic tags from name
        KEYWORDS = {
            "temp":      "temp",    "temperature":"temp",
            "humid":     "humidity","humidity":   "humidity",
            "co2":       "co2",     "pressure":   "pressure",
            "flow":      "flow",    "power":      "power",
            "energy":    "energy",  "speed":      "speed",
            "occupancy": "occupied","damper":      "damper",
            "valve":     "valve",   "fan":         "fan",
            "pump":      "pump",    "chiller":     "chiller",
            "boiler":    "boiler",  "vav":         "vav",
        }
        for kw, tag in KEYWORDS.items():
            if kw in name_lower:
                tags.append({"tag":tag,"value":True})

        return tags

    @staticmethod
    def get_troubleshooting_tips() -> List[str]:
        return [
            "ECLYPSE devices: BACnet/IP must be enabled in EC-Net Network settings.",
            "Default BACnet port: 47808. Verify no port conflict with EC-Net.",
            "EC-gfxProgram controllers: programs uploaded via FTP or EC-Net.",
            "For MS/TP EC-Smart-Vue: baud rate is typically 76800.",
            "If Haystack tags are needed, use the ECLYPSE REST API (port 443).",
            "ECLYPSE firmware ≥ 2.6 required for full BACnet/SC support.",
            "EC-BOS: use the device's IP address for unicast WhoIs if broadcast fails.",
        ]

    def __repr__(self) -> str:
        return f"<DistechVendorProfile adapter={self.adapter!r}>"


# Fix missing import in strip_unit_suffix
from typing import Tuple
