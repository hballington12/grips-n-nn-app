"""Export predictions to CSV or ASCII files.

Output format mirrors the FK .wup2 style: one row per packet with
timestamp, packet index, probability, and temperature. A scientific
header documents provenance (models used, threshold, generation date).
"""

import datetime as dt
from pathlib import Path

from data.model_runner import BOLTZMANN_PATH, CLASSIFIER_PATH
from data.parser import PacketData


def _build_header(
    dat_filename: str,
    p_threshold: float,
    export_format: str,
    good_only: bool,
    has_overrides: bool = False,
) -> list[str]:
    """Build a comment header with provenance metadata."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    clf_mtime = dt.datetime.fromtimestamp(
        CLASSIFIER_PATH.stat().st_mtime, tz=dt.timezone.utc
    ).strftime("%Y-%m-%d")
    boltz_mtime = dt.datetime.fromtimestamp(
        BOLTZMANN_PATH.stat().st_mtime, tz=dt.timezone.utc
    ).strftime("%Y-%m-%d")

    if good_only:
        filter_line = f"Good spectra with P >= {p_threshold:.2f}"
    else:
        filter_line = f"All spectra exported (P threshold {p_threshold:.2f} for temperature only)"

    prefix = "#"

    lines = [
        f"{prefix} GRIPS Spectra Viewer — prediction export",
        f"{prefix} Generated: {now}",
        f"{prefix} Source file: {dat_filename}",
        f"{prefix} Classifier model: {CLASSIFIER_PATH.name} (modified {clf_mtime})",
        f"{prefix} Temperature model: {BOLTZMANN_PATH.name} (modified {boltz_mtime})",
        f"{prefix} Filter: {filter_line}",
    ]

    if has_overrides:
        lines.append(f"{prefix} Note: manual overrides applied (see override column)")

    lines.append(f"{prefix}")

    if export_format == "csv":
        lines.append("timestamp,packet_index,probability,temperature,override")
    else:
        lines.append(
            f"{prefix} Columns: timestamp  packet_index  probability  temperature  override"
        )

    return lines


_OVERRIDE_LABELS = {0: "none", 1: "good", 2: "bad"}


def export_predictions(
    output_dir: Path,
    dat_filename: str,
    packets: list[PacketData],
    predictions: list[tuple[int, float, float]],
    p_threshold: float,
    export_format: str = "csv",
    good_only: bool = False,
    overrides: dict[int, int] | None = None,
) -> Path:
    """Write predictions to a file.

    Args:
        output_dir: directory to write the file into.
        dat_filename: source .dat filename (e.g. "GRIPSII_2023-01-01.dat").
        packets: parsed packets from the .dat file.
        predictions: list of (packet_index, probability, temperature) tuples.
        p_threshold: current P threshold (recorded in header).
        export_format: "csv" or "ascii".
        good_only: if True, skip rows with P < threshold (respecting overrides).
        overrides: dict of packet_index -> OverrideState int (1=good, 2=bad).

    Returns the path to the written file.
    """
    if overrides is None:
        overrides = {}

    pkt_map = {p.index: p for p in packets}
    pred_map = {idx: (prob, temp) for idx, prob, temp in predictions}

    stem = Path(dat_filename).stem
    ext = ".csv" if export_format == "csv" else ".dat"
    out_path = output_dir / f"{stem}_predictions{ext}"

    sep = "," if export_format == "csv" else "\t"

    header = _build_header(
        dat_filename, p_threshold, export_format, good_only,
        has_overrides=bool(overrides),
    )

    with open(out_path, "w", newline="") as f:
        for line in header:
            f.write(line + "\n")

        for idx in sorted(pred_map.keys()):
            prob, temp = pred_map[idx]
            pkt = pkt_map.get(idx)
            if pkt is None:
                continue

            ov = overrides.get(idx, 0)

            # Filter logic: override takes precedence over threshold
            if good_only:
                if ov == 2:  # BAD override — always skip
                    continue
                if ov != 1 and prob < p_threshold:  # not overridden good, below threshold
                    continue

            # Temperature: shown if good (by override or threshold)
            is_good = ov == 1 or (ov != 2 and prob >= p_threshold)
            timestamp = pkt.datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
            temp_str = f"{temp:.1f}" if is_good else ""
            ov_label = _OVERRIDE_LABELS.get(ov, "none")

            fields = [timestamp, str(idx), f"{prob:.4f}", temp_str, ov_label]
            f.write(sep.join(fields) + "\n")

    return out_path
