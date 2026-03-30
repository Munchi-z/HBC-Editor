# HBCE — Hybrid Controls Editor
# version.py — Single source of truth for version string

VERSION_MAJOR = 0
VERSION_MINOR = 0
VERSION_PATCH = 9
VERSION_LABEL = "alpha"

VERSION = f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}-{VERSION_LABEL}" \
          if VERSION_LABEL else \
          f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

VERSION_TUPLE = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

APP_NAME      = "HBCE"
APP_FULL_NAME = "Hybrid Controls Editor"
APP_AUTHOR    = "HBCE Project"
APP_URL       = "https://github.com/Munchi-z/HBC-Editor"
BUILD_DATE    = "2026-03-30"

# ── Version history ─────────────────────────────────────────────────────────
# V0.0.9-alpha  2026-03-30  Alarm Viewer visual redesign — stripe+pill style
# V0.0.8-alpha  2026-03-30  Alarm Viewer — full implementation
# V0.0.7-alpha  2026-03-29  Point Browser — full implementation
# V0.0.6-alpha  2026-03-29  Connection Wizard — full implementation
# V0.0.5-alpha  2026-03-29  Full file sync
# V0.0.3-alpha  2026-03-29  UI redesign: sidebar, tools menu, dashboard
# V0.0.2-alpha  2026-03-29  CI fix: permissions block
# V0.0.1        2026-03-29  Initial skeleton
