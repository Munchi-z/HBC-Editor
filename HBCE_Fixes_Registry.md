# HBCE — Hybrid Controls Editor
## 🔧 Fixes Registry & Permanent Solutions Log
> Last Updated: 2026-03-31 | Current Version: **V0.1.2-alpha**

---

## 📊 STATS
| Fixes logged | 6 | Gotchas | 16 | Arch decisions | 13 |
|---|---|---|---|---|---|

---

## 🏗️ ARCHITECTURAL DECISIONS

| ID | Decision | Rationale | Date |
|----|----------|-----------|------|
| ARCH-001 | Python + PyQt6 | BACnet lib, fast dev, .exe via PyInstaller | 2026-03-29 |
| ARCH-002 | Comms plugin/adapter | New protocols snap in without core rebuild | 2026-03-29 |
| ARCH-003 | SQLite + optional cloud | Portable, no server dep | 2026-03-29 |
| ARCH-004 | PyInstaller + GitHub Actions | Free Windows runners | 2026-03-29 |
| ARCH-005 | All 8 panels from day one | No dead-end UI | 2026-03-29 |
| ARCH-006 | Encrypted permissions in SQLite | Prevents tampering | 2026-03-29 |
| ARCH-007 | Theme: QSS + JSON profile | Colors survive reinstalls | 2026-03-29 |
| ARCH-008 | HBCE_LICENSE_ENABLED = False | Dev mode — free | 2026-03-29 |
| ARCH-009 | Graphical editor: node + FBD | TGP2 + Metasys/Niagara | 2026-03-29 |
| ARCH-010 | Editor: palette + Ctrl+Space | Browse OR type | 2026-03-29 |
| ARCH-011 | Upload: diff → backup → confirm | Safest flow | 2026-03-29 |
| ARCH-012 | Flask portal 3-layer (ON HOLD) | Incremental layers | 2026-03-29 |
| ARCH-013 | Sidebar logo = Dashboard home | Cleaner UX | 2026-03-29 |

---

## ⚠️ KNOWN GOTCHAS

| ID | Area | Issue | Fix |
|----|------|-------|-----|
| GOTCHA-001 | PyInstaller | PyQt6 plugins not auto-detected | hbce_ci.spec hiddenimports |
| GOTCHA-002 | BAC0 | MS/TP wrong port/baud → hard crash | bacnet_mstp.py _validate_port() |
| GOTCHA-003 | PyQt6 QSS | Not all CSS3 supported | QSS-safe subset only |
| GOTCHA-004 | pyserial | RS-485 driver missing = silent fail | _validate_port() + user prompt |
| GOTCHA-005 | Google Drive | OAuth token expiry = silent fail | Planned in cloud_sync.py |
| GOTCHA-006 | PyInstaller+Qt | qwindows.dll missing | hbce_ci.spec collected |
| GOTCHA-007 | BAC0+PyQt6 | BAC0 thread can't call Qt UI | Qt signals only |
| GOTCHA-008 | QGraphicsScene | Wire z-order flicker | Wire z below block z |
| GOTCHA-009 | pymodbus 3.x | API changed from 2.x | 3.x API only |
| GOTCHA-010 | Flask+SQLite | Multi-worker writes unsafe | Single gunicorn worker |
| GOTCHA-011 | GitHub Actions | New repos: token read-only | `permissions: contents: write` |
| GOTCHA-012 | Dashboard stats | psutil missing = unavailable | Added to requirements.txt |
| GOTCHA-013 | Connection tests | Must use QThread — never block UI | ConnectionTestThread in wizard |
| GOTCHA-014 | Point Browser reads | Object list + value reads must be threaded | ObjectListThread + PointReadThread |
| GOTCHA-015 | PyQt6 QStyledItemDelegate | `option.state.State.Selected` is wrong — `option.state` is a flags value not a class | Use `QStyle.StateFlag.State_Selected` |
| GOTCHA-016 | crash_handler + paint() | Delegate crash fires per-row per-repaint → excepthook fires hundreds of times → stack overflow | Add reentrance guard + 5s deduplication in `_handle_crash()` |

