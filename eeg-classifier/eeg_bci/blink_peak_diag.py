"""Diagnostic: test the blink-peak hypothesis in the RAW microvolt domain.

The Step-2 viz detected peaks on the z-scored signal (the only thing feature
extraction normally sees) and the hypothesis failed. Before concluding the
hypothesis is wrong, re-test it in the domain the user actually specified:
the filtered + CAR signal in microvolts, BEFORE per-recording z-scoring -- with
the user's literal thresholds (height=50 µV, prominence=30 µV, distance=150 ms).

If double_blink shows ~2 peaks and muscle classes ~0 here, the hypothesis is
REAL and the bug is that z-scoring destroys it (=> compute blink features from
un-normalized epochs). If it still fails here, the hypothesis is genuinely not
supported by these 2 s epochs.
"""

from __future__ import annotations

import numpy as np
import mne
from scipy.signal import find_peaks

from eeg_bci import config as cfg
from eeg_bci.loader import discover_recordings, load_raw
from eeg_bci.preprocessing import filter_and_car

mne.set_log_level("ERROR")

_SESSIONS = ("Session1", "Session2")
_HEIGHT_UV = 50.0
_PROM_UV = 30.0
_DIST_SEC = 0.15
_V_TO_UV = 1e6


def _class_name(label: int) -> str:
    for lbl, name in cfg.LABEL_MAP.values():
        if lbl == label:
            return name
    return cfg.COMMAND_MAP[label][1]


def _epoch_uv(raw: mne.io.BaseRaw) -> np.ndarray:
    """Filtered+CAR epochs in microvolts (no z-score), shape (n_ep, n_ch, n_s)."""
    overlap = cfg.EPOCH_SEC * cfg.EPOCH_OVERLAP
    ep = mne.make_fixed_length_epochs(
        raw, duration=cfg.EPOCH_SEC, overlap=overlap, preload=True, verbose="ERROR")
    return ep.get_data(copy=True) * _V_TO_UV


def _count(sig_uv: np.ndarray, mode: str) -> int:
    """Count peaks in µV with the user's thresholds. mode: pos|neg|abs."""
    x = {"pos": sig_uv, "neg": -sig_uv, "abs": np.abs(sig_uv)}[mode]
    peaks, _ = find_peaks(
        x, height=_HEIGHT_UV, prominence=_PROM_UV,
        distance=max(1, int(_DIST_SEC * cfg.SFREQ)))
    return len(peaks)


def run_diag() -> None:
    recs = [r for r in discover_recordings() if r.session in _SESSIONS]
    i_fp1 = cfg.ALL_CH.index("Fp1-Ref")
    i_fp2 = cfg.ALL_CH.index("Fp2-Ref")

    # Accumulate per-class peak counts and frontal ptp, per polarity mode.
    by_label: dict[int, dict] = {}
    for rec in recs:
        raw = load_raw(rec)
        if raw.times[-1] <= cfg.CROP_SECONDS:
            continue
        raw.crop(tmin=cfg.CROP_SECONDS)
        filter_and_car(raw)
        data = _epoch_uv(raw)                      # (n_ep, n_ch, n_s) µV
        d = by_label.setdefault(rec.label, {
            "n": 0, "pos": [], "neg": [], "abs": [], "ptp": []})
        for ep in data:
            f1, f2 = ep[i_fp1], ep[i_fp2]
            d["n"] += 1
            for mode in ("pos", "neg", "abs"):
                d[mode].append((_count(f1, mode) + _count(f2, mode)) / 2.0)
            d["ptp"].append((np.ptp(f1) + np.ptp(f2)) / 2.0)

    print("\n" + "═" * 78)
    print(" Diagnostic — avg frontal peaks per class in RAW µV "
          f"(height={_HEIGHT_UV}µV, prom={_PROM_UV}µV)")
    print("═" * 78)
    print(f" {'Class':<15}{'pos-peaks':>11}{'neg-peaks':>11}{'abs-peaks':>11}"
          f"{'frontal ptp µV':>16}{'epochs':>8}")
    print("─" * 78)
    for label in sorted(by_label):
        d = by_label[label]
        note = ""
        nm = _class_name(label)
        if nm == "double_blink":
            note = " <-~2?"
        elif nm in ("clinch", "bruxism_left", "bruxism_right"):
            note = " <-~0?"
        print(f" {nm:<15}{np.mean(d['pos']):>11.2f}{np.mean(d['neg']):>11.2f}"
              f"{np.mean(d['abs']):>11.2f}{np.mean(d['ptp']):>16.1f}"
              f"{d['n']:>8}{note}")
    print("═" * 78)


if __name__ == "__main__":
    run_diag()
