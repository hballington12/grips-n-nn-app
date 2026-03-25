# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for GRIPS Spectra Viewer.

Platform-specific packaging:
- macOS: creates a .app bundle via BUNDLE (double-clickable, shows in Dock)
- Linux/Windows: creates a directory with the executable + libraries
"""

import sys

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("models/*.onnx", "models"),
    ],
    hiddenimports=[
        "onnxruntime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tensorflow",
        "keras",
        "torch",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GRIPSSpectraViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GRIPSSpectraViewer",
)

# macOS: wrap the COLLECT output in a .app bundle.
# BUNDLE creates the standard macOS application structure:
#   GRIPSSpectraViewer.app/
#     Contents/
#       MacOS/GRIPSSpectraViewer  (the executable)
#       Resources/                (icons, etc.)
#       Info.plist                (app metadata)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GRIPSSpectraViewer.app",
        bundle_identifier="com.grips.spectraviewer",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleName": "GRIPS Spectra Viewer",
            "NSHighResolutionCapable": True,
        },
    )
