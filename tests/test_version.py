"""tests/test_version.py — Version smoke tests (stdlib unittest)."""
import sys, os, re, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version

class TestVersion(unittest.TestCase):
    def test_version_starts_with_V(self):
        self.assertTrue(version.VERSION.startswith("V"))

    def test_version_has_dot(self):
        self.assertIn(".", version.VERSION)

    def test_version_components_are_ints(self):
        self.assertIsInstance(version.VERSION_MAJOR, int)
        self.assertIsInstance(version.VERSION_MINOR, int)
        self.assertIsInstance(version.VERSION_PATCH, int)

    def test_version_tuple_length(self):
        self.assertEqual(len(version.VERSION_TUPLE), 3)
        self.assertTrue(all(isinstance(x, int) for x in version.VERSION_TUPLE))

    def test_app_name(self):
        self.assertEqual(version.APP_NAME, "HBCE")
        self.assertEqual(version.APP_FULL_NAME, "Hybrid Controls Editor")

    def test_build_date_format(self):
        self.assertRegex(version.BUILD_DATE, r"\d{4}-\d{2}-\d{2}")

    def test_version_label_is_alpha(self):
        self.assertEqual(version.VERSION_LABEL, "alpha")

    def test_patch_at_least_8(self):
        self.assertGreaterEqual(version.VERSION_PATCH, 8)

if __name__ == "__main__":
    unittest.main()
