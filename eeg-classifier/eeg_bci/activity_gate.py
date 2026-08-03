"""Activity-gated epoching: drop rest-period epochs that contain no gesture.

The recordings are gesture-then-rest sequences, but the sliding-window epoching
labels EVERY 2 s window with the recording's class -- including the rest windows
between gestures. A rest window from the double-blink recording is then identical
to a rest window from the triple-blink recording, yet they carry different labels
=> label noise that caps S<->T and the muscle confusions.

This module scores each epoch by the peak-to-peak amplitude (µV) of its
gesture-relevant channels (frontal Fp1/Fp2 for blinks, temporal T3/T4 for jaw
gestures) and gates out the low-activity "rest" epochs. Gating is RECORDING-
RELATIVE (a fraction of each recording's own active level) so it adapts to each
gesture's amplitude and to electrode differences across sessions.
"""

from __future__ import annotations

import numpy as np

from eeg_bci import config as cfg

_V_TO_UV = 1e6

# Gesture-relevant channels per class label.
_BLINK_LABELS = {0, 1}              # double / single blink -> frontal (EOG)
_JAW_LABELS = {2, 3, 4}             # clinch / bruxism L / R -> temporal (EMG)
_FRONTAL_IDX = [cfg.ALL_CH.index(c) for c in ("Fp1-Ref", "Fp2-Ref")]
_TEMPORAL_IDX = [cfg.ALL_CH.index(c) for c in ("T3-Ref", "T4-Ref")]


def relevant_idx(label: int) -> list[int]:
    """Channel indices whose activity defines 'gesture present' for a class."""
    return _FRONTAL_IDX if label in _BLINK_LABELS else _TEMPORAL_IDX


def epoch_activity(epoch_uv: np.ndarray, label: int) -> float:
    """Peak-to-peak amplitude (µV) over the gesture-relevant channels."""
    sig = epoch_uv[relevant_idx(label)] * _V_TO_UV
    return float(np.max(np.ptp(sig, axis=1)))


def activity_scores(epochs_uv: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per-epoch activity (µV ptp on relevant channels)."""
    return np.array([epoch_activity(epochs_uv[i], int(y[i]))
                     for i in range(epochs_uv.shape[0])])


def gate_mask(
    scores: np.ndarray, y: np.ndarray, groups: np.ndarray, *, frac: float = 0.5
) -> np.ndarray:
    """Keep epochs whose activity exceeds ``frac`` * (that recording's 90th pct).

    Recording-relative so the threshold tracks each gesture's own amplitude.

    Args:
        scores: Per-epoch activity (µV).
        y: Labels (unused except for shape; kept for symmetry/clarity).
        groups: Per-epoch recording index.
        frac: Fraction of each recording's 90th-percentile activity to require.

    Returns:
        Boolean keep-mask (True = active gesture epoch).
    """
    keep = np.zeros(scores.shape[0], dtype=bool)
    for g in np.unique(groups):
        m = groups == g
        thr = frac * np.percentile(scores[m], 90)
        keep[m] = scores[m] >= thr
    return keep
