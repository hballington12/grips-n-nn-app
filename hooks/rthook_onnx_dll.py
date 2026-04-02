"""PyInstaller runtime hook: register DLL search paths for ONNX Runtime on Windows.

Windows' native LoadLibrary doesn't find DLLs inside PyInstaller's bundle
unless we explicitly add those directories via os.add_dll_directory().
This hook runs before any user code, so it's in place by the time
onnxruntime tries to load onnxruntime_pybind11_state.pyd.
"""

import os
import sys

if sys.platform == "win32" and getattr(sys, "frozen", False):
    bundle_dir = sys._MEIPASS

    # Add the bundle root (where we duplicate core DLLs)
    os.add_dll_directory(bundle_dir)

    # Add the onnxruntime/capi directory (where the .pyd and its
    # companion DLLs live in the original package layout)
    capi_dir = os.path.join(bundle_dir, "onnxruntime", "capi")
    if os.path.isdir(capi_dir):
        os.add_dll_directory(capi_dir)
