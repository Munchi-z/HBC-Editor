# data/models.py
# HBCE — Hybrid Controls Editor
# Core domain dataclasses — V0.1.7-alpha
#
# These are the canonical in-memory representations of every object
# HBCE works with.  UI panels, adapters, and the project serialiser
# all speak this language — never raw dicts from the DB.
#
# Nothing here imports Qt or any comms library; this module is
# deliberately dependency-free so it can be imported anywhere.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, auto
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  Enumerations
# ═══════════════════════════════════════════════════════════════════════════════

class UserRole(IntEnum):
    OPERATOR    = 1
    TECHNICIAN  = 2
    ADMIN       = 3

    @classmethod
    def from_str(cls, s: str) -> "UserRole":
        return {"Operator": cls.OPERATOR,
                "Technician": cls.TECHNICIAN,
                "Admin": cls.ADMIN}.get(s, cls.OPERATOR)

    def label(self) -> str:
        return {1: "Operator", 2: "Technician", 3: "Admin"}[self.value]


class AlarmPriority(IntEnum):
    LIFE_SAFETY    = 1
    CRITICAL       = 2
    HIGH           = 3
    MED_HIGH       = 4
    MEDIUM         = 5
    MED_LOW        = 6
    LOW            = 7
    INFORMATIONAL  = 8

    def label(self) -> str:
        return {
            1: "Life Safety", 2: "Critical", 3: "High",
            4: "Med-High",    5: "Medium",   6: "Med-Low",
            7: "Low",         8: "Informational",
        }[self.value]

    def color_hex(self) -> str:
        return {
            1: "#7B0000", 2: "#B71C1C", 3: "#E53935",
            4: "#EF6C00", 5: "#F9A825", 6: "#C6CC16",
            7: "#558B2F", 8: "#37474F",
        }[self.value]


class AlarmState(IntEnum):
    ACTIVE_UNACKED  = 1
    ACTIVE_ACKED    = 2
    CLEARED_UNACKED = 3
    CLEARED_ACKED   = 4
    NORMAL          = 5

    def label(self) -> str:
        return {
            1: "Active / Unacked", 2: "Active / Acked",
            3: "Cleared / Unacked", 4: "Cleared / Acked",
            5: "Normal",
        }[self.value]

    @property
    def is_active(self) -> bool:
        return self.value in (1, 2)


class ProtocolKind(IntEnum):
    BACNET_IP   = 1
    BACNET_MSTP = 2
    MODBUS_TCP  = 3
    MODBUS_RTU  = 4
    USB_DIRECT  = 5
    UNKNOWN     = 99

    @classmethod
    def from_str(cls, s: str) -> "ProtocolKind":
        return {
            "bacnet_ip":   cls.BACNET_IP,
            "bacnet_mstp": cls.BACNET_MSTP,
            "modbus_tcp":  cls.MODBUS_TCP,
            "modbus_rtu":  cls.MODBUS_RTU,
            "usb_direct":  cls.USB_DIRECT,
        }.get(s.lower(), cls.UNKNOWN)

    def label(self) -> str:
        return {
            1: "BACnet/IP",   2: "BACnet MS/TP",
            3: "Modbus TCP",  4: "Modbus RTU",
            5: "USB Direct",  99: "Unknown",
        }[self.value]


