"""Diagnostic script for Windows ONNX Runtime DLL issues.

Run this from the built bundle directory:
    cd dist\GRIPSSpectraViewer
    .\GRIPSSpectraViewer.exe --diagnose   (if wired up)

Or standalone with the bundled Python:
    cd dist\GRIPSSpectraViewer
    python ..\..\scripts\diagnose_windows_dll.py

Or just copy this file into dist\GRIPSSpectraViewer\ and run:
    python diagnose_windows_dll.py
"""

import ctypes
import os
import sys
from pathlib import Path


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main():
    section("ENVIRONMENT")
    print(f"Python:        {sys.version}")
    print(f"Platform:      {sys.platform}")
    print(f"Frozen:        {getattr(sys, 'frozen', False)}")
    print(f"sys.executable:{sys.executable}")
    print(f"cwd:           {os.getcwd()}")

    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)
        print(f"_MEIPASS:      {bundle_dir}")
    else:
        bundle_dir = Path(sys.executable).parent
        print(f"exe dir:       {bundle_dir}")

    section("ONNX RUNTIME FILES IN BUNDLE")
    ort_files = list(bundle_dir.rglob("onnxruntime*"))
    if not ort_files:
        print("  !! NO onnxruntime files found in bundle!")
    for f in sorted(ort_files):
        rel = f.relative_to(bundle_dir)
        size_kb = f.stat().st_size / 1024
        print(f"  {rel}  ({size_kb:.0f} KB)")

    section("ONNX CAPI DIRECTORY")
    capi_dir = bundle_dir / "onnxruntime" / "capi"
    if capi_dir.is_dir():
        print(f"  EXISTS: {capi_dir}")
        for f in sorted(capi_dir.iterdir()):
            size_kb = f.stat().st_size / 1024
            print(f"    {f.name}  ({size_kb:.0f} KB)")
    else:
        print(f"  !! NOT FOUND: {capi_dir}")
        # Check alternative locations
        for alt in ["onnxruntime/capi", "onnxruntime\\capi", "_internal/onnxruntime/capi"]:
            alt_path = bundle_dir / alt
            if alt_path.is_dir():
                print(f"  Found at alternative: {alt_path}")

    section("DLLs AT BUNDLE ROOT")
    root_dlls = list(bundle_dir.glob("*.dll")) + list(bundle_dir.glob("*.pyd"))
    ort_root = [f for f in root_dlls if "onnx" in f.name.lower()]
    if ort_root:
        for f in sorted(ort_root):
            print(f"  {f.name}  ({f.stat().st_size / 1024:.0f} KB)")
    else:
        print("  No onnxruntime DLLs at bundle root")

    section("ATTEMPTING DLL LOAD WITH ctypes")
    # Try loading onnxruntime.dll directly to see the real error
    dll_candidates = [
        bundle_dir / "onnxruntime.dll",
        bundle_dir / "onnxruntime" / "capi" / "onnxruntime.dll",
    ]
    for dll_path in dll_candidates:
        if dll_path.exists():
            print(f"\n  Trying ctypes.CDLL('{dll_path}')...")
            try:
                ctypes.CDLL(str(dll_path))
                print(f"  SUCCESS loading {dll_path}")
            except OSError as e:
                print(f"  FAILED: {e}")
        else:
            print(f"  {dll_path} — not found")

    section("ATTEMPTING os.add_dll_directory()")
    dirs_to_add = [bundle_dir, capi_dir]
    for d in dirs_to_add:
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
                print(f"  Added: {d}")
            except OSError as e:
                print(f"  FAILED to add {d}: {e}")

    # Retry DLL load after adding directories
    print("\n  Retrying DLL load after add_dll_directory...")
    for dll_path in dll_candidates:
        if dll_path.exists():
            try:
                ctypes.CDLL(str(dll_path))
                print(f"  SUCCESS loading {dll_path}")
            except OSError as e:
                print(f"  FAILED: {e}")

    section("ATTEMPTING ONNX RUNTIME IMPORT")
    try:
        import onnxruntime
        print(f"  SUCCESS — version {onnxruntime.__version__}")
    except ImportError as e:
        print(f"  FAILED: {e}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

    section("PATH ENVIRONMENT VARIABLE")
    for p in os.environ.get("PATH", "").split(os.pathsep)[:20]:
        print(f"  {p}")
    path_count = len(os.environ.get("PATH", "").split(os.pathsep))
    if path_count > 20:
        print(f"  ... ({path_count - 20} more)")

    section("VC++ RUNTIME CHECK")
    vc_dlls = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]
    for dll in vc_dlls:
        try:
            ctypes.CDLL(dll)
            print(f"  {dll}: found (system)")
        except OSError:
            # Check bundle
            bundle_path = bundle_dir / dll
            if bundle_path.exists():
                print(f"  {dll}: found (in bundle)")
            else:
                print(f"  {dll}: !! NOT FOUND")

    print("\n" + "=" * 60)
    print("  Done. Copy all output above and share it.")
    print("=" * 60)


if __name__ == "__main__":
    main()
