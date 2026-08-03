"""Fit the Riemannian-hybrid model on ALL gated data and save it.

Best model on every protocol (LOSO mean 89.5% vs 85.1% for flat/hierarchical):
feature-based Stage 1 (blink/muscle) + Stage 2a (S/O), Riemannian Stage 2b (C/L/R)
on the raw 19-channel covariance. Fitted on every gated epoch and saved to
``config.HYBRID_MODEL_PATH``; inference.py loads it for ``--model hybrid`` (default).

The Riemannian stage is fit on the RAW filtered+CAR epochs in VOLTS (config's Xuv);
inference must feed windows in the same units (it converts µV->volts).

Run:  python -m eeg_bci.train_hybrid
"""

from __future__ import annotations

import numpy as np

from eeg_bci import config as cfg
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.hierarchical import (
    BLINK_LABELS, MUSCLE_LABELS, RiemannHybridClassifier, extract_superset,
    save, superset_names)
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual

_GATE_FRAC = 0.5


def run() -> None:
    print("[train-hybrid] discover -> preprocess -> gate -> fit (feat S1/S2a + Riemann S2b)")
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)

    keep = gate_mask(activity_scores(Xuv, y), y, groups, frac=_GATE_FRAC)
    Xg, Xuvg, yg = X[keep], Xuv[keep], y[keep]
    print(f"[train-hybrid] activity-gated frac={_GATE_FRAC}: kept {keep.sum()}/{len(keep)} "
          f"epochs, class counts {np.bincount(yg)}")

    names = superset_names()
    F = extract_superset(Xg, Xuvg)
    n_bl = int(np.isin(yg, BLINK_LABELS).sum())
    n_mu = int(np.isin(yg, MUSCLE_LABELS).sum())
    print(f"[train-hybrid] feat superset {F.shape[1]}f, raw tensor {tuple(Xuvg.shape)} (volts); "
          f"Stage2b Riemannian on {n_mu} muscle epochs (19-ch covariance)")

    model = RiemannHybridClassifier(names)
    model.fit(F, Xuvg, yg)

    out = save(model, cfg.HYBRID_MODEL_PATH)
    print(f"[train-hybrid] saved hybrid (Stage1 {len(model.s1_cols)}f / "
          f"Stage2a {len(model.s2a_cols)}f / Stage2b Riemann TS+SVM) -> {out}")


if __name__ == "__main__":
    run()
