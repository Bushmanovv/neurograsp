"""Step 1 (v2) - validate blink peak counting on the RAW µV signal, 6 classes.

The last attempt failed for two reasons now both addressed:
  1. peaks were counted on the z-scored signal -> count on raw µV instead;
  2. the single class pooled BLINK01+BLINK03 -> classes are now pure (triple is
     its own class).

For every training epoch (crop -> filter -> CAR -> 500 µV reject, but kept in
microvolts, NOT z-scored) this counts positive peaks on Fp1-Ref / Fp2-Ref with
the new thresholds, and reports the per-class averages. Polarity is also checked
(neg/abs) because a blink can be negative-going under common-average reference.

Gate: if double_blink ~ 2 peaks AND triple_blink ~ 3 peaks (and clearly ordered
single < double < triple) -> proceed to retrain. Otherwise report and stop.
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
_V_TO_UV = 1e6

# New thresholds (raw µV domain).
PEAK_HEIGHT_UV = 40.0
PEAK_PROM_UV = 25.0
PEAK_DIST_SEC = 0.20


def _class_name(label: int) -> str:
    for lbl, name in cfg.LABEL_MAP.values():
        if lbl == label:
            return name
    return cfg.COMMAND_MAP[label][1]


def _uv_epochs(rec) -> np.ndarray:
    """Training epochs for one recording, kept in µV (crop/filter/CAR/reject)."""
    raw = load_raw(rec)
    if raw.times[-1] <= cfg.CROP_SECONDS:
        return np.empty((0, len(raw.ch_names), int(cfg.EPOCH_SEC * cfg.SFREQ)))
    raw.crop(tmin=cfg.CROP_SECONDS)
    filter_and_car(raw)
    overlap = cfg.EPOCH_SEC * cfg.EPOCH_OVERLAP
    ep = mne.make_fixed_length_epochs(
        raw, duration=cfg.EPOCH_SEC, overlap=overlap, preload=True,
        verbose="ERROR").get_data(copy=True)            # volts
    data_uv = ep * _V_TO_UV
    peak = np.max(np.abs(data_uv), axis=(1, 2))          # same reject as training
    return data_uv[peak <= cfg.REJECT_UV]


def _peaks(sig_uv: np.ndarray, mode: str = "pos"):
    """Return (n_peaks, ipi_sec_array, peak_amp_mean) in µV. mode: pos|neg|abs."""
    x = {"pos": sig_uv, "neg": -sig_uv, "abs": np.abs(sig_uv)}[mode]
    peaks, props = find_peaks(
        x, height=PEAK_HEIGHT_UV, prominence=PEAK_PROM_UV,
        distance=max(1, int(PEAK_DIST_SEC * cfg.SFREQ)))
    ipi = np.diff(peaks) / cfg.SFREQ if len(peaks) >= 2 else np.empty(0)
    amp = float(np.mean(props["peak_heights"])) if len(peaks) else 0.0
    return len(peaks), ipi, amp


def run_viz() -> bool:
    recs = [r for r in discover_recordings() if r.session in _SESSIONS]
    i_fp1, i_fp2 = cfg.ALL_CH.index("Fp1-Ref"), cfg.ALL_CH.index("Fp2-Ref")

    agg: dict[int, dict] = {}
    for rec in recs:
        for ep in _uv_epochs(rec):
            d = agg.setdefault(rec.label, {
                "n": 0, "fp1": [], "fp2": [], "ipi": [], "amp": [],
                "fp1_abs": [], "fp2_abs": []})
            n1, ipi1, a1 = _peaks(ep[i_fp1], "pos")
            n2, ipi2, a2 = _peaks(ep[i_fp2], "pos")
            d["n"] += 1
            d["fp1"].append(n1)
            d["fp2"].append(n2)
            d["amp"].append((a1 + a2) / 2.0)
            pooled = np.concatenate([ipi1, ipi2])
            d["ipi"].append(float(np.mean(pooled)) if pooled.size else 0.0)
            d["fp1_abs"].append(_peaks(ep[i_fp1], "abs")[0])
            d["fp2_abs"].append(_peaks(ep[i_fp2], "abs")[0])

    print(f"\n[v2viz] thresholds (raw µV): height={PEAK_HEIGHT_UV}, "
          f"prom={PEAK_PROM_UV}, distance={PEAK_DIST_SEC}s")
    print("\n" + "═" * 78)
    print(" Step 1 (v2) — avg blink peaks per class on RAW µV (positive-going)")
    print("═" * 78)
    print(f" {'Class':<15}{'fp1_n':>8}{'fp2_n':>8}{'ipi_mean':>10}"
          f"{'amp µV':>9}{'|abs|fp1':>10}{'|abs|fp2':>10}{'epochs':>8}")
    print("─" * 78)
    avg = {}
    for label in sorted(agg):
        d = agg[label]
        avg[label] = (np.mean(d["fp1"]) + np.mean(d["fp2"])) / 2.0
        print(f" {_class_name(label):<15}{np.mean(d['fp1']):>8.2f}"
              f"{np.mean(d['fp2']):>8.2f}{np.mean(d['ipi']):>10.3f}"
              f"{np.mean(d['amp']):>9.1f}{np.mean(d['fp1_abs']):>10.2f}"
              f"{np.mean(d['fp2_abs']):>10.2f}{d['n']:>8}")
    print("═" * 78)

    by_name = {_class_name(l): v for l, v in avg.items()}
    s, dbl, tri = (by_name["single_blink"], by_name["double_blink"],
                   by_name["triple_blink"])
    print(f"\n[v2viz] single={s:.2f}  double={dbl:.2f}  triple={tri:.2f}")
    ok = dbl >= 1.6 and tri >= 2.2 and s < dbl < tri
    if ok:
        print("[v2viz] GATE PASSED: double~2, triple~3, ordered -> retrain.")
    else:
        print("[v2viz] GATE FAILED: peak counts do not match double~2 / triple~3 "
              "ordering -> report and STOP (do not retrain).")
    return ok


if __name__ == "__main__":
    run_viz()
