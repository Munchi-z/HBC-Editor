# HBCE — Hybrid Controls Editor
# version.py — Single source of truth for version string
# Update this file ONLY when releasing a new version.
# All other files import from here — never hardcode the version elsewhere.

VERSION_MAJOR = 0
VERSION_MINOR = 0
VERSION_PATCH = 2
VERSION_LABEL = "alpha"      # alpha / beta / rc / "" (empty = stable release)

VERSION = f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}-{VERSION_LABEL}" \
          if VERSION_LABEL else \
          f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

VERSION_TUPLE = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

APP_NAME      = "HBCE"
APP_FULL_NAME = "Hybrid Controls Editor"
APP_AUTHOR    = "HBCE Project"
APP_URL       = "https://github.com/Munchi-z/HBC-Editor"

# Build date — update manually or via CI on each release
BUILD_DATE = "2026-03-29"

# ── Version history ────────────────────────────────────────────────────────
# V0.0.2-alpha  2026-03-29  CI pipeline fixed (FIX-006: permissions block)
# V0.0.1        2026-03-29  Initial skeleton — all core files, CI/CD setup
