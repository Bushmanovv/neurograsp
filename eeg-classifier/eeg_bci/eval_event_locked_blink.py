"""Attempt #4 at the blink ceiling: EVENT-LOCKED epoching for the blink branch.

Diagnosis from attempt #3 (eval_blink_counter.py): fixed 2 s sliding windows are
arbitrary slices of continuous repeated blinking, so per-window blink counts don't
map to single/double/triple. The fix tried here: detect each blink GESTURE on the
continuous signal (contiguous moving-std bursts, grouped within 700 ms), crop
TIGHTLY around it, then classify the one-gesture epoch.

ISOLATED EXPERIMENT — Stage 1 and Stage 2b (muscle) are NOT touched, production is
NOT modified, triple_blink is re-introduced via a LOCAL LABEL_MAP only.

Order (the user's gates):
  Step 2 VALIDATION is printed FIRST. If blinks-per-gesture does not separate
  single<double<triple with a clear gap, STOP -- it's a fundamental resolution
  limit, not fixable by epoching, and we keep the 89.2% hybrid.

No leakage: the burst threshold is per-recording adaptive (median + 3·MAD of that
recording's own envelope -- unsupervised, nothing fixed crosses sessions); the
classifier is LOSO (trained on the training sessions only). Detection uses a short
100 ms moving-std window -> causal-friendly (a trailing window works in real time).

Run:  python -m eeg_bci.eval_event_locked_blink
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from scipy.ndimage import uniform_filter1d
from sklearn.metrics import accuracy_score, f1_score

from eeg_bci import config as cfg
from eeg_bci import features
from eeg_bci.loader import discover_recordings, load_raw
from eeg_bci.preprocessing import filter_and_car

# Blink labels: double=S(0), single=O(1), triple=T(5).
_S, _O, _T = 0, 1, 5
_NAME = {_S: "double(S)", _O: "single(O)", _T: "triple(T)"}
_EXP = {_O: 1, _S: 2, _T: 3}

_F3 = [cfg.ALL_CH.index(c) for c in ("Fp1-Ref", "Fp2-Ref", "Fz-Ref")]
_V_TO_UV = 1e6

# Detector params (fixed, unsupervised).
_ENV_WIN_S = 0.10          # moving-std window (causal-friendly trailing window in RT)
_THR_K = 3.0               # threshold = median + k·MAD of the recording's envelope
_MIN_BURST_S = 0.05        # ignore sub-50 ms blips
_GROUP_GAP_S = 0.70        # bursts within 700 ms = one gesture
_PAD_S = 0.10              # tight-crop padding around the gesture


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _moving_std(sig, w):
    m = uniform_filter1d(sig, w, mode="nearest")
    msq = uniform_filter1d(sig * sig, w, mode="nearest")
    return np.sqrt(np.maximum(msq - m * m, 0.0))


def _contiguous(mask):
    d = np.diff(mask.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if mask[0]:
        starts = [0] + starts
    if mask[-1]:
        ends = ends + [len(mask)]
    return list(zip(starts, ends))


def detect_gestures(blink_uv, sfreq):
    """Detect blink gestures on the continuous frontal signal.

    Returns a list of dicts ``{start, end, n_bursts, bursts}`` (sample indices).
    """
    env = _moving_std(blink_uv, max(1, int(_ENV_WIN_S * sfreq)))
    med = float(np.median(env))
    mad = float(np.median(np.abs(env - med))) * 1.4826 + 1e-12
    mask = env > (med + _THR_K * mad)
    min_burst = max(1, int(_MIN_BURST_S * sfreq))
    bursts = [(s, e) for (s, e) in _contiguous(mask) if e - s >= min_burst]
    gap = int(_GROUP_GAP_S * sfreq)
    gestures = []
    for (s, e) in bursts:
        if gestures and s - gestures[-1]["end"] <= gap:
            gestures[-1]["end"] = e
            gestures[-1]["n_bursts"] += 1
            gestures[-1]["bursts"].append((s, e))
        else:
            gestures.append({"start": s, "end": e, "n_bursts": 1, "bursts": [(s, e)]})
    return gestures


def _event_feats(blink_uv, g, sfreq):
    bursts = g["bursts"]
    n = g["n_bursts"]
    centers = [(s + e) // 2 for (s, e) in bursts]
    ibi = np.diff(centers) / sfreq if n >= 2 else np.array([])
    amps = [float(np.max(np.abs(blink_uv[s:e]))) for (s, e) in bursts]
    return [
        float(n),
        (g["end"] - g["start"]) / sfreq,                 # gesture duration
        float(ibi.mean()) if n >= 2 else 0.0,
        float(ibi.std()) if n >= 2 else 0.0,
        amps[0],
        float(np.mean(amps)),
        float(np.max(amps)),
    ]


def load_continuous(rec):
    raw = load_raw(rec)
    if raw.times[-1] <= cfg.CROP_SECONDS:
        return None
    raw.crop(tmin=cfg.CROP_SECONDS)
    filter_and_car(raw)
    data_v = raw.get_data()
    mean = data_v.mean(axis=1, keepdims=True)
    std = data_v.std(axis=1, keepdims=True)
    return data_v * _V_TO_UV, (data_v - mean) / (std + 1e-8)


def build_dataset():
    """Detect gestures across all blink recordings -> per-gesture rows."""
    cfg.LABEL_MAP["BLINK03"] = (_T, "triple_blink")      # re-introduce triple (local)
    features.DWT_FEATURES = features.TKEO_FEATURES = features.EMG_DESCRIPTORS = False
    features.BLINK_PEAK_FEATURES = False                  # the existing 93 features
    recs = [r for r in discover_recordings() if r.label in (_S, _O, _T)]

    rows = []
    per_rec = []
    for rec in recs:
        out = _quiet(load_continuous, rec)
        if out is None:
            continue
        data_uv, data_z = out
        blink_uv = data_uv[_F3].mean(axis=0)
        gestures = detect_gestures(blink_uv, cfg.SFREQ)
        pad = int(_PAD_S * cfg.SFREQ)
        n_tot = data_uv.shape[1]
        nb = []
        for g in gestures:
            a = max(0, g["start"] - pad)
            b = min(n_tot, g["end"] + pad)
            if b - a < int(0.15 * cfg.SFREQ):            # too short to feature
                continue
            ev = _event_feats(blink_uv, g, cfg.SFREQ)
            f93 = _quiet(features.extract_epoch, data_z[:, a:b])
            rows.append({"label": rec.label, "session": rec.session,
                         "n_blinks": g["n_bursts"], "ev": ev, "f93": f93})
            nb.append(g["n_bursts"])
        per_rec.append((rec, len(nb), float(np.mean(nb)) if nb else 0.0))
    return rows, per_rec


def validate(rows, per_rec):
    print("\n" + "=" * 72)
    print(" STEP 2 VALIDATION — event-locked gesture detection (printed FIRST)")
    print("=" * 72)
    print(f" {'Recording':<34}{'class':<11}{'gestures':>9}{'blinks/gest':>12}")
    print("-" * 72)
    for rec, n_g, mean_b in per_rec:
        print(f" {(rec.session+'/'+rec.path.name)[:33]:<34}{_NAME[rec.label]:<11}"
              f"{n_g:>9}{mean_b:>12.2f}")
    print("-" * 72)
    y = np.array([r["label"] for r in rows])
    nb = np.array([r["n_blinks"] for r in rows])
    print(f" {'PER-CLASS blinks/gesture':<34}{'expect':>9}{'mean':>8}{'std':>8}")
    stats = {}
    for lbl in (_O, _S, _T):
        m = y == lbl
        stats[lbl] = (nb[m].mean(), nb[m].std())
        print(f" {'  '+_NAME[lbl]:<34}{_EXP[lbl]:>9}{nb[m].mean():>8.2f}{nb[m].std():>8.2f}")
    print("-" * 72)

    # separability proxies (no labels used to set the detector threshold)
    bin_rule = np.where(nb >= 2, _S, _O)
    mask_so = np.isin(y, (_S, _O))
    bin_acc = accuracy_score(y[mask_so], bin_rule[mask_so])
    tri_rule = np.where(nb >= 3, _T, np.where(nb == 2, _S, _O))
    tri_acc = accuracy_score(y, tri_rule)
    gap_so = stats[_S][0] - stats[_O][0]
    print(f" n_blinks-only rule:  S-vs-O acc {bin_acc*100:.1f}%   "
          f"3-class acc {tri_acc*100:.1f}%")
    print(f" single→double mean gap: {gap_so:.2f} blinks "
          f"(single {stats[_O][0]:.2f} vs double {stats[_S][0]:.2f})")
    # GATE: clear separation = the binary count rule clearly beats chance AND the
    # means are ordered with a real gap. (Chance for S/O ~ majority class.)
    passed = (stats[_O][0] < stats[_S][0] < stats[_T][0]) and gap_so >= 0.5 and bin_acc >= 0.70
    print("=" * 72)
    print(f" GATE: {'PASS — proceed to classification' if passed else 'FAIL — STOP (resolution limit; keep the 89.2% hybrid)'}")
    print("=" * 72)
    return passed


def _stage_pipe_simple(kind):
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    clf = (RandomForestClassifier(n_estimators=400, class_weight="balanced_subsample",
                                  random_state=cfg.RANDOM_STATE, n_jobs=-1)
           if kind == "RF" else
           SVC(kernel="rbf", class_weight="balanced", random_state=cfg.RANDOM_STATE))
    return ImbPipeline([("sc", StandardScaler()),
                        ("smote", SMOTE(random_state=cfg.RANDOM_STATE)),
                        ("clf", clf)])


def classify(rows):
    y = np.array([r["label"] for r in rows])
    sess = np.array([r["session"] for r in rows])
    Xall = np.array([r["ev"] + list(r["f93"]) for r in rows])   # 7 event + 93 = 100
    sessions = sorted(np.unique(sess))

    def loso(idx, labels, kind):
        accs, per = [], np.zeros(len(labels))
        for s in sessions:
            te = idx[sess[idx] == s]
            tr = idx[sess[idx] != s]
            m = _stage_pipe_simple(kind).fit(Xall[tr], y[tr])
            yp = m.predict(Xall[te])
            accs.append(accuracy_score(y[te], yp))
            per += f1_score(y[te], yp, labels=labels, average=None)
        return np.mean(accs), per / len(sessions)

    all_idx = np.arange(len(y))
    bin_idx = np.where(np.isin(y, (_S, _O)))[0]

    print("\n" + "=" * 72)
    print(" STEP 4 — event-locked classification (LOSO 3-fold mean, 100 feats)")
    print("=" * 72)
    print(f" {'Method':<30}{'S-F1':>7}{'O-F1':>7}{'T-F1':>7}{'acc':>9}")
    print("-" * 72)
    print(f" {'Current whole-window (ref)':<30}{0.749:>7.3f}{0.780:>7.3f}{'—':>7}{77.8:>8.1f}%")
    for kind in ("RF", "SVM"):
        acc, per = loso(bin_idx, [_S, _O], kind)
        print(f" {'Event-locked '+kind+' (S vs O)':<30}{per[0]:>7.3f}{per[1]:>7.3f}{'—':>7}{acc*100:>8.1f}%")
    for kind in ("RF", "SVM"):
        acc, per = loso(all_idx, [_S, _O, _T], kind)
        print(f" {'Event-locked '+kind+' (S/O/T)':<30}{per[0]:>7.3f}{per[1]:>7.3f}{per[2]:>7.3f}{acc*100:>8.1f}%")
    print("=" * 72)
    print(" GATE to production: only wire in if S-vs-O beats 77.8% by >2pt.")


def run():
    rows, per_rec = build_dataset()
    print(f"\n[evlock] detected {len(rows)} event-locked gestures across "
          f"{len(per_rec)} recordings")
    passed = validate(rows, per_rec)
    if passed:
        classify(rows)
    else:
        print("\n[evlock] validation gate FAILED -> not classifying. The single/double/"
              "triple resolution limit is fundamental (attempt #4). Keep the 89.2% hybrid.")


if __name__ == "__main__":
    run()
