"""Neural network inference for GRIPS spectra using ONNX Runtime.

ONNX Runtime is a lightweight inference engine (~50MB vs ~500MB for
TensorFlow). The models were converted from Keras .keras → .onnx using
tf2onnx. The ONNX files are self-contained — they embed the full
computation graph including the Boltzmann physics layer.

ONNX Runtime API:
- ort.InferenceSession(path) — loads the model graph
- session.run(None, {"input": array}) — runs inference, returns list of outputs
- The first arg (None) means "return all outputs"; you can also name specific ones
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
from PyQt6.QtCore import QThread, pyqtSignal

from data.parser import PacketData

# -- Model paths -----------------------------------------------------------
# PyInstaller bundles data files into a _MEIPASS temp directory (onefile)
# or _internal/ (onedir). sys._MEIPASS is set when running frozen.
# In development, we resolve relative to this file's location.

import sys as _sys

if getattr(_sys, "frozen", False):
    _BASE = Path(_sys._MEIPASS)
else:
    _BASE = Path(__file__).resolve().parent.parent

MODELS_DIR = _BASE / "models"
CLASSIFIER_PATH = MODELS_DIR / "classifier.onnx"
BOLTZMANN_PATH = MODELS_DIR / "boltzmann.onnx"


class ModelRunner:
    """Loads and runs both ONNX models.

    ONNX Runtime InferenceSession is thread-safe for concurrent reads,
    so it's fine to call predict() from a QThread while the session
    objects live on the main thread.
    """

    def __init__(self) -> None:
        self._classifier: ort.InferenceSession | None = None
        self._boltzmann: ort.InferenceSession | None = None

    def load(self) -> None:
        """Load both ONNX models. Call once at startup."""
        # CPUExecutionProvider is the default and works everywhere.
        # On machines with CUDA, onnxruntime-gpu would add GPU support.
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        providers = ["CPUExecutionProvider"]

        self._classifier = ort.InferenceSession(
            str(CLASSIFIER_PATH), opts, providers=providers
        )
        self._boltzmann = ort.InferenceSession(
            str(BOLTZMANN_PATH), opts, providers=providers
        )

    @property
    def is_loaded(self) -> bool:
        return self._classifier is not None and self._boltzmann is not None

    def predict(
        self,
        packets: list[PacketData],
        chunk_size: int = 10,
        on_progress: callable | None = None,
    ) -> list[tuple[int, float, float]]:
        """Run both models on all packets in chunks, reporting progress.

        Returns list of (packet_index, probability, temperature) tuples.
        """
        if not self.is_loaded:
            raise RuntimeError("Models not loaded — call load() first")

        n = len(packets)
        all_probs = np.empty(n, dtype=np.float32)
        all_temps = np.empty(n, dtype=np.float32)

        # Get input tensor names from the ONNX models
        clf_input = self._classifier.get_inputs()[0].name
        boltz_input = self._boltzmann.get_inputs()[0].name

        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            chunk_packets = packets[start:end]

            raw = np.array(
                [p.intensities for p in chunk_packets], dtype=np.float32
            )

            # -- Classifier: min-max normalize, add channel dim --
            row_min = raw.min(axis=1, keepdims=True)
            row_max = raw.max(axis=1, keepdims=True)
            row_range = np.maximum(row_max - row_min, 1e-8)
            normed = (raw - row_min) / row_range
            normed = normed.reshape(-1, 301, 1)

            clf_out = self._classifier.run(None, {clf_input: normed})
            all_probs[start:end] = clf_out[0].flatten()

            # -- Boltzmann: raw intensities --
            boltz_out = self._boltzmann.run(None, {boltz_input: raw})
            all_temps[start:end] = boltz_out[0].flatten()

            if on_progress:
                on_progress(end, n)

        return [
            (p.index, float(prob), float(temp))
            for p, prob, temp in zip(packets, all_probs, all_temps)
        ]


# -- Session cache ---------------------------------------------------------

class PredictionCache:
    """In-memory cache for model predictions, keyed by file path."""

    def __init__(self) -> None:
        self._cache: dict[str, list[tuple[int, float, float]]] = {}

    def get(self, filepath: Path) -> list[tuple[int, float, float]] | None:
        return self._cache.get(str(filepath))

    def put(self, filepath: Path, predictions: list[tuple[int, float, float]]) -> None:
        self._cache[str(filepath)] = predictions

    def has(self, filepath: Path) -> bool:
        return str(filepath) in self._cache

    def clear(self) -> None:
        self._cache.clear()


# -- QThread worker --------------------------------------------------------

class InferenceWorker(QThread):
    """Runs model inference on a background thread."""

    finished_with_results = pyqtSignal(str, list)
    progress = pyqtSignal(int, int)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        runner: ModelRunner,
        packets: list[PacketData],
        filepath: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._packets = packets
        self._filepath = filepath

    def run(self) -> None:
        try:
            predictions = self._runner.predict(
                self._packets,
                on_progress=lambda done, total: self.progress.emit(done, total),
            )
            self.finished_with_results.emit(str(self._filepath), predictions)
        except Exception as e:
            self.error_occurred.emit(f"Inference failed: {e}")
