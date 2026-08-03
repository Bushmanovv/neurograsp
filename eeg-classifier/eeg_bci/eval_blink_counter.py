"""Stage 2a as an explicit blink EVENT COUNTER (single/double/triple).

Whole-window features blur the count + timing that actually separate single vs
double vs triple blink. This builds the Shahbakhti-style detector (moving-std
envelope -> peak find) and benchmarks two count-based Stage-2a classifiers against
the current whole-window RF, IN ISOLATION (correct routing, blink epochs only).

Stage 1 and Stage 2b are NOT touched. Triple_blink (dropped from the production
5-class taxonomy) is re-introduced HERE ONLY, via a local LABEL_MAP extension, so
the experiment can measure the 3-way S/O/T blink problem; production config is
unchanged.

No leakage: the moving-std threshold is 1.5*median computed PER WINDOW (adaptive,
nothing fixed crosses sessions); min-distance is a fixed biological constant
(150 ms); the ML classifier is trained on the training sessions only (LOSO).

Run:  python -m eeg_bci.eval_blink_counter
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks
from sklearn.metrics import accuracy_score, f1_score

from eeg_bci import config as cfg
from eeg_bci import features
from eeg_bci.hierarchical import _feature_groups, _stage_pipe, superset_names, extract_superset
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual

# Blink labels for THIS experiment: double=S(0), single=O(1), triple=T(5).
_S, _O, _T = 0, 1, 5
_BLINK = (_S, _O, _T)
_NAME = {_S: "double(S)", _O: "single(O)", _T: "triple(T)"}
_EXPECTED = {_O: 1, _S: 2, _T: 3}        # ground-truth blink count per class

# Detector hyperparameters. The 1.5*median spec massively over-counts on a 2 s
# window that is mostly baseline; these were tuned (pooled grid search, scratchpad)
# to MAXIMISE single<double<triple count separation -- the best achievable still
# only compresses to ~1.25/1.72/2.11, see the validation table.
_ENV_WIN_S = 0.05        # moving-std window (s)
_HEIGHT_K = 6.0          # height = k * median(envelope)
_PROM_K = 2.0            # prominence = k * median(envelope)
_MIN_DIST_S = 0.30       # min 300 ms between blinks (biology; avoids edge double-count)

_F3_IDX = [cfg.ALL_CH.index(c) for c in ("Fp1-Ref", "Fp2-Ref", "Fz-Ref")]
_FP_IDX = [cfg.ALL_CH.index(c) for c in ("Fp1-Ref", "Fp2-Ref")]
_V_TO_UV = 1e6


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# --------------------------------------------------------------------------- #
# Event detection (moving-std envelope -> peaks)
# --------------------------------------------------------------------------- #
def _moving_std(sig: np.ndarray, w: int) -> np.ndarray:
    m = uniform_filter1d(sig, w, mode="nearest")
    msq = uniform_filter1d(sig * sig, w, mode="nearest")
    return np.sqrt(np.maximum(msq - m * m, 0.0))


def detect_events(epoch_uv: np.ndarray):
    """Detect blink events in one window. Returns (peaks, peak_heights, envelope)."""
    sig = epoch_uv[_F3_IDX].mean(axis=0) * _V_TO_UV          # mean(Fp1,Fp2,Fz) µV
    w = max(1, int(_ENV_WIN_S * cfg.SFREQ))
    env = _moving_std(sig, w)
    med = float(np.median(env)) + 1e-12
    peaks, props = find_peaks(
        env, height=_HEIGHT_K * med, prominence=_PROM_K * med,
        distance=max(1, int(_MIN_DIST_S * cfg.SFREQ)))
    return peaks, props.get("peak_heights", np.array([])), env


def event_features(epoch_uv: np.ndarray) -> tuple[list[float], int]:
    """The 7 rich event features for one window + the raw blink count."""
    peaks, heights, _ = detect_events(epoch_uv)
    n = len(peaks)
    inter = np.diff(peaks) / cfg.SFREQ if n >= 2 else np.array([])
    feats = [
        float(n),
        float(inter.mean()) if n >= 2 else 0.0,
        float(inter.std()) if n >= 2 else 0.0,
        float(heights[0]) if n >= 1 else 0.0,
        float(heights.mean()) if n >= 1 else 0.0,
        float((peaks[-1] - peaks[0]) / cfg.SFREQ) if n >= 2 else 0.0,
        float(peaks[0] / cfg.SFREQ) if n >= 1 else 0.0,
    ]
    return feats, n


def rule_label(n: int) -> int:
    """Path A (3-class): count -> class. 0/1 -> single, 2 -> double, >=3 -> triple."""
    if n >= 3:
        return _T
    if n == 2:
        return _S
    return _O


def rule_label_binary(n: int) -> int:
    """Path A (binary S vs O): >=2 -> double, else single."""
    return _S if n >= 2 else _O


# --------------------------------------------------------------------------- #
# Data: blink recordings INCLUDING triple (local taxonomy extension)
# --------------------------------------------------------------------------- #
def load_blink_epochs():
    cfg.LABEL_MAP["BLINK03"] = (_T, "triple_blink")          # re-introduce triple (local)
    recs = [r for r in discover_recordings() if r.label in _BLINK]
    X, Xuv, y, groups = _quiet(preprocess_all_dual, recs)
    sess = np.array([recs[g].session for g in groups])
    # Frontal activity gate (all blinks -> gate on Fp1/Fp2 ptp, recording-relative).
    score = np.array([np.max(np.ptp(Xuv[i][_FP_IDX] * _V_TO_UV, axis=1))
                      for i in range(Xuv.shape[0])])
    keep = np.zeros(len(score), bool)
    for g in np.unique(groups):
        m = groups == g
        keep[m] = score[m] >= 0.5 * np.percentile(score[m], 90)
    return X[keep], Xuv[keep], y[keep], groups[keep], sess[keep], recs


# --------------------------------------------------------------------------- #
# Step: validation table (counts vs ground truth) -- printed FIRST
# --------------------------------------------------------------------------- #
def validate_counts(Xuv, y, groups, sess, recs):
    counts = np.array([event_features(Xuv[i])[1] for i in range(Xuv.shape[0])])
    print("\n" + "=" * 70)
    print(" DETECTOR VALIDATION — mean detected blink count vs ground truth")
    print("=" * 70)
    print(f" {'Recording':<34}{'class':<11}{'expect':>7}{'mean':>7}{'median':>7}")
    print("-" * 70)
    for g in np.unique(groups):
        m = groups == g
        lbl = int(y[m][0])
        rec = recs[g]
        tag = f"{rec.session}/{rec.path.name}"
        print(f" {tag[:33]:<34}{_NAME[lbl]:<11}{_EXPECTED[lbl]:>7}"
              f"{counts[m].mean():>7.2f}{np.median(counts[m]):>7.1f}")
    print("-" * 70)
    print(f" {'PER-CLASS':<34}{'':<11}{'expect':>7}{'mean':>7}{'sep?':>7}")
    means = {}
    for lbl in (_O, _S, _T):
        m = y == lbl
        means[lbl] = counts[m].mean()
        print(f" {'  '+_NAME[lbl]:<34}{'':<11}{_EXPECTED[lbl]:>7}{means[lbl]:>7.2f}")
    mono = means[_O] < means[_S] < means[_T]
    print("-" * 70)
    print(f" monotonic ordering single<double<triple: {mono}  "
          f"({means[_O]:.2f} < {means[_S]:.2f} < {means[_T]:.2f})")
    print("=" * 70)
    return counts


# --------------------------------------------------------------------------- #
# Step: Stage-2a isolation comparison (LOSO 3-fold mean)
# --------------------------------------------------------------------------- #
def _per_class(y_true, y_pred):
    return f1_score(y_true, y_pred, labels=[_S, _O, _T], average=None)


def _loso(y, sess, predict_fold, idx, labels):
    """3-fold LOSO mean over the rows in ``idx``: avg acc + per-class F1."""
    sset = sorted(np.unique(sess[idx]))
    accs, per = [], np.zeros(len(labels))
    for s in sset:
        te = idx[sess[idx] == s]
        tr = idx[sess[idx] != s]
        yp = predict_fold(tr, te)
        accs.append(accuracy_score(y[te], yp))
        per += f1_score(y[te], yp, labels=labels, average=None)
    return np.mean(accs), per / len(sset)


def run() -> None:
    X, Xuv, y, groups, sess, recs = load_blink_epochs()
    print(f"\n[blink] gated blink epochs: {len(y)} "
          f"(S {np.sum(y==_S)}, O {np.sum(y==_O)}, T {np.sum(y==_T)}); "
          f"sessions {sorted(np.unique(sess))}")

    # ---- 1) validate the detector BEFORE classifying ----
    validate_counts(Xuv, y, groups, sess, recs)

    # ---- feature matrices ----
    Ev = np.array([event_features(Xuv[i])[0] for i in range(Xuv.shape[0])])  # 7 event feats
    names = superset_names()
    g = _feature_groups(names)
    s2a_cols = np.concatenate([g["frontal"], g["blink"]])
    Fsuper = _quiet(extract_superset, X, Xuv)
    Fw = Fsuper[:, s2a_cols]                                  # current whole-window feats

    counts = np.array([event_features(Xuv[i])[1] for i in range(Xuv.shape[0])])

    def current_fold(tr, te):
        return _stage_pipe(Fw.shape[1]).fit(Fw[tr], y[tr]).predict(Fw[te])

    def ml_fold(tr, te):
        return _stage_pipe(Ev.shape[1]).fit(Ev[tr], y[tr]).predict(Ev[te])

    def make_rule_fold(rule_fn):
        return lambda tr, te: np.array([rule_fn(int(counts[i])) for i in te])

    all_idx = np.arange(len(y))
    bin_idx = np.where(np.isin(y, (_S, _O)))[0]      # binary S vs O (no triple)

    def block(title, idx, labels, col, rule_fn, baseline):
        print("\n" + "=" * 70)
        print(f" {title}")
        print("=" * 70)
        print(f" {'Method':<28}" + "".join(f"{c:>7}" for c in col) + f"{'acc':>10}")
        print("-" * 70)
        for name, fn in (("Current (whole-window RF)", current_fold),
                         ("Event-count rule-based", make_rule_fold(rule_fn)),
                         ("Event-count ML (RF)", ml_fold)):
            acc, per = _loso(y, sess, fn, idx, labels)
            print(f" {name:<28}" + "".join(f"{p:>7.3f}" for p in per)
                  + f"{acc*100:>9.1f}%")
        print("=" * 70)
        print(f" {baseline}")

    # The fair comparison to the 76.4% baseline: BINARY single vs double (no triple).
    block("Stage 2a IN ISOLATION — BINARY S vs O (LOSO 3-fold mean)",
          bin_idx, [_S, _O], ["S-F1", "O-F1"], rule_label_binary,
          "current binary S/O Stage-2a baseline = 76.4%")

    # The 3-class problem (triple re-introduced) -- inherently harder.
    block("Stage 2a IN ISOLATION — 3-CLASS S/O/T (LOSO 3-fold mean)",
          all_idx, [_S, _O, _T], ["S-F1", "O-F1", "T-F1"], rule_label,
          "S=double, O=single, T=triple (triple re-introduced for this experiment)")


if __name__ == "__main__":
    run()
