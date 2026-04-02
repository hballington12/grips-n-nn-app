"""Persistent application settings backed by QSettings.

QSettings is Qt's built-in key-value store for app preferences.
It automatically picks the right storage backend per OS:
  - Linux:   ~/.config/<org>/<app>.conf  (INI file)
  - macOS:   ~/Library/Preferences/<bundle-id>.plist
  - Windows: Registry under HKEY_CURRENT_USER\Software\<org>\<app>

Usage is simple: settings.value("key") to read, settings.setValue("key", val)
to write. Writes are flushed automatically (or call .sync() to force).

We wrap it in a thin class so the rest of the app has a typed API
instead of passing magic strings everywhere.
"""

import json
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSettings, QStandardPaths

# These identify the app in the OS config system.
# QSettings uses them to build the storage path.
ORGANIZATION = "GRIPS"
APPLICATION = "GRIPSSpectraViewer"


class AppSettings:
    """Typed wrapper around QSettings for persistent app configuration."""

    def __init__(self) -> None:
        self._qs = QSettings(ORGANIZATION, APPLICATION)

    # -- Data directory -----------------------------------------------------

    @property
    def data_directory(self) -> Path | None:
        """Last-used raw data directory, or None if never set."""
        val = self._qs.value("data/directory")
        if val:
            return Path(val)
        return None

    @data_directory.setter
    def data_directory(self, path: Path | None) -> None:
        if path is None:
            self._qs.remove("data/directory")
        else:
            self._qs.setValue("data/directory", str(path))

    # -- Export directory -------------------------------------------------------

    @property
    def export_directory(self) -> Path | None:
        val = self._qs.value("export/directory")
        if val:
            return Path(val)
        return None

    @export_directory.setter
    def export_directory(self, path: Path | None) -> None:
        if path is None:
            self._qs.remove("export/directory")
        else:
            self._qs.setValue("export/directory", str(path))

    @property
    def export_format(self) -> str:
        """Export format: 'csv' or 'ascii'. Default 'csv'."""
        val = self._qs.value("export/format")
        return val if val in ("csv", "ascii") else "csv"

    @export_format.setter
    def export_format(self, fmt: str) -> None:
        self._qs.setValue("export/format", fmt)

    @property
    def export_good_only(self) -> bool:
        val = self._qs.value("export/good_only")
        if val is None:
            return True  # default: export good only
        return val in (True, "true")

    @export_good_only.setter
    def export_good_only(self, value: bool) -> None:
        self._qs.setValue("export/good_only", value)

    # -- Classification threshold -----------------------------------------------

    @property
    def p_threshold(self) -> float:
        """Classifier probability threshold for 'good' spectra. Default 0.50."""
        val = self._qs.value("data/p_threshold")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0.50

    @p_threshold.setter
    def p_threshold(self, value: float) -> None:
        self._qs.setValue("data/p_threshold", value)

    # -- Active selections -----------------------------------------------------

    @property
    def active_dat_file(self) -> str | None:
        """Filename (not full path) of the last-selected .dat file."""
        val = self._qs.value("data/active_dat_file")
        return val if val else None

    @active_dat_file.setter
    def active_dat_file(self, name: str | None) -> None:
        if name is None:
            self._qs.remove("data/active_dat_file")
        else:
            self._qs.setValue("data/active_dat_file", name)

    @property
    def active_spectrum(self) -> str | None:
        """Identifier of the last-selected spectrum within a .dat file."""
        val = self._qs.value("data/active_spectrum")
        return val if val else None

    @active_spectrum.setter
    def active_spectrum(self, name: str | None) -> None:
        if name is None:
            self._qs.remove("data/active_spectrum")
        else:
            self._qs.setValue("data/active_spectrum", name)

    @property
    def active_spectrum_index(self) -> int | None:
        """Packet index of the last-selected spectrum."""
        val = self._qs.value("data/active_spectrum_index")
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return None

    @active_spectrum_index.setter
    def active_spectrum_index(self, index: int | None) -> None:
        if index is None:
            self._qs.remove("data/active_spectrum_index")
        else:
            self._qs.setValue("data/active_spectrum_index", index)

    # -- Table sort state ------------------------------------------------------
    # Each table's sort column + order is stored as two values.
    # QSettings stores everything as strings, so we convert explicitly.

    def save_table_sort(self, name: str, column: int, ascending: bool) -> None:
        """Persist sort column and direction for a named table."""
        self._qs.setValue(f"tables/{name}/sort_column", column)
        self._qs.setValue(f"tables/{name}/sort_ascending", ascending)

    def load_table_sort(self, name: str) -> tuple[int, bool] | None:
        """Load saved sort state. Returns (column, ascending) or None."""
        col = self._qs.value(f"tables/{name}/sort_column")
        asc = self._qs.value(f"tables/{name}/sort_ascending")
        if col is None or asc is None:
            return None
        try:
            # QSettings may return strings — coerce explicitly
            return int(col), asc in (True, "true")
        except (ValueError, TypeError):
            return None

    # -- Window layout -------------------------------------------------------
    # Qt widgets like QMainWindow and QSplitter can serialize their entire
    # layout state (position, size, splitter positions) into a QByteArray.
    # We store these blobs as-is — QSettings handles QByteArray natively.

    def save_window_geometry(self, geometry: QByteArray) -> None:
        self._qs.setValue("window/geometry", geometry)

    def load_window_geometry(self) -> QByteArray | None:
        val = self._qs.value("window/geometry")
        return val if isinstance(val, QByteArray) else None

    def save_splitter_state(self, name: str, state: QByteArray) -> None:
        """Save a named splitter's state. Use a unique name per splitter."""
        self._qs.setValue(f"splitters/{name}", state)

    def load_splitter_state(self, name: str) -> QByteArray | None:
        val = self._qs.value(f"splitters/{name}")
        return val if isinstance(val, QByteArray) else None

    # -- Utility ------------------------------------------------------------

    def sync(self) -> None:
        """Force-flush pending writes to disk.

        QSettings normally writes lazily (on a timer or at app exit).
        Call this after critical changes if you want immediate persistence.
        """
        self._qs.sync()

    @property
    def file_path(self) -> str:
        """Where QSettings is actually storing data — useful for debugging."""
        return self._qs.fileName()


