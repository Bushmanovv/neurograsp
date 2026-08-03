"""Fit the DTW-hybrid (best model, 91.7% LOSO) on ALL gated data and save it.

Stage 1 (feature blink/muscle) + Stage 2a (DTW-KNN on blink waveform) + Stage 2b
(Riemannian muscle covariance). Saved to ``config.DTW_HYBRID_MODEL_PATH``;
inference.py loads it for ``--model dtw`` (the default).

Run:  python -m eeg_bci.train_dtw_hybrid
"""

from __future__ import annotations

import numpy as np

from eeg_bci import config as cfg
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.hierarchical import (
    BLINK_LABELS, MUSCLE_LABELS, DtwRiemannHybridClassifier, blink_waveform,
    extract_superset, save, superset_names)
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual

_GATE_FRAC = 0.5


def run() -> None:
    print("[train-dtw] discover -> preprocess -> gate -> fit (feat S1 + DTW S2a + Riemann S2b)")
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)

    keep = gate_mask(activity_scores(Xuv, y), y, groups, frac=_GATE_FRAC)
    Xg, Xuvg, yg = X[keep], Xuv[keep], y[keep]
    print(f"[train-dtw] activity-gated frac={_GATE_FRAC}: kept {keep.sum()}/{len(keep)} "
          f"epochs, class counts {np.bincount(yg)}")

    names = superset_names()
    F = extract_superset(Xg, Xuvg)
    W = blink_waveform(Xuvg)                              # DTW Stage-2a waveforms
    n_bl = int(np.isin(yg, BLINK_LABELS).sum())
    n_mu = int(np.isin(yg, MUSCLE_LABELS).sum())
    print(f"[train-dtw] feat {F.shape[1]} | DTW waveforms {W.shape} | "
          f"Stage2a DTW-KNN on {n_bl} blink, Stage2b Riemann on {n_mu} muscle")

    model = DtwRiemannHybridClassifier(names)
    model.fit(F, W, Xuvg, yg)

    out = save(model, cfg.DTW_HYBRID_MODEL_PATH)
    print(f"[train-dtw] saved DTW-hybrid (Stage1 {len(model.s1_cols)}f / "
          f"Stage2a DTW-KNN k={model.s2a.n_neighbors} / Stage2b Riemann) -> {out}")


if __name__ == "__main__":
    run()
