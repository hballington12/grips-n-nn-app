"""Config panel — data source selection and app settings."""

import re
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from settings import AppSettings
from style import COLORS

# Matches dates in filenames like GRIPSII_2012-12-12.dat
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Shared style for stat value labels
_STAT_STYLE = f"color: {COLORS['text_secondary']}; font-weight: normal; font-size: 13px;"
_STAT_LABEL_STYLE = f"color: {COLORS['text_muted']}; font-weight: normal; font-size: 13px;"


class EllidedLabel(QLabel):
    """A QLabel that ellides text on the LEFT side when it overflows."""

    def __init__(self, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._placeholder = placeholder
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._show_placeholder()

    def set_path(self, path: str) -> None:
        self._full_text = path
        self._update_elided_text()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        if not self._full_text:
            self._show_placeholder()
            return
        metrics = self.fontMetrics()
        available = self.width() - 8
        elided = metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideLeft, available
        )
        self.setText(elided)
        self.setStyleSheet(f"color: {COLORS['text_primary']};")
        self.setToolTip(self._full_text)

    def _show_placeholder(self) -> None:
        self.setText(self._placeholder)
        self.setStyleSheet(f"color: {COLORS['text_muted']};")
        self.setToolTip("")


def _scan_dat_files(directory: Path) -> tuple[int, str, str]:
    """Scan a directory for .dat files and extract date range from filenames.

    Returns (file_count, earliest_date, latest_date).
    Dates are strings like "2012-12-12" or "—" if none found.
    """
    dates: list[str] = []
    count = 0
    for f in directory.iterdir():
        if f.suffix == ".dat" and f.is_file():
            count += 1
            match = _DATE_RE.search(f.stem)
            if match:
                dates.append(match.group(1))

    if not dates:
        return count, "—", "—"

    dates.sort()
    return count, dates[0], dates[-1]


