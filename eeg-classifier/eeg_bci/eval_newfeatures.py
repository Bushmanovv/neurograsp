"""GroupKFold dev protocol for the 2026-06-29 research feature families.

Measures the per-class-F1 delta of three new feature families -- DWT, TKEO and
classic EMG time-domain descriptors -- on top of the 93-feature baseline, using
the honest dev protocol:

    * task    : activity-gated (frac=0.5) -- the deployment task (FSM only ever
                fires on gesture-present windows), and where burst-detecting
                features can actually show value (rest windows are label noise).
    * CV      : 5-fold StratifiedGroupKFold, grouped BY RECORDING -- no epoch
                from one recording is ever in both train and test of a fold, so
                there is no within-recording leakage. (Stratified variant chosen
                over plain GroupKFold only so each of the 3 recordings/class is
                spread across folds and pooled per-class F1 is stable.)
    * model   : the deployed RandomForest (tuned), inside the shipped pipeline
                StandardScaler -> SelectKBest(mutual_info, k=50) -> SMOTE -> RF.
                Selection/SMOTE are refit per fold (inside cross_val_predict), so
                they never see the test fold.

Features are extracted once per config (the new families are toggled on the
``features`` module globals). The same gated row set is used for every config,
so the reported deltas are apples-to-apples.

Run:  python -m eeg_bci.eval_newfeatures
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict

from eeg_bci import config as cfg
from eeg_bci import features
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual
from eeg_bci.train import build_classifiers, build_pipeline

_GATE_FRAC = 0.5
_N_SPLITS = 5

# Report column order requested: C, L, R, S, O  -> label indices 2,3,4,0,1.
_COL_LABELS = [2, 3, 4, 0, 1]
_COL_NAMES = ["C-F1", "L-F1", "R-F1", "S-F1", "O-F1"]

# (row label, dwt, tkeo, emg) -- cumulative stack matching the requested table.
_CUMULATIVE = [
    ("Baseline (93 feats)", False, False, False),
    ("+ DWT features",      True,  False, False),
    ("+ TKEO",              True,  True,  False),
    ("+ EMG descriptors",   True,  True,  True),
]

# Each family alone vs baseline, to attribute the marginal contribution honestly.
_EACH_ALONE = [
    ("Baseline",          False, False, False),
    ("+ DWT only",        True,  False, False),
    ("+ TKEO only",       False, True,  False),
    ("+ EMG only",        False, False, True),
]


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _eval_config(X, y, groups, dwt, tkeo, emg) -> tuple[int, float, np.ndarray]:
    """Extract features for one toggle combo and run the grouped 5-fold CV.

    Returns ``(n_features, overall_accuracy, per_class_f1_indexed_by_label)``.
    """
    features.DWT_FEATURES = dwt
    features.TKEO_FEATURES = tkeo
    features.EMG_DESCRIPTORS = emg
    feat = _quiet(features.extract_features, X)

    cv = StratifiedGroupKFold(
        n_splits=_N_SPLITS, shuffle=True, random_state=cfg.RANDOM_STATE)
    pipe = build_pipeline(build_classifiers()["RandomForest"])
    y_pred = cross_val_predict(pipe, feat, y, groups=groups, cv=cv, n_jobs=-1)

    acc = accuracy_score(y, y_pred)
    labels = sorted(cfg.COMMAND_MAP)
    per = f1_score(y, y_pred, labels=labels, average=None)
    return feat.shape[1], float(acc), per


def _print_table(title, rows, results, baseline_key) -> None:
    """Print one delta table; ``results[key] = (nfeat, acc, per_label_f1)``."""
    print("\n" + "=" * 78)
    print(f" {title}")
    print("=" * 78)
    header = f" {'Feature set':<22}{'Nfeat':>6}{'Overall':>9}"
    header += "".join(f"{c:>7}" for c in _COL_NAMES)
    print(header)
    print("-" * 78)
    b_nf, b_acc, b_per = results[baseline_key]
    for label, key in rows:
        nf, acc, per = results[key]
        cols = "".join(f"{per[l]:>7.3f}" for l in _COL_LABELS)
        print(f" {label:<22}{nf:>6}{acc*100:>8.1f}%{cols}")
        if key != baseline_key:
            d_cols = "".join(f"{per[l]-b_per[l]:>+7.3f}" for l in _COL_LABELS)
            print(f" {'   Δ vs baseline':<22}{nf-b_nf:>+6}{(acc-b_acc)*100:>+8.1f}%"
                  f"{d_cols}")
    print("=" * 78)


def run() -> None:
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)

    # Activity gate (recording-relative, frac=0.5) -> the deployment task.
    scores = activity_scores(Xuv, y)
    keep = gate_mask(scores, y, groups, frac=_GATE_FRAC)
    Xg, yg, gg = X[keep], y[keep], groups[keep]
    print(f"\n[dev] activity-gated frac={_GATE_FRAC}: kept {keep.sum()}/{len(keep)} "
          f"epochs ({100*keep.mean():.0f}%), {len(np.unique(gg))} recordings")
    print(f"[dev] gated class counts (S,O,C,L,R order={sorted(cfg.COMMAND_MAP)}): "
          f"{np.bincount(yg, minlength=5)}")
    print(f"[dev] CV = {_N_SPLITS}-fold StratifiedGroupKFold by recording, "
          f"model = RandomForest (shipped pipeline)\n")

    # Run every unique toggle combo once, key by (dwt,tkeo,emg).
    combos = {(d, t, e) for _, d, t, e in _CUMULATIVE + _EACH_ALONE}
    results: dict[tuple, tuple] = {}
    for (d, t, e) in sorted(combos):
        nf, acc, per = _eval_config(Xg, yg, gg, d, t, e)
        results[(d, t, e)] = (nf, acc, per)
        tags = [n for n, on in (("DWT", d), ("TKEO", t), ("EMG", e)) if on] or ["baseline"]
        print(f"[dev] ran {'+'.join(tags):<16} -> {nf:>3} feats, "
              f"acc={acc*100:.1f}%")

    cum_rows = [(lbl, (d, t, e)) for lbl, d, t, e in _CUMULATIVE]
    alone_rows = [(lbl, (d, t, e)) for lbl, d, t, e in _EACH_ALONE]
    _print_table("CUMULATIVE  (each family added on top of the previous)",
                 cum_rows, results, (False, False, False))
    _print_table("EACH FAMILY ALONE  (marginal contribution vs baseline)",
                 alone_rows, results, (False, False, False))


if __name__ == "__main__":
    run()
