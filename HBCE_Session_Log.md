# HBCE — Hybrid Controls Editor
## 📋 Session Log & Conversation Tracker
> Last Updated: 2026-03-31 | Current Version: V0.1.2-alpha
> Drag into a new Claude chat to continue from exactly here.

---

## 🗂️ PROJECT IDENTITY

| Field | Value |
|-------|-------|
| App Name | HBCE — Hybrid Controls Editor |
| Current Version | **V0.1.1-alpha** |
| GitHub | https://github.com/Munchi-z/HBC-Editor.git |
| Framework | Python + PyQt6 |
| Build | PyInstaller → .exe via GitHub Actions CI/CD |
| Target OS | Windows 10 + Windows 11 (64-bit) |
| License | DEV MODE — free (HBCE_LICENSE_ENABLED = False) |
| Logo | Hex Vortex (Option B) — locked |

---

## ✅ ALL PLANNING DECISIONS — LOCKED

| Area | Decision |
|------|----------|
| Framework | Python + PyQt6 |
| Comms | Plugin/adapter system — BACnet/IP, MS/TP, USB, Modbus TCP/RTU + BT/WiFi slots |
| Storage | Local SQLite + optional Google Drive / OneDrive sync |
| License | HBCE_LICENSE_ENABLED = False — Flask portal ON HOLD |
| Roles | Admin / Technician / Operator |
| Vendors | JCI Metasys, Trane Tracer, Distech ECLYPSE + generic BACnet/Modbus |
| Graphical Editor | Node canvas (TGP2) + FBD (Metasys/Niagara) |
| Upload flow | Diff preview → auto-backup → confirm → upload |
| Reports | PDF (ReportLab) + Excel (openpyxl) — both |
| Logo | Hex Vortex Option B — all formats generated |
| Dashboard | Fully editable widget layout |
| Sidebar | Logo = Dashboard home, device items only, collapse toggle |
| Tools menu | Alarms, Trends, Editor, Scheduler, Backup, Reports |
| Connection Wizard | 5-step: vendor → protocol → params+help → test+picker → save |
| Point Browser | Tree + table + detail panel, inline write, live poll, CSV export |
| Alarm Viewer | Table + detail panel, priority color coding, ack, filters, CSV/PDF export |

---

## 🏗️ COMPLETE FILE INVENTORY — V0.1.1-alpha

### ✅ FULLY IMPLEMENTED

| File | Lines | Notes |
|------|-------|-------|
| `main.py` | 48 | Entry point |
| `version.py` | 30 | **V0.1.1-alpha** |
| `requirements.txt` | 42 | psutil + reportlab included |
| `hbce.spec` | 137 | PyInstaller local spec |
| `.github/workflows/build.yml` | 268 | v4 — all 6 fixes applied |
| `core/app.py` | 125 | Startup orchestrator |
| `core/config.py` | 120 | JSON config |
| `core/logger.py` | 79 | Logging |
| `ui/theme_engine.py` | 539 | Dark/light + color picker |
| `ui/main_window.py` | 368 | Tools menu, redesigned layout |
| `ui/sidebar.py` | 336 | Logo=home, collapse, conn status |
| `ui/login_dialog.py` | 214 | Login + first-launch setup |
| `ui/panels/dashboard.py` | 730 | Full — 5 widgets, editable layout |
| `ui/panels/connection_wizard.py` | 1,403 | Full — 5-step wizard |
| `ui/panels/point_browser.py` | 1,426 | Full — V0.0.7-alpha |
| `ui/panels/alarm_viewer.py` | **1,294** | **FULL IMPLEMENTATION V0.1.1-alpha** |
| `data/db.py` | 184 | SQLite schema + helpers |
| `licensing/activator.py` | 219 | Dev bypass + prod path |
| `comms/base_adapter.py` | 277 | Abstract protocol interface |
| `comms/bacnet_ip.py` | 279 | BACnet/IP via BAC0 |
| `comms/bacnet_mstp.py` | 276 | BACnet MS/TP + port validation |
| `comms/modbus_tcp.py` | 203 | Modbus TCP via pymodbus 3.x |
| `comms/modbus_rtu.py` | 233 | Modbus RTU RS-485 |
| `comms/usb_direct.py` | 201 | USB direct → delegates |
| `portal/app.py` | 297 | Flask portal (ON HOLD) |
| `assets/icons/` | — | SVG, ICO, 5x PNG |

### 🔲 STUB — Navigable, not yet implemented (81 lines each)

| File | Priority |
|------|----------|
| `ui/panels/backup_restore.py` | **1,762** | **FULL IMPLEMENTATION V0.1.2-alpha** |
| `ui/panels/graphic_editor.py` | 🟡 MEDIUM (most complex) |
| `ui/panels/backup_restore.py` | 🟡 MEDIUM |
| `ui/panels/scheduler.py` | 🟡 MEDIUM |
| `ui/panels/report_builder.py` | 🟡 MEDIUM |
| `ui/panels/custom_controller.py` | 🔵 LOW — reserved |

### 🔲 NOT YET CREATED

