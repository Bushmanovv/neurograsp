"""Attempt #5 at the blink ceiling: DTW template-matching on the blink WAVEFORM.

The 4 counting methods failed partly because the single-blink recordings are
contaminated with multi-blink clusters (eval_event_locked_blink.py). DTW compares
waveform SHAPE with elastic time-warping, so it is timing/position-invariant and
*might* separate single vs double better than counting -- a contaminated "single"
window still has a somewhat different overall morphology than a clean double. Tested
here honestly.

ISOLATED experiment. Stage 1 / Stage 2b untouched, production hybrid stays default,
triple re-introduced via the local LABEL_MAP in eval_blink_counter.load_blink_epochs.

Uses the SAME activity-gated blink epochs that produced the 77.8% whole-window
baseline, so the comparison is apples-to-apples. Waveform = mean(Fp1,Fp2,Fz) in µV,
downsampled to 100 pts (~50 Hz; blinks are low-frequency), then per-epoch z-scored
(TimeSeriesScalerMeanVariance) -> pure amplitude-invariant SHAPE. Barycenter
templates are fit on TRAINING data only, per fold. Latency per window is reported
(KNN compares to all training series; templates compare to 2-3 -> fast for RT).

Run:  python -m eeg_bci.eval_dtw_blink
"""

from __future__ import annotations

import time

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from tslearn.barycenters import dtw_barycenter_averaging
from tslearn.metrics import dtw
from tslearn.neighbors import KNeighborsTimeSeriesClassifier
from tslearn.preprocessing import TimeSeriesScalerMeanVariance

from eeg_bci import config as cfg
from eeg_bci.eval_blink_counter import load_blink_epochs, _S, _O, _T, _NAME

_F3 = [cfg.ALL_CH.index(c) for c in ("Fp1-Ref", "Fp2-Ref", "Fz-Ref")]
_DS = 4                      # downsample factor 400 -> 100 pts
_RADIUS = 10                 # Sakoe-Chiba band
_K = 5
_MAX_PER_CLASS = 100         # cap DBA training series per class (speed)
_DBA_ITER = 10
_RNG = np.random.default_rng(cfg.RANDOM_STATE)


def _waveforms(Xuv):
    W = Xuv[:, _F3, :].mean(axis=1)[:, ::_DS]          # (n, ~100) µV, frontal mean
    W = TimeSeriesScalerMeanVariance().fit_transform(W[..., None])   # per-epoch z-score
    return W                                            # (n, sz, 1)


def knn_fold(W, y, tr, te, labels=None):
    clf = KNeighborsTimeSeriesClassifier(
        n_neighbors=_K, metric="dtw",
        metric_params={"sakoe_chiba_radius": _RADIUS}, n_jobs=-1)
    clf.fit(W[tr], y[tr])
    t0 = time.perf_counter()
    pred = clf.predict(W[te])
    lat = (time.perf_counter() - t0) / len(te)
    return pred, lat


def bary_fold(W, y, tr, te, labels):
    templates = {}
    for lbl in labels:
        idx = tr[y[tr] == lbl]
        if len(idx) > _MAX_PER_CLASS:
            idx = _RNG.choice(idx, _MAX_PER_CLASS, replace=False)
        templates[lbl] = dtw_barycenter_averaging(W[idx], max_iter=_DBA_ITER)
    t0 = time.perf_counter()
    pred = []
    for i in te:
        d = {lbl: dtw(W[i], templates[lbl], global_constraint="sakoe_chiba",
                      sakoe_chiba_radius=_RADIUS) for lbl in labels}
        pred.append(min(d, key=d.get))
    lat = (time.perf_counter() - t0) / len(te)
    return np.array(pred), lat


def _loso(W, y, sess, idx, labels, fold_fn):
    accs, per, lats = [], np.zeros(len(labels)), []
    for s in sorted(np.unique(sess[idx])):
        te = idx[sess[idx] == s]
        tr = idx[sess[idx] != s]
        pred, lat = fold_fn(W, y, tr, te, labels)
        accs.append(accuracy_score(y[te], pred))
        per += f1_score(y[te], pred, labels=labels, average=None)
        lats.append(lat)
    return np.mean(accs), per / len(np.unique(sess[idx])), np.mean(lats)


