# vendors/__init__.py
# HBCE Vendor Profile Registry
#
# VENDOR_REGISTRY maps vendor_key → profile class.
# Connection Wizard uses this to show vendor-specific templates and tips.

from vendors.johnson_controls.metasys import MetasysVendorProfile
from vendors.trane.tracer              import TraneVendorProfile
from vendors.distech.eclypse           import DistechVendorProfile

VENDOR_REGISTRY = {
    MetasysVendorProfile.VENDOR_KEY: MetasysVendorProfile,
    TraneVendorProfile.VENDOR_KEY:   TraneVendorProfile,
    DistechVendorProfile.VENDOR_KEY: DistechVendorProfile,
}

VENDOR_ID_MAP = {
    MetasysVendorProfile.VENDOR_ID: MetasysVendorProfile,
    TraneVendorProfile.VENDOR_ID:   TraneVendorProfile,
    DistechVendorProfile.VENDOR_ID: DistechVendorProfile,
}

ALL_VENDOR_NAMES = [
    MetasysVendorProfile.DISPLAY_NAME,
    TraneVendorProfile.DISPLAY_NAME,
    DistechVendorProfile.DISPLAY_NAME,
    "Generic BACnet",
    "Generic Modbus",
]

def get_profile_for_vendor_id(vendor_id: int):
    """Return a vendor profile class for a BACnet Vendor ID, or None."""
    return VENDOR_ID_MAP.get(vendor_id)

def get_all_connection_templates() -> list:
    """Flatten all vendor connection templates into one list."""
    templates = []
    for cls in VENDOR_REGISTRY.values():
        for t in cls.CONNECTION_TEMPLATES:
            templates.append({**t, "vendor": cls.DISPLAY_NAME})
    return templates
