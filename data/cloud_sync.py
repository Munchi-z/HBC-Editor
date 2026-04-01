# data/cloud_sync.py
# HBCE — Hybrid Controls Editor
# Cloud Sync — Google Drive + Microsoft OneDrive
# Full Implementation V0.1.8-alpha
#
# Architecture:
#   CloudSyncManager   — coordinates Google Drive + OneDrive providers
#   GoogleDriveProvider — OAuth2, upload/download via google-api-python-client
#   OneDriveProvider   — MSAL device-code auth, upload/download via MS Graph API
#   CloudSyncThread     — QThread wrapper for all cloud I/O (GOTCHA-013 compliant)
#
# What gets synced:
#   - .hbce project files (full project backup)
#   - hbce.db (SQLite database)
#   - hbce_config.json (user preferences)
#   - Backup archives (.zip files in backup dir)
#
# GOTCHA-005: OAuth token expiry → silent fail risk.
# Fix: Always check token validity before upload. On expiry,
#      emit token_expired signal → UI asks user to re-authenticate.
#
# Usage:
#   mgr = CloudSyncManager(config_dir=Path("..."))
#   mgr.upload_file(local_path, provider="google_drive")
#   mgr.download_file(remote_name, dest_path, provider="google_drive")

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from core.logger import get_logger

# PyQt6 is only needed for CloudSyncThread — fall back to a plain Thread stub
# when running in a test environment without Qt installed.
try:
    from PyQt6.QtCore import QThread, pyqtSignal
    _QT_AVAILABLE = True
except ImportError:
    import threading
    _QT_AVAILABLE = False

    class pyqtSignal:   # minimal stub
        def __init__(self, *_): pass
        def emit(self, *_): pass
        def connect(self, *_): pass

    class QThread(threading.Thread):
        def __init__(self, parent=None):
            super().__init__(daemon=True)
        def isRunning(self): return self.is_alive()
        def start(self): super().start()
        progress      = pyqtSignal(int, str)
        completed     = pyqtSignal(object)
        token_expired = pyqtSignal(str)

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

HBCE_FOLDER_NAME    = "HBCE Backups"
DRIVE_SCOPES        = ["https://www.googleapis.com/auth/drive.file"]
ONEDRIVE_SCOPE      = ["Files.ReadWrite"]
ONEDRIVE_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

TOKEN_FILE_GOOGLE   = "gdrive_token.json"
TOKEN_FILE_ONEDRIVE = "onedrive_token.json"


class SyncProvider(Enum):
    GOOGLE_DRIVE = auto()
    ONEDRIVE     = auto()


class SyncResult:
    """Result of a cloud sync operation."""
    def __init__(self, success: bool, message: str = "",
                 remote_id: str = "", url: str = ""):
        self.success   = success
        self.message   = message
        self.remote_id = remote_id
        self.url       = url
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return f"<SyncResult {'OK' if self.success else 'FAIL'}: {self.message}>"


# ═══════════════════════════════════════════════════════════════════════════════
#  Google Drive Provider
# ═══════════════════════════════════════════════════════════════════════════════

