"""Evaluate the trained model on the held-out Random session via its markers CSV.

Train = Session1 + Session2 (already saved to ``config.MODEL_PATH``).
Test  = the Random recording, scored marker-by-marker:

    1. Load RANDOM.EDF, reorder to the canonical montage.
    2. Preprocess the full signal: notch -> bandpass -> CAR (NO 40 s crop).
    3. Per-recording z-score normalize (same as training).
    4. For each of the 45 markers, slice the exact 2 s epoch at ``time_sec``,
       extract the same feature set, and predict with the loaded pipeline.
    5. Map the marker's ``signal_name`` to a ground-truth class and compare.
"""

from __future__ import annotations

import csv
from pathlib import Path

import joblib
import numpy as np
import mne
from scipy.signal import find_peaks

from eeg_bci import config as cfg
from eeg_bci.features import extract_epoch
from eeg_bci.preprocessing import filter_and_car, normalize_per_recording

mne.set_log_level("ERROR")

# Trial period (Cue 1s + Action 2s + Rest 1s) used as a structural prior.
_TRIAL_PERIOD_SEC = 4.0
# Muscle vs blink signal-name groups, for alignment validation.
_MUSCLE = {"jaw_clench_both", "jaw_clench_left", "jaw_clench_right",
           "bruxism_both", "bruxism_left", "bruxism_right"}

# Random-session marker signal names -> class label.
SIGNAL_TO_CLASS = {
    "single_blink":     1,
    "double_blink":     0,
    "triple_blink":     1,
    "jaw_clench_both":  2,
    "jaw_clench_left":  2,
    "jaw_clench_right": 2,
    "bruxism_both":     2,
    "bruxism_left":     3,
    "bruxism_right":    4,
}

_RANDOM_DIR = Path(cfg.DATA_ROOT) / "Random"
_RANDOM_EDF = _RANDOM_DIR / "RANDOM.EDF"
_RANDOM_CSV = _RANDOM_DIR / "S0040_MIX_test_R01_20260602_142203_markers.csv"


def _load_markers(csv_path: Path) -> list[dict]:
    """Read accepted markers from the Random-session CSV.

    Args:
        csv_path: Path to the markers CSV.

    Returns:
        List of marker dicts with parsed ``time_sec`` / ``trial`` / ``signal``.
    """
    markers: list[dict] = []
    with open(csv_path, newline="") as fh:
        for row in csv.DictReader(fh):
            markers.append({
                "trial": int(row["trial_num"]),
                "time": float(row["time_sec"]),
                "signal": row["signal_name"],
            })
    return markers


