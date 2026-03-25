# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for GRIPS Spectra Viewer.

PyInstaller bundles the Python interpreter, all dependencies, and our
code into a single directory (--onedir) or executable (--onefile).

Key concepts:
- Analysis: scans imports to find all dependencies
- datas: extra non-Python files to include (models, etc.)
- hiddenimports: modules that PyInstaller can't detect automatically
- Tree/COLLECT: assembles everything into the output directory
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # Include ONNX model files in the bundle
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
    console=False,  # No terminal window on launch
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
