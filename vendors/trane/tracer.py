# vendors/trane/tracer.py
# HBCE — Hybrid Controls Editor
# Trane Tracer Vendor Profile — V0.1.7-alpha
#
# Covers:
#   Tracer SC+ / Tracer UC / Tracer BCX controllers
#   Trane BACnet/IP and MS/TP topologies
#
# Trane-specific knowledge:
#   Vendor ID: 24 (Trane)
#   Object naming: Trane uses descriptive names with spaces (e.g. "Discharge Air Temp")
#   Alarm categories: Equipment, Zone, Network, Safety
#   Tracer SC+: Building supervisor / NAE equivalent
#   Tracer UC: Unitary controller (AHU, RTU)
#   Tracer BCX: Chiller plant controller
#   Priority mapping: Trane manual override = priority 8
#   Proprietary properties: Trane Energy Metering, Runtime Hours

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from comms.base_adapter import AlarmRecord, DeviceInfo
from data.models import AlarmPriority, ObjectType
from core.logger import get_logger

logger = get_logger(__name__)

# ── Trane constants ───────────────────────────────────────────────────────────

TRANE_VENDOR_ID   = 24
TRANE_VENDOR_NAME = "Trane"

TRANE_ALARM_CATEGORIES = {
    "Safety":    AlarmPriority.LIFE_SAFETY,
    "Equipment": AlarmPriority.HIGH,
    "Zone":      AlarmPriority.MEDIUM,
    "Network":   AlarmPriority.LOW,
    "General":   AlarmPriority.INFORMATIONAL,
}

TRANE_CONTROLLER_PROFILES = {
    "SC+":      {"type":"supervisor",       "max_objects":50000,"ms_tp":False},
    "UC400":    {"type":"unitary_ctrl",     "max_objects":800,  "ms_tp":True},
    "UC600":    {"type":"unitary_ctrl",     "max_objects":1200, "ms_tp":True},
    "BCX":      {"type":"chiller_plant",    "max_objects":2000, "ms_tp":False},
    "VAV-X":    {"type":"vav",              "max_objects":200,  "ms_tp":True},
    "BCI-C":    {"type":"bacnet_interface", "max_objects":500,  "ms_tp":True},
}

TRANE_CONNECTION_TEMPLATES = [
    {
        "name":        "Tracer SC+ — BACnet/IP (supervisor)",
        "protocol_id": "bacnet_ip",
        "params":      {"port": 47808},
        "description": "Trane Tracer SC+ building supervisor over BACnet/IP.",
    },
    {
        "name":        "Tracer UC — BACnet MS/TP",
        "protocol_id": "bacnet_mstp",
        "params":      {"baud_rate": 76800, "mac_address": 2},
        "description": "Unitary controller (AHU/RTU) on RS-485 MS/TP.",
    },
    {
        "name":        "Tracer BCX — BACnet/IP (chiller plant)",
        "protocol_id": "bacnet_ip",
        "params":      {"port": 47808},
        "description": "Trane chiller plant controller over BACnet/IP.",
    },
]


@dataclass
class TraneDeviceProfile:
    """Detected capabilities of a Trane device."""
    vendor_id:          int   = TRANE_VENDOR_ID
    vendor_name:        str   = TRANE_VENDOR_NAME
    model_identifier:   str   = ""
    firmware_revision:  str   = ""
    controller_family:  str   = ""
    supports_programs:  bool  = False
    supports_schedules: bool  = True
    supports_trends:    bool  = True
    supports_alarms:    bool  = True
    runtime_hours_prop: Optional[int] = None   # proprietary prop ID
    energy_meter_prop:  Optional[int] = None

    def from_device_info(self, info: DeviceInfo) -> "TraneDeviceProfile":
        self.firmware_revision = info.firmware
        model = info.model.upper()
        for key, profile in TRANE_CONTROLLER_PROFILES.items():
            if key in model:
                self.controller_family = key
                break
        return self

    def capabilities_summary(self) -> str:
        caps = []
        if self.supports_programs:  caps.append("Programs")
        if self.supports_schedules: caps.append("Schedules")
        if self.supports_trends:    caps.append("Trends")
        if self.supports_alarms:    caps.append("Alarms")
        return ", ".join(caps) if caps else "Basic BACnet"


