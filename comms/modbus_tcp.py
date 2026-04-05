"""
HBCE — Hybrid Controls Editor
comms/modbus_tcp.py — Modbus TCP Adapter

Uses pymodbus 3.x (IMPORTANT: API differs significantly from 2.x — see GOTCHA-009).
Connects to Modbus TCP devices over Ethernet.
"""

import threading
from typing import Any, Dict

from comms.base_adapter import (
    BaseCommAdapter, DeviceInfo, PointValue, AlarmRecord, TrendRecord
)
from core.logger import get_logger

logger = get_logger(__name__)


class ModbusTCPAdapter(BaseCommAdapter):
    """Modbus TCP adapter using pymodbus 3.x."""

    def __init__(self):
        super().__init__()
        self._client = None
        self._lock = threading.Lock()
        self._params = {}
        # Per-device register maps: {device_id: {"coil": (start, count), ...}}
        # Populated by set_register_map() — called from Point Browser when
        # loading a device whose map has been saved to the DB.
        self._register_maps: Dict[int, Dict[str, tuple]] = {}

    @property
    def protocol_name(self) -> str:
        return "Modbus TCP"

    @property
    def protocol_id(self) -> str:
        return "modbus_tcp"

    def get_required_params(self) -> list[dict]:
        return [
            {
                "key":      "host",
                "label":    "IP Address / Hostname",
                "type":     "text",
                "default":  "192.168.1.1",
                "tooltip":  "IP address or hostname of the Modbus TCP device.",
                "required": True,
            },
            {
                "key":      "port",
                "label":    "TCP Port",
                "type":     "int",
                "default":  502,
                "tooltip":  "Modbus TCP port. Default is 502. "
                            "Some devices use 503 or a custom port.",
                "required": False,
            },
            {
                "key":      "unit_id",
                "label":    "Unit ID (Slave ID)",
                "type":     "int",
                "default":  1,
                "tooltip":  "Modbus unit/slave ID (1–247). "
                            "Most devices use 1. Check your device documentation.",
                "required": False,
            },
            {
                "key":      "timeout",
                "label":    "Timeout (seconds)",
                "type":     "float",
                "default":  3.0,
                "tooltip":  "How long to wait for a response before giving up.",
                "required": False,
            },
        ]

    def connect(self, params: dict) -> bool:
        host    = params.get("host", "192.168.1.1")
        port    = int(params.get("port", 502))
        timeout = float(params.get("timeout", 3.0))
        try:
            # pymodbus 3.x API — do NOT use old ModbusTcpClient syntax
            from pymodbus.client import ModbusTcpClient
            self._client = ModbusTcpClient(host=host, port=port, timeout=timeout)
            result = self._client.connect()
            if result:
                self._connected = True
                self._params = params
                logger.info(f"Modbus TCP: connected to {host}:{port}")
                return True
            else:
                logger.error(f"Modbus TCP: connection refused at {host}:{port}")
                return False
        except ImportError:
            logger.error("pymodbus not installed. Run: pip install pymodbus>=3.5")
            return False
        except Exception as e:
            logger.error(f"Modbus TCP connect failed: {e}")
            return False

    def disconnect(self) -> None:
        try:
            if self._client:
                self._client.close()
                self._client = None
            self._connected = False
            logger.info("Modbus TCP: disconnected")
        except Exception as e:
            logger.warning(f"Modbus TCP disconnect error: {e}")

    def test_connection(self) -> tuple[bool, str]:
        if not self._connected or not self._client:
            return False, "Not connected"
        try:
            unit_id = int(self._params.get("unit_id", 1))
            with self._lock:
                result = self._client.read_holding_registers(0, 1, slave=unit_id)
            if result.isError():
                return False, f"Device responded with error: {result}"
            return True, f"Modbus TCP device responding at unit ID {unit_id}"
        except Exception as e:
            return False, str(e)

    def who_is(self, low: int = 0, high: int = 4194303) -> list[DeviceInfo]:
        """Modbus has no discovery — returns the single configured device."""
        if not self._connected:
            return []
        host = self._params.get("host", "unknown")
        unit = self._params.get("unit_id", 1)
        return [DeviceInfo(
            device_id=int(unit),
            name=f"Modbus Device @ {host}",
            address=host,
            protocol="Modbus TCP",
        )]

    def set_register_map(self, device_id: int, config: Dict[str, tuple]) -> None:
        """
        Store a per-device register map for use by get_object_list().

        Called from Point Browser when loading a device that has a saved
        register map in the DB (stored as JSON in the device's config column).

        config format:
            {
                "coil":             (start_address, count),   # e.g. (0, 256)
                "discrete_input":   (start_address, count),
                "holding_register": (start_address, count),
                "input_register":   (start_address, count),
            }
        Any key can be omitted to suppress that register type entirely.

        Example — 64-coil relay board:
            adapter.set_register_map(1, {"coil": (0, 64)})
        """
        self._register_maps[device_id] = config
        logger.info(
            f"Modbus TCP: register map set for device {device_id}: {config}"
        )

    def get_register_map(self, device_id: int) -> Dict[str, tuple]:
        """Return the stored register map for device_id, or the default."""
        return self._register_maps.get(device_id, self._default_register_map())

    @staticmethod
    def _default_register_map() -> Dict[str, tuple]:
        """
        Default register map when no device-specific map has been configured.
        Covers the practical range of most Modbus field devices:
          coils / discrete inputs : 0 – 9999  (10,000 points)
          holding / input registers: 0 – 9999  (10,000 registers)
        The Point Browser will only display points that respond without error,
        so padding doesn't cause false positives — it just determines how far
        the scan goes.
        """
        return {
            "coil":             (0, 10_000),
            "discrete_input":   (0, 10_000),
            "holding_register": (0, 10_000),
            "input_register":   (0, 10_000),
        }

    def get_object_list(self, device_id: int) -> list[tuple[str, int]]:
        """
        Return the list of (register_type, address) pairs for this device.

        Priority order:
          1. Device-specific map set via set_register_map()  ← DB-stored config
          2. Default map (0–9999 for all four register types)

        Modbus has no protocol-level discovery — this is always a configured
        or assumed range.  The Point Browser filters the list by actually
        attempting reads and discarding addresses that return errors.
        """
        reg_map = self.get_register_map(device_id)
        result = []
        for reg_type, (start, count) in reg_map.items():
            result.extend((reg_type, addr) for addr in range(start, start + count))
        logger.debug(
            f"Modbus TCP get_object_list device={device_id}: "
            f"{len(result)} addresses across {len(reg_map)} register type(s)"
        )
        return result

    def read_property(
        self, device_id, object_type, instance, property_id="presentValue"
    ) -> PointValue:
        pv = PointValue(object_type=object_type, instance=instance)
        if not self._client:
            return pv
        unit = int(self._params.get("unit_id", 1))
        try:
            with self._lock:
                if object_type == "coil":
                    r = self._client.read_coils(instance, 1, slave=unit)
                    if not r.isError():
                        pv.present_value = r.bits[0]
                elif object_type == "discrete_input":
                    r = self._client.read_discrete_inputs(instance, 1, slave=unit)
                    if not r.isError():
                        pv.present_value = r.bits[0]
                elif object_type == "holding_register":
                    r = self._client.read_holding_registers(instance, 1, slave=unit)
                    if not r.isError():
                        pv.present_value = r.registers[0]
                elif object_type == "input_register":
                    r = self._client.read_input_registers(instance, 1, slave=unit)
                    if not r.isError():
                        pv.present_value = r.registers[0]
            pv.name = f"{object_type}[{instance}]"
            return pv
        except Exception as e:
            logger.warning(f"Modbus TCP read failed {object_type}:{instance}: {e}")
            return pv

    def write_property(
        self, device_id, object_type, instance, property_id, value, priority=8
    ) -> bool:
        if not self._client:
            return False
        unit = int(self._params.get("unit_id", 1))
        try:
            with self._lock:
                if object_type == "coil":
                    r = self._client.write_coil(instance, bool(value), slave=unit)
                elif object_type == "holding_register":
                    r = self._client.write_register(instance, int(value), slave=unit)
                else:
                    logger.warning(f"Modbus TCP: cannot write to {object_type}")
                    return False
            return not r.isError()
        except Exception as e:
            logger.error(f"Modbus TCP write failed: {e}")
            return False

    def read_alarm_summary(self, device_id: int) -> list[AlarmRecord]:
        """
        Modbus TCP has no native alarm or event service.

        Alarm detection for Modbus devices must be done at the application
        layer by comparing register/coil values against configured thresholds.
        That is the responsibility of the Alarm Viewer's threshold-check logic
        (future ITEM-ALARM-001), not the adapter.

        Returns [] intentionally — this is not a stub.
        """
        return []

    def get_trend_log(
        self,
        device_id:       int,
        object_instance: int,
        count:           int = 100,
    ) -> list[TrendRecord]:
        """
        Modbus TCP has no native trend-log or data-log service.

        Historical data for Modbus devices is collected exclusively by
        HBCE's live polling (TrendPollThread) and stored in the local DB.
        ReadRange-style log retrieval is not available from the device.

        Returns [] intentionally — this is not a stub.
        """
        return []
