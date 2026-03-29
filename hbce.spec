# HBCE — Hybrid Controls Editor
# hbce.spec — PyInstaller build specification
#
# Build command:
#   pyinstaller hbce.spec --clean --noconfirm
#
# Output: dist/HBCE/HBCE.exe (one-dir) or dist/HBCE.exe (one-file)
# We use one-dir for faster startup; wrap with Inno Setup for installer.
#
# GOTCHA-001: PyQt6 plugins (platform, styles, imageformats) are NOT
#             auto-detected by PyInstaller. They are explicitly collected below.
# GOTCHA-006: platforms/qwindows.dll must be included or app won't open.

import sys
from pathlib import Path

block_cipher = None

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        # Include all assets
        ('assets/icons',  'assets/icons'),
        ('assets/themes', 'assets/themes'),
    ],
    hiddenimports=[
        # PyQt6 internals
        'PyQt6.sip',
        'PyQt6.QtPrintSupport',

        # BAC0 hidden deps
        'BAC0',
        'BAC0.core',
        'BAC0.core.io',
        'bacpypes3',

        # pymodbus 3.x
        'pymodbus',
        'pymodbus.client',
        'pymodbus.client.tcp',
        'pymodbus.client.serial',
        'pymodbus.framer',
        'pymodbus.framer.rtu_framer',
        'pymodbus.framer.socket_framer',

        # pyserial
        'serial',
        'serial.tools',
        'serial.tools.list_ports',

        # cryptography
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.backends',

        # Cloud sync
        'google.oauth2',
        'google.auth',
        'googleapiclient',
        'msal',

        # Reports
        'reportlab',
        'reportlab.lib',
        'reportlab.platypus',
        'openpyxl',

        # pyqtgraph
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',       # only include if pyqtgraph requires it
        'scipy',
        'PIL',
        'cv2',
        'IPython',
        'notebook',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Collect PyQt6 plugins (fixes GOTCHA-001 and GOTCHA-006) ──────────────────
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Executable ────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HBCE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No console window (set True for debugging)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/hbce_icon.ico',  # Replace with real icon
    version='version_info.txt',         # Windows version info block
    uac_admin=False,                     # Do not require admin rights
)

# ── One-Dir Collection ────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HBCE',
)

# ── Version info file (create version_info.txt separately) ───────────────────
# Run: python -c "import PyInstaller; print(PyInstaller.__version__)"
# Then generate version_info.txt with:
#   pyi-set_version version_info.txt dist/HBCE/HBCE.exe