class ObjectType(IntEnum):
    """BACnet / HBCE object type codes."""
    ANALOG_INPUT   = 0
    ANALOG_OUTPUT  = 1
    ANALOG_VALUE   = 2
    BINARY_INPUT   = 3
    BINARY_OUTPUT  = 4
    BINARY_VALUE   = 5
    MULTI_INPUT    = 13
    MULTI_OUTPUT   = 14
    MULTI_VALUE    = 19
    TREND_LOG      = 20
    SCHEDULE       = 17
    NOTIFICATION   = 15
    PROGRAM        = 16
    DEVICE         = 8
    UNKNOWN        = 999

    @classmethod
    def from_str(cls, s: str) -> "ObjectType":
        _MAP = {
            "analogInput": cls.ANALOG_INPUT,
            "analogOutput": cls.ANALOG_OUTPUT,
            "analogValue": cls.ANALOG_VALUE,
            "binaryInput": cls.BINARY_INPUT,
            "binaryOutput": cls.BINARY_OUTPUT,
            "binaryValue": cls.BINARY_VALUE,
            "multiStateInput": cls.MULTI_INPUT,
            "multiStateOutput": cls.MULTI_OUTPUT,
            "multiStateValue": cls.MULTI_VALUE,
            "trendLog": cls.TREND_LOG,
            "schedule": cls.SCHEDULE,
            "notificationClass": cls.NOTIFICATION,
            "program": cls.PROGRAM,
            "device": cls.DEVICE,
        }
        return _MAP.get(s, cls.UNKNOWN)

    def label(self) -> str:
        return {
            0:"Analog Input",    1:"Analog Output",   2:"Analog Value",
            3:"Binary Input",    4:"Binary Output",   5:"Binary Value",
            13:"MS Input",       14:"MS Output",      19:"MS Value",
            20:"Trend Log",      17:"Schedule",       15:"Notification",
            16:"Program",        8:"Device",          999:"Unknown",
        }.get(self.value, "Unknown")

    def short(self) -> str:
        return {
            0:"AI", 1:"AO", 2:"AV",
            3:"BI", 4:"BO", 5:"BV",
            13:"MSI", 14:"MSO", 19:"MSV",
            20:"TL", 17:"SCH", 15:"NC",
            16:"PRG", 8:"DEV",
        }.get(self.value, "?")


# ═══════════════════════════════════════════════════════════════════════════════
#  Core domain objects
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class User:
    user_id:    int
    username:   str
    role:       UserRole
    created:    str         = ""
    last_login: str         = ""

    @classmethod
    def from_db_row(cls, row: dict) -> "User":
        return cls(
            user_id    = row.get("id", 0),
            username   = row.get("username", ""),
            role       = UserRole.from_str(row.get("role", "Operator")),
            created    = row.get("created", ""),
            last_login = row.get("last_login", ""),
        )


@dataclass
class Device:
    """A controller/device reachable via any supported protocol."""
    device_id:     int                    = 0
    name:          str                    = ""
    vendor:        str                    = ""
    model:         str                    = ""
    firmware:      str                    = ""
    address:       str                    = ""
    protocol:      ProtocolKind           = ProtocolKind.UNKNOWN
    protocol_id:   str                    = ""
    params:        Dict[str, Any]         = field(default_factory=dict)
    description:   str                    = ""
    # BACnet-specific
    bacnet_instance: Optional[int]        = None
    vendor_id:       Optional[int]        = None
    # Runtime (not persisted)
    is_connected:  bool                   = False
    db_id:         Optional[int]          = None   # devices.id in SQLite

    @classmethod
    def from_db_row(cls, row: dict, params: dict = None) -> "Device":
        import json as _json
        raw_params = params or {}
        if "params_json" in row and row["params_json"]:
            try:
                raw_params = _json.loads(row["params_json"])
            except Exception:
                pass
        return cls(
            db_id      = row.get("id"),
            name       = row.get("name",""),
            vendor     = row.get("vendor",""),
            model      = row.get("model",""),
            protocol_id= row.get("protocol",""),
            protocol   = ProtocolKind.from_str(row.get("protocol","")),
            params     = raw_params,
        )

    def to_db_dict(self) -> dict:
        import json as _json
        return {
            "name":        self.name,
            "vendor":      self.vendor,
            "model":       self.model,
            "protocol":    self.protocol_id or self.protocol.name.lower(),
            "params_json": _json.dumps(self.params),
        }


