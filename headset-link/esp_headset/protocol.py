"""Wire format for the virtual headset -> classifier link.

One *segment* (a replayed artifact clip) is a 20-byte header followed by
sample-major int16 payload::

    header : magic "VHS1" | class_id u8 | n_ch u8 | sfreq u16
             | scale f32 | offset f32 | n_samples u32
    payload: for each sample t: int16 ch0, ch1, ... ch18   (little-endian)

The samples are the EDF's *native digital counts*, unfiltered and un-referenced
-- exactly what an ADC hands you. Notch, band-pass, CAR and the per-recording
z-score all stay on the Pi, in ``inference.preprocess_stream``.

Recovering a count needs both calibration constants, not just the scale::

    microvolts = count * scale + offset

The recordings map +/-5000 uV onto the full int16 range, and that range is
*asymmetric* (-32768..32767), so the offset is a non-zero half-LSB:
scale = 0.1526 uV, offset = 0.0763 uV. Dropping it and computing
``rint(microvolts / scale)`` yields ``rint(count + 0.5)``, which round-half-to-
even pushes off by one LSB on roughly half the samples -- an audible-in-the-data
0.1526 uV dither correlated with sample parity. Both constants ride in the
header, so the receiver reconstructs the exact physical value.

Channel order is ``config.ALL_CH``; sample-major interleave lets the receiver
decode incrementally, and keeps a chunk boundary from ever splitting a sample.

The format is transport-agnostic: a byte stream (TCP, RFCOMM/SPP) sends it
verbatim, and a packet transport (BLE GATT) frames it however it likes.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"VHS1"

# Optional reply, classifier -> headset: whatever the Pi's FSM confirmed. The
# headset never classifies; it only replays, transmits, and displays what comes
# back. A headset that ignores this reply is still a correct headset.
RESULT_MAGIC = b"VHSR"
_RESULT = struct.Struct("<4sI")

# EDF calibration: +/-5000 uV over the asymmetric int16 range (-32768..32767).
#   gain   = (pmax - pmin) / (dmax - dmin)
#   offset = pmin - gain * dmin        (== gain/2 for a symmetric physical range)
SCALE_UV_PER_LSB = 10000.0 / 65535.0        # 0.152590 uV
OFFSET_UV = -5000.0 + SCALE_UV_PER_LSB * 32768.0   # 0.076295 uV

_HEADER = struct.Struct("<4sBBHffI")  # 4+1+1+2+4+4+4 = 20 bytes, no padding
HEADER_SIZE = _HEADER.size

N_CHANNELS = 19
SFREQ = 200


@dataclass(frozen=True)
class Header:
    class_id: int
    n_ch: int
    sfreq: int
    scale_uv_per_lsb: float
    offset_uv: float
    n_samples: int

    def __post_init__(self) -> None:
        # The wire carries float32 (the ESP32 has no double-precision FPU), so
        # narrow here: encode -> decode is then exact and the firmware and this
        # simulator agree on the calibration bit-for-bit.
        object.__setattr__(self, "scale_uv_per_lsb",
                           float(np.float32(self.scale_uv_per_lsb)))
        object.__setattr__(self, "offset_uv", float(np.float32(self.offset_uv)))

    @property
    def payload_nbytes(self) -> int:
        return self.n_ch * self.n_samples * 2

    @property
    def seconds(self) -> float:
        return self.n_samples / self.sfreq


def encode_header(h: Header) -> bytes:
    return _HEADER.pack(MAGIC, h.class_id, h.n_ch, h.sfreq,
                        h.scale_uv_per_lsb, h.offset_uv, h.n_samples)


def decode_header(buf: bytes) -> Header:
    if len(buf) < HEADER_SIZE:
        raise ValueError(f"header needs {HEADER_SIZE} bytes, got {len(buf)}")
    magic, class_id, n_ch, sfreq, scale, offset, n_samples = _HEADER.unpack(buf[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}, expected {MAGIC!r}")
    if n_ch != N_CHANNELS:
        raise ValueError(f"expected {N_CHANNELS} channels, header says {n_ch}")
    if sfreq <= 0 or n_samples == 0:
        raise ValueError(f"bad header: sfreq={sfreq} n_samples={n_samples}")
    if not 0 < scale < 100:
        raise ValueError(f"implausible scale {scale} uV/LSB")
    return Header(class_id, n_ch, sfreq, scale, offset, n_samples)


def encode_samples(counts: np.ndarray) -> bytes:
    """``(n_ch, n_samples)`` int16 -> sample-major little-endian bytes."""
    if counts.ndim != 2:
        raise ValueError(f"expected (n_ch, n_samples), got shape {counts.shape}")
    if counts.dtype != np.int16:
        raise ValueError(f"expected int16 counts, got {counts.dtype}")
    return np.ascontiguousarray(counts.T).astype("<i2", copy=False).tobytes()


def decode_samples(buf: bytes, n_ch: int) -> np.ndarray:
    """Sample-major bytes -> ``(n_ch, n_samples)`` int16."""
    flat = np.frombuffer(buf, dtype="<i2")
    if flat.size % n_ch:
        raise ValueError(f"{flat.size} samples is not a multiple of {n_ch} channels")
    return flat.reshape(-1, n_ch).T.copy()


def counts_to_volts(counts: np.ndarray, scale_uv_per_lsb: float,
                    offset_uv: float = OFFSET_UV) -> np.ndarray:
    """Digital counts -> volts, the unit ``mne.io.RawArray`` expects."""
    return (counts.astype(np.float64) * scale_uv_per_lsb + offset_uv) * 1e-6


def volts_to_counts(volts: np.ndarray, scale_uv_per_lsb: float,
                    offset_uv: float = OFFSET_UV) -> np.ndarray:
    """Volts -> digital counts, saturating rather than wrapping at int16 limits.

    Subtracting ``offset_uv`` first is what lands each sample back on the exact
    integer the ADC produced; without it every value sits a half-LSB off the
    grid and rounds unpredictably.
    """
    counts = np.rint((volts * 1e6 - offset_uv) / scale_uv_per_lsb)
    return np.clip(counts, -32768, 32767).astype(np.int16)


def encode_segment(h: Header, counts: np.ndarray) -> bytes:
    if counts.shape != (h.n_ch, h.n_samples):
        raise ValueError(f"counts {counts.shape} != header ({h.n_ch}, {h.n_samples})")
    return encode_header(h) + encode_samples(counts)


def decode_segment(buf: bytes) -> tuple[Header, np.ndarray]:
    h = decode_header(buf)
    payload = buf[HEADER_SIZE:HEADER_SIZE + h.payload_nbytes]
    if len(payload) != h.payload_nbytes:
        raise ValueError(f"truncated payload: {len(payload)}/{h.payload_nbytes} bytes")
    return h, decode_samples(payload, h.n_ch)


# --------------------------------------------------------------------------- #
# Result reply (classifier -> headset)
# --------------------------------------------------------------------------- #
def encode_result(obj) -> bytes:
    """Length-prefixed JSON, so a stream transport can frame it without a delimiter."""
    body = json.dumps(obj).encode()
    return _RESULT.pack(RESULT_MAGIC, len(body)) + body


def decode_result(buf: bytes):
    magic, n = _RESULT.unpack(buf[:_RESULT.size])
    if magic != RESULT_MAGIC:
        raise ValueError(f"bad result magic {magic!r}, expected {RESULT_MAGIC!r}")
    body = buf[_RESULT.size:_RESULT.size + n]
    if len(body) != n:
        raise ValueError(f"truncated result: {len(body)}/{n} bytes")
    return json.loads(body)


def read_result(transport):
    """Block for one result frame on an open transport."""
    head = transport.recv_exactly(_RESULT.size)
    magic, n = _RESULT.unpack(head)
    if magic != RESULT_MAGIC:
        raise ValueError(f"bad result magic {magic!r}, expected {RESULT_MAGIC!r}")
    return json.loads(transport.recv_exactly(n)) if n else None