| File | Notes |
|------|-------|
| `data/models.py` | Python dataclasses |
| `data/project.py` | .hbce ZIP project file |
| `data/cloud_sync.py` | Google Drive + OneDrive |
| `vendors/johnson_controls/metasys.py` | JCI profile |
| `vendors/trane/tracer.py` | Trane profile |
| `vendors/distech/eclypse.py` | Distech profile |
| `reports/pdf_builder.py` | PDF generation |
| `reports/excel_builder.py` | Excel generation |
| `tests/` | Unit + smoke tests |

---

## 📋 ALARM VIEWER — FULL SPEC (V0.1.1-alpha)

| Feature | Implementation |
|---------|---------------|
| Layout | Toolbar + filter bar + left table + right detail panel (splitter-resizable) |
| Priority colors | P1 Life Safety (#7B0000 deep red) → P8 Informational (#37474F blue-grey) |
| Bold/italic | Active P1–P2 = bold; Cleared = italic |
| Table columns | ID, Timestamp, Age, Device, Object, Description, Priority, State, Category, Acked By |
| Single ack | Double-click row OR right-click → Acknowledge |
| Bulk ack | Select multiple rows → toolbar button (live active count shown) |
| Ack All Active | Acknowledges all visible active alarms in one action |
| AckDialog | Requires name/ID, optional note; pre-fills logged-in username |
| Filter bar | Text search (device/object/desc), State, Priority, Category combos |
| Category combo | Auto-populated from loaded alarm data |
| Live polling | Toggle ON/OFF, 10s/30s/1min/5min, AlarmPollThread |
| Detail panel | Priority badge, all fields, notes, acknowledge button |
| Context menu | Acknowledge, View Details, Copy Description, Copy Row CSV, Go to Point |
| CSV export | All visible/filtered rows, full field set |
| PDF export | ReportLab landscape A4, priority-colored rows |
| Age column | Auto-refreshes every 60 s (QTimer, no full reload) |
| Status bar | Total / Visible / Active counts + polling interval |
| Threading | AlarmLoadThread + AlarmAckThread + AlarmPollThread (GOTCHA-013) |

---

## 📅 SESSION HISTORY

| # | Date | What Happened |
|---|------|---------------|
| 1 | 2026-03-29 | Full planning Q&A |
| 2 | 2026-03-29 | 45 files — core skeleton |
| 3 | 2026-03-29 | Logo rounds, dev mode |
| 4 | 2026-03-29 | CI/CD pipeline |
| 5 | 2026-03-29 | Logo locked, all icons |
| 6 | 2026-03-29 | CI FIX-001→005 |
| 7 | 2026-03-29 | CI FIX-006. V0.0.2-alpha |
| 8 | 2026-03-29 | ✅ App launched! |
| 9 | 2026-03-29 | UI redesign. V0.0.3-alpha |
| 10 | 2026-03-29 | Full doc sync. V0.0.5-alpha |
| 11 | 2026-03-29 | Connection Wizard 1,403 ln. V0.0.6-alpha |
| 12 | 2026-03-29 | Point Browser 1,426 ln. V0.0.7-alpha |
| 13 | 2026-03-30 | Alarm Viewer 1,294 ln + packaged. V0.0.8-alpha. |
| 14 | 2026-03-30 | Alarm Viewer visual redesign (stripe+pill). V0.0.9-alpha. |
| 15 | 2026-03-31 | Delegate crash fix, crash handler guard, security/app_integrity.py, V0.1.0-alpha. |
| 16 | 2026-03-31 | Trend Viewer 1,085 ln — pyqtgraph, multi-series, live poll, CSV. V0.1.1-alpha. |
| 17 | 2026-03-31 | Backup/Restore 1,762 ln — ARCH-011 flow, diff viewer, auto-backup, typed confirm. V0.1.2-alpha. |

---

## 🔜 IMPLEMENTATION QUEUE

1. 🔴 `ui/panels/trend_viewer.py` — pyqtgraph live charts, multi-point overlay, configurable time window, CSV export
2. 🟡 `ui/panels/graphic_editor.py` — node canvas + FBD (most complex)
4. 🟡 `ui/panels/scheduler.py` — 7-day grid, exception schedules
5. 🟡 `ui/panels/report_builder.py` — PDF + Excel export
6. 🔵 Vendor profiles — JCI, Trane, Distech
7. 🔵 `data/models.py` + `project.py`
8. 🔵 `data/cloud_sync.py`

---

## 🔜 NEXT SESSION PROMPT
> "Here is my session log [attach] and fixes registry [attach].
> V0.1.2-alpha — Backup/Restore fully implemented (1,762 lines).
> Implement the Scheduler panel next — 7-day week grid, BACnet schedule
> object read/write, exception schedules, holiday overrides, per-day
> start/stop time slots, live sync with connected device."

---

## 📌 STANDING REMINDERS
- ⏸️ DigitalOcean portal — ON HOLD
- Reports = PDF + Excel both
- Logo = Hex Vortex B — locked
- GOTCHA-011: Always `permissions: contents: write` in release CI jobs
- GOTCHA-013: All network ops use QThread — never block UI
- Constructor pattern: always `config=None, db=None, current_user=None, parent=None`
