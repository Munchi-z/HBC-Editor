"""tests/test_models.py — Unit tests for data/models.py (stdlib unittest)."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.models import (
    UserRole, AlarmPriority, AlarmState, ProtocolKind, ObjectType,
    User, Device, Point, AlarmRecord, TrendSample, TrendSeries,
    ScheduleBlock, Schedule, BackupEntry, Program, Project,
    make_point_from_bacnet,
)

class TestUserRole(unittest.TestCase):
    def test_from_str(self):
        self.assertEqual(UserRole.from_str("Admin"),      UserRole.ADMIN)
        self.assertEqual(UserRole.from_str("Technician"), UserRole.TECHNICIAN)
        self.assertEqual(UserRole.from_str("Operator"),   UserRole.OPERATOR)
        self.assertEqual(UserRole.from_str("Unknown"),    UserRole.OPERATOR)

    def test_labels(self):
        self.assertEqual(UserRole.ADMIN.label(),      "Admin")
        self.assertEqual(UserRole.TECHNICIAN.label(), "Technician")
        self.assertEqual(UserRole.OPERATOR.label(),   "Operator")

    def test_ordering(self):
        self.assertGreater(UserRole.ADMIN, UserRole.TECHNICIAN)
        self.assertGreater(UserRole.TECHNICIAN, UserRole.OPERATOR)


class TestAlarmPriority(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(AlarmPriority.LIFE_SAFETY.label(),   "Life Safety")
        self.assertEqual(AlarmPriority.INFORMATIONAL.label(), "Informational")

    def test_colors_are_hex(self):
        for pri in AlarmPriority:
            col = pri.color_hex()
            self.assertTrue(col.startswith("#"), f"{pri} color must start with #")
            self.assertEqual(len(col), 7, f"{pri} color must be #RRGGBB")

    def test_range(self):
        self.assertEqual(int(AlarmPriority.LIFE_SAFETY),   1)
        self.assertEqual(int(AlarmPriority.INFORMATIONAL), 8)


class TestAlarmState(unittest.TestCase):
    def test_is_active(self):
        self.assertTrue(AlarmState.ACTIVE_UNACKED.is_active)
        self.assertTrue(AlarmState.ACTIVE_ACKED.is_active)
        self.assertFalse(AlarmState.CLEARED_ACKED.is_active)
        self.assertFalse(AlarmState.NORMAL.is_active)

    def test_labels(self):
        self.assertIn("Active", AlarmState.ACTIVE_UNACKED.label())
        self.assertIn("Normal", AlarmState.NORMAL.label())


class TestProtocolKind(unittest.TestCase):
    def test_from_str(self):
        self.assertEqual(ProtocolKind.from_str("bacnet_ip"),   ProtocolKind.BACNET_IP)
        self.assertEqual(ProtocolKind.from_str("modbus_rtu"),  ProtocolKind.MODBUS_RTU)
        self.assertEqual(ProtocolKind.from_str("BACNET_IP"),   ProtocolKind.BACNET_IP)
        self.assertEqual(ProtocolKind.from_str("unknown_xyz"), ProtocolKind.UNKNOWN)

    def test_labels(self):
        self.assertIn("BACnet", ProtocolKind.BACNET_IP.label())
        self.assertIn("Modbus", ProtocolKind.MODBUS_TCP.label())


class TestObjectType(unittest.TestCase):
    def test_from_str(self):
        self.assertEqual(ObjectType.from_str("analogInput"),  ObjectType.ANALOG_INPUT)
        self.assertEqual(ObjectType.from_str("binaryOutput"), ObjectType.BINARY_OUTPUT)
        self.assertEqual(ObjectType.from_str("trendLog"),     ObjectType.TREND_LOG)
        self.assertEqual(ObjectType.from_str("bogus"),        ObjectType.UNKNOWN)

    def test_short(self):
        self.assertEqual(ObjectType.ANALOG_INPUT.short(),  "AI")
        self.assertEqual(ObjectType.BINARY_OUTPUT.short(), "BO")
        self.assertEqual(ObjectType.TREND_LOG.short(),     "TL")


class TestPoint(unittest.TestCase):
    def test_object_id(self):
        p = Point(object_type=ObjectType.ANALOG_INPUT, instance=5)
        self.assertEqual(p.object_id, "AI-5")

    def test_is_writable(self):
        self.assertTrue( Point(object_type=ObjectType.ANALOG_OUTPUT).is_writable)
        self.assertFalse(Point(object_type=ObjectType.ANALOG_INPUT).is_writable)

    def test_is_binary(self):
        self.assertTrue( Point(object_type=ObjectType.BINARY_INPUT).is_binary)
        self.assertFalse(Point(object_type=ObjectType.ANALOG_VALUE).is_binary)

    def test_value_str_analog(self):
        p = Point(object_type=ObjectType.ANALOG_VALUE, instance=1,
                  present_value=72.5, units="°F")
        self.assertIn("72.50", p.value_str())
        self.assertIn("°F",    p.value_str())

    def test_value_str_binary(self):
        on  = Point(object_type=ObjectType.BINARY_INPUT, present_value=True)
        off = Point(object_type=ObjectType.BINARY_INPUT, present_value=False)
        self.assertEqual(on.value_str(),  "ON")
        self.assertEqual(off.value_str(), "OFF")

    def test_value_str_none(self):
        p = Point(object_type=ObjectType.ANALOG_INPUT)
        self.assertEqual(p.value_str(), "—")

    def test_active_priority(self):
        p = Point(object_type=ObjectType.ANALOG_OUTPUT)
        p.priority_array = [None] * 16
        self.assertIsNone(p.active_priority)
        p.priority_array[7] = 55.0
        self.assertEqual(p.active_priority, 8)
        p.priority_array[2] = 60.0
        self.assertEqual(p.active_priority, 3)


class TestMakePoint(unittest.TestCase):
    def test_make_point(self):
        p = make_point_from_bacnet("analogInput", 3, "Zone Temp", 68.0, "°F")
        self.assertEqual(p.object_type,   ObjectType.ANALOG_INPUT)
        self.assertEqual(p.instance,      3)
        self.assertEqual(p.name,          "Zone Temp")
        self.assertEqual(p.present_value, 68.0)
        self.assertEqual(p.units,         "°F")


class TestAlarmRecord(unittest.TestCase):
    def test_age_labels(self):
        a = AlarmRecord(age_seconds=30)
        self.assertIn("s", a.age_label)
        a.age_seconds = 90;    self.assertIn("m", a.age_label)
        a.age_seconds = 7200;  self.assertIn("h", a.age_label)
        a.age_seconds = 86401; self.assertIn("d", a.age_label)

    def test_from_db_row(self):
        row = {"id":42,"timestamp":"2026-04-01","device_id":1,"object_ref":"AV-3",
               "description":"High","priority":3,"ack_by":"admin","ack_time":""}
        a = AlarmRecord.from_db_row(row)
        self.assertEqual(a.alarm_id, 42)
        self.assertEqual(a.priority, AlarmPriority.HIGH)
        self.assertEqual(a.acked_by, "admin")


class TestTrendSample(unittest.TestCase):
    def test_dt_valid(self):
        ts = TrendSample(timestamp=1_700_000_000.0, value=72.5)
        self.assertIsNotNone(ts.dt)
        self.assertGreater(ts.dt.year, 2000)

    def test_dt_invalid(self):
        self.assertIsNone(TrendSample(timestamp=0.0).dt)
        self.assertIsNone(TrendSample(timestamp=-1.0).dt)


class TestTrendSeries(unittest.TestCase):
    def test_last_value(self):
        s = TrendSeries("s1","Dev","AV-1","Zone Temp","°F")
        self.assertIsNone(s.last_value())
        s.samples = [TrendSample(1_700_000_000,70.0), TrendSample(1_700_001_000,72.0)]
        self.assertEqual(s.last_value(), 72.0)


class TestScheduleBlock(unittest.TestCase):
    def test_hhmm(self):
        b = ScheduleBlock(day=0, start_min=8*60, end_min=17*60)
        self.assertEqual(b.start_hhmm, "08:00")
        self.assertEqual(b.end_hhmm,   "17:00")


class TestBackupEntry(unittest.TestCase):
    def test_size_label(self):
        b = BackupEntry(size_bytes=512)
        self.assertIn("B", b.size_label)
        b.size_bytes = 2048
        self.assertIn("KB", b.size_label)
        b.size_bytes = 2*1024*1024
        self.assertIn("MB", b.size_label)


class TestProgram(unittest.TestCase):
    def test_counts(self):
        p = Program(program_json={"blocks":[{"id":"a"},{"id":"b"}],"wires":[{"id":"w1"}]})
        self.assertEqual(p.block_count, 2)
        self.assertEqual(p.wire_count,  1)

    def test_from_db_row(self):
        import json
        row = {"id":7,"program_name":"Test","description":"","device_name":"Local",
               "program_json":json.dumps({"blocks":[],"wires":[]}),"created_at":"",
               "updated_at":"","created_by":"admin"}
        p = Program.from_db_row(row)
        self.assertEqual(p.program_id,   7)
        self.assertEqual(p.program_name, "Test")


class TestDevice(unittest.TestCase):
    def test_to_db_dict(self):
        import json
        d = Device(name="D1", vendor="JCI", protocol_id="bacnet_ip",
                   params={"port":47808})
        db = d.to_db_dict()
        self.assertEqual(db["name"], "D1")
        self.assertEqual(db["protocol"], "bacnet_ip")
        self.assertEqual(json.loads(db["params_json"])["port"], 47808)

    def test_from_db_row(self):
        import json
        row = {"id":1,"name":"Dev1","vendor":"Trane","model":"UC400",
               "protocol":"bacnet_mstp","params_json":json.dumps({"baud":76800})}
        d = Device.from_db_row(row)
        self.assertEqual(d.name,          "Dev1")
        self.assertEqual(d.protocol,      ProtocolKind.BACNET_MSTP)
        self.assertEqual(d.params["baud"],76800)


class TestProject(unittest.TestCase):
    def test_counts(self):
        proj = Project(name="P", devices=[Device(),Device()], programs=[Program()])
        self.assertEqual(proj.device_count,  2)
        self.assertEqual(proj.program_count, 1)


if __name__ == "__main__":
    unittest.main()
