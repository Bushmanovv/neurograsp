"""The dashboard decodes the snippet it sends, without mne. Pin that decoder.

The EDFs here are synthetic and built byte by byte, so the expected microvolts are
known exactly rather than taken on faith from another reader.
"""

import numpy as np
import pytest

from edf import read_edf

HERE_DATA = "firmware/esp32_headset/data"


def _fixed(value, width: int) -> bytes:
    text = str(value)
    assert len(text) <= width, f"{text!r} does not fit in {width}"
    return text.ljust(width).encode("ascii")


def write_edf(path, signals, n_records=2, record_seconds=1.0):
    """Build an EDF from ``signals``: dicts of label/unit/pmin/pmax/dmin/dmax/digital.

    ``digital`` is (n_records, samples_per_record) int16 -- the samples as stored.
    """
    ns = len(signals)
    header_bytes = 256 * (ns + 1)

    head = (_fixed(0, 8) + _fixed("X", 80) + _fixed("X", 80)
            + _fixed("01.01.26", 8) + _fixed("00.00.00", 8)
            + _fixed(header_bytes, 8) + _fixed("EDF+C", 44)
            + _fixed(n_records, 8) + _fixed(record_seconds, 8) + _fixed(ns, 4))
    assert len(head) == 256

    # Every field is a column across all signals, not a row per signal.
    block = b"".join([
        b"".join(_fixed(s["label"], 16) for s in signals),
        b"".join(_fixed("", 80) for _ in signals),                  # transducer
        b"".join(_fixed(s["unit"], 8) for s in signals),
        b"".join(_fixed(s["pmin"], 8) for s in signals),
        b"".join(_fixed(s["pmax"], 8) for s in signals),
        b"".join(_fixed(s["dmin"], 8) for s in signals),
        b"".join(_fixed(s["dmax"], 8) for s in signals),
        b"".join(_fixed("", 80) for _ in signals),                  # prefiltering
        b"".join(_fixed(s["digital"].shape[1], 8) for s in signals),
        b"".join(_fixed("", 32) for _ in signals),                  # reserved
    ])
    assert len(block) == 256 * ns

    records = b"".join(
        b"".join(s["digital"][r].astype("<i2").tobytes() for s in signals)
        for r in range(n_records)
    )
    path.write_bytes(head + block + records)
    return path


def signal(label, digital, unit="uV", pmin=-100.0, pmax=100.0, dmin=-32767, dmax=32767):
    return {"label": label, "unit": unit, "pmin": pmin, "pmax": pmax,
            "dmin": dmin, "dmax": dmax, "digital": np.asarray(digital, dtype=np.int16)}


def test_digital_counts_become_the_microvolts_the_header_promises(tmp_path):
    # Endpoints and centre of a symmetric +/-100 uV mapping.
    digital = [[-32767, 0, 32767, 16384]]
    path = write_edf(tmp_path / "a.edf", [signal("Fp1-Ref", digital)], n_records=1)

    e = read_edf(path)
    assert e.labels == ["Fp1-Ref"]
    assert e.electrodes == ["Fp1"]
    assert e.sfreq == 4
    assert e.seconds == 1.0
    np.testing.assert_allclose(e.uv[0], [-100.0, 0.0, 100.0, 100.0 * 16384 / 32767])


def test_an_asymmetric_calibration_is_read_from_the_file_not_assumed(tmp_path):
    # mne exports the tight range of the data, not +/-5000 uV. Reading the file's
    # own two ranges is what keeps the plot on the real scale.
    path = write_edf(tmp_path / "a.edf",
                     [signal("Cz-Ref", [[-32767, 32767]], pmin=-346.762, pmax=146.4104)],
                     n_records=1)
    np.testing.assert_allclose(read_edf(path).uv[0], [-346.762, 146.4104], rtol=1e-9)


def test_millivolts_are_converted_to_microvolts(tmp_path):
    path = write_edf(tmp_path / "a.edf",
                     [signal("Fp1-Ref", [[32767]], unit="mV", pmin=-1.0, pmax=1.0)],
                     n_records=1)
    np.testing.assert_allclose(read_edf(path).uv[0], [1000.0])


def test_annotation_channel_is_dropped_without_shifting_the_data(tmp_path):
    # The regression this guards: an EDF+ annotations signal has its own, different
    # sample count, so the record stride is the SUM of the per-signal counts. Treat
    # every signal as having the EEG's rate and every channel after it decodes shifted.
    eeg_a = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.int16)
    eeg_b = np.array([[10, 20, 30, 40], [50, 60, 70, 80]], dtype=np.int16)
    notes = np.array([[999, -999, 7], [1, 2, 3]], dtype=np.int16)   # 3 samples, not 4

    path = write_edf(tmp_path / "a.edf", [
        signal("Fp1-Ref", eeg_a),
        signal("EDF Annotations", notes, unit="", pmin=-32768, pmax=32767,
               dmin=-32768, dmax=32767),
        signal("Fp2-Ref", eeg_b),
    ], n_records=2)

    e = read_edf(path)
    assert e.labels == ["Fp1-Ref", "Fp2-Ref"]          # annotations gone
    assert e.uv.shape == (2, 8)
    gain = 100.0 / 32767                                # +/-100 uV over +/-32767
    np.testing.assert_allclose(e.uv[0], eeg_a.reshape(-1) * gain, rtol=1e-9)
    np.testing.assert_allclose(e.uv[1], eeg_b.reshape(-1) * gain, rtol=1e-9)


def test_the_bytes_are_kept_verbatim_for_the_wire(tmp_path):
    # The dashboard plots e.uv and sends e.data. If they came from different reads
    # the picture could drift from the payload; they must be the same bytes.
    path = write_edf(tmp_path / "a.edf", [signal("Fp1-Ref", [[1, 2]])], n_records=1)
    assert read_edf(path).data == path.read_bytes()


def test_truncated_file_is_refused(tmp_path):
    four = [[1, 2], [3, 4], [5, 6], [7, 8]]
    path = write_edf(tmp_path / "a.edf", [signal("Fp1-Ref", four)], n_records=4)
    path.write_bytes(path.read_bytes()[:-6])           # lose a few samples
    with pytest.raises(ValueError, match="truncated data"):
        read_edf(path)


def test_channels_at_different_rates_are_refused(tmp_path):
    path = write_edf(tmp_path / "a.edf", [
        signal("Fp1-Ref", [[1, 2, 3, 4]]),
        signal("Fp2-Ref", [[1, 2]]),
    ], n_records=1)
    with pytest.raises(ValueError, match="disagree on sample rate"):
        read_edf(path)


@pytest.mark.parametrize("class_id", range(5))
def test_the_shipped_snippets_decode(class_id, request):
    """The five files the dashboard actually sends."""
    path = request.config.rootpath / HERE_DATA / f"s{class_id}.edf"
    if not path.exists():
        pytest.skip(f"{path} not built (run make_snippets.py)")

    e = read_edf(path)
    assert e.n_ch == 19
    assert "EDF Annotations" not in e.labels
    assert e.sfreq == 200
    assert e.seconds == 5.0
    assert np.isfinite(e.uv).all()
    assert 10 < np.abs(e.uv).max() < 1e4          # real EEG, in microvolts
    assert e.data == path.read_bytes()
