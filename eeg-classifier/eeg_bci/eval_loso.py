"""Leave-One-Session-Out: flat RF vs hierarchical, the strictest cross-session test.

The honest per-user cross-DAY metric (train on 2 sessions/days, test on the unseen
3rd): no epoch from the test day is ever seen in training. Activity-gated (frac=0.5)
to match the deployment task and the existing 85.1% flat headline. Reports the
specific held-out-S3 fold (train S1+S2 -> test S3) AND the 3-fold LOSO mean, for
both models on the IDENTICAL gated epochs.

Run:  python -m eeg_bci.eval_loso
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix, f1_score)

from eeg_bci import config as cfg
from eeg_bci import features
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.hierarchical import (
    DtwRiemannHybridClassifier, HierarchicalClassifier, blink_waveform,
    extract_superset, superset_names)
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual
from eeg_bci.train import build_classifiers, build_pipeline

_GATE_FRAC = 0.5
_COL_LABELS = [0, 1, 2, 3, 4]
_COL_NAMES = ["S-F1", "O-F1", "C-F1", "L-F1", "R-F1"]
_LABELS = [0, 1, 2, 3, 4]
_CLASS_NAMES = ["single_blink", "double_blink", "clinch",
                "bruxism_left", "bruxism_right"]


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _metrics(y_true, y_pred):
    acc = accuracy_score(y_true, y_pred)
    macro = f1_score(y_true, y_pred, labels=_LABELS, average="macro")
    per = f1_score(y_true, y_pred, labels=_LABELS, average=None)
    return acc, macro, per


def _fold(Fbase, Fsuper, yg, sessg, names, test_session):
    """Train on all-but-``test_session``, test on it. Returns (flat, hier) metrics."""
    te = sessg == test_session
    tr = ~te
    flat = build_pipeline(build_classifiers()["RandomForest"]).fit(Fbase[tr], yg[tr])
    flat_m = _metrics(yg[te], flat.predict(Fbase[te]))
    hier = HierarchicalClassifier(names).fit(Fsuper[tr], yg[tr])
    hier_m = _metrics(yg[te], hier.predict(Fsuper[te]))
    return flat_m, hier_m


def _dtw_fold(Fsuper, Wg, Xuvg, yg, sessg, names, test_session):
    """Fit the PRODUCTION model (``DtwRiemannHybridClassifier``) on all-but-
    ``test_session``, predict on it. Returns raw ``(y_true, y_pred)`` for pooling
    -- same fold split as :func:`_fold`, just a different model."""
    te = sessg == test_session
    tr = ~te
    model = DtwRiemannHybridClassifier(names).fit(
        Fsuper[tr], Wg[tr], Xuvg[tr], yg[tr])
    pred = model.predict(Fsuper[te], Wg[te], Xuvg[te])
    return yg[te], pred


def _print_pair(title, flat_m, hier_m):
    print("\n" + "=" * 64)
    print(f" {title}")
    print("=" * 64)
    print(f" {'Model':<20}{'Overall':>9}{'macroF1':>9}" +
          "".join(f"{c:>7}" for c in _COL_NAMES))
    print("-" * 64)
    for tag, (acc, macro, per) in (("Flat RF (93f)", flat_m), ("Hierarchical", hier_m)):
        print(f" {tag:<20}{acc*100:>8.1f}%{macro:>9.3f}" +
              "".join(f"{per[l]:>7.3f}" for l in _COL_LABELS))
    dacc = (hier_m[0] - flat_m[0]) * 100
    dmac = hier_m[1] - flat_m[1]
    dper = "".join(f"{hier_m[2][l]-flat_m[2][l]:>+7.3f}" for l in _COL_LABELS)
    print(f" {'   Δ (hier-flat)':<20}{dacc:>+8.1f}%{dmac:>+9.3f}{dper}")
    print("=" * 64)


def run() -> None:
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)
    sess = np.array([recs[g].session for g in groups])

    scores = activity_scores(Xuv, y)
    keep = gate_mask(scores, y, groups, frac=_GATE_FRAC)
    Xg, Xuvg, yg, sessg = X[keep], Xuv[keep], y[keep], sess[keep]

    names = superset_names()
    Fsuper = _quiet(extract_superset, Xg, Xuvg)
    Fbase = _quiet(features.extract_features, Xg)
    Wg = blink_waveform(Xuvg)

    sessions = sorted(np.unique(sessg))
    print(f"\n[loso] gated frac={_GATE_FRAC}: {keep.sum()} epochs, sessions {sessions}")
    for s in sessions:
        print(f"[loso]   {s}: {int((sessg==s).sum())} gated epochs, "
              f"classes {np.bincount(yg[sessg==s], minlength=5)}")

    # Primary fold requested: train S1+S2 -> test S3.
    flat_s3, hier_s3 = _fold(Fbase, Fsuper, yg, sessg, names, "Session3")
    _print_pair("LOSO  train S1+S2  ->  test S3   (the requested fold)",
                flat_s3, hier_s3)

    # 3-fold LOSO mean (parity with the 85.1% flat headline).
    flat_accs, flat_macs, hier_accs, hier_macs = [], [], [], []
    flat_per = np.zeros(5); hier_per = np.zeros(5)
    y_true_dtw, y_pred_dtw = [], []
    print("\n[loso] per-fold (hold out each session):")
    for s in sessions:
        fm, hm = _fold(Fbase, Fsuper, yg, sessg, names, s)
        flat_accs.append(fm[0]); flat_macs.append(fm[1]); flat_per += fm[2]
        hier_accs.append(hm[0]); hier_macs.append(hm[1]); hier_per += hm[2]
        yt, yp = _dtw_fold(Fsuper, Wg, Xuvg, yg, sessg, names, s)
        y_true_dtw.append(yt); y_pred_dtw.append(yp)
        print(f"   hold-out {s}:  flat {fm[0]*100:>5.1f}% / {fm[1]:.3f}   "
              f"hier {hm[0]*100:>5.1f}% / {hm[1]:.3f}   "
              f"dtw-hybrid {accuracy_score(yt, yp)*100:>5.1f}%")
    n = len(sessions)
    flat_mean = (np.mean(flat_accs), np.mean(flat_macs), flat_per / n)
    hier_mean = (np.mean(hier_accs), np.mean(hier_macs), hier_per / n)
    _print_pair(f"LOSO  {n}-fold MEAN (hold out each session)", flat_mean, hier_mean)

    # ----------------------------------------------------------------- #
    # Pooled report for the PRODUCTION model (DtwRiemannHybridClassifier):
    # raw predictions concatenated across all 3 folds (NOT averaged per-fold
    # confusion matrices) -- every gated epoch appears exactly once as a
    # held-out prediction.
    # ----------------------------------------------------------------- #
    y_true_dtw = np.concatenate(y_true_dtw)
    y_pred_dtw = np.concatenate(y_pred_dtw)

    print("\n" + "=" * 64)
    print(" LOSO POOLED  --  production DTW-hybrid model (3-fold pooled preds)")
    print("=" * 64)
    print(classification_report(y_true_dtw, y_pred_dtw, labels=_LABELS,
                                 target_names=_CLASS_NAMES, digits=3))

    cm = confusion_matrix(y_true_dtw, y_pred_dtw, labels=_LABELS)
    print("Confusion matrix (rows=true, cols=predicted), plain numpy array:")
    print(cm)

    name_w = max(len(n) for n in _CLASS_NAMES)
    print("\nLabelled:")
    print(" " * (name_w + 1) + "".join(f"{n:>16}" for n in _CLASS_NAMES))
    for i, nm in enumerate(_CLASS_NAMES):
        print(f"{nm:<{name_w + 1}}" + "".join(f"{v:>16d}" for v in cm[i]))

    support = cm.sum(axis=1)
    print("\nSupport (true epoch count) per class:")
    for nm, s in zip(_CLASS_NAMES, support):
        print(f"  {nm:<16}{s:>6d}")
    print(f"  {'TOTAL':<16}{support.sum():>6d}")


if __name__ == "__main__":
    run()