def _prepare_signal(edf_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load + preprocess the Random EDF.

    Applies notch -> bandpass -> CAR (no crop). Returns BOTH the microvolt
    signal (for amplitude-based burst detection) and the per-recording
    z-scored signal (for feature extraction, matching training).

    Args:
        edf_path: Path to RANDOM.EDF.

    Returns:
        Tuple ``(uv_data, norm_data)`` each ``(n_channels, n_samples)`` ordered
        as ``config.ALL_CH``.
    """
    raw = mne.io.read_raw_edf(edf_path, preload=True, verbose="ERROR")
    present = [ch for ch in cfg.ALL_CH if ch in raw.ch_names]
    raw.reorder_channels(present)
    filter_and_car(raw, verbose=True)
    uv_data = raw.get_data() * 1e6
    normalize_per_recording(raw)
    print("    normalized: per-recording per-channel z-score (no 40s crop)")
    return uv_data, raw.get_data()


def detect_onsets(uv_data: np.ndarray, n_expected: int) -> np.ndarray:
    """Detect gesture-burst centers by amplitude (clock-independent alignment).

    The marker CSV timestamps do not align to the EDF clock, but the recording
    is periodic (~4 s/trial). We detect the ``n_expected`` activity bursts and
    pair them, in time order, with the CSV's (still-valid) label order. Falls
    back to a periodic 4 s grid if the peak count differs from ``n_expected``.

    Args:
        uv_data: Microvolt signal ``(n_channels, n_samples)``.
        n_expected: Number of trials expected (rows in the markers CSV).

    Returns:
        Sorted array of burst-center sample indices (length ``n_expected``).
    """
    sf = cfg.SFREQ
    env = np.mean(np.abs(uv_data), axis=0)
    win = int(0.5 * sf)
    env = np.convolve(env, np.ones(win) / win, mode="same")

    peaks, _ = find_peaks(
        env, height=np.percentile(env, 60), distance=int(2.5 * sf),
    )
    if len(peaks) == n_expected:
        print(f"    detected {len(peaks)} bursts (matches {n_expected} trials)")
        return np.sort(peaks)

    # Fallback: periodic grid with the phase that maximizes burst energy.
    print(f"    detected {len(peaks)} bursts != {n_expected}; "
          f"using periodic {_TRIAL_PERIOD_SEC}s grid")
    n_samp = int(round(cfg.EPOCH_SEC * sf))
    best_phi, best_score = 0.0, -1.0
    for phi in np.arange(0, _TRIAL_PERIOD_SEC, 0.05):
        starts = [int((k * _TRIAL_PERIOD_SEC + phi) * sf) for k in range(n_expected)]
        score = np.mean([
            env[s:s + n_samp].mean()
            for s in starts if s + n_samp <= len(env)
        ])
        if score > best_score:
            best_score, best_phi = score, phi
    centers = [int((k * _TRIAL_PERIOD_SEC + best_phi) * sf) + n_samp // 2
               for k in range(n_expected)]
    return np.array(sorted(min(c, uv_data.shape[1] - 1) for c in centers))


def _epoch_centered(data: np.ndarray, center: int) -> np.ndarray:
    """Slice a 2 s epoch centered on a sample index (clamped to bounds).

    Args:
        data: Full signal ``(n_channels, n_samples)``.
        center: Center sample index of the burst.

    Returns:
        Epoch array ``(n_channels, EPOCH_SEC * SFREQ)``.
    """
    n_samp = int(round(cfg.EPOCH_SEC * cfg.SFREQ))
    total = data.shape[1]
    start = center - n_samp // 2
    start = max(0, min(start, total - n_samp))
    return data[:, start:start + n_samp]


def _alignment_confidence(uv_data: np.ndarray, centers: np.ndarray,
                          markers: list[dict]) -> float:
    """Sanity-check order alignment: muscle bursts should out-energize blinks.

    Args:
        uv_data: Microvolt signal.
        centers: Detected burst centers (time order).
        markers: Markers in CSV (label) order.

    Returns:
        Ratio of median temporal peak-to-peak (muscle / blink). >1 supports the
        order pairing; ~1 means the alignment is unreliable.
    """
    t_idx = [cfg.ALL_CH.index("T3-Ref"), cfg.ALL_CH.index("T4-Ref")]
    musc, blink = [], []
    for k, m in enumerate(markers):
        if k >= len(centers):
            break
        ep = _epoch_centered(uv_data, centers[k])
        ptp = float(np.ptp(ep[t_idx]))
        (musc if m["signal"] in _MUSCLE else blink).append(ptp)
    if not musc or not blink:
        return float("nan")
    return float(np.median(musc) / (np.median(blink) + 1e-9))


def evaluate_random() -> None:
    """Run the order-aligned Random-session evaluation and print result tables."""
    print(f"[eval] loading model: {cfg.MODEL_PATH}")
    pipeline = joblib.load(cfg.MODEL_PATH)

    print(f"[eval] preprocessing {_RANDOM_EDF}")
    uv_data, norm_data = _prepare_signal(_RANDOM_EDF)
    markers = _load_markers(_RANDOM_CSV)
    print(f"[eval] {len(markers)} markers loaded (used for label ORDER only - "
          f"CSV timestamps do not align to the EDF clock)")

    centers = detect_onsets(uv_data, n_expected=len(markers))
    conf = _alignment_confidence(uv_data, centers, markers)
    print(f"[eval] alignment confidence (muscle/blink temporal ptp): {conf:.2f} "
          f"({'ok' if conf > 1.3 else 'WEAK - results uncertain'})\n")

    labels = sorted(cfg.COMMAND_MAP)
    trials = {l: 0 for l in labels}
    correct = {l: 0 for l in labels}
    confusion = np.zeros((len(labels), len(labels)), dtype=int)

    header = f"{'Trial':>5}  {'Burst':>7}  {'Signal':<18}  {'GT':<4} {'Pred':<5} Match"
    print(header)
    print("─" * len(header))

    for k, m in enumerate(markers):
        gt = SIGNAL_TO_CLASS[m["signal"]]
        center = int(centers[k]) if k < len(centers) else norm_data.shape[1] // 2
        epoch = _epoch_centered(norm_data, center)
        # uv_data is already in µV; extract_epoch expects volts, so scale back.
        epoch_uv = _epoch_centered(uv_data, center) / 1e6
        feat = extract_epoch(epoch, epoch_uv).reshape(1, -1)
        pred = int(pipeline.predict(feat)[0])

        gt_char = cfg.COMMAND_MAP[gt][0]
        pred_char = cfg.COMMAND_MAP[pred][0]
        ok = pred == gt
        mark = "✓" if ok else "✗"
        print(f"{m['trial']:>5}  {center / cfg.SFREQ:>6.1f}s  {m['signal']:<18}  "
              f"{gt_char:<4} {pred_char:<5} {mark}")

        trials[gt] += 1
        correct[gt] += ok
        confusion[labels.index(gt), labels.index(pred)] += 1

    _print_summary(labels, trials, correct)
    _print_confusion(labels, confusion)


def _print_summary(labels, trials, correct) -> None:
    """Print the final per-command accuracy table.

    Args:
        labels: Sorted class labels.
        trials: Trials-per-class tally.
        correct: Correct-per-class tally.
    """
    print("\n" + "═" * 54)
    print(" FINAL — Train: Session1+2 → Test: Random (45 trials)")
    print("═" * 54)
    print(f" {'Command':<10}{'Trials':>8}{'Correct':>10}{'Accuracy':>11}")
    names = {0: "S (start)", 1: "O (open )", 2: "C (close)",
             3: "L (left )", 4: "R (right)"}
    for l in labels:
        n, c = trials[l], correct[l]
        acc = 100.0 * c / n if n else 0.0
        print(f" {names[l]:<10}{n:>8}{c:>10}{acc:>10.1f}%")
    tot_n = sum(trials.values())
    tot_c = sum(correct.values())
    tot_acc = 100.0 * tot_c / tot_n if tot_n else 0.0
    print("─" * 54)
    print(f" {'Overall':<10}{tot_n:>8}{tot_c:>10}{tot_acc:>10.1f}%")
    print("═" * 54)


def _print_confusion(labels, confusion) -> None:
    """Print the confusion matrix (rows = ground truth, cols = predicted).

    Args:
        labels: Sorted class labels.
        confusion: Integer confusion matrix.
    """
    chars = [cfg.COMMAND_MAP[l][0] for l in labels]
    print("\n Confusion matrix (rows=GT, cols=Pred)")
    print("        " + "".join(f"{c:>5}" for c in chars))
    for i, l in enumerate(labels):
        row = "".join(f"{confusion[i, j]:>5}" for j in range(len(labels)))
        print(f"   {chars[i]:<4}{row}")


if __name__ == "__main__":
    evaluate_random()
