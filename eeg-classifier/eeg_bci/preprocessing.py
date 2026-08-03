"""Stage 2 - preprocessing.

For each recording, in this exact order:

    1. Crop      - skip the first ``config.CROP_SECONDS`` seconds.
    2. Notch     - notch filter at ``config.NOTCH_HZ``.
    3. Bandpass  - band-pass filter ``config.BANDPASS_HZ``.
    4. CAR       - common-average reference (subtract the mean over channels).
    5. Epoch     - fixed-length ``config.EPOCH_SEC`` windows, ``EPOCH_OVERLAP`` overlap.
    6. Reject    - drop epochs where any channel exceeds ``config.REJECT_UV`` µV.

A separate :func:`filter_and_car` path (no crop, no epoching) is provided for
real-time inference, which filters the full signal before sliding windows.
"""

from __future__ import annotations

import numpy as np
import mne

from eeg_bci import config as cfg
from eeg_bci.loader import Recording, load_raw

mne.set_log_level("ERROR")

# Microvolts -> volts (MNE stores EEG data in volts).
_UV_TO_V = 1e-6


def _as_eeg(raw: mne.io.BaseRaw) -> mne.io.BaseRaw:
    """Force every channel to type ``eeg`` so filters and CAR apply to all.

    Args:
        raw: Raw object (modified in place).

    Returns:
        The same raw object, with all channel types set to ``eeg``.
    """
    raw.set_channel_types({ch: "eeg" for ch in raw.ch_names})
    return raw


def filter_and_car(raw: mne.io.BaseRaw, *, verbose: bool = False) -> mne.io.BaseRaw:
    """Apply notch -> bandpass -> CAR to a raw signal (no cropping/epoching).

    Used by both the training preprocessing path (after cropping) and the
    inference path (on the full signal).

    Args:
        raw: Preloaded raw object (modified in place).
        verbose: If ``True``, print the filtering steps.

    Returns:
        The filtered, common-average-referenced raw object.
    """
    _as_eeg(raw)
    raw.notch_filter(freqs=cfg.NOTCH_HZ, picks="eeg", verbose="ERROR")
    raw.filter(
        l_freq=cfg.BANDPASS_HZ[0], h_freq=cfg.BANDPASS_HZ[1],
        picks="eeg", verbose="ERROR",
    )
    # Common Average Reference.
    raw.set_eeg_reference(ref_channels="average", verbose="ERROR")
    if verbose:
        print(f"    filter applied: notch {cfg.NOTCH_HZ} Hz, "
              f"bandpass {cfg.BANDPASS_HZ[0]}-{cfg.BANDPASS_HZ[1]} Hz, CAR")
    return raw


def normalize_per_recording(raw: mne.io.BaseRaw) -> mne.io.BaseRaw:
    """Z-score each channel over the whole recording (per-recording normalization).

    Removes absolute amplitude differences between recordings/sessions/electrodes
    so features describe the *shape* of the artifact, not the recording's gain::

        mean = signal.mean(axis=1, keepdims=True)
        std  = signal.std(axis=1,  keepdims=True)
        signal = (signal - mean) / (std + 1e-8)

    Args:
        raw: Filtered, CAR'd raw object (modified in place).

    Returns:
        The normalized raw object.
    """
    data = raw.get_data()
    mean = data.mean(axis=1, keepdims=True)
    std = data.std(axis=1, keepdims=True)
    raw._data = (data - mean) / (std + 1e-8)
    return raw


def _epoch_array(raw: mne.io.BaseRaw) -> np.ndarray:
    """Slice a raw signal into overlapping fixed-length epochs.

    Args:
        raw: Filtered raw object.

    Returns:
        Array of shape ``(n_epochs, n_channels, n_samples)`` in volts.
    """
    overlap_sec = cfg.EPOCH_SEC * cfg.EPOCH_OVERLAP
    epochs = mne.make_fixed_length_epochs(
        raw, duration=cfg.EPOCH_SEC, overlap=overlap_sec,
        preload=True, verbose="ERROR",
    )
    return epochs.get_data(copy=True)


