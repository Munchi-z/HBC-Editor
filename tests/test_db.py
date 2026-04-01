"""tests/test_db.py — Unit tests for data/db.py (stdlib unittest)."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tempfile, shutil
from data.db import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db  = Database(os.path.join(self.tmp, "test.db"))
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tables_created(self):
        rows  = self.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        names = {r["name"] for r in rows}
        for t in ("devices","points","alarms","users","schedules","audit_log","projects"):
            self.assertIn(t, names)

    def test_default_admin_created(self):
        user = self.db.get_user("admin")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "Admin")

    def test_insert_and_fetchone(self):
        rid = self.db.insert(
            "INSERT INTO projects (name,created,modified) VALUES (?,?,?)",
            ("P1","2026-04-01","2026-04-01"))
        self.assertGreater(rid, 0)
        row = self.db.fetchone("SELECT * FROM projects WHERE id=?", (rid,))
        self.assertEqual(row["name"], "P1")

    def test_fetchall(self):
        for name in ("A","B","C"):
            self.db.insert("INSERT INTO projects (name,created,modified) VALUES (?,?,?)",
                           (name,"2026-04-01","2026-04-01"))
        rows = self.db.fetchall(
            "SELECT name FROM projects WHERE name IN ('A','B','C') ORDER BY name")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "A")

    def test_update(self):
        rid = self.db.insert(
            "INSERT INTO projects (name,created,modified) VALUES (?,?,?)",
            ("Old","2026-04-01","2026-04-01"))
        self.db.update("UPDATE projects SET name=? WHERE id=?", ("New", rid))
        row = self.db.fetchone("SELECT name FROM projects WHERE id=?", (rid,))
        self.assertEqual(row["name"], "New")

    def test_fetchone_missing_returns_none(self):
        row = self.db.fetchone("SELECT * FROM projects WHERE id=?", (999999,))
        self.assertIsNone(row)

    def test_get_user_not_found(self):
        self.assertIsNone(self.db.get_user("nobody"))

    def test_log_audit(self):
        user = self.db.get_user("admin")
        self.db.log_audit(user["id"], "TEST_ACTION", "detail text")
        rows = self.db.fetchall("SELECT * FROM audit_log WHERE action=?", ("TEST_ACTION",))
        self.assertEqual(len(rows), 1)
        self.assertIn("detail", rows[0]["detail"])

    def test_close_and_reopen(self):
        path = os.path.join(self.tmp, "persist.db")
        d = Database(path)
        d.initialize()
        d.insert("INSERT INTO projects (name,created,modified) VALUES (?,?,?)",
                 ("Persist","2026-04-01","2026-04-01"))
        d.close()
        d2 = Database(path)
        d2.initialize()
        rows = d2.fetchall("SELECT name FROM projects WHERE name='Persist'")
        self.assertEqual(len(rows), 1)
        d2.close()

if __name__ == "__main__":
    unittest.main()
