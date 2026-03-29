"""
HBCE — Hybrid Controls Editor
comms/base_adapter.py — Abstract base class for all communication adapters

All protocol adapters (BACnet/IP, MS/TP, USB, Modbus, future Bluetooth/WiFi)
must implement this interface. The Connection Wizard and all panels use ONLY
this interface — they never talk to a specific adapter directly.

To add a new protocol:
  1. Create a new file in comms/ (or comms/plugins/)
  2. Subclass BaseCommAdapter
  3. Implement all abstract methods
  4. Register your adapter in comms/__init__.py
  The Connection Wizard auto-discovers all registered adapters.
"""

from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    """Information about a discovered device."""
    device_id:    int    = 0
    name:         str    = ""
    vendor:       str    = ""
    model:        str    = ""
    address:      str    = ""
    protocol:     str    = ""
    firmware:     str    = ""
    description:  str    = ""


@dataclass
class PointValue:
    """A single point read result."""
    object_type:    str  = ""
    instance:       int  = 0
    name:           str  = ""
    present_value:  Any  = None
    units:          str  = ""
    status_flags:   list = field(default_factory=list)
    priority_array: list = field(default_factory=list)
    out_of_service: bool = False


@dataclass
class AlarmRecord:
    """A single alarm record."""
    timestamp:    str  = ""
    device_id:    int  = 0
    object_ref:   str  = ""
    description:  str  = ""
    priority:     int  = 0
    ack_state:    str  = "unacknowledged"


@dataclass
class TrendRecord:
    """A single trend log entry."""
    timestamp:  str   = ""
    value:      float = 0.0
    status:     str   = "good"


class BaseCommAdapter(ABC):
    """
    Abstract base class for all HBCE communication adapters.

    Subclass this and implement all abstract methods to support
    a new protocol. Drop the file into comms/ or comms/plugins/.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Human-readable protocol name, e.g. 'BACnet/IP'"""
        ...

    @property
    @abstractmethod
    def protocol_id(self) -> str:
        """Short identifier used in config, e.g. 'bacnet_ip'"""
        ...

    @property
    def is_connected(self) -> bool:
        """Returns True if currently connected."""
        return self._connected

    def __init__(self):
        self._connected = False

    # ── Connection ────────────────────────────────────────────────────────────

    @abstractmethod
    def connect(self, params: dict) -> bool:
        """
        Establish connection using the provided parameters.
        Returns True on success, False on failure.
        Sets self._connected appropriately.

        Params dict keys vary by protocol — see each adapter for details.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection and clean up resources."""
        ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """
        Quick connectivity test.
        Returns (success: bool, message: str).
        Used by the Connection Wizard's "Test Connection" step.
        """
        ...

    # ── Device Discovery ──────────────────────────────────────────────────────

    @abstractmethod
    def who_is(self, low: int = 0, high: int = 4194303) -> list[DeviceInfo]:
        """
        Discover devices on the network.
        BACnet: sends WhoIs, returns list of DeviceInfo from IAm responses.
        Modbus: pings the configured unit ID, returns single DeviceInfo.
        """
        ...

    # ── Point Read / Write ────────────────────────────────────────────────────

    @abstractmethod
    def read_property(
        self,
        device_id:   int,
        object_type: str,
        instance:    int,
        property_id: str = "presentValue",
    ) -> PointValue:
        """Read a single property from a device object."""
        ...

    @abstractmethod
    def write_property(
        self,
        device_id:   int,
        object_type: str,
        instance:    int,
        property_id: str,
        value:       Any,
        priority:    int = 8,
    ) -> bool:
        """
        Write a value to a device object property.
        Priority 1–16 (BACnet priority array); 8 = manual operator.
        Returns True on success.
        """
        ...

    def read_multiple(
        self,
        device_id: int,
        object_list: list[tuple],
    ) -> list[PointValue]:
        """
        Read multiple properties in one request (ReadPropertyMultiple).
        Default: loop over read_property. Override for efficiency.
        object_list: list of (object_type, instance, property_id) tuples.
        """
        results = []
        for obj_type, instance, prop_id in object_list:
            try:
                val = self.read_property(device_id, obj_type, instance, prop_id)
                results.append(val)
            except Exception:
                results.append(PointValue(object_type=obj_type, instance=instance))
        return results

    # ── Object Discovery ──────────────────────────────────────────────────────

    @abstractmethod
    def get_object_list(self, device_id: int) -> list[tuple[str, int]]:
        """
        Return all objects on a device as list of (object_type, instance) tuples.
        BACnet: reads the objectList property of the device object.
        Modbus: returns register map entries.
        """
        ...

    # ── Alarms ────────────────────────────────────────────────────────────────

    @abstractmethod
    def read_alarm_summary(self, device_id: int) -> list[AlarmRecord]:
        """
        Read current alarm summary from device.
        BACnet: GetAlarmSummary service.
        Modbus: read alarm coil/register map.
        """
        ...

    def acknowledge_alarm(
        self,
        device_id:   int,
        object_type: str,
        instance:    int,
        timestamp:   str,
        ack_text:    str = "Acknowledged via HBCE",
    ) -> bool:
        """
        Acknowledge a BACnet alarm. Returns True on success.
        Modbus adapters can override with a write to an alarm-reset register.
        Default: not implemented (return False).
        """
        return False

    # ── Trend Logs ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_trend_log(
        self,
        device_id: int,
        object_instance: int,
        count: int = 100,
    ) -> list[TrendRecord]:
        """
        Read trend log entries from a TrendLog object.
        Returns the most recent `count` records.
        """
        ...

    # ── Schedules ─────────────────────────────────────────────────────────────

    def get_schedule(self, device_id: int, object_instance: int) -> dict:
        """Read a Schedule object. Returns schedule dict. Override to implement."""
        return {}

    def write_schedule(
        self, device_id: int, object_instance: int, schedule: dict
    ) -> bool:
        """Write a Schedule object. Override to implement."""
        return False

    # ── Backup / Restore ──────────────────────────────────────────────────────

    def backup_device(self, device_id: int) -> dict:
        """
        Read full configuration from device for backup.
        Returns a dict that can be serialized to .hbcebak JSON.
        Override in each adapter to capture vendor-specific data.
        """
        return {"device_id": device_id, "objects": []}

    def restore_device(self, device_id: int, backup_data: dict) -> bool:
        """
        Restore a device configuration from backup dict.
        Returns True on success.
        """
        return False

    # ── Utility ───────────────────────────────────────────────────────────────

    def get_required_params(self) -> list[dict]:
        """
        Return a list of parameter descriptors for the Connection Wizard UI.
        Each dict: { 'key': str, 'label': str, 'type': str, 'default': any,
                     'tooltip': str, 'required': bool }
        """
        return []

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<{self.__class__.__name__} [{self.protocol_name}] {status}>"
