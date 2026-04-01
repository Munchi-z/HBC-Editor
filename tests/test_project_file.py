"""tests/test_project_file.py — ZIP round-trip tests (stdlib unittest)."""
import sys, os, unittest, zipfile, tempfile, shutil, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.models import Device, Program, Schedule, ScheduleBlock, Project
from data.project import ProjectFile, ProjectFileError, _safe_name

def _make_project():
    dev  = Device(name="Dev1", vendor="JCI", protocol_id="bacnet_ip", params={"port":47808})
    prog = Program(program_name="Prog1", device_name="Dev1",
                   program_json={"blocks":[{"block_id":"b1","type_id":"AND",
                                            "x":0.0,"y":0.0,"label":"AND","params":{}}],
                                 "wires":[]})
    sched = Schedule(schedule_name="HVAC", device_name="Dev1", object_instance=1,
                     blocks=[ScheduleBlock(day=0, start_min=480, end_min=1020)])
    return Project(name="Test Project", description="UT", devices=[dev],
                   programs=[prog], schedules=[sched])

class TestSafeName(unittest.TestCase):
    def test_spaces(self):      self.assertEqual(_safe_name("My Program"), "My_Program")
    def test_slashes(self):     self.assertNotIn("/", _safe_name("a/b\\c"))
    def test_empty(self):       self.assertEqual(_safe_name(""), "unnamed")
    def test_whitespace(self):  self.assertEqual(_safe_name("   "), "unnamed")
    def test_max_length(self):  self.assertLessEqual(len(_safe_name("x"*200)), 80)

class TestProjectRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp  = tempfile.mkdtemp()
        self.proj = _make_project()
        self.path = os.path.join(self.tmp, "test.hbce")
        ProjectFile.save(self.proj, self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_created(self):
        self.assertTrue(os.path.exists(self.path))
        self.assertGreater(os.path.getsize(self.path), 0)

    def test_extension_added(self):
        noext = os.path.join(self.tmp, "noext")
        ProjectFile.save(self.proj, noext)
        self.assertTrue(os.path.exists(noext + ".hbce"))

    def test_zip_structure(self):
        with zipfile.ZipFile(self.path,"r") as zf:
            names = set(zf.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("devices.json",  names)
            self.assertTrue(any(n.startswith("programs/")  for n in names))
            self.assertTrue(any(n.startswith("schedules/") for n in names))

    def test_manifest(self):
        m = ProjectFile.peek_manifest(self.path)
        self.assertEqual(m["project_name"],   "Test Project")
        self.assertEqual(m["format_version"], "1")
        self.assertEqual(m["device_count"],   1)
        self.assertEqual(m["program_count"],  1)
        self.assertEqual(m["schedule_count"], 1)

    def test_devices_roundtrip(self):
        loaded = ProjectFile.load(self.path)
        self.assertEqual(len(loaded.devices), 1)
        dev = loaded.devices[0]
        self.assertEqual(dev.name,         "Dev1")
        self.assertEqual(dev.protocol_id,  "bacnet_ip")
        self.assertEqual(dev.params["port"], 47808)

    def test_programs_roundtrip(self):
        loaded = ProjectFile.load(self.path)
        self.assertEqual(len(loaded.programs), 1)
        p = loaded.programs[0]
        self.assertEqual(p.program_name, "Prog1")
        self.assertEqual(len(p.program_json["blocks"]), 1)

    def test_schedules_roundtrip(self):
        loaded = ProjectFile.load(self.path)
        self.assertEqual(len(loaded.schedules), 1)
        s = loaded.schedules[0]
        self.assertEqual(s.schedule_name,      "HVAC")
        self.assertEqual(s.blocks[0].start_min, 480)

    def test_name_roundtrip(self):
        loaded = ProjectFile.load(self.path)
        self.assertEqual(loaded.name,        "Test Project")
        self.assertEqual(loaded.description, "UT")

    def test_load_invalid_raises(self):
        bad = os.path.join(self.tmp, "bad.hbce")
        with open(bad, "wb") as f:
            f.write(b"not a zip")
        with self.assertRaises(ProjectFileError):
            ProjectFile.load(bad)

    def test_load_no_manifest_raises(self):
        path = os.path.join(self.tmp, "noman.hbce")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("devices.json", "[]")
        with self.assertRaises(ProjectFileError):
            ProjectFile.load(path)

    def test_load_missing_file_raises(self):
        with self.assertRaises(ProjectFileError):
            ProjectFile.load(os.path.join(self.tmp, "missing.hbce"))

if __name__ == "__main__":
    unittest.main()
