# HBCE — Hybrid Controls Editor
# version.py — Single source of truth for version string

VERSION_MAJOR = 0
VERSION_MINOR = 1
VERSION_PATCH = 9
VERSION_LABEL = "a-alpha"

# Label is appended with no separator if it starts with a letter suffix (e.g. "a-alpha")
_patch_str = f"{VERSION_PATCH}-{VERSION_LABEL}" if VERSION_LABEL else str(VERSION_PATCH)
VERSION = f"V{VERSION_MAJOR}.{VERSION_MINOR}.{_patch_str}"

VERSION_TUPLE = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

APP_NAME      = "HBCE"
APP_FULL_NAME = "Hybrid Controls Editor"
APP_AUTHOR    = "HBCE Project"
APP_URL       = "https://github.com/Munchi-z/HBC-Editor"
BUILD_DATE    = "2026-04-01"

# ── Version history ─────────────────────────────────────────────────────────
# V0.1.9a-alpha 2026-04-01  FIX-010: graphic_editor _palette AttributeError
#                           (same family as FIX-009 — toolbar built before
#                           self._palette assigned → wrap in lambda)
#                           Full AST audit confirmed no other instances anywhere
# V0.1.9-alpha  2026-04-01  CloudSyncPanel in Backup/Restore (Tab 3)
#                           Google Drive + OneDrive auth, upload, download
#                           Auto-sync trigger + selection bridge
# V0.1.8-alpha  2026-04-01  FIX: graphic_editor _view AttributeError
#                           Connection Wizard vendor profile tips
#                           data/cloud_sync.py (733 ln), tests/ smoke suite
# V0.1.7-alpha  2026-04-01  data/models.py (510 ln), data/project.py (441 ln),
#                           vendors: JCI Metasys, Trane Tracer, Distech ECLYPSE
#                           FIX: graphic_editor last_insert_rowid → db.insert()
# V0.1.6-alpha  2026-04-01  Program Editor — full FBD/node canvas (1,403 lines)
# V0.1.5-alpha  2026-03-31  Report Builder — PDF+Excel, 5 report types
# V0.1.1-alpha  2026-03-31  Trend Viewer — full implementation
# V0.1.0-alpha  2026-03-31  Version milestone — alarm viewer fix + security stubs
# V0.0.9-alpha  2026-03-30  Alarm Viewer visual redesign + crash handler
# V0.0.8-alpha  2026-03-30  Alarm Viewer — full implementation
# V0.0.7-alpha  2026-03-29  Point Browser — full implementation
# V0.0.6-alpha  2026-03-29  Connection Wizard — full implementation
# V0.0.5-alpha  2026-03-29  Full file sync
# V0.0.3-alpha  2026-03-29  UI redesign: sidebar, tools menu, dashboard
# V0.0.2-alpha  2026-03-29  CI fix: permissions block
# V0.0.1        2026-03-29  Initial skeleton