class ConfigPanel(QFrame):
    """Config panel with data directory selector and file statistics."""

    # Custom signal emitted when the user selects a new data directory.
    # pyqtSignal is declared as a class attribute — Qt's meta-object system
    # needs to see it at class definition time (not in __init__).
    # The argument type (Path) tells Qt what payload the signal carries.
    directory_changed = pyqtSignal(Path)

    # Emitted when the user changes the P threshold slider.
    # Carries the new threshold as a float (0.00–1.00).
    threshold_changed = pyqtSignal(float)

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)

        self._settings = settings
        self._data_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Section title ---
        title = QLabel("Config")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        # --- Data source row: [label] [path display] [browse button] ---
        source_row = QHBoxLayout()
        source_label = QLabel("Data:")
        source_label.setFixedWidth(40)
        source_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._path_display = EllidedLabel(placeholder="No directory selected")
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse)
        source_row.addWidget(source_label)
        source_row.addWidget(self._path_display, stretch=1)
        source_row.addWidget(browse_btn)
        layout.addLayout(source_row)

        # --- Stats row: [files: N] [from: DATE] [to: DATE] ---
        stats_row = QHBoxLayout()

        files_label = QLabel("Files:")
        files_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._files_value = QLabel("—")
        self._files_value.setStyleSheet(_STAT_STYLE)

        from_label = QLabel("From:")
        from_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._from_value = QLabel("—")
        self._from_value.setStyleSheet(_STAT_STYLE)

        to_label = QLabel("To:")
        to_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._to_value = QLabel("—")
        self._to_value.setStyleSheet(_STAT_STYLE)

        stats_row.addWidget(files_label)
        stats_row.addWidget(self._files_value)
        stats_row.addSpacing(12)
        stats_row.addWidget(from_label)
        stats_row.addWidget(self._from_value)
        stats_row.addSpacing(12)
        stats_row.addWidget(to_label)
        stats_row.addWidget(self._to_value)
        stats_row.addStretch()

        layout.addLayout(stats_row)

        # --- Active selection row: [active file] [active spectrum] ---
        active_row = QHBoxLayout()

        active_file_label = QLabel("Active file:")
        active_file_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._active_file_value = QLabel("—")
        self._active_file_value.setStyleSheet(_STAT_STYLE)

        active_spectrum_label = QLabel("Active spectrum:")
        active_spectrum_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._active_spectrum_value = QLabel("—")
        self._active_spectrum_value.setStyleSheet(_STAT_STYLE)

        active_row.addWidget(active_file_label)
        active_row.addWidget(self._active_file_value)
        active_row.addSpacing(12)
        active_row.addWidget(active_spectrum_label)
        active_row.addWidget(self._active_spectrum_value)
        active_row.addStretch()

        layout.addLayout(active_row)

        # --- P threshold slider row: [label] [slider] [value] ---
        # QSlider only works with integers, so we map 0–100 → 0.00–1.00.
        # valueChanged fires on every tick as the user drags, giving
        # real-time feedback.
        threshold_row = QHBoxLayout()

        threshold_label = QLabel("P threshold:")
        threshold_label.setStyleSheet(_STAT_LABEL_STYLE)

        self._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self._threshold_slider.setRange(0, 100)
        self._threshold_slider.setSingleStep(1)
        self._threshold_slider.setPageStep(5)
        self._threshold_slider.setValue(int(self._settings.p_threshold * 100))
        self._threshold_slider.valueChanged.connect(self._on_threshold_changed)

        self._threshold_value = QLabel(f"{self._settings.p_threshold:.2f}")
        self._threshold_value.setFixedWidth(36)
        self._threshold_value.setStyleSheet(
            f"color: {COLORS['green']}; font-weight: normal; font-size: 13px;"
        )

        threshold_row.addWidget(threshold_label)
        threshold_row.addWidget(self._threshold_slider, stretch=1)
        threshold_row.addWidget(self._threshold_value)

        layout.addLayout(threshold_row)

        # --- Mean temperature row ---
        mean_temp_row = QHBoxLayout()
        mean_temp_label = QLabel("Mean temp:")
        mean_temp_label.setStyleSheet(_STAT_LABEL_STYLE)
        self._mean_temp_value = QLabel("—")
        self._mean_temp_value.setStyleSheet(_STAT_STYLE)
        mean_temp_row.addWidget(mean_temp_label)
        mean_temp_row.addWidget(self._mean_temp_value)
        mean_temp_row.addStretch()
        layout.addLayout(mean_temp_row)

        layout.addStretch()

    def restore_settings(self) -> None:
        """Reload persisted settings.

        Called by MainWindow AFTER signal connections are established,
        so that directory_changed reaches the spectra selector.
        """
        saved_dir = self._settings.data_directory
        if saved_dir and saved_dir.is_dir():
            self._data_path = saved_dir
            self._path_display.set_path(str(saved_dir))
            self._update_stats()
            self.directory_changed.emit(saved_dir)

    def _update_stats(self) -> None:
        """Scan the selected directory and update stat labels."""
        if not self._data_path or not self._data_path.is_dir():
            self._files_value.setText("—")
            self._from_value.setText("—")
            self._to_value.setText("—")
            return

        count, date_from, date_to = _scan_dat_files(self._data_path)
        self._files_value.setText(str(count))
        self._from_value.setText(date_from)
        self._to_value.setText(date_to)

    def set_active_file(self, filename: str) -> None:
        """Update the active file display and persist the selection."""
        self._active_file_value.setText(filename)
        self._active_file_value.setStyleSheet(
            f"color: {COLORS['green']}; font-weight: normal; font-size: 13px;"
        )
        self._settings.active_dat_file = filename
        self.clear_active_spectrum()

    def set_active_spectrum(self, spectrum: str) -> None:
        """Update the active spectrum display and persist the selection."""
        self._active_spectrum_value.setText(spectrum)
        self._active_spectrum_value.setStyleSheet(
            f"color: {COLORS['green']}; font-weight: normal; font-size: 13px;"
        )
        self._settings.active_spectrum = spectrum

    def clear_active_file(self) -> None:
        """Reset active file display and persistence."""
        self._active_file_value.setText("—")
        self._active_file_value.setStyleSheet(_STAT_STYLE)
        self._settings.active_dat_file = None
        self.set_mean_temperature(None)

    def clear_active_spectrum(self) -> None:
        """Reset active spectrum display and persistence."""
        self._active_spectrum_value.setText("—")
        self._active_spectrum_value.setStyleSheet(_STAT_STYLE)
        self._settings.active_spectrum = None
        self._settings.active_spectrum_index = None

    def set_mean_temperature(self, temp: float | None) -> None:
        """Update the mean temperature display."""
        if temp is None:
            self._mean_temp_value.setText("—")
            self._mean_temp_value.setStyleSheet(_STAT_STYLE)
        else:
            self._mean_temp_value.setText(f"{temp:.1f} K")
            self._mean_temp_value.setStyleSheet(
                f"color: {COLORS['teal']}; font-weight: normal; font-size: 13px;"
            )

    def _on_threshold_changed(self, int_value: int) -> None:
        """Handle slider movement — update display and persist."""
        threshold = int_value / 100.0
        self._threshold_value.setText(f"{threshold:.2f}")
        self._settings.p_threshold = threshold
        self.threshold_changed.emit(threshold)

    def _on_browse(self) -> None:
        start_dir = str(self._data_path) if self._data_path else str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Raw Data Directory",
            start_dir,
        )
        if path:
            self._data_path = Path(path)
            self._path_display.set_path(path)
            self._settings.data_directory = self._data_path
            self._update_stats()
            self.clear_active_file()
            self.clear_active_spectrum()
            self.directory_changed.emit(self._data_path)
