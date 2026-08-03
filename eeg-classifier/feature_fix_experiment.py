"""Cross-session experiment: lateralization feature fixes for the C<->R confusion.

Preprocesses Session1/Session2 once, then for each cumulative fix toggles the
feature flags in ``eeg_bci.features``, re-extracts features, refits a clone of
``models/best_model.pkl`` (LDA pipeline) on Session1, and scores Session2.
Reports bruxism_right F1 after each fix and a final comparison table.

Run with zero arguments::

    python feature_fix_experiment.py
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
import joblib
from sklearn.base import clone
from sklearn.metrics import f1_score

from eeg_bci import config as cfg
from eeg_bci import features as F
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all

_R = 4  # bruxism_right label
_C = 2  # clinch label


def _quiet(fn, *args, **kwargs):
    """Invoke ``fn`` while swallowing stdout."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _epochs(session: str) -> tuple[np.ndarray, np.ndarray]:
    """Preprocess one session into epochs + labels (features extracted later).

    Args:
        session: Session folder name.

    Returns:
        (epochs, labels).
    """
    recs = [r for r in _quiet(discover_recordings) if r.session == session]
    x, y, _ = _quiet(preprocess_all, recs)
    return x, y


def _set_flags(fix1: bool, fix2: bool, fix3: bool) -> None:
    """Set the three feature-fix toggles on the features module.

    Args:
        fix1: Enable asymmetry ratio/normalized-difference features.
        fix2: Drop RMS from temporal channel blocks.
        fix3: Add the discrete lateral index.
    """
    F.FIX1_ASYM_RATIOS = fix1
    F.FIX2_DROP_TEMPORAL_RMS = fix2
    F.FIX3_LATERAL_INDEX = fix3


def _evaluate(epochs_tr, y_tr, epochs_te, y_te) -> dict:
    """Extract features under current flags, refit LDA on S1, score S2.

    Returns:
        Dict with R/C accuracy, overall accuracy, R F1 and feature count.
    """
    f_tr = _quiet(F.extract_features, epochs_tr)
    f_te = _quiet(F.extract_features, epochs_te)
    pipe = clone(joblib.load(cfg.MODEL_PATH))
    pipe.fit(f_tr, y_tr)
    y_pred = pipe.predict(f_te)

    def recall(c):
        m = y_te == c
        return 100.0 * (y_pred[m] == c).sum() / m.sum()

    overall = 100.0 * (y_pred == y_te).mean()
    r_f1 = f1_score(y_te, y_pred, labels=[_R], average="macro")
    return {
        "R_acc": recall(_R), "C_acc": recall(_C),
        "overall": overall, "R_f1": r_f1, "n_feat": f_tr.shape[1],
    }


def main() -> None:
    """Run the staged feature-fix experiment and print the comparison table."""
    print("[exp] preprocessing Session1 (train) + Session2 (test) once ...")
    ep_tr, y_tr = _epochs("Session1")
    ep_te, y_te = _epochs("Session2")
    print(f"[exp] train epochs={len(y_tr)} test epochs={len(y_te)}\n")

    stages = [
        ("Baseline",                 (False, False, False)),
        ("+ asymmetry ratios",       (True,  False, False)),
        ("+ drop global RMS",        (True,  True,  False)),
        ("+ lateralization index",   (True,  True,  True)),
    ]

    rows = []
    for name, flags in stages:
        _set_flags(*flags)
        res = _evaluate(ep_tr, y_tr, ep_te, y_te)
        rows.append((name, res))
        if name != "Baseline":
            print(f"[exp] after '{name}': bruxism_right F1 = {res['R_f1']:.2f} "
                  f"(R acc {res['R_acc']:.0f}%, {res['n_feat']} features)")

    print("\n" + "─" * 61)
    print(f"{'Fix':<27}{'R accuracy':>12}{'C accuracy':>12}{'Overall':>10}")
    print("─" * 61)
    for name, r in rows:
        print(f"{name:<27}{r['R_acc']:>11.0f}%{r['C_acc']:>11.0f}%"
              f"{r['overall']:>9.0f}%")
    print("─" * 61)
    best_name, best = max(rows, key=lambda kv: kv[1]["overall"])
    print(f"{'Best: ' + best_name:<27}{best['R_acc']:>11.0f}%"
          f"{best['C_acc']:>11.0f}%{best['overall']:>9.0f}%")
    print("─" * 61)
    print(f"\nBest config bruxism_right F1: {best['R_f1']:.2f}  "
          f"(baseline was {rows[0][1]['R_f1']:.2f})")


if __name__ == "__main__":
    main()
