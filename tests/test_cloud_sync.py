"""tests/test_cloud_sync.py — Cloud sync unit tests (stdlib unittest, no network)."""
import sys, os, json, time, unittest, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.cloud_sync import (
    CloudSyncManager, SyncProvider, SyncResult,
    GoogleDriveProvider, OneDriveProvider, CloudSyncThread,
    HBCE_FOLDER_NAME, TOKEN_FILE_ONEDRIVE,
)

class TestSyncResult(unittest.TestCase):
    def test_success(self):
        r = SyncResult(True, "OK", remote_id="abc")
        self.assertTrue(r.success)
        self.assertEqual(r.remote_id, "abc")
        self.assertNotEqual(r.timestamp, "")

    def test_failure(self):
        r = SyncResult(False, "Upload failed")
        self.assertFalse(r.success)
        self.assertIn("failed", r.message)

    def test_repr(self):
        self.assertIn("OK",   repr(SyncResult(True,  "x")))
        self.assertIn("FAIL", repr(SyncResult(False, "x")))


class TestGoogleDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p   = GoogleDriveProvider(self.tmp, client_secrets_path=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_not_configured_without_secrets(self):
        self.assertFalse(self.p.is_configured())

    def test_not_authenticated_no_token(self):
        self.assertFalse(self.p.is_authenticated())

    def test_revoke_no_token_does_not_raise(self):
        self.p.revoke()   # should be silent

    def test_upload_fails_gracefully(self):
        r = self.p.upload_file(os.path.join(self.tmp, "nonexistent.txt"))
        self.assertFalse(r.success)
        self.assertTrue(r.message)

    def test_download_fails_gracefully(self):
        r = self.p.download_file("file.hbce", os.path.join(self.tmp, "out.hbce"))
        self.assertFalse(r.success)

    def test_list_returns_empty_unauthenticated(self):
        files = self.p.list_files()
        self.assertIsInstance(files, list)
        self.assertEqual(len(files), 0)


class TestOneDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _provider(self, client_id=""):
        return OneDriveProvider(self.tmp, client_id=client_id)

    def test_not_configured_without_client_id(self):
        self.assertFalse(self._provider().is_configured())

    def test_configured_with_client_id(self):
        self.assertTrue(self._provider("fake-id").is_configured())

    def test_not_authenticated_no_token(self):
        self.assertFalse(self._provider("fake").is_authenticated())

    def test_authenticated_with_valid_token(self):
        token = {"access_token": "tok", "refresh_token": "ref",
                 "expires_at": time.time() + 3600, "client_id": "fake", "tenant": "consumers"}
        (import_path := __import__("pathlib").Path(self.tmp) / TOKEN_FILE_ONEDRIVE).write_text(
            json.dumps(token))
        self.assertTrue(self._provider("fake").is_authenticated())

    def test_not_authenticated_expired_token(self):
        token = {"access_token": "old", "expires_at": time.time() - 100}
        (__import__("pathlib").Path(self.tmp) / TOKEN_FILE_ONEDRIVE).write_text(
            json.dumps(token))
        self.assertFalse(self._provider("fake").is_authenticated())

    def test_revoke_no_token_does_not_raise(self):
        self._provider("fake").revoke()

    def test_upload_fails_gracefully(self):
        r = self._provider().upload_file(os.path.join(self.tmp, "nofile.txt"))
        self.assertFalse(r.success)

    def test_download_fails_gracefully(self):
        r = self._provider().download_file("file.hbce", os.path.join(self.tmp, "out.hbce"))
        self.assertFalse(r.success)

    def test_list_returns_empty(self):
        self.assertIsInstance(self._provider().list_files(), list)


class TestCloudSyncManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mgr = CloudSyncManager.from_config_dir(__import__("pathlib").Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_providers_created(self):
        self.assertIsNotNone(self.mgr.google)
        self.assertIsNotNone(self.mgr.onedrive)

    def test_status_structure(self):
        s = self.mgr.status()
        for key in ("google_drive", "onedrive"):
            self.assertIn(key, s)
            for field in ("configured", "authenticated", "display_name"):
                self.assertIn(field, s[key])

    def test_auto_sync_no_providers(self):
        enabled = self.mgr.auto_sync_enabled_providers()
        self.assertIsInstance(enabled, list)

    def test_get_provider(self):
        self.assertIs(self.mgr.get_provider(SyncProvider.GOOGLE_DRIVE), self.mgr.google)
        self.assertIs(self.mgr.get_provider(SyncProvider.ONEDRIVE),     self.mgr.onedrive)

    def test_upload_async_returns_thread(self):
        t = self.mgr.upload_async(os.path.join(self.tmp, "f.hbce"), SyncProvider.GOOGLE_DRIVE)
        self.assertIsInstance(t, CloudSyncThread)
        self.assertFalse(t.isRunning())

    def test_download_async_returns_thread(self):
        t = self.mgr.download_async("f.hbce", os.path.join(self.tmp, "out.hbce"))
        self.assertIsInstance(t, CloudSyncThread)

    def test_backup_database_returns_thread(self):
        t = self.mgr.backup_database(os.path.join(self.tmp, "hbce.db"))
        self.assertIsInstance(t, CloudSyncThread)

    def test_constants(self):
        self.assertEqual(HBCE_FOLDER_NAME, "HBCE Backups")


if __name__ == "__main__":
    unittest.main()
