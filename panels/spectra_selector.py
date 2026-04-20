"""Spectra selector panel — browse .dat files and their spectra."""

import math
import re
from enum import IntEnum
from pathlib import Path

import qtawesome as qta
from PyQt6.QtCore import QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableView,
    QVBoxLayout,
)

from data import DatFileCache, PacketData
from settings import AppSettings, OverrideStore
from style import COLORS

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class OverrideState(IntEnum):
    """Manual override for the good/bad classification."""
    NONE = 0
    GOOD = 1
    BAD = 2


def _traffic_light_color(probability: float) -> QColor:
    """Map a 0→1 probability to a red→yellow→green color.

    0.0 = pure red (#db4b4b)
    0.5 = yellow  (#e0af68)
    1.0 = pure green (#9ece6a)

    We interpolate linearly through HSV space for smooth transitions.
    """
    # Hue: 0° (red) → 60° (yellow) → 120° (green)
    # Map probability [0,1] to hue [0, 120]
    hue = int(probability * 120)
    # Keep saturation and value high for visibility on dark background
    color = QColor.fromHsv(hue, 200, 210)
    return color


_SORT_ROLE = Qt.ItemDataRole.UserRole + 100
_OVERRIDE_ROLE = Qt.ItemDataRole.UserRole + 101
_RAW_TEMP_ROLE = Qt.ItemDataRole.UserRole + 102


_OV_DISPLAY = {
    OverrideState.NONE: "—",
    OverrideState.GOOD: "Good",
    OverrideState.BAD: "Bad",
}

# Override colors match the traffic-light endpoints: p=1.0 for Good, p=0.0 for Bad
_OV_COLOR = {
    OverrideState.NONE: QColor(COLORS["text_muted"]),
    OverrideState.GOOD: _traffic_light_color(1.0),
    OverrideState.BAD: _traffic_light_color(0.0),
}


def _apply_override_cell(model: QStandardItemModel, row: int) -> None:
    """Update the OV column display for the current override state."""
    ov_item = model.item(row, 4)
    idx_item = model.item(row, 0)
    state = idx_item.data(_OVERRIDE_ROLE)
    if state is None:
        state = OverrideState.NONE
    ov_item.setText(_OV_DISPLAY[state])
    ov_item.setForeground(QBrush(_OV_COLOR[state]))
    ov_item.setData(int(state), _SORT_ROLE)


def _apply_prediction(
    model: QStandardItemModel, row: int, prob: float, temp: float,
    threshold: float = 0.0,
) -> None:
    """Set the P and Temp cells for a single row.

    Temperature is only shown if prob >= threshold.
    Override state affects display: overridden rows show solid green/red
    and an asterisk on the P value.
    """
    idx_item = model.item(row, 0)
    override = idx_item.data(_OVERRIDE_ROLE)
    if override is None:
        override = OverrideState.NONE

    p_item = model.item(row, 2)
    p_item.setData(prob, _SORT_ROLE)

    if override == OverrideState.GOOD:
        p_item.setText(f"{prob:.2f}*")
        p_item.setForeground(QBrush(_traffic_light_color(1.0)))
    elif override == OverrideState.BAD:
        p_item.setText(f"{prob:.2f}*")
        p_item.setForeground(QBrush(_traffic_light_color(0.0)))
    else:
        p_item.setText(f"{prob:.2f}")
        p_item.setForeground(QBrush(_traffic_light_color(prob)))

    # Temperature: shown if good (by threshold or override), hidden if bad
    is_good = (
        override == OverrideState.GOOD
        or (override == OverrideState.NONE and prob >= threshold)
    )

    temp_item = model.item(row, 3)
    temp_item.setData(temp, _RAW_TEMP_ROLE)
    if math.isnan(temp) or not is_good:
        temp_item.setText("—")
        temp_item.setData(-1.0, _SORT_ROLE)
    else:
        temp_item.setText(f"{temp:.1f}")
        temp_item.setData(temp, _SORT_ROLE)


