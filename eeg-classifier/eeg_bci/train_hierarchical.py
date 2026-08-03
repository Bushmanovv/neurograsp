"""Fit the 2-stage hierarchical model on ALL gated data and save it.

Mirrors train.py but for the hierarchy: discover -> preprocess (dual) -> activity
gate (frac=0.5, the deployment task) -> extract the 129-feature superset once ->
fit a single :class:`~eeg_bci.hierarchical.HierarchicalClassifier` (all 3 stages
+ feature routing) on every gated epoch -> save to ``config.HIER_MODEL_PATH``.

The saved object is one picklable bundle: Stage1/2a/2b pipelines plus the
column-routing indices and superset feature names. inference.py loads it directly.

Run:  python -m eeg_bci.train_hierarchical
"""

from __future__ import annotations

import numpy as np

from eeg_bci import config as cfg
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.hierarchical import (
    BLINK_LABELS, MUSCLE_LABELS, HierarchicalClassifier,
    extract_superset, save, superset_names)
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual

_GATE_FRAC = 0.5


def run() -> None:
    print("[train-hier] discover -> preprocess -> gate -> extract superset -> fit")
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)

    scores = activity_scores(Xuv, y)
    keep = gate_mask(scores, y, groups, frac=_GATE_FRAC)
    Xg, Xuvg, yg = X[keep], Xuv[keep], y[keep]
    print(f"[train-hier] activity-gated frac={_GATE_FRAC}: kept {keep.sum()}/{len(keep)} "
          f"epochs, class counts {np.bincount(yg)}")

    names = superset_names()
    F = extract_superset(Xg, Xuvg)
    print(f"[train-hier] superset: {F.shape[1]} features")

    model = HierarchicalClassifier(names)
    n_bl = int(np.isin(yg, BLINK_LABELS).sum())
    n_mu = int(np.isin(yg, MUSCLE_LABELS).sum())
    print(f"[train-hier] fitting Stage1 (blink {n_bl} vs muscle {n_mu}) | "
          f"Stage2a (S/O on {n_bl}) | Stage2b (C/L/R on {n_mu}) ...")
    model.fit(F, yg)

    out = save(model, cfg.HIER_MODEL_PATH)
    print(f"[train-hier] saved hierarchical model (Stage1 {len(model.s1_cols)}f, "
          f"Stage2a {len(model.s2a_cols)}f, Stage2b {len(model.s2b_cols)}f) -> {out}")


if __name__ == "__main__":
    run()