class TraneVendorProfile:
    """
    Trane Tracer vendor knowledge layer.
    Wraps a generic BACnet adapter with Trane-specific translations.
    """

    VENDOR_ID    = TRANE_VENDOR_ID
    VENDOR_NAME  = TRANE_VENDOR_NAME
    VENDOR_KEY   = "trane"
    DISPLAY_NAME = "Trane Tracer"

    SUPPORTED_PROTOCOLS  = ["bacnet_ip", "bacnet_mstp"]
    CONNECTION_TEMPLATES = TRANE_CONNECTION_TEMPLATES

    def __init__(self, adapter=None):
        self.adapter = adapter
        self._device_profiles: Dict[int, TraneDeviceProfile] = {}

    @classmethod
    def is_trane_device(cls, info: DeviceInfo) -> bool:
        return info.vendor == TRANE_VENDOR_NAME or \
               str(getattr(info,"vendor_id",None)) == str(TRANE_VENDOR_ID)

    def get_device_profile(self, device_id: int) -> TraneDeviceProfile:
        if device_id not in self._device_profiles:
            self._device_profiles[device_id] = TraneDeviceProfile()
        return self._device_profiles[device_id]

    @staticmethod
    def format_object_name(obj_type_str: str, instance: int,
                           raw_name: str = "") -> str:
        """Trane devices provide descriptive names — prefer raw_name."""
        if raw_name:
            return raw_name
        return f"{ObjectType.from_str(obj_type_str).short()}-{instance}"

    @staticmethod
    def enrich_alarm(alarm: AlarmRecord, raw: dict) -> AlarmRecord:
        """Map Trane alarm fields to HBCE AlarmRecord."""
        msg = raw.get("messageText","")
        for cat, pri in TRANE_ALARM_CATEGORIES.items():
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
        """Trane schedule format is standard BACnet — pass through with defaults."""
        blocks = []
        day_map = ["monday","tuesday","wednesday","thursday",
                   "friday","saturday","sunday"]
        for day_idx, day_name in enumerate(day_map):
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
            "blocks": blocks,
            "exceptions": raw.get("exceptionSchedule",[]),
            "holidays": [],
            "default_value": raw.get("scheduleDefault", False),
        }

    @staticmethod
    def hbce_schedule_to_bacnet(hbce: dict) -> dict:
        day_names = ["monday","tuesday","wednesday","thursday",
                     "friday","saturday","sunday"]
        weekly: Dict[str, list] = {d:[] for d in day_names}
        for b in hbce.get("blocks",[]):
            day = b.get("day",0)
            if 0 <= day <= 6:
                hh, mm = divmod(b.get("start_min",0), 60)
                weekly[day_names[day]].append({
                    "time":  f"{hh:02d}:{mm:02d}",
                    "value": b.get("value",False),
                })
        return {
            "weeklySchedule":    weekly,
            "exceptionSchedule": hbce.get("exceptions",[]),
            "scheduleDefault":   hbce.get("default_value", False),
        }

    @staticmethod
    def get_troubleshooting_tips() -> List[str]:
        return [
            "Tracer SC+: ensure BACnet/IP is enabled under System → Communications.",
            "UC controllers on MS/TP: verify baud rate (usually 76800).",
            "Trane devices accept WhoIs with device ID range 0–4194303.",
            "For BCX chiller controllers, check that BACnet is licensed.",
            "If discovery fails, try unicast WhoIs to the SC+ IP address directly.",
            "Trane trend logs use standard BACnet TrendLog objects.",
        ]

    def __repr__(self) -> str:
        return f"<TraneVendorProfile adapter={self.adapter!r}>"