---

## 🐛 BUG FIX LOG

### FIX-001 → FIX-006 (all previously documented, all verified ✅)
- FIX-001: `shell: python` invalid → script file approach
- FIX-002: BAC0 pip crash → split core/optional
- FIX-003: `version_info.txt` missing → clean hbce_ci.spec
- FIX-004: Bash heredoc garbled → PowerShell here-strings
- FIX-005: Node.js 20 warning → informational only
- FIX-006: `permissions: contents: write` missing → added

---

## 🔄 VERSION CHANGELOG

### V0.1.2-alpha — 2026-03-30
**Alarm Viewer — full implementation (1,294 lines):**
- Layout: toolbar + filter bar + left table + right detail panel (splitter)
- Priority color coding: P1 Life Safety (deep red) → P8 Informational (blue-grey)
- Active critical alarms (P1–P2) render bold; cleared alarms render italic
- Table columns: ID, Timestamp, Age, Device, Object, Description, Priority, State, Category, Acked By
- Single acknowledge: double-click row OR right-click → Acknowledge
- Bulk acknowledge: select multiple rows → toolbar button (shows live active count)
- Ack All Active: acknowledges all visible active alarms in one action
- AckDialog: requires technician name/ID, optional note; pre-fills logged-in username
- Ack thread: AlarmAckThread (QThread) — GOTCHA-013 compliant
- Filter bar: real-time text search (device/object/description), State combo, Priority combo, Category combo
- Category combo: auto-populated from loaded alarm data
- Clear filters button resets all four filters
- Live polling: toggle ON/OFF, configurable 10s/30s/1min/5min interval
- AlarmPollThread: independent poll loop, stop() safe shutdown
- Detail panel: priority badge, all alarm fields, notes field, acknowledge button
- Context menu: Acknowledge, View Details, Copy Description, Copy Row as CSV, Go to Point in Browser
- CSV export: all visible/filtered rows, full field set
- PDF export: ReportLab landscape A4, priority-colored rows, graceful ImportError message
- Age column: auto-refreshes every 60 s via QTimer (no full reload)
- Status bar: Total / Visible / Active counts + polling interval
- Constructor signature: config=None, db=None, current_user=None (matches main_window pattern)
- Username pre-fill: reads current_user["username"] for AckDialog

### V0.0.7-alpha — 2026-03-29
**Point Browser — full implementation (1,426 lines):**
- Layout: left object tree + center point table + right detail panel (splitter)
- Tree: Device → Groups (Analog/Binary/MS/Schedule/Trend/Notification/Modbus) → Objects
- Table: 8 columns — Name, Type, Instance, Value, Units, Status, Override, Priority
- Value coloring: blue=analog, green/grey=binary, red=error
- Inline write: double-click writable row → WriteDialog with 16-level priority selector
- Priority warning: dialog warns when writing priority < 8
- Override indicator: 🔴 badge in Override column
- Release override: context menu → write null at P8
- Filter bar: real-time search by name, type, or value
- Type filter: All / Analog / Binary / Multi-State / Overrides only / Alarms only
- Context menu: Write, Override P8, Release, Read Now, COV Subscribe, Add to Trend, Copy
- COV subscription: tracked set, visual indicator
- Live polling: QTimer toggle, configurable 1–60s interval, polls all visible rows
- Detail panel: all properties, priority array viewer, write button
- Background threads: ObjectListThread (loads list), PointReadThread (reads values), WriteThread
- CSV export: filtered visible rows via file dialog
- Status bar: object count, visible count, polling status
- GOTCHA-014 added

### V0.0.6-alpha — 2026-03-29
- Connection Wizard 1,403 lines — 5-step, templates, recent, QThread

### V0.0.5-alpha — 2026-03-29
- Full file audit and sync

### V0.0.3-alpha — 2026-03-29
- UI redesign: sidebar, tools menu, dashboard

### V0.0.2-alpha — 2026-03-29
- FIX-006: CI permissions — app confirmed running

### V0.0.1 — 2026-03-29
- Initial 52-file skeleton
