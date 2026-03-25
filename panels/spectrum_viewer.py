"""Spectrum viewer — matplotlib plot embedded in a Qt widget."""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QFrame, QVBoxLayout

from data.parser import FULL_PACKET_SIZE, WAVELENGTH_START, WAVELENGTH_STEP, PacketData
from style import COLORS

# Physical wavelength grid (nm) — same conversion as grips-n-nn
WAVELENGTHS = (
    np.arange(FULL_PACKET_SIZE) * WAVELENGTH_STEP + WAVELENGTH_START
) / 2


def _apply_theme(ax) -> None:
    """Style a matplotlib Axes to match the Tokyo Night theme.

    Matplotlib Axes have many visual components — spines (the border
    lines), tick marks, tick labels, axis labels, title. Each needs
    its color set individually. We also thin out the spines and ticks
    for a cleaner look.
    """
    text_color = COLORS["text_secondary"]
    border_color = COLORS["border"]

    # Spine colors and width
    for spine in ax.spines.values():
        spine.set_color(border_color)
        spine.set_linewidth(0.5)

    # Tick colors and label colors
    ax.tick_params(
        colors=text_color,
        labelsize=9,
        length=3,
        width=0.5,
    )

    # Axis label colors
    ax.xaxis.label.set_color(text_color)
    ax.yaxis.label.set_color(text_color)
    ax.title.set_color(COLORS["text_bright"])


class SpectrumViewerPanel(QFrame):
    """Embeds a matplotlib figure for displaying a single spectrum.

    FigureCanvasQTAgg is matplotlib's Qt integration — it's a QWidget
    subclass that renders a matplotlib Figure. We create the figure once
    and redraw it whenever a new spectrum is selected, which is much
    faster than recreating the figure each time.
    """

    def __init__(self, title: str = "Spectrum", parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)

        # Create figure with transparent background.
        # facecolor="none" makes the figure background fully transparent,
        # so the panel's QSS background shows through.
        self._fig = Figure(facecolor="none", constrained_layout=True)
        self._ax = self._fig.add_subplot(111)

        # The canvas is the bridge between matplotlib and Qt.
        self._canvas = FigureCanvasQTAgg(self._fig)
        # Make the canvas widget background transparent too — by default
        # Qt paints an opaque background behind it.
        self._canvas.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._canvas)

        self._title = title
        self._draw_empty()

    def _draw_empty(self) -> None:
        """Show an empty plot with 'No spectrum selected' message."""
        ax = self._ax
        ax.clear()
        ax.set_facecolor("none")
        _apply_theme(ax)

        ax.text(
            0.5, 0.5, "No spectrum selected",
            transform=ax.transAxes,
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=12,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        self._canvas.draw_idle()

    def plot_spectrum(
        self,
        packet: PacketData,
        probability: float | None = None,
        title_override: str | None = None,
    ) -> None:
        """Plot a single spectrum.

        Args:
            packet: the packet to display.
            probability: classifier probability (0-1), used to pick
                the line color — green for good, red for bad.
            title_override: custom title string. If None, uses the
                default "Packet #N — HH:MM:SS UTC" format.
        """
        ax = self._ax
        ax.clear()
        ax.set_facecolor("none")
        _apply_theme(ax)

        # Pick line color based on classification probability
        if probability is not None and probability >= 0.5:
            line_color = COLORS["green"]
        elif probability is not None:
            line_color = COLORS["red"]
        else:
            line_color = COLORS["accent"]

        ax.plot(
            WAVELENGTHS,
            packet.intensities,
            color=line_color,
            linewidth=0.8,
            alpha=0.9,
        )

        ax.set_xlabel("Wavelength (nm)", fontsize=10)
        ax.set_ylabel("Intensity", fontsize=10)

        title = title_override or f"Packet #{packet.index}  —  {packet.time_str} UTC"
        ax.set_title(title, fontsize=11, pad=8)

        ax.grid(True, alpha=0.15, color=COLORS["text_muted"], linewidth=0.5)

        self._canvas.draw_idle()

    def clear(self) -> None:
        """Reset to empty state."""
        self._draw_empty()
