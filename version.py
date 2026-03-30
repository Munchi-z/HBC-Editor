# HBCE — Hybrid Controls Editor
# version.py

VERSION_MAJOR = 0
VERSION_MINOR = 0
VERSION_PATCH = 3
VERSION_LABEL = "alpha"

VERSION = f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}-{VERSION_LABEL}" \
          if VERSION_LABEL else \
          f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

VERSION_TUPLE = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

APP_NAME      = "HBCE"
APP_FULL_NAME = "Hybrid Controls Editor"
APP_AUTHOR    = "HBCE Project"
APP_URL       = "https://github.com/Munchi-z/HBC-Editor"
BUILD_DATE    = "2026-03-29"

# ── Version history ────────────────────────────────────────────────────────
# V0.0.3-alpha  2026-03-29  UI redesign: sidebar logo, tools menu, full dashboard
# V0.0.2-alpha  2026-03-29  CI fix: permissions block (FIX-006)
# V0.0.1        2026-03-29  Initial skeleton