def run():
    X, Xuv, y, groups, sess, recs = load_blink_epochs()
    W = _waveforms(Xuv)
    print(f"\n[dtw] gated blink epochs {W.shape[0]} (S{np.sum(y==_S)} O{np.sum(y==_O)} "
          f"T{np.sum(y==_T)}), waveform shape {W.shape[1:]}, "
          f"radius={_RADIUS}, k={_K}")

    all_idx = np.arange(len(y))
    bin_idx = np.where(np.isin(y, (_S, _O)))[0]

    print("\n" + "=" * 78)
    print(" STEP 4 — DTW blink classification (LOSO 3-fold mean)")
    print("=" * 78)
    print(f" {'Method':<30}{'S-F1':>7}{'O-F1':>7}{'T-F1':>7}{'acc':>8}{'lat/win':>11}")
    print("-" * 78)
    print(f" {'Current whole-window (ref)':<30}{0.749:>7.3f}{0.780:>7.3f}{'—':>7}"
          f"{77.8:>7.1f}%{'~1 ms':>11}")

    # Binary S vs O (the production-relevant comparison to 77.8%).
    for name, fn in (("DTW-KNN (S vs O)", knn_fold),
                     ("DTW barycenter (S vs O)", bary_fold)):
        acc, per, lat = _loso(W, y, sess, bin_idx, [_S, _O], fn)
        print(f" {name:<30}{per[0]:>7.3f}{per[1]:>7.3f}{'—':>7}{acc*100:>7.1f}%"
              f"{lat*1e3:>9.1f}ms")

    # 3-class S/O/T.
    for name, fn in (("DTW-KNN (S/O/T)", knn_fold),
                     ("DTW barycenter (S/O/T)", bary_fold)):
        acc, per, lat = _loso(W, y, sess, all_idx, [_S, _O, _T], fn)
        print(f" {name:<30}{per[0]:>7.3f}{per[1]:>7.3f}{per[2]:>7.3f}{acc*100:>7.1f}%"
              f"{lat*1e3:>9.1f}ms")
    print("=" * 78)
    print(" GATE to production: wire in only if S-vs-O beats 77.8% by >2pt.")


def run_end_to_end():
    """S-vs-O gate passed (+5.8pt) -> end-to-end 5-class LOSO with DTW Stage 2a.

    Replaces ONLY Stage 2a (S/O) with a DTW-KNN on the blink waveform; Stage 1
    (feature blink/muscle) and Stage 2b (Riemannian muscle) are identical to the
    production hybrid. Production taxonomy (5-class, no triple)."""
    from eeg_bci.activity_gate import activity_scores, gate_mask
    from eeg_bci.hierarchical import (
        BLINK_LABELS, MUSCLE_LABELS, _feature_groups, _stage_pipe,
        extract_superset, superset_names)
    from eeg_bci.loader import discover_recordings
    from eeg_bci.preprocessing import preprocess_all_dual
    from eeg_bci.riemann import build_ts_svm

    cfg.LABEL_MAP.pop("BLINK03", None)                   # restore 5-class production taxonomy
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)
    sess = np.array([recs[g].session for g in groups])
    keep = gate_mask(activity_scores(Xuv, y), y, groups, frac=0.5)
    X, Xuv, y, sess = X[keep], Xuv[keep], y[keep], sess[keep]

    names = superset_names()
    g = _feature_groups(names)
    s1_cols = np.concatenate([g["frontal"], g["mus_base"]])
    s2a_cols = np.concatenate([g["frontal"], g["blink"]])
    F = extract_superset(X, Xuv)
    Wd = _waveforms(Xuv)
    labels5 = [0, 1, 2, 3, 4]

    def fold(test_sess, dtw_2a):
        te = np.where(sess == test_sess)[0]
        tr = np.where(sess != test_sess)[0]
        ytr = y[tr]
        s1 = _stage_pipe(len(s1_cols)).fit(
            F[tr][:, s1_cols], np.isin(ytr, MUSCLE_LABELS).astype(int))
        mu = np.isin(ytr, MUSCLE_LABELS)
        s2b = build_ts_svm().fit(Xuv[tr][mu], ytr[mu])
        bl = np.isin(ytr, BLINK_LABELS)
        if dtw_2a:
            s2a = KNeighborsTimeSeriesClassifier(
                n_neighbors=_K, metric="dtw",
                metric_params={"sakoe_chiba_radius": _RADIUS}, n_jobs=-1
            ).fit(Wd[tr][bl], ytr[bl])
        else:
            s2a = _stage_pipe(len(s2a_cols)).fit(F[tr][bl][:, s2a_cols], ytr[bl])
        branch = s1.predict(F[te][:, s1_cols])
        out = np.empty(len(te), dtype=int)
        bi, mi = np.where(branch == 0)[0], np.where(branch == 1)[0]
        if bi.size:
            out[bi] = s2a.predict(Wd[te][bi]) if dtw_2a else s2a.predict(F[te][bi][:, s2a_cols])
        if mi.size:
            out[mi] = s2b.predict(Xuv[te][mi])
        return y[te], out

    print("\n" + "=" * 78)
    print(" STEP 5 — END-TO-END 5-class LOSO (3-fold mean): Stage 2a = DTW vs feature RF")
    print("=" * 78)
    print(f" {'Model':<28}{'Overall':>9}{'macroF1':>9}" +
          "".join(f"{c:>7}" for c in ("S-F1", "O-F1", "C-F1", "L-F1", "R-F1")))
    print("-" * 78)
    for name, dtw_2a in (("Current hybrid (feat 2a)", False),
                         ("Hybrid + DTW Stage 2a", True)):
        accs, macs, per = [], [], np.zeros(5)
        for s in sorted(np.unique(sess)):
            yt, yp = fold(s, dtw_2a)
            accs.append(accuracy_score(yt, yp))
            macs.append(f1_score(yt, yp, labels=labels5, average="macro"))
            per += f1_score(yt, yp, labels=labels5, average=None) / len(np.unique(sess))
        print(f" {name:<28}{np.mean(accs)*100:>8.1f}%{np.mean(macs):>9.3f}" +
              "".join(f"{p:>7.3f}" for p in per))
    print("=" * 78)


if __name__ == "__main__":
    run()
    run_end_to_end()
