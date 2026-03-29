# HBCE — Hybrid Controls Editor
# version.py — Single source of truth for version string
# Update this file ONLY when releasing a new version.
# All other files import from here — never hardcode the version elsewhere.

VERSION_MAJOR = 0
VERSION_MINOR = 0
VERSION_PATCH = 1

VERSION = f"V{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
VERSION_TUPLE = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

APP_NAME = "HBCE"
APP_FULL_NAME = "Hybrid Controls Editor"
APP_AUTHOR = "HBCE Project"
APP_URL = "https://hbce.io"  # placeholder

# Build date — update manually or via CI on each release
BUILD_DATE = "2026-03-29"