class OverrideStore:
    """JSON-backed persistent storage for manual classification overrides.

    Stores a dict of {dat_filename: {packet_index_str: override_int}}.
    Lives in the OS app-data directory alongside other config.
    """

    def __init__(self) -> None:
        config_dir = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppConfigLocation
            )
        )
        config_dir.mkdir(parents=True, exist_ok=True)
        self._path = config_dir / "overrides.json"
        self._data: dict[str, dict[str, int]] = self._load()

    def _load(self) -> dict[str, dict[str, int]]:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def get_overrides(self, dat_filename: str) -> dict[int, int]:
        """Return {packet_index: override_state} for a given .dat file."""
        raw = self._data.get(dat_filename, {})
        return {int(k): v for k, v in raw.items()}

    def set_override(self, dat_filename: str, packet_index: int, state: int) -> None:
        """Set or clear a single override. state=0 removes the entry."""
        if dat_filename not in self._data:
            self._data[dat_filename] = {}

        key = str(packet_index)
        if state == 0:
            self._data[dat_filename].pop(key, None)
            if not self._data[dat_filename]:
                del self._data[dat_filename]
        else:
            self._data[dat_filename][key] = state

        self._save()

    def set_all_overrides(self, dat_filename: str, overrides: dict[int, int]) -> None:
        """Replace all overrides for a .dat file. Empty dict removes the entry."""
        filtered = {str(k): v for k, v in overrides.items() if v != 0}
        if filtered:
            self._data[dat_filename] = filtered
        else:
            self._data.pop(dat_filename, None)
        self._save()

    @property
    def file_path(self) -> Path:
        return self._path
