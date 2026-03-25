"""Export panel — write predictions to CSV or ASCII files."""

import datetime as dt
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from settings import AppSettings
from style import COLORS

_LABEL_STYLE = f"color: {COLORS['text_muted']}; font-weight: normal; font-size: 13px;"
_VALUE_STYLE = f"color: {COLORS['text_secondary']}; font-weight: normal; font-size: 13px;"


class EllidedLabel(QLabel):
    """Left-elided label (reused from config panel pattern)."""

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


class ExportPanel(QFrame):
    """Export options — format selection, output directory, export button."""

    # Emitted when the user clicks Export. MainWindow handles the actual writing.
    export_requested = pyqtSignal()

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Export")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        # --- Output directory row ---
        dir_row = QHBoxLayout()
        dir_label = QLabel("Output:")
        dir_label.setFixedWidth(50)
        dir_label.setStyleSheet(_LABEL_STYLE)
        self._dir_display = EllidedLabel(placeholder="No directory selected")
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse_output)
        dir_row.addWidget(dir_label)
        dir_row.addWidget(self._dir_display, stretch=1)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # --- Format + Export button row ---
        # QRadioButton is a toggle — only one in a QButtonGroup can be
        # active at a time. Clicking one automatically deselects the other.
        action_row = QHBoxLayout()

        format_label = QLabel("Format:")
        format_label.setStyleSheet(_LABEL_STYLE)

        self._csv_radio = QRadioButton("CSV")
        self._ascii_radio = QRadioButton("ASCII")
        self._csv_radio.setStyleSheet(f"color: {COLORS['text_primary']};")
        self._ascii_radio.setStyleSheet(f"color: {COLORS['text_primary']};")

        # QButtonGroup manages mutual exclusivity. We don't strictly need
        # it (radios in the same parent are already exclusive), but it
        # gives us a clean API for reading which is selected.
        self._format_group = QButtonGroup(self)
        self._format_group.addButton(self._csv_radio)
        self._format_group.addButton(self._ascii_radio)

        # Restore saved format
        if self._settings.export_format == "ascii":
            self._ascii_radio.setChecked(True)
        else:
            self._csv_radio.setChecked(True)

        self._csv_radio.toggled.connect(self._on_format_changed)

        self._export_btn = QPushButton("Export")
        self._export_btn.setFixedWidth(80)
        self._export_btn.clicked.connect(self._on_export)

        # Status label — constrained so long filenames don't force-expand the panel
        self._status = QLabel("")
        self._status.setStyleSheet(_VALUE_STYLE)
        self._status.setMinimumWidth(0)
        self._status.setMaximumWidth(200)

        # QCheckBox — a simple boolean toggle. Unlike radio buttons,
        # checkboxes are independent (no mutual exclusivity).
        self._good_only_cb = QCheckBox("Good only")
        self._good_only_cb.setStyleSheet(f"color: {COLORS['text_primary']};")
        self._good_only_cb.setToolTip("Only export spectra with P ≥ threshold")
        self._good_only_cb.setChecked(self._settings.export_good_only)
        self._good_only_cb.toggled.connect(self._on_good_only_changed)

        action_row.addWidget(format_label)
        action_row.addWidget(self._csv_radio)
        action_row.addWidget(self._ascii_radio)
        action_row.addSpacing(12)
        action_row.addWidget(self._good_only_cb)
        action_row.addSpacing(12)
        action_row.addWidget(self._status, stretch=1)
        action_row.addWidget(self._export_btn)

        layout.addLayout(action_row)
        layout.addStretch()

        # Restore saved output directory
        saved = self._settings.export_directory
        if saved and saved.is_dir():
            self._dir_display.set_path(str(saved))

    @property
    def selected_format(self) -> str:
        return "ascii" if self._ascii_radio.isChecked() else "csv"

    @property
    def good_only(self) -> bool:
        return self._good_only_cb.isChecked()

    @property
    def output_directory(self) -> Path | None:
        saved = self._settings.export_directory
        if saved and saved.is_dir():
            return saved
        return None

    def set_status(self, text: str, color: str | None = None) -> None:
        """Show a brief status message (e.g. 'Exported!' or error)."""
        c = color or COLORS["green"]
        # Elide long text with "..." and show full text on hover
        metrics = self._status.fontMetrics()
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, self._status.maximumWidth() - 4)
        self._status.setText(elided)
        self._status.setToolTip(text)
        self._status.setStyleSheet(f"color: {c}; font-weight: normal; font-size: 13px;")

    def _on_browse_output(self) -> None:
        start = str(self._settings.export_directory or Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory", start)
        if path:
            self._settings.export_directory = Path(path)
            self._dir_display.set_path(path)

    def _on_format_changed(self, _checked: bool) -> None:
        self._settings.export_format = self.selected_format

    def _on_good_only_changed(self, checked: bool) -> None:
        self._settings.export_good_only = checked

    def _on_export(self) -> None:
        if not self.output_directory:
            self.set_status("No output directory set", COLORS["red"])
            return
        self.export_requested.emit()
