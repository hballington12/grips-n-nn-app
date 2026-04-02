"""GRIPS Spectra Viewer — main application entry point."""

import sys
from pathlib import Path

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
