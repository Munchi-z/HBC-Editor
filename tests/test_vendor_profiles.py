"""tests/test_vendor_profiles.py — Vendor profile unit tests (stdlib unittest)."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vendors.johnson_controls.metasys import MetasysVendorProfile, MetasysObjectRef
from vendors.trane.tracer              import TraneVendorProfile
from vendors.distech.eclypse           import DistechVendorProfile
from vendors import VENDOR_REGISTRY, get_all_connection_templates
from comms.base_adapter import DeviceInfo

class TestVendorRegistry(unittest.TestCase):
    def test_all_three_vendors_present(self):
        for key in ("johnson_controls","trane","distech"):
            self.assertIn(key, VENDOR_REGISTRY)

    def test_registry_classes(self):
        self.assertIs(VENDOR_REGISTRY["johnson_controls"], MetasysVendorProfile)
        self.assertIs(VENDOR_REGISTRY["trane"],            TraneVendorProfile)
        self.assertIs(VENDOR_REGISTRY["distech"],          DistechVendorProfile)

    def test_connection_templates(self):
        templates = get_all_connection_templates()
        self.assertGreaterEqual(len(templates), 6)
        for t in templates:
            self.assertIn("name",        t)
            self.assertIn("protocol_id", t)
            self.assertIn("vendor",      t)

class TestMetasys(unittest.TestCase):
    def test_vendor_id(self):
        self.assertEqual(MetasysVendorProfile.VENDOR_ID, 5)

    def test_display_name(self):
        self.assertIn("Johnson", MetasysVendorProfile.DISPLAY_NAME)
        self.assertIn("Metasys", MetasysVendorProfile.DISPLAY_NAME)

    def test_protocols(self):
        self.assertIn("bacnet_ip",   MetasysVendorProfile.SUPPORTED_PROTOCOLS)
        self.assertIn("bacnet_mstp", MetasysVendorProfile.SUPPORTED_PROTOCOLS)

    def test_troubleshooting_tips(self):
        tips = MetasysVendorProfile.get_troubleshooting_tips()
        self.assertIsInstance(tips, list)
        self.assertGreater(len(tips), 0)
        for t in tips:
            self.assertIsInstance(t, str)
            self.assertGreater(len(t), 10)

    def test_is_metasys_device(self):
        self.assertTrue( MetasysVendorProfile.is_metasys_device(DeviceInfo(vendor="Johnson Controls")))
        self.assertFalse(MetasysVendorProfile.is_metasys_device(DeviceInfo(vendor="Siemens")))

    def test_format_object_name(self):
        self.assertEqual(MetasysVendorProfile.format_object_name("analogInput", 3, "Zone Temp"), "Zone Temp")
        self.assertEqual(MetasysVendorProfile.format_object_name("analogInput", 5), "AI-5")

    def test_fqr_parse_full(self):
        ref = MetasysObjectRef.parse("Site1:Dev1/AHU-1.presentValue")
        self.assertEqual(ref.site,     "Site1")
        self.assertEqual(ref.device,   "Dev1")
        self.assertEqual(ref.object,   "AHU-1")
        self.assertEqual(ref.property, "presentValue")

    def test_fqr_parse_simple(self):
        ref = MetasysObjectRef.parse("AHU-1")
        self.assertEqual(ref.object, "AHU-1")

    def test_schedule_to_hbce(self):
        raw = {"weeklySchedule":{"monday":[{"time":"08:00","value":True}]},
               "scheduleDefault":False}
        result = MetasysVendorProfile.bacnet_schedule_to_hbce(raw)
        self.assertIn("blocks", result)
        mon = [b for b in result["blocks"] if b["day"]==0]
        self.assertEqual(len(mon), 1)
        self.assertEqual(mon[0]["start_min"], 480)

    def test_schedule_roundtrip(self):
        hbce = {"blocks":[{"day":0,"start_min":480,"end_min":1020,"value":True,"label":""}],
                "exceptions":[],"default_value":False}
        bacnet = MetasysVendorProfile.hbce_schedule_to_bacnet(hbce)
        self.assertIn("weeklySchedule", bacnet)
        self.assertEqual(bacnet["weeklySchedule"]["monday"][0]["time"], "08:00")

class TestTrane(unittest.TestCase):
    def test_vendor_id(self):      self.assertEqual(TraneVendorProfile.VENDOR_ID, 24)
    def test_display_name(self):   self.assertIn("Trane", TraneVendorProfile.DISPLAY_NAME)
    def test_tips_not_empty(self): self.assertGreater(len(TraneVendorProfile.get_troubleshooting_tips()), 0)
    def test_is_trane(self):
        self.assertTrue(TraneVendorProfile.is_trane_device(DeviceInfo(vendor="Trane")))

class TestDistech(unittest.TestCase):
    def test_vendor_id(self):     self.assertEqual(DistechVendorProfile.VENDOR_ID, 76)
    def test_display_name(self):
        self.assertIn("ECLYPSE", DistechVendorProfile.DISPLAY_NAME)
        self.assertIn("Distech", DistechVendorProfile.DISPLAY_NAME)
    def test_tips(self):          self.assertGreater(len(DistechVendorProfile.get_troubleshooting_tips()), 0)
    def test_is_distech(self):
        self.assertTrue(DistechVendorProfile.is_distech_device(DeviceInfo(vendor="Distech Controls")))
    def test_haystack_sensor(self):
        tags = DistechVendorProfile.make_haystack_tags("Zone Temp", "analogInput")
        names = [t["tag"] for t in tags]
        self.assertIn("point",  names)
        self.assertIn("sensor", names)
    def test_haystack_semantic_temp(self):
        tags = DistechVendorProfile.make_haystack_tags("Discharge Air Temp", "analogInput")
        self.assertIn("temp", [t["tag"] for t in tags])
    def test_strip_unit(self):
        name, unit = DistechVendorProfile.strip_unit_suffix("Zone Temp [°C]")
        self.assertEqual(name, "Zone Temp")
        self.assertEqual(unit, "°C")
    def test_strip_no_unit(self):
        name, unit = DistechVendorProfile.strip_unit_suffix("Fan Status")
        self.assertEqual(name, "Fan Status")
        self.assertEqual(unit, "")

if __name__ == "__main__":
    unittest.main()