def _make_table() -> tuple[QTableView, QStandardItemModel, QSortFilterProxyModel]:
    """Create a styled, sortable table view with an empty model."""
    model = QStandardItemModel()
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    # Tell the proxy to sort by our custom role instead of DisplayRole.
    # This lets us store numeric/typed sort keys on items while showing
    # formatted strings in the cells.
    proxy.setSortRole(_SORT_ROLE)

    table = QTableView()
    table.setModel(proxy)
    table.setSortingEnabled(True)

    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.horizontalHeader().setStretchLastSection(True)

    return table, model, proxy


class SpectraSelectorPanel(QFrame):
    """Two side-by-side tables: .dat file browser and spectrum browser."""

    # Emitted when the user clicks a .dat file row. Carries the filename.
    file_selected = pyqtSignal(str)

    # Emitted when a file's packets are loaded and ready for inference.
    # Carries (filepath, packets_list).
    file_loaded = pyqtSignal(Path, list)

    # Emitted when the user clicks a spectrum row. Carries the PacketData.
    spectrum_selected = pyqtSignal(object)

    # Emitted when the user toggles an override. Carries (packet_index, OverrideState).
    override_changed = pyqtSignal(int, int)

    def __init__(self, settings: AppSettings, override_store: OverrideStore, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)

        self._settings = settings
        self._override_store = override_store
        self._active_file: str | None = None
        self._data_dir: Path | None = None
        self._cache = DatFileCache(maxsize=32)

        self._icon_default = qta.icon("fa5s.file-alt", color=COLORS["accent"])
        self._icon_active = qta.icon("fa5s.file-alt", color=COLORS["green"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Spectra Selector")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        # --- Two tables side by side in a splitter ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: .dat file browser (multi-select for batch export)
        self._file_table, self._file_model, self._file_proxy = _make_table()
        self._file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_model.setHorizontalHeaderLabels(["File", "Date"])

        # Right: spectra (packets) within the selected file
        self._spectrum_table, self._spectrum_model, self._spectrum_proxy = _make_table()
        self._spectrum_model.setHorizontalHeaderLabels(["#", "Time", "P", "Temp", "Override"])

        self.splitter.addWidget(self._file_table)
        self.splitter.addWidget(self._spectrum_table)
        self.splitter.setStretchFactor(0, 50)
        self.splitter.setStretchFactor(1, 50)

        layout.addWidget(self.splitter, stretch=1)

        # --- Processing overlay ---
        # Parented to the table's *viewport* — that's the inner widget
        # that actually renders rows. Parenting to the QTableView itself
        # doesn't work because the viewport paints over sibling children.
        self._overlay = QLabel(self._spectrum_table.viewport())
        self._overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay.setStyleSheet(
            f"background-color: rgba(22, 22, 30, 200);"
            f"color: {COLORS['accent']};"
            f"font-size: 14px;"
            f"font-weight: bold;"
            f"border-radius: 6px;"
            f"padding: 8px 16px;"
        )
        self._overlay.hide()

        # --- Connect selection signals ---
        self._file_table.selectionModel().currentRowChanged.connect(
            self._on_file_row_changed
        )
        self._spectrum_table.selectionModel().currentRowChanged.connect(
            self._on_spectrum_row_changed
        )

        # --- Space key for override toggle ---
        self._spectrum_table.keyPressEvent = self._on_spectrum_key_press

        # --- Connect sort change signals ---
        # QHeaderView.sortIndicatorChanged fires when the user clicks
        # a column header to change sort column or direction.
        self._file_table.horizontalHeader().sortIndicatorChanged.connect(
            self._on_file_sort_changed
        )
        self._spectrum_table.horizontalHeader().sortIndicatorChanged.connect(
            self._on_spectrum_sort_changed
        )

        # --- Restore sort state ---
        self._restore_sort_state()

    def load_directory(self, directory: Path) -> None:
        """Scan a directory for .dat files and populate the file table."""
        self._data_dir = directory
        self._cache.clear()
        self._file_model.removeRows(0, self._file_model.rowCount())
        self._spectrum_model.removeRows(0, self._spectrum_model.rowCount())
        self._active_file = None

        dat_files = sorted(directory.glob("*.dat"))
        for f in dat_files:
            name_item = QStandardItem(self._icon_default, f.name)
            name_item.setEditable(False)
            name_item.setData(str(f), Qt.ItemDataRole.UserRole)
            name_item.setData(f.name, _SORT_ROLE)

            match = _DATE_RE.search(f.stem)
            date_str = match.group(1) if match else ""
            date_item = QStandardItem(date_str)
            date_item.setEditable(False)
            date_item.setData(date_str, _SORT_ROLE)

            self._file_model.appendRow([name_item, date_item])

        self._file_table.resizeColumnToContents(0)

    def select_file_by_name(self, filename: str) -> None:
        """Programmatically select a file row by filename."""
        for row in range(self._file_model.rowCount()):
            item = self._file_model.item(row, 0)
            if item and item.text() == filename:
                source_idx = self._file_model.index(row, 0)
                proxy_idx = self._file_proxy.mapFromSource(source_idx)
                self._file_table.setCurrentIndex(proxy_idx)
                return

    def select_spectrum_by_index(self, packet_index: int) -> None:
        """Programmatically select a spectrum row by packet index."""
        for row in range(self._spectrum_model.rowCount()):
            item = self._spectrum_model.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == packet_index:
                source_idx = self._spectrum_model.index(row, 0)
                proxy_idx = self._spectrum_proxy.mapFromSource(source_idx)
                self._spectrum_table.setCurrentIndex(proxy_idx)
                return

    def get_selected_filepaths(self) -> list[Path]:
        """Return Paths for all selected rows in the file table."""
        selection = self._file_table.selectionModel().selectedRows(0)
        paths = []
        for proxy_idx in selection:
            source_idx = self._file_proxy.mapToSource(proxy_idx)
            item = self._file_model.item(source_idx.row(), 0)
            if item:
                paths.append(Path(item.data(Qt.ItemDataRole.UserRole)))
        return sorted(paths)

    # -- File table interaction -----------------------------------------------

    def _on_file_row_changed(self, current, _previous) -> None:
        if not current.isValid():
            return

        source_idx = self._file_proxy.mapToSource(current)
        row = source_idx.row()

        if self._active_file:
            self._set_file_row_style(self._active_file, bold=False)

        name_item = self._file_model.item(row, 0)
        if not name_item:
            return

        filename = name_item.text()
        filepath = Path(name_item.data(Qt.ItemDataRole.UserRole))

        self._active_file = filename
        self._set_file_row_style(filename, bold=True)
        self.file_selected.emit(filename)

        # Load and display packets for this file
        self._load_spectra(filepath)

    def _set_file_row_style(self, filename: str, *, bold: bool) -> None:
        for row in range(self._file_model.rowCount()):
            item = self._file_model.item(row, 0)
            if item and item.text() == filename:
                font = item.font()
                font.setBold(bold)
                icon = self._icon_active if bold else self._icon_default
                for col in range(self._file_model.columnCount()):
                    col_item = self._file_model.item(row, col)
                    if col_item:
                        col_item.setFont(font)
                item.setIcon(icon)
                return

    # -- Spectrum table -------------------------------------------------------

    def _load_spectra(self, filepath: Path) -> None:
        """Parse the .dat file and populate the spectrum table.

        Each row shows:
        - #: packet index
        - Time: HH:MM:SS UTC timestamp
        - P: classification probability (placeholder 0.0 until model runs)
        - Temp: predicted temperature (placeholder — until model runs)
        """
        self._spectrum_model.removeRows(0, self._spectrum_model.rowCount())

        packets = self._cache.get_full_packets(filepath)

        for packet in packets:
            # Column 0: packet index (stored as UserRole for selection)
            idx_item = QStandardItem(str(packet.index))
            idx_item.setEditable(False)
            idx_item.setData(packet.index, Qt.ItemDataRole.UserRole)
            idx_item.setData(packet, Qt.ItemDataRole.UserRole + 1)
            idx_item.setData(packet.index, _SORT_ROLE)  # numeric sort

            # Column 1: timestamp
            time_item = QStandardItem(packet.time_str)
            time_item.setEditable(False)
            time_item.setData(packet.timestamp, _SORT_ROLE)  # numeric sort

            # Column 2: classification probability (placeholder)
            p_item = QStandardItem("—")
            p_item.setEditable(False)
            p_item.setData(-1.0, _SORT_ROLE)  # placeholders sort to bottom

            # Column 3: temperature (placeholder)
            temp_item = QStandardItem("—")
            temp_item.setEditable(False)
            temp_item.setData(-1.0, _SORT_ROLE)

            # Column 4: override state
            ov_item = QStandardItem("—")
            ov_item.setEditable(False)
            ov_item.setForeground(QBrush(QColor(COLORS["text_muted"])))
            ov_item.setData(0, _SORT_ROLE)

            # Store initial override state on the index item
            idx_item.setData(OverrideState.NONE, _OVERRIDE_ROLE)

            self._spectrum_model.appendRow([idx_item, time_item, p_item, temp_item, ov_item])

        self._spectrum_table.resizeColumnToContents(0)
        self._spectrum_table.resizeColumnToContents(1)
        # Override column: compact fixed width
        self._spectrum_table.setColumnWidth(4, 56)

        # Restore persisted overrides for this file
        self._restore_overrides(filepath.name)

        # Auto-select the first spectrum row
        if self._spectrum_model.rowCount() > 0:
            first_proxy_idx = self._spectrum_proxy.index(0, 0)
            self._spectrum_table.setCurrentIndex(first_proxy_idx)

        # Notify that packets are ready for inference
        self.file_loaded.emit(filepath, packets)

    def _restore_overrides(self, dat_filename: str) -> None:
        """Restore persisted overrides for all rows of the given .dat file."""
        saved = self._override_store.get_overrides(dat_filename)
        if not saved:
            return

        for row in range(self._spectrum_model.rowCount()):
            idx_item = self._spectrum_model.item(row, 0)
            if not idx_item:
                continue
            pkt_idx = idx_item.data(Qt.ItemDataRole.UserRole)
            state = saved.get(pkt_idx)
            if state is not None and state != OverrideState.NONE:
                idx_item.setData(OverrideState(state), _OVERRIDE_ROLE)
                _apply_override_cell(self._spectrum_model, row)

    def update_all_predictions(
        self, predictions: list[tuple[int, float, float]],
        threshold: float = 0.0,
    ) -> None:
        """Batch-update predictions for multiple packets.

        predictions: list of (packet_index, probability, temperature) tuples.
        threshold: P value below which temperature is hidden.
        """
        pred_map = {idx: (prob, temp) for idx, prob, temp in predictions}

        for row in range(self._spectrum_model.rowCount()):
            idx_item = self._spectrum_model.item(row, 0)
            if not idx_item:
                continue
            pkt_idx = idx_item.data(Qt.ItemDataRole.UserRole)
            if pkt_idx not in pred_map:
                continue

            prob, temp = pred_map[pkt_idx]
            _apply_prediction(self._spectrum_model, row, prob, temp, threshold)

    # -- Spectrum selection ---------------------------------------------------

    def _on_spectrum_row_changed(self, current, _previous) -> None:
        """Handle spectrum table row selection."""
        if not current.isValid():
            return

        source_idx = self._spectrum_proxy.mapToSource(current)
        row = source_idx.row()

        idx_item = self._spectrum_model.item(row, 0)
        if not idx_item:
            return

        # Retrieve the stored PacketData
        packet = idx_item.data(Qt.ItemDataRole.UserRole + 1)
        if packet:
            self._settings.active_spectrum_index = packet.index
            self.spectrum_selected.emit(packet)

    # -- Override toggle -------------------------------------------------------

    def _on_spectrum_key_press(self, event) -> None:
        """Handle key presses on the spectrum table."""
        if event.key() == Qt.Key.Key_Space:
            self._toggle_override()
        else:
            QTableView.keyPressEvent(self._spectrum_table, event)

    def _toggle_override(self) -> None:
        """Rotate the override state of the currently selected spectrum row."""
        current = self._spectrum_table.currentIndex()
        if not current.isValid():
            return

        source_idx = self._spectrum_proxy.mapToSource(current)
        row = source_idx.row()

        idx_item = self._spectrum_model.item(row, 0)
        if not idx_item:
            return

        state = idx_item.data(_OVERRIDE_ROLE)
        if state is None:
            state = OverrideState.NONE

        # Rotate: NONE -> GOOD -> BAD -> NONE
        new_state = OverrideState((state + 1) % 3)
        idx_item.setData(new_state, _OVERRIDE_ROLE)

        # Update the OV column display
        _apply_override_cell(self._spectrum_model, row)

        # Re-apply prediction display (asterisk, color) if predictions exist
        p_item = self._spectrum_model.item(row, 2)
        prob = p_item.data(_SORT_ROLE)
        if prob is not None and prob >= 0:
            temp_item = self._spectrum_model.item(row, 3)
            temp = temp_item.data(_RAW_TEMP_ROLE)
            if temp is None:
                temp = float("nan")
            _apply_prediction(
                self._spectrum_model, row, prob, temp,
                threshold=self._settings.p_threshold,
            )

        packet_index = idx_item.data(Qt.ItemDataRole.UserRole)

        # Persist to disk
        if self._active_file:
            self._override_store.set_override(
                self._active_file, packet_index, int(new_state)
            )

        self.override_changed.emit(packet_index, int(new_state))

    def get_all_overrides(self) -> dict[int, OverrideState]:
        """Return a dict of packet_index -> OverrideState for all non-NONE overrides."""
        overrides = {}
        for row in range(self._spectrum_model.rowCount()):
            idx_item = self._spectrum_model.item(row, 0)
            if not idx_item:
                continue
            state = idx_item.data(_OVERRIDE_ROLE)
            if state is not None and state != OverrideState.NONE:
                pkt_idx = idx_item.data(Qt.ItemDataRole.UserRole)
                overrides[pkt_idx] = OverrideState(state)
        return overrides

    # -- Processing overlay ---------------------------------------------------

    def show_progress(self, processed: int, total: int) -> None:
        """Update and show the processing overlay."""
        self._overlay.setText(f"Processing... ({processed}/{total})")
        self._overlay.adjustSize()
        # Center on the viewport (the actual visible content area)
        vp = self._spectrum_table.viewport()
        x = (vp.width() - self._overlay.width()) // 2
        y = (vp.height() - self._overlay.height()) // 2
        self._overlay.move(max(x, 0), max(y, 0))
        self._overlay.raise_()
        self._overlay.show()

    def hide_progress(self) -> None:
        """Hide the processing overlay."""
        self._overlay.hide()

    # -- Sort persistence -----------------------------------------------------

    def _on_file_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        self._settings.save_table_sort(
            "file_table", column, order == Qt.SortOrder.AscendingOrder
        )

    def _on_spectrum_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        self._settings.save_table_sort(
            "spectrum_table", column, order == Qt.SortOrder.AscendingOrder
        )

    def _restore_sort_state(self) -> None:
        """Apply saved sort column/direction to both tables."""
        file_sort = self._settings.load_table_sort("file_table")
        if file_sort:
            col, ascending = file_sort
            order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
            self._file_table.sortByColumn(col, order)

        spectrum_sort = self._settings.load_table_sort("spectrum_table")
        if spectrum_sort:
            col, ascending = spectrum_sort
            order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
            self._spectrum_table.sortByColumn(col, order)
