#!/usr/bin/env python3
"""Read just enough of an .edf to draw it -- no mne, no edfio.

The dashboard sends a snippet as opaque bytes; it reads the same bytes back
through here to plot them. Importing mne to do that would add ~4 s to startup for
a file this program already holds in memory, and would let the plot drift away
from the payload. What you see is what was sent, decoded from the very bytes.

EDF is fixed-width ASCII: one 256-byte file header, one 256-byte block per signal
(stored field-by-field, not signal-by-signal -- all 20 labels, then all 20
transducers, ...), then data records of little-endian int16.

An EDF+ file carries an extra "EDF Annotations" signal whose samples are text,
not measurements. It is skipped: `signals` returns only the real channels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

ANNOTATION_LABEL = "EDF Annotations"

# EDF names its physical dimension in the header; honour it rather than assuming.
_TO_UV = {"uv": 1.0, "µv": 1.0, "mv": 1e3, "v": 1e6}


@dataclass(frozen=True)
class Edf:
    """The measurement channels of an EDF, in microvolts."""

    labels: list[str]          # e.g. ["Fp1-Ref", ...], file order preserved
    sfreq: float
    uv: np.ndarray             # (n_ch, n_samples) float64
    data: bytes                # the file, verbatim -- this is what goes on the wire

    @property
    def n_ch(self) -> int:
        return len(self.labels)

    @property
    def seconds(self) -> float:
        return self.uv.shape[1] / self.sfreq

    @property
    def electrodes(self) -> list[str]:
        """Bare electrode names: ``Fp1-Ref`` -> ``Fp1``."""
        return [lab.split("-")[0] for lab in self.labels]


def _column(block: str, n: int, width: int, offset: int) -> list[str]:
    """One header field for every signal: they are laid out contiguously."""
    return [block[offset + i * width: offset + (i + 1) * width].strip() for i in range(n)]


def read_edf(path: str | Path) -> Edf:
    raw = Path(path).read_bytes()
    if len(raw) < 256:
        raise ValueError(f"{path}: too short to be an EDF ({len(raw)} bytes)")

    head = raw[:256].decode("latin-1")
    try:
        header_bytes = int(head[184:192])
        n_records = int(head[236:244])
        record_seconds = float(head[244:252])
        n_signals = int(head[252:256])
    except ValueError as exc:
        raise ValueError(f"{path}: unreadable EDF header ({exc})") from exc

    if n_signals <= 0 or n_records <= 0 or record_seconds <= 0:
        raise ValueError(f"{path}: bad EDF header "
                         f"(signals={n_signals} records={n_records} rec={record_seconds}s)")

    block = raw[256:256 + n_signals * 256].decode("latin-1")
    if len(block) < n_signals * 256:
        raise ValueError(f"{path}: truncated signal header")

    at = 0
    labels = _column(block, n_signals, 16, at);        at += 16 * n_signals
    at += 80 * n_signals                               # transducer type
    units = _column(block, n_signals, 8, at);          at += 8 * n_signals
    phys_min = _column(block, n_signals, 8, at);       at += 8 * n_signals
    phys_max = _column(block, n_signals, 8, at);       at += 8 * n_signals
    dig_min = _column(block, n_signals, 8, at);        at += 8 * n_signals
    dig_max = _column(block, n_signals, 8, at);        at += 8 * n_signals
    at += 80 * n_signals                               # prefiltering
    per_record = [int(x) for x in _column(block, n_signals, 8, at)]

    # Records are the unit of interleave: every signal's samples for second 0,
    # then every signal's samples for second 1. Signals may differ in rate, so
    # the stride is the sum, not n_signals * one rate.
    stride = sum(per_record)
    payload = raw[header_bytes:]
    want = n_records * stride * 2
    if len(payload) < want:
        raise ValueError(f"{path}: truncated data: {len(payload)}/{want} bytes")

    records = np.frombuffer(payload[:want], dtype="<i2").reshape(n_records, stride)

    keep = [i for i, lab in enumerate(labels) if lab != ANNOTATION_LABEL]
    if not keep:
        raise ValueError(f"{path}: no measurement signals, only annotations")

    rates = {per_record[i] for i in keep}
    if len(rates) != 1:
        raise ValueError(f"{path}: channels disagree on sample rate: {sorted(rates)}")
    n_per_record = rates.pop()

    starts = np.cumsum([0] + per_record)
    out = np.empty((len(keep), n_records * n_per_record), dtype=np.float64)
    for row, i in enumerate(keep):
        digital = records[:, starts[i]:starts[i] + per_record[i]].reshape(-1)

        # Digital -> physical is a straight line through the two header ranges;
        # the file states its own calibration, so read it instead of assuming the
        # +/-5000 uV mapping the raw-sample path used.
        dmin, dmax = float(dig_min[i]), float(dig_max[i])
        pmin, pmax = float(phys_min[i]), float(phys_max[i])
        if dmax == dmin:
            raise ValueError(f"{path}: {labels[i]} has an empty digital range")
        gain = (pmax - pmin) / (dmax - dmin)
        scale = _TO_UV.get(units[i].lower(), 1.0)
        out[row] = ((digital - dmin) * gain + pmin) * scale

    return Edf(
        labels=[labels[i] for i in keep],
        sfreq=n_per_record / record_seconds,
        uv=out,
        data=raw,
    )


if __name__ == "__main__":  # quick look: python edf.py firmware/esp32_headset/data/s0.edf
    import sys

    for arg in sys.argv[1:]:
        e = read_edf(arg)
        print(f"{arg}: {e.n_ch} ch  {e.sfreq:g} Hz  {e.seconds:g} s  "
              f"{len(e.data):,} B  peak {np.abs(e.uv).max():.0f} uV")
        print("  " + ", ".join(e.electrodes))
