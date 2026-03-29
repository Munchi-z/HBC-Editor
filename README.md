# ⚡ HBCE — Hybrid Controls Editor

![Version](https://img.shields.io/badge/version-V0.0.1-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![Python](https://img.shields.io/badge/python-3.11%2B-yellow)
![License](https://img.shields.io/badge/license-Proprietary-red)
![Build](https://github.com/Munchi-z/HBC-Editor/actions/workflows/build.yml/badge.svg)

**Universal BAS/B-AAC controller configuration, monitoring, and programming tool.**

HBCE is a Windows desktop application for building automation engineers,
technicians, and operators. It provides a single unified interface for connecting
to, configuring, monitoring, and programming controllers from multiple vendors.

---

## 📦 Download

> **Latest release:** [Releases page →](https://github.com/Munchi-z/HBC-Editor/releases/latest)

1. Download `HBCE-vX.X.X-windows.zip` from the latest release
2. Extract the folder anywhere on your PC
3. Double-click `HBCE.exe`
4. No installation or Python required

**Requirements:** Windows 10 or Windows 11 (64-bit)

---

## 🔌 Supported Protocols

| Protocol | Transport |
|----------|-----------|
| BACnet/IP | Ethernet / WiFi |
| BACnet MS/TP | RS-485 Serial |
| USB Direct | USB cable to controller |
| Modbus TCP | Ethernet |
| Modbus RTU | RS-485 Serial |
| Bluetooth / WiFi device | *Coming soon* |

## 🏭 Supported Vendors

| Vendor | Controllers |
|--------|------------|
| Johnson Controls | Metasys NAE, NCE, ADX |
| Trane | Tracer UC210, UC400, UC600, UC800 |
| Distech Controls | ECLYPSE series |
| Generic BACnet | Any BACnet/IP or MS/TP device |
| Generic Modbus | Any Modbus TCP/RTU device |

## 🛠️ Features

- **Connection Wizard** — step-by-step device connection for any protocol
- **Point Browser** — read/write BACnet objects and Modbus registers
- **Alarm Viewer** — view and acknowledge alarms from all connected devices
- **Trend Viewer** — live and historical charts for any data point
- **Program Editor** — node-based canvas (Trane TGP2 style) + FBD (Metasys/Niagara style)
- **Backup / Restore** — full controller config backup with diff preview
- **Scheduler** — weekly and exception schedule editor
- **Reports** — PDF and Excel export

---

## 🚀 Building from Source

```bash
# Clone the repo
git clone https://github.com/Munchi-z/HBC-Editor.git
cd HBC-Editor

# Create a virtual environment
python -m venv venv
venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt

# Run in development mode (no license needed)
python main.py

# Build the .exe
pyinstaller hbce.spec --clean --noconfirm
# Output: dist\HBCE\HBCE.exe
```

### Automatic builds via GitHub Actions

Push a version tag and GitHub builds the .exe automatically:

```bash
git tag v0.0.1
git push origin v0.0.1
# GitHub Actions builds HBCE.exe and creates a Release with the zip attached
```

Check build status: [Actions tab →](https://github.com/Munchi-z/HBC-Editor/actions)

---

## 📁 Project Structure

```
HBCE/
├── main.py                  Entry point
├── version.py               Version string (update before tagging)
├── requirements.txt         Dependencies
├── hbce.spec                PyInstaller build spec
├── .github/workflows/       GitHub Actions CI/CD
├── core/                    Config, logging, app bootstrap
├── ui/                      Theme engine, windows, panels
├── comms/                   Protocol adapters (BACnet, Modbus, USB)
├── vendors/                 Vendor-specific controller profiles
├── data/                    SQLite DB, project file, cloud sync
├── licensing/               License system (dev mode by default)
├── reports/                 PDF + Excel report generation
├── portal/                  Flask license portal (future)
└── assets/                  Icons, themes
```

---

## 📋 Changelog

### V0.0.1 — In Progress
- Initial project skeleton
- All 5 communication adapters (BACnet/IP, MS/TP, USB, Modbus TCP/RTU)
- Theme engine with dark/light mode and user color customization
- Login system with role-based access (Admin/Technician/Operator)
- All 8 feature modules scaffolded and navigable
- GitHub Actions CI/CD build pipeline

---

## ⚠️ License

HBCE is proprietary software. All rights reserved.
For licensing inquiries, contact the project maintainer.

*Dev mode is currently enabled — no license required for development and testing.*