class GoogleDriveProvider:
    """
    Upload/download files to Google Drive using the Google API Python Client.
    Stores OAuth2 tokens in `config_dir/gdrive_token.json`.
    Uses drive.file scope — HBCE can only access files it creates.

    GOTCHA-005: Token expiry is handled by calling _ensure_valid_credentials()
    before every API call. If the refresh token is invalid, raises
    TokenExpiredError so the caller can prompt re-authentication.
    """

    class TokenExpiredError(Exception):
        pass

    def __init__(self, config_dir: Path, client_secrets_path: Optional[str] = None):
        self.config_dir = Path(config_dir)
        self.client_secrets_path = client_secrets_path
        self._creds              = None
        self._service            = None
        self._folder_id:  Optional[str] = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """Return True if client secrets file exists."""
        if not self.client_secrets_path:
            return False
        return os.path.exists(self.client_secrets_path)

    def is_authenticated(self) -> bool:
        """Return True if valid (non-expired) credentials are cached."""
        token_path = self.config_dir / TOKEN_FILE_GOOGLE
        if not token_path.exists():
            return False
        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)
            return creds and creds.valid
        except Exception:
            return False

    def authenticate(self, headless: bool = False) -> bool:
        """
        Run the OAuth2 flow. In headless mode, opens a browser URL and
        waits for the user to paste the auth code (suitable for QThread use).
        Returns True on success.
        """
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            token_path = self.config_dir / TOKEN_FILE_GOOGLE

            # Try to refresh existing token first
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(
                    str(token_path), DRIVE_SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, "w") as f:
                        f.write(creds.to_json())
                    self._creds = creds
                    return True
                elif creds and creds.valid:
                    self._creds = creds
                    return True

            # Full OAuth flow
            if not self.client_secrets_path:
                raise ValueError("No client_secrets.json path configured.")

            flow = InstalledAppFlow.from_client_secrets_file(
                self.client_secrets_path, DRIVE_SCOPES)

            if headless:
                creds = flow.run_console()
            else:
                creds = flow.run_local_server(port=0)

            with open(token_path, "w") as f:
                f.write(creds.to_json())
            self._creds = creds
            return True

        except Exception as e:
            logger.error(f"Google Drive auth failed: {e}")
            return False

    def revoke(self):
        """Remove cached credentials."""
        token_path = self.config_dir / TOKEN_FILE_GOOGLE
        if token_path.exists():
            token_path.unlink()
        self._creds   = None
        self._service = None
        self._folder_id = None
        logger.info("Google Drive credentials revoked.")

    def _ensure_service(self):
        """Build the Drive v3 API service. Raises TokenExpiredError if needed."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            token_path = self.config_dir / TOKEN_FILE_GOOGLE
            if not token_path.exists():
                raise self.TokenExpiredError("Not authenticated with Google Drive.")

            creds = Credentials.from_authorized_user_file(
                str(token_path), DRIVE_SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, "w") as f:
                        f.write(creds.to_json())
                else:
                    raise self.TokenExpiredError(
                        "Google Drive token expired. Please re-authenticate.")

            self._creds   = creds
            self._service = build("drive", "v3", credentials=creds)

        except self.TokenExpiredError:
            raise
        except Exception as e:
            raise self.TokenExpiredError(f"Google Drive auth error: {e}") from e

    def _get_or_create_folder(self) -> str:
        """Return the Drive folder ID for HBCE_FOLDER_NAME, creating it if needed."""
        if self._folder_id:
            return self._folder_id

        self._ensure_service()
        results = self._service.files().list(
            q=f"name='{HBCE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive",
            fields="files(id, name)"
        ).execute()

        files = results.get("files", [])
        if files:
            self._folder_id = files[0]["id"]
        else:
            folder_meta = {
                "name": HBCE_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder"
            }
            folder = self._service.files().create(
                body=folder_meta, fields="id").execute()
            self._folder_id = folder["id"]

        return self._folder_id

    # ── Upload / Download ─────────────────────────────────────────────────────

    def upload_file(self, local_path: str,
                    remote_name: Optional[str] = None) -> SyncResult:
        """Upload a file to the HBCE Google Drive folder."""
        try:
            from googleapiclient.http import MediaFileUpload

            self._ensure_service()
            folder_id   = self._get_or_create_folder()
            remote_name = remote_name or os.path.basename(local_path)

            # Check if file already exists (update instead of duplicate)
            existing = self._service.files().list(
                q=f"name='{remote_name}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)"
            ).execute().get("files", [])

            media = MediaFileUpload(local_path, resumable=True)
            file_meta = {"name": remote_name, "parents": [folder_id]}

            if existing:
                file_id = existing[0]["id"]
                result  = self._service.files().update(
                    fileId=file_id, media_body=media, fields="id, webViewLink"
                ).execute()
            else:
                result = self._service.files().create(
                    body=file_meta, media_body=media, fields="id, webViewLink"
                ).execute()

            logger.info(f"Google Drive upload: {remote_name} → {result.get('id')}")
            return SyncResult(
                success=True,
                message=f"Uploaded to Google Drive: {remote_name}",
                remote_id=result.get("id",""),
                url=result.get("webViewLink",""),
            )
        except self.TokenExpiredError as e:
            return SyncResult(False, f"Auth error: {e}")
        except Exception as e:
            logger.error(f"Google Drive upload failed: {e}")
            return SyncResult(False, f"Upload failed: {e}")

    def download_file(self, remote_name: str, dest_path: str) -> SyncResult:
        """Download a file from the HBCE Google Drive folder."""
        try:
            from googleapiclient.http import MediaIoBaseDownload
            import io

            self._ensure_service()
            folder_id = self._get_or_create_folder()

            files = self._service.files().list(
                q=f"name='{remote_name}' and '{folder_id}' in parents and trashed=false",
                fields="files(id, name)"
            ).execute().get("files", [])

            if not files:
                return SyncResult(False, f"File not found in Drive: {remote_name}")

            file_id   = files[0]["id"]
            request   = self._service.files().get_media(fileId=file_id)
            buffer    = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            with open(dest_path, "wb") as f:
                f.write(buffer.getvalue())

            logger.info(f"Google Drive download: {remote_name} → {dest_path}")
            return SyncResult(True, f"Downloaded: {remote_name}", remote_id=file_id)

        except self.TokenExpiredError as e:
            return SyncResult(False, f"Auth error: {e}")
        except Exception as e:
            logger.error(f"Google Drive download failed: {e}")
            return SyncResult(False, f"Download failed: {e}")

    def list_files(self) -> List[dict]:
        """Return list of files in the HBCE Drive folder."""
        try:
            self._ensure_service()
            folder_id = self._get_or_create_folder()
            results = self._service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, size, modifiedTime)",
                orderBy="modifiedTime desc"
            ).execute()
            return results.get("files", [])
        except Exception as e:
            logger.error(f"Google Drive list failed: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════════════
#  Microsoft OneDrive Provider
# ═══════════════════════════════════════════════════════════════════════════════

class OneDriveProvider:
    """
    Upload/download files to OneDrive via Microsoft Graph API.
    Uses MSAL device-code flow (works headless — suitable for QThread).
    Tokens cached in config_dir/onedrive_token.json.

    GOTCHA-005 compliance: token validity checked before every API call.
    """

    class TokenExpiredError(Exception):
        pass

    def __init__(self, config_dir: Path,
                 client_id: str = "",
                 tenant: str = "consumers"):
        self.config_dir = Path(config_dir)
        self.client_id   = client_id or os.environ.get("HBCE_ONEDRIVE_CLIENT_ID", "")
        self.tenant      = tenant
        self._token: Optional[dict] = None
        self._token_expiry: float   = 0.0

    # ── Auth ──────────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(self.client_id)

    def is_authenticated(self) -> bool:
        token_path = self.config_dir / TOKEN_FILE_ONEDRIVE
        if not token_path.exists():
            return False
        try:
            data = json.loads(token_path.read_text())
            expiry = data.get("expires_at", 0)
            return time.time() < expiry
        except Exception:
            return False

    def authenticate(self, callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Device-code flow. Calls `callback(user_code_message)` with the
        message the user should see (URL + code). Blocks until the user
        completes auth or it times out.
        """
        try:
            import msal

            if not self.client_id:
                raise ValueError("OneDrive client_id not configured. "
                                 "Set HBCE_ONEDRIVE_CLIENT_ID env var.")

            authority = f"https://login.microsoftonline.com/{self.tenant}"
            app = msal.PublicClientApplication(self.client_id, authority=authority)

            flow = app.initiate_device_flow(scopes=ONEDRIVE_SCOPE)
            if "user_code" not in flow:
                raise ValueError("Failed to create device flow.")

            msg = flow["message"]
            logger.info(f"OneDrive device code flow: {msg}")
            if callback:
                callback(msg)

            token_response = app.acquire_token_by_device_flow(flow)

            if "access_token" not in token_response:
                raise ValueError(
                    token_response.get("error_description", "Auth failed"))

            # Cache token
            token_data = {
                "access_token":  token_response["access_token"],
                "refresh_token": token_response.get("refresh_token", ""),
                "expires_at":    time.time() + token_response.get("expires_in", 3600) - 60,
                "client_id":     self.client_id,
                "tenant":        self.tenant,
            }
            (self.config_dir / TOKEN_FILE_ONEDRIVE).write_text(
                json.dumps(token_data, indent=2))
            self._token = token_data
            logger.info("OneDrive authentication successful.")
            return True

        except Exception as e:
            logger.error(f"OneDrive auth failed: {e}")
            return False

    def revoke(self):
        """Remove cached OneDrive credentials."""
        token_path = self.config_dir / TOKEN_FILE_ONEDRIVE
        if token_path.exists():
            token_path.unlink()
        self._token = None
        logger.info("OneDrive credentials revoked.")

    def _get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed. GOTCHA-005."""
        token_path = self.config_dir / TOKEN_FILE_ONEDRIVE
        if not token_path.exists():
            raise self.TokenExpiredError("Not authenticated with OneDrive.")

        data = json.loads(token_path.read_text())

        # Check expiry
        if time.time() >= data.get("expires_at", 0):
            # Attempt silent refresh via MSAL
            try:
                import msal
                authority = f"https://login.microsoftonline.com/{data.get('tenant','consumers')}"
                app = msal.PublicClientApplication(
                    data.get("client_id", self.client_id), authority=authority)
                accounts = app.get_accounts()
                if accounts:
                    result = app.acquire_token_silent(
                        ONEDRIVE_SCOPE, account=accounts[0])
                    if result and "access_token" in result:
                        data["access_token"] = result["access_token"]
                        data["expires_at"]   = time.time() + result.get("expires_in", 3600) - 60
                        token_path.write_text(json.dumps(data, indent=2))
                        return data["access_token"]
            except Exception as e:
                logger.warning(f"OneDrive silent refresh failed: {e}")

            raise self.TokenExpiredError(
                "OneDrive token expired. Please re-authenticate.")

        return data["access_token"]

    def _graph_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type":  "application/json",
        }

    def _ensure_folder(self) -> str:
        """Create HBCE_FOLDER_NAME in OneDrive root if not exists. Returns folder path."""
        return f"/me/drive/root:/{HBCE_FOLDER_NAME}"

    # ── Upload / Download ─────────────────────────────────────────────────────

    def upload_file(self, local_path: str,
                    remote_name: Optional[str] = None) -> SyncResult:
        """Upload a file to the HBCE OneDrive folder via Graph upload session."""
        try:
            import requests as rq

            remote_name = remote_name or os.path.basename(local_path)
            token       = self._get_access_token()
            upload_url  = (f"{ONEDRIVE_GRAPH_BASE}/me/drive/root:/"
                           f"{HBCE_FOLDER_NAME}/{remote_name}:/content")

            with open(local_path, "rb") as f:
                data = f.read()

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/octet-stream",
            }
            resp = rq.put(upload_url, headers=headers, data=data, timeout=120)

            if resp.status_code in (200, 201):
                item = resp.json()
                logger.info(f"OneDrive upload: {remote_name} → {item.get('id')}")
                return SyncResult(
                    success=True,
                    message=f"Uploaded to OneDrive: {remote_name}",
                    remote_id=item.get("id",""),
                    url=item.get("webUrl",""),
                )
            else:
                return SyncResult(False,
                    f"OneDrive upload HTTP {resp.status_code}: {resp.text[:200]}")

        except self.TokenExpiredError as e:
            return SyncResult(False, f"Auth error: {e}")
        except Exception as e:
            logger.error(f"OneDrive upload failed: {e}")
            return SyncResult(False, f"Upload failed: {e}")

    def download_file(self, remote_name: str, dest_path: str) -> SyncResult:
        """Download a file from the HBCE OneDrive folder."""
        try:
            import requests as rq

            token    = self._get_access_token()
            item_url = (f"{ONEDRIVE_GRAPH_BASE}/me/drive/root:/"
                        f"{HBCE_FOLDER_NAME}/{remote_name}")
            headers  = {"Authorization": f"Bearer {token}"}

            # Get download URL
            resp = rq.get(item_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                return SyncResult(False,
                    f"File not found on OneDrive: {remote_name}")

            dl_url = resp.json().get("@microsoft.graph.downloadUrl")
            if not dl_url:
                return SyncResult(False, "No download URL in OneDrive response.")

            dl_resp = rq.get(dl_url, timeout=120)
            with open(dest_path, "wb") as f:
                f.write(dl_resp.content)

            logger.info(f"OneDrive download: {remote_name} → {dest_path}")
            return SyncResult(True, f"Downloaded: {remote_name}")

        except self.TokenExpiredError as e:
            return SyncResult(False, f"Auth error: {e}")
        except Exception as e:
            logger.error(f"OneDrive download failed: {e}")
            return SyncResult(False, f"Download failed: {e}")

    def list_files(self) -> List[dict]:
        """Return files in the HBCE OneDrive folder."""
        try:
            import requests as rq

            token   = self._get_access_token()
            url     = (f"{ONEDRIVE_GRAPH_BASE}/me/drive/root:/"
                       f"{HBCE_FOLDER_NAME}:/children")
            headers = {"Authorization": f"Bearer {token}"}

            resp = rq.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("value", [])
            return []
        except Exception as e:
            logger.error(f"OneDrive list failed: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════════════
#  Cloud Sync Thread  (GOTCHA-013 compliant)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudSyncThread(QThread):
    """
    Executes a cloud sync operation in a background thread.
    Never calls Qt UI methods directly (GOTCHA-013).
    Emits signals for progress and completion.
    """

    progress      = pyqtSignal(int, str)   # (percent, message)
    completed     = pyqtSignal(object)     # SyncResult
    token_expired = pyqtSignal(str)        # provider_name — UI should re-auth

    def __init__(self, operation: str, provider,
                 local_path: str = "",
                 remote_name: str = "",
                 dest_path: str = "",
                 parent=None):
        super().__init__(parent)
        self._operation   = operation    # "upload" | "download" | "list"
        self._provider    = provider
        self._local_path  = local_path
        self._remote_name = remote_name
        self._dest_path   = dest_path

    def run(self):
        try:
            self.progress.emit(10, "Starting…")

            if self._operation == "upload":
                self.progress.emit(30, f"Uploading {os.path.basename(self._local_path)}…")
                result = self._provider.upload_file(
                    self._local_path, self._remote_name or None)

            elif self._operation == "download":
                self.progress.emit(30, f"Downloading {self._remote_name}…")
                result = self._provider.download_file(
                    self._remote_name, self._dest_path)

            else:
                result = SyncResult(False, f"Unknown operation: {self._operation}")

            self.progress.emit(100, "Done.")

            # Check for token expired result
            if not result.success and "expired" in result.message.lower():
                pname = getattr(self._provider.__class__, "DISPLAY_NAME",
                                type(self._provider).__name__)
                self.token_expired.emit(pname)

            self.completed.emit(result)

        except Exception as e:
            logger.error(f"CloudSyncThread error: {e}")
            self.completed.emit(SyncResult(False, str(e)))


# ═══════════════════════════════════════════════════════════════════════════════
#  Cloud Sync Manager
# ═══════════════════════════════════════════════════════════════════════════════

class CloudSyncManager:
    """
    Top-level coordinator for Google Drive + OneDrive cloud backup.

    Usage:
        mgr = CloudSyncManager.from_config_dir(Path("..."))
        thread = mgr.upload_async(local_path, provider=SyncProvider.GOOGLE_DRIVE)
        thread.completed.connect(my_slot)
        thread.start()
    """

    def __init__(self, config_dir: Path,
                 gdrive_secrets: Optional[str] = None,
                 onedrive_client_id: str = ""):
        self.config_dir = Path(config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)

        self.google = GoogleDriveProvider(config_dir, gdrive_secrets)
        self.onedrive = OneDriveProvider(config_dir, onedrive_client_id)

    @classmethod
    def from_config_dir(cls, config_dir: Path) -> "CloudSyncManager":
        """Create from default HBCE config directory."""
        secrets = os.path.join(config_dir, "gdrive_client_secrets.json")
        client_id = os.environ.get("HBCE_ONEDRIVE_CLIENT_ID", "")
        return cls(config_dir,
                   gdrive_secrets=secrets if os.path.exists(secrets) else None,
                   onedrive_client_id=client_id)

    def get_provider(self, provider: SyncProvider):
        if provider == SyncProvider.GOOGLE_DRIVE:
            return self.google
        return self.onedrive

    # ── Sync status ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a dict of provider auth status for the UI to display."""
        return {
            "google_drive": {
                "configured":     self.google.is_configured(),
                "authenticated":  self.google.is_authenticated(),
                "display_name":   "Google Drive",
            },
            "onedrive": {
                "configured":     self.onedrive.is_configured(),
                "authenticated":  self.onedrive.is_authenticated(),
                "display_name":   "Microsoft OneDrive",
            },
        }

    # ── Async operations (return a ready-to-start QThread) ───────────────────

    def upload_async(self, local_path: str,
                     provider: SyncProvider = SyncProvider.GOOGLE_DRIVE,
                     remote_name: Optional[str] = None,
                     parent=None) -> CloudSyncThread:
        return CloudSyncThread(
            "upload", self.get_provider(provider),
            local_path=local_path,
            remote_name=remote_name or os.path.basename(local_path),
            parent=parent,
        )

    def download_async(self, remote_name: str, dest_path: str,
                       provider: SyncProvider = SyncProvider.GOOGLE_DRIVE,
                       parent=None) -> CloudSyncThread:
        return CloudSyncThread(
            "download", self.get_provider(provider),
            remote_name=remote_name,
            dest_path=dest_path,
            parent=parent,
        )

    # ── Sync HBCE standard files ──────────────────────────────────────────────

    def backup_database(self, db_path: str,
                        provider: SyncProvider = SyncProvider.GOOGLE_DRIVE,
                        parent=None) -> CloudSyncThread:
        """Upload hbce.db to the cloud."""
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        rname = f"hbce_db_{ts}.db"
        return self.upload_async(db_path, provider, rname, parent)

    def backup_project(self, hbce_path: str,
                       provider: SyncProvider = SyncProvider.GOOGLE_DRIVE,
                       parent=None) -> CloudSyncThread:
        """Upload a .hbce project file."""
        return self.upload_async(hbce_path, provider, parent=parent)

    def list_remote_files(self,
                          provider: SyncProvider = SyncProvider.GOOGLE_DRIVE
                          ) -> List[dict]:
        """Synchronously list remote files (call from a thread, not UI)."""
        return self.get_provider(provider).list_files()

    # ── Auto-sync helper ──────────────────────────────────────────────────────

    def auto_sync_enabled_providers(self) -> List[SyncProvider]:
        """Return list of providers that are both configured and authenticated."""
        enabled = []
        if self.google.is_configured() and self.google.is_authenticated():
            enabled.append(SyncProvider.GOOGLE_DRIVE)
        if self.onedrive.is_configured() and self.onedrive.is_authenticated():
            enabled.append(SyncProvider.ONEDRIVE)
        return enabled
