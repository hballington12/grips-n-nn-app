"""GRIPS Spectra Viewer — main application entry point."""

import sys
from pathlib import Path

# --- Windows DLL diagnostics (runs before onnxruntime import) ---
# Writes a log file next to the exe when running as a frozen bundle.
# Remove this block once the DLL issue is resolved.
if getattr(sys, "frozen", False) and sys.platform == "win32":
    import ctypes
    import ctypes.wintypes
    import os
    import struct
    import subprocess

    _bundle = Path(sys._MEIPASS)
    _log = Path(sys.executable).parent / "dll_diagnostic.log"
    _lines = []

    def _section(title):
        _lines.append(f"\n{'=' * 70}")
        _lines.append(f"  {title}")
        _lines.append(f"{'=' * 70}")

    # ---- Environment ----
    _section("ENVIRONMENT")
    _lines.append(f"Python:          {sys.version}")
    _lines.append(f"Executable:      {sys.executable}")
    _lines.append(f"_MEIPASS:        {_bundle}")
    _lines.append(f"Pointer size:    {struct.calcsize('P') * 8}-bit")
    _lines.append(f"OS version:      {sys.getwindowsversion()}")
    _lines.append(f"cwd:             {os.getcwd()}")

    # ---- All DLLs in bundle (not just onnxruntime) ----
    _section("ALL .dll AND .pyd FILES IN BUNDLE")
    _all_dlls = sorted(_bundle.rglob("*.dll")) + sorted(_bundle.rglob("*.pyd"))
    for f in _all_dlls:
        _lines.append(f"  {f.relative_to(_bundle)}  ({f.stat().st_size / 1024:.0f} KB)")
    _lines.append(f"\n  Total: {len(_all_dlls)} files")

    # ---- onnxruntime package structure ----
    _section("FULL onnxruntime/ DIRECTORY TREE")
    _ort_root = _bundle / "onnxruntime"
    if _ort_root.is_dir():
        for f in sorted(_ort_root.rglob("*")):
            if f.is_file():
                _lines.append(f"  {f.relative_to(_bundle)}  ({f.stat().st_size / 1024:.0f} KB)")
    else:
        _lines.append(f"  !! {_ort_root} does not exist")

    _capi = _bundle / "onnxruntime" / "capi"

    # ---- onnxruntime files at bundle root ----
    _section("onnxruntime* FILES AT BUNDLE ROOT (_internal/)")
    for f in sorted(_bundle.glob("onnxruntime*")):
        if f.is_file():
            _lines.append(f"  {f.name}  ({f.stat().st_size / 1024:.0f} KB)")

    # ---- PE header check: is the DLL 32-bit or 64-bit? ----
    _section("PE ARCHITECTURE CHECK")
    for _candidate in [_bundle / "onnxruntime.dll", _capi / "onnxruntime.dll"]:
        if _candidate.exists():
            try:
                with open(_candidate, "rb") as _f:
                    _f.seek(0x3C)  # PE header offset location
                    _pe_off = struct.unpack("<I", _f.read(4))[0]
                    _f.seek(_pe_off + 4)  # skip PE signature
                    _machine = struct.unpack("<H", _f.read(2))[0]
                    _arch = {0x14c: "x86 (32-bit)", 0x8664: "x64 (64-bit)", 0xAA64: "ARM64"}.get(_machine, f"unknown (0x{_machine:04x})")
                _lines.append(f"  {_candidate.relative_to(_bundle)}: {_arch}")
            except Exception as e:
                _lines.append(f"  {_candidate.relative_to(_bundle)}: read error — {e}")

    # ---- VC++ runtime ----
    _section("VC++ RUNTIME CHECK")
    _vc_dlls = [
        "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
        "msvcp140_1.dll", "msvcp140_2.dll",
        "concrt140.dll", "vccorlib140.dll", "ucrtbase.dll",
        "api-ms-win-crt-runtime-l1-1-0.dll",
    ]
    for _dll in _vc_dlls:
        try:
            ctypes.CDLL(_dll)
            _status = "found (system)"
        except OSError:
            if (_bundle / _dll).exists():
                _status = "found (in bundle)"
            else:
                _status = "NOT FOUND"
        _lines.append(f"  {_dll}: {_status}")

    # ---- Kernel32 LoadLibraryExW with error codes ----
    _section("LoadLibraryExW WITH WINDOWS ERROR CODES")
    _kernel32 = ctypes.windll.kernel32
    _kernel32.SetLastError(0)
    _LoadLibraryExW = _kernel32.LoadLibraryExW
    _LoadLibraryExW.restype = ctypes.wintypes.HMODULE
    _LoadLibraryExW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    _FreeLibrary = _kernel32.FreeLibrary
    _FormatMessageW = _kernel32.FormatMessageW
    _FormatMessageW.restype = ctypes.wintypes.DWORD
    _FormatMessageW.argtypes = [
        ctypes.wintypes.DWORD, ctypes.wintypes.LPVOID, ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD, ctypes.wintypes.LPWSTR, ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID,
    ]

    def _get_win_error_msg(code):
        buf = ctypes.create_unicode_buffer(512)
        _FormatMessageW(0x1000, None, code, 0, buf, 512, None)
        return buf.value.strip()

    # LOAD_WITH_ALTERED_SEARCH_PATH = 0x8
    # LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR = 0x100
    # LOAD_LIBRARY_SEARCH_DEFAULT_DIRS = 0x1000
    _load_flags = [
        ("default (0)", 0),
        ("LOAD_WITH_ALTERED_SEARCH_PATH (0x8)", 0x8),
        ("LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR (0x100)", 0x100),
        ("LOAD_LIBRARY_SEARCH_DEFAULT_DIRS (0x1000)", 0x1000),
        ("DLL_LOAD_DIR | DEFAULT_DIRS (0x1100)", 0x1100),
    ]

    for _candidate in [_capi / "onnxruntime.dll", _bundle / "onnxruntime.dll"]:
        if not _candidate.exists():
            continue
        _lines.append(f"\n  Target: {_candidate.relative_to(_bundle)}")
        for _flag_name, _flag_val in _load_flags:
            _kernel32.SetLastError(0)
            _handle = _LoadLibraryExW(str(_candidate), None, _flag_val)
            _err = ctypes.get_last_error()
            if _handle:
                _lines.append(f"    {_flag_name}: SUCCESS (handle=0x{_handle:x})")
                _FreeLibrary(_handle)
            else:
                _msg = _get_win_error_msg(_err)
                _lines.append(f"    {_flag_name}: FAILED — error {_err} (0x{_err:04x}): {_msg}")

    # ---- Try adding bundle dirs to PATH (old-school approach) ----
    _section("PATH MANIPULATION + RETRY")
    _orig_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{_bundle};{_capi};{_orig_path}"
    _lines.append(f"  Prepended to PATH: {_bundle} and {_capi}")

    for _candidate in [_capi / "onnxruntime.dll", _bundle / "onnxruntime.dll"]:
        if not _candidate.exists():
            continue
        try:
            # winmode=0 uses the old search behavior that includes PATH
            _h = ctypes.CDLL(str(_candidate), winmode=0)
            _lines.append(f"  ctypes.CDLL(winmode=0) {_candidate.relative_to(_bundle)}: SUCCESS")
            del _h
        except OSError as e:
            _lines.append(f"  ctypes.CDLL(winmode=0) {_candidate.relative_to(_bundle)}: FAILED — {e}")

    os.environ["PATH"] = _orig_path

    # ---- os.add_dll_directory ----
    _section("os.add_dll_directory")
    for _d in [_bundle, _capi]:
        if _d.is_dir():
            try:
                os.add_dll_directory(str(_d))
                _lines.append(f"  Added: {_d}")
            except OSError as e:
                _lines.append(f"  FAILED to add {_d}: {e}")

    # ---- dumpbin /dependents if available ----
    _section("DEPENDENCY ANALYSIS (dumpbin)")
    _dll_path = _capi / "onnxruntime.dll"
    if not _dll_path.exists():
        _dll_path = _bundle / "onnxruntime.dll"
    if _dll_path.exists():
        # Try dumpbin (comes with Visual Studio)
        for _tool in ["dumpbin", r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.23.27820\bin\Hostx64\x64\dumpbin.exe"]:
            try:
                _result = subprocess.run(
                    [_tool, "/dependents", str(_dll_path)],
                    capture_output=True, text=True, timeout=15,
                )
                if _result.returncode == 0:
                    _lines.append(f"  dumpbin /dependents {_dll_path.name}:")
                    for _line in _result.stdout.splitlines():
                        _stripped = _line.strip()
                        if _stripped and _stripped.endswith(".dll"):
                            _lines.append(f"    {_stripped}")
                            # Check if this dependency exists in bundle
                            _found_in = []
                            if (_bundle / _stripped).exists():
                                _found_in.append("bundle root")
                            if (_capi / _stripped).exists():
                                _found_in.append("capi/")
                            try:
                                ctypes.CDLL(_stripped)
                                _found_in.append("system")
                            except OSError:
                                pass
                            if _found_in:
                                _lines.append(f"      -> found in: {', '.join(_found_in)}")
                            else:
                                _lines.append(f"      -> !! NOT FOUND ANYWHERE")
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        else:
            _lines.append("  dumpbin not found — trying powershell approach")
            # Fallback: use powershell to read PE imports
            try:
                _ps_cmd = f"""
                $bytes = [System.IO.File]::ReadAllBytes('{_dll_path}')
                $assembly = [System.Reflection.Assembly]::LoadFrom
                # Just list file size and basic info as fallback
                Write-Output "File size: $($bytes.Length) bytes"
                """
                _lines.append("  (dumpbin unavailable, skipping dependency listing)")
            except Exception:
                _lines.append("  (dependency analysis unavailable)")

    # ---- Final import attempt ----
    _section("FINAL IMPORT ATTEMPT")
    try:
        import onnxruntime as _ort
        _lines.append(f"  SUCCESS — version {_ort.__version__}")
    except Exception as e:
        import traceback
        _lines.append(f"  FAILED — {type(e).__name__}: {e}")
        _lines.append(f"\n  Full traceback:")
        for _tb_line in traceback.format_exc().splitlines():
            _lines.append(f"    {_tb_line}")

    _lines.append(f"\n{'=' * 70}")
    _lines.append("  Done. Share this entire file for debugging.")
    _lines.append(f"{'=' * 70}")

    _log.write_text("\n".join(_lines), encoding="utf-8")
    # Don't bother cleaning up — we're about to crash anyway

import numpy as np

from data import InferenceWorker, ModelRunner, PredictionCache, export_predictions
from data.parser import DatFileCache, PacketData
from panels import ConfigPanel, ExportPanel, SpectraSelectorPanel, SpectrumViewerPanel
from panels.spectra_selector import OverrideState
from settings import AppSettings, OverrideStore
from style import COLORS, build_stylesheet
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QWidget,
)


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self, settings: AppSettings, model_runner: ModelRunner, override_store: OverrideStore) -> None:
        super().__init__()
        self._settings = settings
        self._model_runner = model_runner
        self._override_store = override_store
        self._prediction_cache = PredictionCache()
        self._dat_cache = DatFileCache(maxsize=32)
        self._inference_worker: InferenceWorker | None = None
        self._prev_threshold: float = settings.p_threshold

        self.setWindowTitle("GRIPS Spectra Viewer")
        self.resize(1200, 800)

        # --- Central widget ------------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)

        # --- Top-level horizontal splitter ---------------------------------
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left column: two spectra viewers, stacked vertically ----------
        self._left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.spectra_viewer_1 = SpectrumViewerPanel(title="Spectrum")
        self.spectra_viewer_2 = SpectrumViewerPanel(title="Nightly Mean")
        self._left_splitter.addWidget(self.spectra_viewer_1)
        self._left_splitter.addWidget(self.spectra_viewer_2)

        # --- Right column: config / selector / export, stacked vertically --
        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.config_panel = ConfigPanel(settings=self._settings)
        self.spectra_selector = SpectraSelectorPanel(settings=self._settings, override_store=self._override_store)
        self.export_panel = ExportPanel(settings=self._settings)
        self._right_splitter.addWidget(self.config_panel)
        self._right_splitter.addWidget(self.spectra_selector)
        self._right_splitter.addWidget(self.export_panel)

        # --- Assemble into the main splitter -------------------------------
        self._main_splitter.addWidget(self._left_splitter)
        self._main_splitter.addWidget(self._right_splitter)

        # --- Root layout ---------------------------------------------------
        root_layout = QHBoxLayout(central)
        root_layout.addWidget(self._main_splitter)

        # --- Cross-panel signals ----------------------------------------------
        self.config_panel.directory_changed.connect(self._on_directory_changed)
        self.spectra_selector.file_selected.connect(self._on_file_selected)
        self.spectra_selector.file_loaded.connect(self.run_inference)
        self.spectra_selector.spectrum_selected.connect(
            self._on_spectrum_selected
        )
        self.config_panel.threshold_changed.connect(self._on_threshold_changed)
        self.spectra_selector.override_changed.connect(self._on_override_changed)
        self.export_panel.export_requested.connect(self._on_export)

        # --- Restore persisted state -------------------------------------------
        self._restore_layout()
        self.config_panel.restore_settings()
        self._restore_active_selection()

    # -- Directory and file selection -----------------------------------------

    def _on_file_selected(self, filename: str) -> None:
        """Handle new file selection — clear single spectrum, update config."""
        self.config_panel.set_active_file(filename)
        self.spectra_viewer_1.clear()
        self.spectra_viewer_2.clear()

    def _on_directory_changed(self, directory: Path) -> None:
        """Handle new data directory — clear everything and load files."""
        self._prediction_cache.clear()
        self.spectra_viewer_1.clear()
        self.spectra_viewer_2.clear()
        self.spectra_selector.load_directory(directory)

    def _on_spectrum_selected(self, packet) -> None:
        """Handle spectrum row selection — update config panel and plot."""
        label = f"#{packet.index} @ {packet.time_str}"
        self.config_panel.set_active_spectrum(label)
        self._settings.active_spectrum = label

        # Look up the classification probability and override for this packet
        prob = self._get_packet_probability(packet.index)
        override = self._get_packet_override(packet.index)
        self.spectra_viewer_1.plot_spectrum(
            packet, probability=prob, threshold=self._settings.p_threshold,
            override=override,
        )

    def _get_packet_probability(self, packet_index: int) -> float | None:
        """Retrieve cached probability for a packet, if available."""
        file = self._settings.active_dat_file
        data_dir = self._settings.data_directory
        if not file or not data_dir:
            return None
        filepath = data_dir / file
        cached = self._prediction_cache.get(filepath)
        if cached is None:
            return None
        for idx, prob, _temp in cached:
            if idx == packet_index:
                return prob
        return None

    def _on_override_changed(self, packet_index: int, state: int) -> None:
        """Handle override toggle — refresh mean spectrum and replot active."""
        file = self._settings.active_dat_file
        data_dir = self._settings.data_directory
        if not file or not data_dir:
            return
        filepath = data_dir / file
        cached = self._prediction_cache.get(filepath)
        if cached is not None:
            self._update_mean_spectrum(filepath, cached)

        # Replot the active spectrum if it's the one that was overridden
        if self._settings.active_spectrum_index == packet_index:
            self._replot_active_spectrum()

    def _get_packet_override(self, packet_index: int) -> OverrideState:
        """Retrieve the override state for a packet from the spectra table."""
        overrides = self.spectra_selector.get_all_overrides()
        return overrides.get(packet_index, OverrideState.NONE)

    def _restore_active_selection(self) -> None:
        """Re-select the previously active .dat file and spectrum."""
        saved_file = self._settings.active_dat_file
        if saved_file:
            self.spectra_selector.select_file_by_name(saved_file)

        saved_spectrum = self._settings.active_spectrum_index
        if saved_spectrum is not None:
            self.spectra_selector.select_spectrum_by_index(saved_spectrum)

    # -- Model inference ------------------------------------------------------

    def run_inference(self, filepath: Path, packets) -> None:
        """Run model predictions on packets, using cache when available.

        Called by the spectra selector after a file is loaded and displayed.
        If predictions are cached, updates the table immediately.
        Otherwise, spawns a background InferenceWorker thread.
        """
        # Check session cache first
        cached = self._prediction_cache.get(filepath)
        if cached is not None:
            self.spectra_selector.update_all_predictions(
                cached, threshold=self._settings.p_threshold
            )
            self._update_mean_spectrum(filepath, cached)
            return

        # Don't stack up workers — if one is running, let it finish.
        # The next file click will trigger a new one.
        if self._inference_worker is not None and self._inference_worker.isRunning():
            return

        # Show overlay immediately on the main thread, before spawning worker.
        # Progress signals will update the count as chunks complete.
        total = len(packets)
        self.spectra_selector.show_progress(0, total)

        worker = InferenceWorker(
            self._model_runner, packets, filepath, parent=self,
        )
        worker.finished_with_results.connect(self._on_inference_done)
        worker.progress.connect(self.spectra_selector.show_progress)
        worker.error_occurred.connect(self._on_inference_error)
        worker.finished.connect(self._on_worker_finished)
        self._inference_worker = worker
        worker.start()

    def _on_inference_done(self, filepath_str: str, predictions: list) -> None:
        """Handle completed inference — cache results and update table."""
        filepath = Path(filepath_str)
        self._prediction_cache.put(filepath, predictions)
        self.spectra_selector.update_all_predictions(
            predictions, threshold=self._settings.p_threshold
        )
        self.spectra_selector.hide_progress()
        self._update_mean_spectrum(filepath, predictions)
        self._replot_active_spectrum()

    def _replot_active_spectrum(self) -> None:
        """Re-plot the currently selected spectrum with updated probability."""
        idx = self._settings.active_spectrum_index
        if idx is None:
            return
        prob = self._get_packet_probability(idx)
        override = self._get_packet_override(idx)
        # Retrieve the PacketData from the spectra selector's current selection
        current = self.spectra_selector._spectrum_table.currentIndex()
        if not current.isValid():
            return
        source_idx = self.spectra_selector._spectrum_proxy.mapToSource(current)
        item = self.spectra_selector._spectrum_model.item(source_idx.row(), 0)
        if item:
            packet = item.data(Qt.ItemDataRole.UserRole + 1)
            if packet:
                self.spectra_viewer_1.plot_spectrum(
                    packet, probability=prob,
                    threshold=self._settings.p_threshold,
                    override=override,
                )

    def _on_inference_error(self, message: str) -> None:
        """Handle inference failure."""
        self.spectra_selector.hide_progress()
        print(f"[inference error] {message}")

    def _on_worker_finished(self) -> None:
        """Clean up worker reference when thread finishes."""
        self._inference_worker = None

    def _update_mean_spectrum(
        self, filepath: Path, predictions: list[tuple[int, float, float]]
    ) -> None:
        """Compute and display the mean spectrum and temperature across good packets.

        Override states are respected:
        - GOOD override forces inclusion regardless of threshold
        - BAD override forces exclusion regardless of threshold
        - NONE uses the P threshold as usual
        """
        threshold = self._settings.p_threshold
        overrides = self.spectra_selector.get_all_overrides()

        # Filter good predictions respecting overrides
        good_preds = []
        for idx, prob, temp in predictions:
            ov = overrides.get(idx, OverrideState.NONE)
            if ov == OverrideState.BAD:
                continue
            if ov == OverrideState.GOOD or prob >= threshold:
                good_preds.append((idx, prob, temp))

        if not good_preds:
            self.spectra_viewer_2.clear()
            self.config_panel.set_mean_temperature(None)
            return

        good_indices = {idx for idx, _, _ in good_preds}
        good_temps = [temp for _, _, temp in good_preds]
        mean_temp = float(np.mean(good_temps))
        self.config_panel.set_mean_temperature(mean_temp)

        # Get the raw packets from cache for mean spectrum
        packets = self._dat_cache.get_full_packets(filepath)
        good_intensities = [
            p.intensities for p in packets if p.index in good_indices
        ]

        mean_intensity = np.mean(good_intensities, axis=0)

        mean_packet = PacketData(
            index=-1,
            timestamp=packets[0].timestamp,
            intensities=mean_intensity,
            is_partial=False,
        )
        n = len(good_intensities)
        self.spectra_viewer_2.plot_spectrum(
            mean_packet,
            probability=1.0,
            title_override=(
                f"Nightly mean  —  {n} spectra (P ≥ {threshold:.2f})"
                f"  —  T̄ = {mean_temp:.1f} K"
            ),
        )

    def _on_threshold_changed(self, threshold: float) -> None:
        """Re-apply threshold to table display, mean spectrum, and plot color."""
        file = self._settings.active_dat_file
        data_dir = self._settings.data_directory
        if not file or not data_dir:
            return
        filepath = data_dir / file
        cached = self._prediction_cache.get(filepath)
        if cached is not None:
            self.spectra_selector.update_all_predictions(
                cached, threshold=threshold
            )
            self._update_mean_spectrum(filepath, cached)

            # Only replot if the threshold crossed the active packet's P value
            # (i.e. the color classification changed from good↔bad)
            idx = self._settings.active_spectrum_index
            if idx is not None:
                prob = self._get_packet_probability(idx)
                if prob is not None:
                    was_good = prob >= self._prev_threshold
                    is_good = prob >= threshold
                    if was_good != is_good:
                        self._replot_active_spectrum()

        self._prev_threshold = threshold

    # -- Export ---------------------------------------------------------------

    def _on_export(self) -> None:
        """Export predictions for the active .dat file."""
        file = self._settings.active_dat_file
        data_dir = self._settings.data_directory
        output_dir = self.export_panel.output_directory

        if not file or not data_dir:
            self.export_panel.set_status("No file selected", COLORS["red"])
            return
        if not output_dir:
            self.export_panel.set_status("No output directory", COLORS["red"])
            return

        filepath = data_dir / file
        cached = self._prediction_cache.get(filepath)
        if cached is None:
            self.export_panel.set_status("Run inference first", COLORS["orange"])
            return

        packets = self._dat_cache.get_full_packets(filepath)
        overrides = {
            idx: int(state)
            for idx, state in self.spectra_selector.get_all_overrides().items()
        }
        try:
            out_path = export_predictions(
                output_dir=output_dir,
                dat_filename=file,
                packets=packets,
                predictions=cached,
                p_threshold=self._settings.p_threshold,
                export_format=self.export_panel.selected_format,
                good_only=self.export_panel.good_only,
                overrides=overrides,
            )
            self.export_panel.set_status(f"Saved: {out_path.name}", COLORS["green"])
        except Exception as e:
            self.export_panel.set_status(f"Error: {e}", COLORS["red"])

    # -- Layout persistence ---------------------------------------------------

    def _restore_layout(self) -> None:
        geometry = self._settings.load_window_geometry()
        if geometry:
            self.restoreGeometry(geometry)

        main_state = self._settings.load_splitter_state("main")
        if main_state:
            self._main_splitter.restoreState(main_state)
        else:
            self._main_splitter.setStretchFactor(0, 65)
            self._main_splitter.setStretchFactor(1, 35)

        left_state = self._settings.load_splitter_state("left")
        if left_state:
            self._left_splitter.restoreState(left_state)

        right_state = self._settings.load_splitter_state("right")
        if right_state:
            self._right_splitter.restoreState(right_state)
        else:
            self._right_splitter.setSizes([100, 400, 300])

        spectra_state = self._settings.load_splitter_state("spectra_selector")
        if spectra_state:
            self.spectra_selector.splitter.restoreState(spectra_state)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._settings.save_window_geometry(self.saveGeometry())
        self._settings.save_splitter_state("main", self._main_splitter.saveState())
        self._settings.save_splitter_state("left", self._left_splitter.saveState())
        self._settings.save_splitter_state("right", self._right_splitter.saveState())
        self._settings.save_splitter_state(
            "spectra_selector", self.spectra_selector.splitter.saveState()
        )
        self._settings.sync()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet())

    # Load models once at startup — takes ~1s, blocks before window shows.
    # This is acceptable because the window isn't visible yet. If startup
    # time becomes a concern, we could show a splash screen.
    model_runner = ModelRunner()
    model_runner.load()

    settings = AppSettings()
    override_store = OverrideStore()
    window = MainWindow(settings=settings, model_runner=model_runner, override_store=override_store)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
