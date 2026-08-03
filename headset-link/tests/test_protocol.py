"""Wire-format round-trips, framing invariants, and the int16 scale."""

import numpy as np
import pytest

from esp_headset import protocol
from esp_headset.protocol import Header

N_CH, SFREQ = protocol.N_CHANNELS, protocol.SFREQ


def make_counts(n_samples, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(-32768, 32767, (N_CH, n_samples), dtype=np.int16)


def header_for(counts, class_id=0):
    return Header(class_id, counts.shape[0], SFREQ, protocol.SCALE_UV_PER_LSB,
                  protocol.OFFSET_UV, counts.shape[1])


def test_header_is_20_bytes_and_round_trips():
    h = Header(3, N_CH, SFREQ, protocol.SCALE_UV_PER_LSB, protocol.OFFSET_UV, 6000)
    buf = protocol.encode_header(h)

    assert len(buf) == 20 == protocol.HEADER_SIZE
    assert buf[:4] == b"VHS1"
    got = protocol.decode_header(buf)
    assert (got.class_id, got.n_ch, got.sfreq, got.n_samples) == (3, N_CH, SFREQ, 6000)
    assert got.scale_uv_per_lsb == pytest.approx(protocol.SCALE_UV_PER_LSB, rel=1e-6)
    assert got.offset_uv == pytest.approx(protocol.OFFSET_UV, rel=1e-6)
    assert got.seconds == 30.0
    assert got.payload_nbytes == 19 * 6000 * 2


def test_segment_round_trip():
    counts = make_counts(500)
    h = header_for(counts, class_id=4)
    h2, got = protocol.decode_segment(protocol.encode_segment(h, counts))

    assert h2 == h
    assert np.array_equal(got, counts)


def test_payload_is_sample_major():
    # Sample-major means the first 19 int16s are all channels of sample 0.
    counts = np.arange(N_CH * 3, dtype=np.int16).reshape(3, N_CH).T  # ch-major (19, 3)
    buf = protocol.encode_samples(counts)
    first = np.frombuffer(buf[: N_CH * 2], dtype="<i2")

    assert np.array_equal(first, counts[:, 0])


def test_chunk_boundary_never_splits_a_sample():
    from esp_headset.sender import CHUNK_SAMPLES

    assert (CHUNK_SAMPLES * N_CH * 2) % (N_CH * 2) == 0
    counts = make_counts(CHUNK_SAMPLES * 4)
    chunks = [protocol.encode_samples(counts[:, s:s + CHUNK_SAMPLES])
              for s in range(0, counts.shape[1], CHUNK_SAMPLES)]

    assert all(len(c) == CHUNK_SAMPLES * N_CH * 2 for c in chunks)
    assert np.array_equal(protocol.decode_samples(b"".join(chunks), N_CH), counts)


# --------------------------------------------------------------------------- #
# Scale: the EDF's own +/-5000 uV over the full int16 range
# --------------------------------------------------------------------------- #
def test_scale_matches_the_edf_physical_range():
    assert protocol.SCALE_UV_PER_LSB == pytest.approx(10000.0 / 65535.0)
    assert protocol.SCALE_UV_PER_LSB == pytest.approx(0.15259, abs=1e-5)


def test_counts_volts_round_trip_is_lossless_on_the_digital_grid():
    counts = make_counts(200)
    volts = protocol.counts_to_volts(counts, protocol.SCALE_UV_PER_LSB, protocol.OFFSET_UV)
    back = protocol.volts_to_counts(volts, protocol.SCALE_UV_PER_LSB, protocol.OFFSET_UV)

    assert np.array_equal(back, counts)


def test_offset_is_the_half_lsb_the_asymmetric_int16_range_forces():
    # physical +/-5000 uV over digital -32768..32767 -> offset = gain/2, not 0.
    assert protocol.OFFSET_UV == pytest.approx(protocol.SCALE_UV_PER_LSB / 2)
    assert protocol.OFFSET_UV == pytest.approx(0.076295, abs=1e-6)


def test_edf_physical_values_recover_their_exact_adc_codes():
    """The regression: physical = code*gain + offset, so the offset must come off
    before rounding. Ignoring it yields rint(code + 0.5), which round-half-to-even
    corrupts every odd code by one LSB."""
    gain, offset = protocol.SCALE_UV_PER_LSB, protocol.OFFSET_UV
    codes = np.arange(-2000, 2000, dtype=np.int16).reshape(1, -1)
    physical_volts = (codes.astype(np.float64) * gain + offset) * 1e-6

    exact = protocol.volts_to_counts(physical_volts, gain, offset)
    assert np.array_equal(exact, codes)

    naive = np.clip(np.rint(physical_volts * 1e6 / gain), -32768, 32767).astype(np.int16)
    corrupted = int((naive != codes).sum())
    assert corrupted > 1000, "the naive path should mangle ~half the odd codes"


def test_volts_to_counts_saturates_instead_of_wrapping():
    volts = np.array([[+1.0, -1.0]])  # +/-1 V, far outside the +/-5 mV range
    counts = protocol.volts_to_counts(volts, protocol.SCALE_UV_PER_LSB, protocol.OFFSET_UV)

    assert counts.dtype == np.int16
    assert counts[0, 0] == 32767 and counts[0, 1] == -32768


# --------------------------------------------------------------------------- #
# Malformed input
# --------------------------------------------------------------------------- #
def test_bad_magic_rejected():
    buf = bytearray(protocol.encode_header(Header(0, N_CH, SFREQ, 0.15259, 0.0763, 10)))
    buf[:4] = b"XXXX"
    with pytest.raises(ValueError, match="bad magic"):
        protocol.decode_header(bytes(buf))


def test_wrong_channel_count_rejected():
    with pytest.raises(ValueError, match="expected 19 channels"):
        protocol.decode_header(protocol.encode_header(Header(0, 18, SFREQ, 0.15259, 0.0763, 10)))


def test_truncated_payload_rejected():
    counts = make_counts(50)
    blob = protocol.encode_segment(header_for(counts), counts)
    with pytest.raises(ValueError, match="truncated payload"):
        protocol.decode_segment(blob[:-2])


def test_short_header_rejected():
    with pytest.raises(ValueError, match="header needs 20 bytes"):
        protocol.decode_header(b"VHS1")


def test_decode_samples_rejects_ragged_buffer():
    with pytest.raises(ValueError, match="not a multiple of 19 channels"):
        protocol.decode_samples(b"\x00" * (N_CH * 2 + 2), N_CH)


def test_encode_rejects_non_int16():
    with pytest.raises(ValueError, match="expected int16"):
        protocol.encode_samples(np.zeros((N_CH, 4), dtype=np.float32))