@dataclass
class Point:
    """A single BACnet/Modbus data point on a device."""
    object_type:    ObjectType          = ObjectType.UNKNOWN
    instance:       int                 = 0
    name:           str                 = ""
    description:    str                 = ""
    present_value:  Any                 = None
    units:          str                 = ""
    status_flags:   List[str]           = field(default_factory=list)
    priority_array: List[Any]           = field(default_factory=lambda: [None]*16)
    out_of_service: bool                = False
    cov_increment:  float               = 0.0
    # Runtime
    device_id:      int                 = 0
    is_override:    bool                = False
    last_read:      Optional[str]       = None

    @property
    def object_id(self) -> str:
        return f"{self.object_type.short()}-{self.instance}"

    @property
    def is_writable(self) -> bool:
        return self.object_type in (
            ObjectType.ANALOG_OUTPUT, ObjectType.ANALOG_VALUE,
            ObjectType.BINARY_OUTPUT, ObjectType.BINARY_VALUE,
            ObjectType.MULTI_OUTPUT,  ObjectType.MULTI_VALUE,
        )

    @property
    def is_binary(self) -> bool:
        return self.object_type in (
            ObjectType.BINARY_INPUT, ObjectType.BINARY_OUTPUT,
            ObjectType.BINARY_VALUE,
        )

    @property
    def active_priority(self) -> Optional[int]:
        """Return the highest-priority (lowest number) non-null level, or None."""
        for i, v in enumerate(self.priority_array):
            if v is not None:
                return i + 1
        return None

    def value_str(self) -> str:
        """Human-readable present value."""
        if self.present_value is None:
            return "—"
        if self.is_binary:
            return "ON" if self.present_value else "OFF"
        if isinstance(self.present_value, float):
            return f"{self.present_value:.2f} {self.units}".strip()
        return str(self.present_value)


@dataclass
class AlarmRecord:
    """A single alarm event/condition."""
    alarm_id:     int                   = 0
    timestamp:    str                   = ""
    age_seconds:  float                 = 0.0
    device_id:    int                   = 0
    device_name:  str                   = ""
    object_ref:   str                   = ""
    description:  str                   = ""
    priority:     AlarmPriority         = AlarmPriority.INFORMATIONAL
    state:        AlarmState            = AlarmState.NORMAL
    category:     str                   = "General"
    acked_by:     str                   = ""
    ack_time:     str                   = ""
    ack_note:     str                   = ""
    # BACnet
    notification_class: int             = 0
    event_type:         str             = ""

    @property
    def age_label(self) -> str:
        s = self.age_seconds
        if s < 60:    return f"{int(s)}s"
        if s < 3600:  return f"{int(s/60)}m"
        if s < 86400: return f"{int(s/3600)}h"
        return f"{int(s/86400)}d"

    @classmethod
    def from_db_row(cls, row: dict) -> "AlarmRecord":
        return cls(
            alarm_id    = row.get("id", 0),
            timestamp   = row.get("timestamp",""),
            device_id   = row.get("device_id", 0) or 0,
            object_ref  = row.get("object_ref",""),
            description = row.get("description",""),
            priority    = AlarmPriority(min(8, max(1, row.get("priority",8)))),
            acked_by    = row.get("ack_by","") or "",
            ack_time    = row.get("ack_time","") or "",
        )


@dataclass
class TrendSample:
    """One data point in a trend log."""
    timestamp:  float   = 0.0   # Unix epoch float
    value:      float   = 0.0
    status:     str     = "good"    # "good" | "bad" | "uncertain"

    @property
    def dt(self) -> Optional[datetime]:
        try:
            if 1e6 < self.timestamp < 32503680000:
                return datetime.fromtimestamp(self.timestamp)
        except (OSError, OverflowError, ValueError):
            pass
        return None


@dataclass
class TrendSeries:
    """Named collection of samples for one point."""
    series_id:    str
    device_name:  str
    object_ref:   str
    label:        str
    units:        str
    color_hex:    str           = "#4FC3F7"
    samples:      List[TrendSample] = field(default_factory=list)

    def last_value(self) -> Optional[float]:
        return self.samples[-1].value if self.samples else None


@dataclass
class ScheduleBlock:
    """One ON/OFF block in a weekly schedule grid."""
    day:        int     = 0   # 0=Mon … 6=Sun
    start_min:  int     = 0   # minutes from midnight
    end_min:    int     = 60
    value:      Any     = True   # True/False for binary, float for analog
    label:      str     = ""

    @property
    def start_hhmm(self) -> str:
        return f"{self.start_min//60:02d}:{self.start_min%60:02d}"

    @property
    def end_hhmm(self) -> str:
        return f"{self.end_min//60:02d}:{self.end_min%60:02d}"