def _reject_epochs(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Reject epochs whose peak amplitude exceeds ``config.REJECT_UV`` µV.

    Args:
        data: Epoch array ``(n_epochs, n_channels, n_samples)`` in volts.

    Returns:
        Tuple of (kept epochs array, boolean keep-mask over the input epochs).
    """
    thresh_v = cfg.REJECT_UV * _UV_TO_V
    # Max absolute amplitude per epoch across all channels & samples.
    peak = np.max(np.abs(data), axis=(1, 2))
    keep = peak <= thresh_v
    return data[keep], keep


def preprocess_recording_dual(
    recording: Recording,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the full Stage-2 pipeline, returning BOTH z-scored and raw-µV epochs.

    The two arrays share the same epochs and reject mask, so row ``i`` of each
    is the same window: one per-recording z-scored (for most features), one in
    raw microvolts (filtered + CAR, pre-normalization) for the blink peak
    features.

    Args:
        recording: Recording metadata from the loader.

    Returns:
        Tuple ``(norm_epochs, uv_epochs)`` each ``(n_epochs, n_channels,
        n_samples)`` in volts. Both empty (shape ``(0, ...)``) if every epoch
        was rejected or the recording is too short.
    """
    raw = load_raw(recording)
    print(f"[preproc] {recording.session}/{recording.path.name} "
          f"(label {recording.label} {recording.class_name})")

    dur = raw.times[-1]
    if dur <= cfg.CROP_SECONDS:
        print(f"    [WARN] recording is {dur:.1f}s <= crop {cfg.CROP_SECONDS}s; "
              f"nothing left after cropping")
        n_ch = len(raw.ch_names)
        n_samp = int(round(cfg.EPOCH_SEC * cfg.SFREQ))
        empty = np.empty((0, n_ch, n_samp))
        return empty, empty.copy()

    raw.crop(tmin=cfg.CROP_SECONDS)
    print(f"    crops: skipped first {cfg.CROP_SECONDS}s "
          f"(kept {raw.times[-1]:.1f}s)")

    filter_and_car(raw, verbose=True)

    # Reject on the real-microvolt signal (the 500 µV threshold only makes
    # sense before normalization), then normalize and re-epoch, applying the
    # same keep-mask so the epoch set is identical.
    data_uv = _epoch_array(raw)
    n_before = data_uv.shape[0]
    _, keep = _reject_epochs(data_uv)

    normalize_per_recording(raw)
    print("    normalized: per-recording per-channel z-score")
    data_norm = _epoch_array(raw)

    kept_norm = data_norm[keep]
    kept_uv = data_uv[keep]
    n_after = kept_norm.shape[0]
    n_rej = n_before - n_after
    print(f"    epochs: {n_before} before -> {n_after} after rejection "
          f"({n_rej} dropped, >{cfg.REJECT_UV} µV)")
    return kept_norm, kept_uv


def preprocess_recording(recording: Recording) -> np.ndarray:
    """Run the full Stage-2 pipeline on one recording (z-scored epochs only).

    Args:
        recording: Recording metadata from the loader.

    Returns:
        Kept epochs as an array ``(n_epochs, n_channels, n_samples)`` in volts.
        May be empty (shape ``(0, ...)``) if every epoch was rejected.
    """
    kept_norm, _kept_uv = preprocess_recording_dual(recording)
    return kept_norm


def preprocess_all_dual(
    recordings: list[Recording],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Preprocess recordings, stacking BOTH z-scored and raw-µV epochs.

    Args:
        recordings: Recordings discovered by the loader.

    Returns:
        Tuple ``(X, X_uv, y, groups)`` where ``X`` is the z-scored stack and
        ``X_uv`` the matching raw-µV stack (same rows), ``y`` the integer label
        vector, and ``groups`` the per-epoch recording index.
    """
    x_parts: list[np.ndarray] = []
    xuv_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    g_parts: list[np.ndarray] = []
    for gid, rec in enumerate(recordings):
        epochs, epochs_uv = preprocess_recording_dual(rec)
        if epochs.shape[0] == 0:
            continue
        x_parts.append(epochs)
        xuv_parts.append(epochs_uv)
        y_parts.append(np.full(epochs.shape[0], rec.label, dtype=int))
        g_parts.append(np.full(epochs.shape[0], gid, dtype=int))

    if not x_parts:
        raise RuntimeError("No epochs survived preprocessing across all recordings.")

    x = np.concatenate(x_parts, axis=0)
    x_uv = np.concatenate(xuv_parts, axis=0)
    y = np.concatenate(y_parts, axis=0)
    groups = np.concatenate(g_parts, axis=0)
    print(f"[preproc] total epochs: {x.shape[0]} "
          f"(shape {x.shape}), labels {np.bincount(y)}, "
          f"{len(np.unique(groups))} recording groups")
    return x, x_uv, y, groups


def preprocess_all(
    recordings: list[Recording],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Preprocess a list of recordings and stack epochs with labels and groups.

    Args:
        recordings: Recordings discovered by the loader.

    Returns:
        Tuple ``(X, y, groups)`` where ``X`` has shape
        ``(total_epochs, n_channels, n_samples)``, ``y`` is the matching integer
        label vector, and ``groups`` is a per-epoch recording index (so
        group-aware CV never splits one recording across train and test).
    """
    x, _x_uv, y, groups = preprocess_all_dual(recordings)
    return x, y, groups


if __name__ == "__main__":
    from eeg_bci.loader import discover_recordings

    recs = discover_recordings()
    X, Y, G = preprocess_all(recs)
    print("X", X.shape, "y", Y.shape, "groups", G.shape)
