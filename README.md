# ⚡ HBCE — Hybrid Controls Editor

![Version](https://img.shields.io/badge/version-V0.0.5--alpha-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![Python](https://img.shields.io/badge/python-3.11%2B-yellow)
![Build](https://github.com/Munchi-z/HBC-Editor/actions/workflows/build.yml/badge.svg)
![License](https://img.shields.io/badge/license-Proprietary-red)

**Universal BAS/B-AAC controller configuration, monitoring, and programming tool.**

HBCE is a Windows desktop application for building automation engineers, technicians,
and operators. One unified interface for connecting to, configuring, monitoring, and
programming controllers from multiple vendors over multiple protocols.

---

## 📦 Download

> **Latest release:** [Releases →](https://github.com/Munchi-z/HBC-Editor/releases/latest)

1. Download `HBCE-v0.0.5-alpha-windows.zip`
2. Extract the folder anywhere on your PC
3. Double-click `HBCE.exe` — no install or Python needed

**Requires:** Windows 10 or 11 (64-bit)

---

## 🖥️ What's Working (V0.0.5-alpha)

| Feature | Status |
|---------|--------|
| Dark / light theme + full user color customization | ✅ |
| Admin / Technician / Operator role system | ✅ |
| Hex Vortex logo — sidebar home button with collapse toggle | ✅ |
| Tools menu bar — all 8 module panels with keyboard shortcuts | ✅ |
| Dashboard — devices, alarms, stats, projects, quick actions | ✅ |
| Dashboard — drag-to-reorder editable widget layout | ✅ |
| Live system stats (CPU, memory, uptime) | ✅ |
| All module panels navigable (stubs) | ✅ |
| GitHub Actions CI/CD — auto .exe builds on tag push | ✅ |

## 🔜 In Development

| Feature | Priority |
|---------|----------|
| Connection Wizard — full step-by-step UI | 🔴 Next |
| Point Browser — BACnet object tree, read/write | 🔴 |
| Alarm Viewer — table, acknowledge, export | 🟡 |
| Trend Viewer — live pyqtgraph charts | 🟡 |
| Graphical Programming Editor (node + FBD) | 🟡 |
| Backup / Restore | 🟡 |
| Scheduler — weekly + exception schedules | 🟡 |
| Report Builder — PDF + Excel export | 🟡 |
| Vendor profiles (JCI, Trane, Distech) | 🔵 |

---

## 🔌 Protocols

| Protocol | Transport | Status |
|----------|-----------|--------|
| BACnet/IP | Ethernet / WiFi | ✅ Adapter ready |
| BACnet MS/TP | RS-485 Serial | ✅ Adapter ready |
| USB Direct | USB cable | ✅ Adapter ready |
| Modbus TCP | Ethernet | ✅ Adapter ready |
| Modbus RTU | RS-485 Serial | ✅ Adapter ready |
| Bluetooth / BLE | Wireless | Plugin slot reserved |
| WiFi Device | UDP/TCP | Plugin slot reserved |

## 🏭 Vendors

| Vendor | Controllers | Status |
|--------|------------|--------|
| Johnson Controls | Metasys NAE, NCE, ADX | Profile in development |
| Trane | Tracer UC210/400/600/800 | Profile in development |
| Distech Controls | ECLYPSE series | Profile in development |
| Generic BACnet | Any BACnet/IP or MS/TP | ✅ Ready |
| Generic Modbus | Any Modbus TCP/RTU | ✅ Ready |

---

## 🚀 Building from Source

```bash
git clone https://github.com/Munchi-z/HBC-Editor.git
cd HBC-Editor
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py               # Run in dev mode — no license needed
```

### Releasing via GitHub Actions

```bash
git add .
git commit -m "Your changes"
git push
git tag v0.0.5-alpha
git push origin v0.0.5-alpha
# GitHub builds and publishes HBCE.exe automatically
```

Monitor: [Actions →](https://github.com/Munchi-z/HBC-Editor/actions)
Download: [Releases →](https://github.com/Munchi-z/HBC-Editor/releases)

---

## 📁 Project Structure

```
HBCE/
├── main.py                    Entry point
├── version.py                 Version string — V0.0.5-alpha
├── requirements.txt           All dependencies
├── hbce.spec                  PyInstaller spec (local dev)
├── .github/workflows/         GitHub Actions CI/CD (build.yml v4)
├── core/                      Config, logging, app bootstrap
├── ui/
│   ├── theme_engine.py        Dark/light + color picker
│   ├── main_window.py         Main window + Tools menu
│   ├── sidebar.py             Logo home btn + device nav
│   ├── login_dialog.py        Login + role selection
│   └── panels/                All 8 module panels
├── comms/                     Protocol adapters (5 built, 2 reserved)
│   └── plugins/               Future: BLE, WiFi, custom
├── vendors/                   Vendor-specific controller profiles
├── data/                      SQLite DB, project file, cloud sync
├── licensing/                 License system (dev mode = free)
├── reports/                   PDF + Excel generation
├── portal/                    Flask license portal (future)
├── build_scripts/             Icon generator + build helpers
└── assets/                    Hex Vortex logo, icons, QSS themes
```

---

## 📋 Changelog

### V0.0.5-alpha — 2026-03-29
- Full file audit and version sync
- requirements.txt: added psutil for live dashboard stats
- All foundation docs updated

### V0.0.3-alpha — 2026-03-29
- Sidebar: Hex Vortex logo = Dashboard home, collapse toggle, connection status
- Tools menu: all panels moved up with keyboard shortcuts (Ctrl+A, Ctrl+R, etc.)
- Dashboard: fully built — devices, alarms, stats, projects, quick actions
- Dashboard: user-editable layout (drag reorder, show/hide widgets)
- Theme engine: prominent panel headers, DashCard styles, refined QSS

### V0.0.2-alpha — 2026-03-29
- CI fix: `permissions: contents: write` added to GitHub Actions workflow
- App confirmed launching and running on Windows

### V0.0.1 — 2026-03-29
- Initial skeleton: 52 files — core, comms, UI, DB, licensing, CI/CD, logo

---

## ⚠️ License

Proprietary software — all rights reserved.
Dev mode active: `HBCE_LICENSE_ENABLED = False` in `licensing/activator.py`
