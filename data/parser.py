"""Parse GRIPS .dat files into packet data structures.

Each .dat file contains multiple "packets" — complete spectral scans
across 301 wavelength points. Packets are delimited by wavelength resets
(when the scanner jumps back to the start wavelength).

This module provides:
- PacketData: a lightweight container for one parsed packet
- DatFileCache: an LRU cache that lazy-loads and caches parsed packets
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

# Matches the constants in grips-n-nn/src/grips_nn/config.py
FULL_PACKET_SIZE = 301
WAVELENGTH_START = 3040.20
WAVELENGTH_STEP = 0.20


@dataclass(frozen=True, slots=True)
class PacketData:
    """One complete spectral measurement (301 intensity values).

    frozen=True makes instances immutable and hashable.
    slots=True uses __slots__ for lower memory overhead — useful
    when we might hold thousands of packets in cache.
    """

    index: int                          # 0-based position within the .dat file
    timestamp: float                    # Unix timestamp (from first row of packet)
    intensities: np.ndarray             # Shape (301,) — the spectrum
    is_partial: bool                    # True if packet has != 301 points

    @property
    def datetime(self) -> dt.datetime:
        """Convert Unix timestamp to datetime (UTC)."""
        return dt.datetime.fromtimestamp(self.timestamp, tz=dt.timezone.utc)

    @property
    def time_str(self) -> str:
        """Human-readable time string (HH:MM:SS UTC)."""
        return self.datetime.strftime("%H:%M:%S")

    def __hash__(self) -> int:
        return hash((self.index, self.timestamp))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PacketData):
            return NotImplemented
        return self.index == other.index and self.timestamp == other.timestamp


def parse_dat_file(filepath: Path) -> list[PacketData]:
    """Parse a .dat file into a list of PacketData objects.

    Replicates the packet-splitting logic from grips-n-nn loader.py
    but produces structured objects instead of raw arrays.

    Partial packets (truncated scans at file boundaries) are included
    but flagged with is_partial=True so the caller can decide whether
    to skip them.
    """
    data = np.loadtxt(filepath)
    if data.ndim == 1:
        # Single-row file — unlikely but handle gracefully
        data = data.reshape(1, -1)

    wavelengths = data[:, 1]

    # Packet boundaries: wavelength drops back to start
    resets = np.where(np.diff(wavelengths) < 0)[0] + 1
    boundaries = np.concatenate([[0], resets, [len(data)]])

    packets = []
    for idx, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        chunk = data[start:end]
        n_points = len(chunk)

        packets.append(PacketData(
            index=idx,
            timestamp=chunk[0, 0],
            intensities=chunk[:, 2] if n_points == FULL_PACKET_SIZE else chunk[:, 2],
            is_partial=(n_points != FULL_PACKET_SIZE),
        ))

    return packets


class DatFileCache:
    """LRU cache for parsed .dat files.

    Avoids re-reading files from disk when the user clicks back and
    forth between files. The cache holds up to `maxsize` parsed file
    results in memory.

    We use functools.lru_cache on an inner function. lru_cache requires
    hashable arguments, so we cache by the string path.
    """

    def __init__(self, maxsize: int = 32) -> None:
        # Create a closure-based cached function.
        # Each DatFileCache instance gets its own independent cache.
        @lru_cache(maxsize=maxsize)
        def _cached_parse(filepath_str: str) -> list[PacketData]:
            return parse_dat_file(Path(filepath_str))

        self._cached_parse = _cached_parse

    def get(self, filepath: Path) -> list[PacketData]:
        """Get parsed packets for a file, loading from disk if not cached."""
        return self._cached_parse(str(filepath))

    def get_full_packets(self, filepath: Path) -> list[PacketData]:
        """Get only complete (301-point) packets, skipping partials."""
        return [p for p in self.get(filepath) if not p.is_partial]

    def clear(self) -> None:
        """Evict all cached entries (e.g. when switching directories)."""
        self._cached_parse.cache_clear()

    @property
    def cache_info(self) -> str:
        """Cache hit/miss statistics — useful for debugging."""
        info = self._cached_parse.cache_info()
        return f"hits={info.hits}, misses={info.misses}, size={info.currsize}/{info.maxsize}"