@dataclass
class Schedule:
    """Complete weekly schedule for a BACnet Schedule object."""
    schedule_id:     int               = 0
    schedule_name:   str               = ""
    device_name:     str               = "Local"
    object_instance: int               = 0
    blocks:          List[ScheduleBlock] = field(default_factory=list)
    exceptions:      List[dict]        = field(default_factory=list)
    holidays:        List[dict]        = field(default_factory=list)
    default_value:   Any               = False
    last_synced:     str               = ""

    def to_json(self) -> dict:
        return {
            "schedule_name":   self.schedule_name,
            "device_name":     self.device_name,
            "object_instance": self.object_instance,
            "blocks":          [
                {"day": b.day, "start_min": b.start_min,
                 "end_min": b.end_min, "value": b.value, "label": b.label}
                for b in self.blocks
            ],
            "exceptions":  self.exceptions,
            "holidays":    self.holidays,
            "default_value": self.default_value,
        }


@dataclass
class BackupEntry:
    """Metadata for one backup snapshot."""
    backup_id:    int           = 0
    timestamp:    str           = ""
    device_name:  str           = ""
    device_id:    int           = 0
    backup_type:  str           = "manual"    # "manual" | "auto" | "pre_upload"
    file_path:    str           = ""
    size_bytes:   int           = 0
    status:       str           = "ok"        # "ok" | "failed" | "partial"
    notes:        str           = ""
    created_by:   str           = ""

    @property
    def size_label(self) -> str:
        if self.size_bytes < 1024:      return f"{self.size_bytes} B"
        if self.size_bytes < 1048576:   return f"{self.size_bytes/1024:.1f} KB"
        return f"{self.size_bytes/1048576:.1f} MB"


@dataclass
class Program:
    """A graphical FBD/node program saved in HBCE."""
    program_id:   int           = 0
    program_name: str           = "Untitled"
    description:  str           = ""
    device_name:  str           = "Local"
    program_json: dict          = field(default_factory=lambda: {"blocks":[],"wires":[]})
    created_at:   str           = ""
    updated_at:   str           = ""
    created_by:   str           = ""

    @property
    def block_count(self) -> int:
        return len(self.program_json.get("blocks", []))

    @property
    def wire_count(self) -> int:
        return len(self.program_json.get("wires", []))

    @classmethod
    def from_db_row(cls, row: dict) -> "Program":
        import json as _json
        pj = {}
        if row.get("program_json"):
            try: pj = _json.loads(row["program_json"])
            except Exception: pass
        return cls(
            program_id   = row.get("id", 0),
            program_name = row.get("program_name",""),
            description  = row.get("description",""),
            device_name  = row.get("device_name","Local"),
            program_json = pj,
            created_at   = row.get("created_at",""),
            updated_at   = row.get("updated_at",""),
            created_by   = row.get("created_by",""),
        )


@dataclass
class Project:
    """
    Top-level container for an HBCE project.
    Serialised to/from a .hbce ZIP file by data/project.py.
    """
    project_id:    int              = 0
    name:          str              = "New Project"
    description:   str              = ""
    created:       str              = ""
    modified:      str              = ""
    hbce_version:  str              = ""
    devices:       List[Device]     = field(default_factory=list)
    programs:      List[Program]    = field(default_factory=list)
    schedules:     List[Schedule]   = field(default_factory=list)
    backups:       List[BackupEntry]= field(default_factory=list)

    @property
    def device_count(self) -> int:  return len(self.devices)
    @property
    def program_count(self) -> int: return len(self.programs)


# ── Convenience factories ─────────────────────────────────────────────────────

def make_point_from_bacnet(obj_type_str: str, instance: int,
                            name: str = "", value=None,
                            units: str = "") -> Point:
    return Point(
        object_type   = ObjectType.from_str(obj_type_str),
        instance      = instance,
        name          = name,
        present_value = value,
        units         = units,
    )
