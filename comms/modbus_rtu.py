"""
HBCE — Hybrid Controls Editor
comms/modbus_rtu.py — Modbus RTU (RS-485 Serial) Adapter

Uses pymodbus 3.x over a serial port (RS-485 via USB adapter).
GOTCHA-009: pymodbus 3.x API is significantly different from 2.x.
            Always use pymodbus 3.x docs — never copy 2.x examples.
GOTCHA-004: RS-485 USB adapters require drivers. Validate port first.
"""

import threading
from typing import Any

from comms.base_adapter import (
    BaseCommAdapter, DeviceInfo, PointValue, AlarmRecord, TrendRecord
)
from comms.bacnet_mstp import BACnetMSTPAdapter  # reuse port validation helper
from core.logger import get_logger

logger = get_logger(__name__)


class ModbusRTUAdapter(BaseCommAdapter):
    """Modbus RTU adapter over RS-485 serial using pymodbus 3.x."""

    def __init__(self):
        super().__init__()
        self._client = None
        self._lock = threading.Lock()
        self._params = {}

    @property
    def protocol_name(self) -> str:
        return "Modbus RTU (RS-485)"

    @property
    def protocol_id(self) -> str:
        return "modbus_rtu"

    def get_required_params(self) -> list[dict]:
        return [
            {
                "key":      "port",
                "label":    "COM Port",
                "type":     "comport",
                "default":  "COM1",
                "tooltip":  "Serial COM port for your RS-485 adapter. "
                            "Check Device Manager if unsure.",
                "required": True,
            },
            {
                "key":      "baud",
                "label":    "Baud Rate",
                "type":     "combo",
                "options":  [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200],
                "default":  9600,
                "tooltip":  "Must match the baud rate on your Modbus device. "
                            "Most BAS Modbus devices use 9600 or 19200.",
                "required": True,
            },
            {
                "key":      "parity",
                "label":    "Parity",
                "type":     "combo",
                "options":  ["N (None)", "E (Even)", "O (Odd)"],
                "default":  "N (None)",
                "tooltip":  "Parity bit setting. Must match the device. "
                            "'None' is most common.",
                "required": False,
            },
            {
                "key":      "stopbits",
                "label":    "Stop Bits",
                "type":     "combo",
                "options":  [1, 2],
                "default":  1,
                "tooltip":  "Number of stop bits. Usually 1.",
                "required": False,
            },
            {
                "key":      "unit_id",
                "label":    "Unit ID (Slave Address)",
                "type":     "int",
                "default":  1,
                "tooltip":  "Modbus slave address (1–247). Must match the device.",
                "required": True,
            },
            {
                "key":      "timeout",
                "label":    "Timeout (seconds)",
                "type":     "float",
                "default":  2.0,
                "tooltip":  "Response timeout. Increase for slow or noisy RS-485 networks.",
                "required": False,
            },
        ]

    def connect(self, params: dict) -> bool:
        port    = params.get("port", "COM1")
        baud    = int(params.get("baud", 9600))
        parity  = str(params.get("parity", "N (None)"))[0]   # "N", "E", or "O"
        stop    = int(params.get("stopbits", 1))
        timeout = float(params.get("timeout", 2.0))

        # Validate port before connecting (GOTCHA-004)
        ok, msg = BACnetMSTPAdapter._validate_port(port)
        if not ok:
            logger.error(f"Modbus RTU: {msg}")
            return False

        try:
            from pymodbus.client import ModbusSerialClient
            self._client = ModbusSerialClient(
                port=port,
                baudrate=baud,
                parity=parity,
                stopbits=stop,
                timeout=timeout,
            )
            result = self._client.connect()
            if result:
                self._connected = True
                self._params = params
                logger.info(f"Modbus RTU: connected on {port} @ {baud} baud")
                return True
            else:
                logger.error(f"Modbus RTU: failed to open {port}")
                return False
        except ImportError:
            logger.error("pymodbus not installed. Run: pip install pymodbus>=3.5")
            return False
        except Exception as e:
            logger.error(f"Modbus RTU connect failed: {e}")
            return False

    def disconnect(self) -> None:
        try:
            if self._client:
                self._client.close()
                self._client = None
            self._connected = False
            logger.info("Modbus RTU: disconnected")
        except Exception as e:
            logger.warning(f"Modbus RTU disconnect error: {e}")

    def test_connection(self) -> tuple[bool, str]:
        if not self._connected or not self._client:
            return False, "Not connected"
        try:
            unit = int(self._params.get("unit_id", 1))
            with self._lock:
                r = self._client.read_holding_registers(0, 1, slave=unit)
            if r.isError():
                return False, f"Device at unit {unit} returned error — check slave address"
            return True, f"Modbus RTU device at unit ID {unit} responding"
        except Exception as e:
            return False, str(e)

    def who_is(self, low: int = 0, high: int = 4194303) -> list[DeviceInfo]:
        if not self._connected:
            return []
        port = self._params.get("port", "?")
        unit = self._params.get("unit_id", 1)
        return [DeviceInfo(
            device_id=int(unit),
            name=f"Modbus RTU Device @ {port} unit {unit}",
            address=port,
            protocol="Modbus RTU",
        )]

    def get_object_list(self, device_id: int) -> list[tuple[str, int]]:
        result = []
        result += [("coil", i) for i in range(0, 64)]
        result += [("discrete_input", i) for i in range(0, 64)]
        result += [("holding_register", i) for i in range(0, 128)]
        result += [("input_register", i) for i in range(0, 128)]
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
            logger.warning(f"Modbus RTU read failed {object_type}:{instance}: {e}")
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
                    return False
            return not r.isError()
        except Exception as e:
            logger.error(f"Modbus RTU write failed: {e}")
            return False

    def read_alarm_summary(self, device_id: int) -> list[AlarmRecord]:
        return []

    def get_trend_log(self, device_id, object_instance, count=100) -> list[TrendRecord]:
        return []
