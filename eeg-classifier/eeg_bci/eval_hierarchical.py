"""GroupKFold evaluation of the 2-stage hierarchical classifier vs the flat RF.

The model itself lives in eeg_bci/hierarchical.py (single source of truth, so the
pickled class is importable by training and inference). This script only measures
it on the honest dev protocol: activity-gated frac=0.5, 5-fold StratifiedGroupKFold
grouped BY RECORDING (no within-recording leakage), RandomForest. Stage accuracies
are reported in isolation (correct routing); the composed system is reported
end-to-end (routing errors included), head-to-head with the flat 93-feature RF on
the identical gated rows + identical folds.

Run:  python -m eeg_bci.eval_hierarchical
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
from eeg_bci.hierarchical import (
    BLINK_LABELS, MUSCLE_LABELS, HierarchicalClassifier,
    extract_superset, superset_names)
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual
from eeg_bci.train import build_classifiers, build_pipeline

_GATE_FRAC = 0.5
_N_SPLITS = 5

# Report column order: S, O, C, L, R (label indices 0,1,2,3,4).
_COL_LABELS = [0, 1, 2, 3, 4]
_COL_NAMES = ["S-F1", "O-F1", "C-F1", "L-F1", "R-F1"]


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def run() -> None:
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)
    scores = activity_scores(Xuv, y)
    keep = gate_mask(scores, y, groups, frac=_GATE_FRAC)
    Xg, Xuvg, yg, gg = X[keep], Xuv[keep], y[keep], groups[keep]

    names = superset_names()
    Fsuper = _quiet(extract_superset, Xg, Xuvg)          # 129 feats
    Fbase = _quiet(features.extract_features, Xg)        # 93 feats (flags all off)

    cv = StratifiedGroupKFold(
        n_splits=_N_SPLITS, shuffle=True, random_state=cfg.RANDOM_STATE)
    labels = sorted(cfg.COMMAND_MAP)

    print(f"\n[hier] gated frac={_GATE_FRAC}: {keep.sum()} epochs / "
          f"{len(np.unique(gg))} recordings, class counts {np.bincount(yg)}")
    probe = HierarchicalClassifier(names)
    print(f"[hier] feature routing -> Stage1: {len(probe.s1_cols)} frontal+temporal feats | "
          f"Stage2a: {len(probe.s2a_cols)} frontal+blink feats | "
          f"Stage2b: {len(probe.s2b_cols)} muscle+asym+EMG feats")

    # Flat baseline (cross_val_predict, same cv/seed/rows).
    flat_pred = _quiet(
        cross_val_predict, build_pipeline(build_classifiers()["RandomForest"]),
        Fbase, yg, groups=gg, cv=cv, n_jobs=-1)

    # Hierarchical: manual out-of-fold loop over the same folds.
    oof = np.empty(len(yg), dtype=int)
    s1_t, s1_p, s2a_t, s2a_p, s2b_t, s2b_p = [], [], [], [], [], []
    for tr, te in cv.split(Fsuper, yg, gg):
        model = HierarchicalClassifier(names).fit(Fsuper[tr], yg[tr])
        oof[te] = model.predict(Fsuper[te])
        s1_p.append(model.s1.predict(Fsuper[te][:, model.s1_cols]))
        s1_t.append(np.isin(yg[te], MUSCLE_LABELS).astype(int))
        bl, mu = np.isin(yg[te], BLINK_LABELS), np.isin(yg[te], MUSCLE_LABELS)
        if bl.any():
            s2a_p.append(model.s2a.predict(Fsuper[te][bl][:, model.s2a_cols]))
            s2a_t.append(yg[te][bl])
        if mu.any():
            s2b_p.append(model.s2b.predict(Fsuper[te][mu][:, model.s2b_cols]))
            s2b_t.append(yg[te][mu])

    s1_acc = accuracy_score(np.concatenate(s1_t), np.concatenate(s1_p))
    s2a_acc = accuracy_score(np.concatenate(s2a_t), np.concatenate(s2a_p))
    s2b_acc = accuracy_score(np.concatenate(s2b_t), np.concatenate(s2b_p))

    flat_acc = accuracy_score(yg, flat_pred)
    flat_per = f1_score(yg, flat_pred, labels=labels, average=None)
    flat_macro = f1_score(yg, flat_pred, labels=labels, average="macro")
    hier_acc = accuracy_score(yg, oof)
    hier_per = f1_score(yg, oof, labels=labels, average=None)
    hier_macro = f1_score(yg, oof, labels=labels, average="macro")

    print("\n" + "=" * 60)
    print(" Per-stage accuracy (isolation, correct routing) — gated GroupKFold")
    print("=" * 60)
    print(f"   Stage 1 (blink/muscle)        {s1_acc*100:>6.1f}%")
    print(f"   Stage 2a (S vs O)             {s2a_acc*100:>6.1f}%")
    print(f"   Stage 2b (C vs L vs R)        {s2b_acc*100:>6.1f}%")
    print("   " + "-" * 38)
    print(f"   End-to-end 5-class            {hier_acc*100:>6.1f}%   "
          f"(macro-F1 {hier_macro:.3f})")

    print("\n" + "=" * 60)
    print(" Hierarchical vs flat baseline — end-to-end 5-class")
    print("=" * 60)
    print(f" {'Model':<20}{'Overall':>9}{'macroF1':>9}" +
          "".join(f"{c:>7}" for c in _COL_NAMES))
    print("-" * 60)
    fcols = "".join(f"{flat_per[l]:>7.3f}" for l in _COL_LABELS)
    hcols = "".join(f"{hier_per[l]:>7.3f}" for l in _COL_LABELS)
    print(f" {'Flat RF (93 feats)':<20}{flat_acc*100:>8.1f}%{flat_macro:>9.3f}{fcols}")
    print(f" {'Hierarchical':<20}{hier_acc*100:>8.1f}%{hier_macro:>9.3f}{hcols}")
    dcols = "".join(f"{hier_per[l]-flat_per[l]:>+7.3f}" for l in _COL_LABELS)
    print(f" {'   Δ':<20}{(hier_acc-flat_acc)*100:>+8.1f}%"
          f"{hier_macro-flat_macro:>+9.3f}{dcols}")
    print("=" * 60)


if __name__ == "__main__":
    run()
