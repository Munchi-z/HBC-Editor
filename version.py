# HBCE — Hybrid Controls Editor
# version.py — Single source of truth for version string

VERSION_MAJOR = 0
VERSION_MINOR = 2
VERSION_PATCH = 0
VERSION_LABEL = "alpha"

_patch_str = f"{VERSION_PATCH}-{VERSION_LABEL}" if VERSION_LABEL else str(VERSION_PATCH)
VERSION = f"V{VERSION_MAJOR}.{VERSION_MINOR}.{_patch_str}"

VERSION_TUPLE = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

APP_NAME      = "HBCE"
APP_FULL_NAME = "Hybrid Controls Editor"
APP_AUTHOR    = "HBCE Project"
APP_URL       = "https://github.com/Munchi-z/HBC-Editor"
BUILD_DATE    = "2026-04-01"

# ── Version history ─────────────────────────────────────────────────────────
# V0.2.0-alpha  2026-04-01  MILESTONE — all panels functional, device flow
#                           wired end-to-end
#                           Trend Viewer empty-state overlay
#                           Startup device list refresh (all 5 panels)
#                           Alarm Viewer DB-first load + refresh_from_db()
#                           Scheduler device picker dialog on new schedule
#                           Report Builder device filter dropdown
#                           All 5 refresh hooks verified via AST check
# V0.1.9b-alpha 2026-04-01  device_saved signal wired: wizard → main_window
#                           → dashboard + point_browser + alarm_viewer
#                           + scheduler + report_builder
#                           Dashboard 10s periodic device refresh
# V0.1.9a-alpha 2026-04-01  FIX-010: graphic_editor _palette AttributeError
#                           (lambda wrap) — full AST audit, no other instances
# V0.1.9-alpha  2026-04-01  CloudSyncPanel in Backup/Restore Tab 3
#                           Google Drive + OneDrive auth, upload, download
# V0.1.8-alpha  2026-04-01  FIX-009: graphic_editor _view AttributeError
#                           Connection Wizard vendor profile tips
#                           data/cloud_sync.py (733 ln)
#                           tests/ suite (6 files, 116 tests, stdlib unittest)
# V0.1.7-alpha  2026-04-01  data/models.py (510 ln), data/project.py (441 ln)
#                           vendors: JCI Metasys, Trane Tracer, Distech ECLYPSE
# V0.1.6-alpha  2026-04-01  Program Editor — FBD/node canvas (1,402 ln)
# V0.1.5-alpha  2026-03-31  Report Builder — PDF + Excel, 5 report types
# V0.1.4-alpha  2026-03-31  FIX: trend_viewer OSError (GOTCHA-017)
#                           FIX: scheduler device_name migration
# V0.1.3-alpha  2026-03-31  Scheduler — 7-day grid
# V0.1.2-alpha  2026-03-31  Backup / Restore — ARCH-011 flow
# V0.1.1-alpha  2026-03-31  Trend Viewer — pyqtgraph multi-series
# V0.1.0-alpha  2026-03-31  crash handler guard + security stubs
# V0.0.9-alpha  2026-03-30  Alarm Viewer visual redesign
# V0.0.7-alpha  2026-03-29  Point Browser — full implementation
# V0.0.6-alpha  2026-03-29  Connection Wizard — full implementation
# V0.0.1        2026-03-29  Initial skeleton
