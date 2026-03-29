"""
HBCE — Hybrid Controls Editor
comms/__init__.py — Communications adapter registry

All adapters registered here. Connection Wizard reads REGISTERED_ADAPTERS.
To add a new protocol: import adapter class and append to REGISTERED_ADAPTERS.
"""

from comms.bacnet_ip   import BACnetIPAdapter
from comms.bacnet_mstp import BACnetMSTPAdapter
from comms.usb_direct  import USBDirectAdapter
from comms.modbus_tcp  import ModbusTCPAdapter
from comms.modbus_rtu  import ModbusRTUAdapter

# Future plugins uncomment when ready:
# from comms.plugins.bluetooth_ble import BluetoothBLEAdapter
# from comms.plugins.wifi_device   import WiFiDeviceAdapter
# from comms.plugins.hbce_native   import HBCENativeAdapter

REGISTERED_ADAPTERS = [
    BACnetIPAdapter,
    BACnetMSTPAdapter,
    USBDirectAdapter,
    ModbusTCPAdapter,
    ModbusRTUAdapter,
]

ADAPTER_MAP = {cls().protocol_id: cls for cls in REGISTERED_ADAPTERS}

def get_adapter(protocol_id: str):
    cls = ADAPTER_MAP.get(protocol_id)
    if cls is None:
        raise KeyError(f"No adapter registered for protocol: {protocol_id}")
    return cls()
