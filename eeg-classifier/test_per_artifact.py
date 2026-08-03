"""Per-artifact cross-session accuracy + per-class feature importance.

Cross-session split: train on Session1, test on Session2. For each class we
report how many of its epochs were classified correctly, what they were most
confused with, and the model's average confidence on the correct ones. Then we
print the top-3 LDA features per class.

Note on the model: the saved ``models/best_model.pkl`` was trained on ALL data
(Session1+2), so predicting Session2 with it would be in-sample (leakage) and
would not reflect true cross-session accuracy. To keep the split honest we
``clone`` that pipeline's exact architecture/hyper-params (no model re-selection,
no retraining of a *different* model) and fit it on Session1 only.

Run with zero arguments::

    python test_per_artifact.py
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
import joblib
from sklearn.base import clone

from eeg_bci import config as cfg
from eeg_bci.features import extract_features, feature_names
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all

_LABELS = sorted(cfg.COMMAND_MAP)


def _quiet(fn, *args, **kwargs):
    """Call ``fn`` swallowing its stdout.

    Args:
        fn: Callable to invoke.
        *args: Positional args.
        **kwargs: Keyword args.

    Returns:
        ``fn``'s return value.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _class_name(label: int) -> str:
    """Human-readable class name for a label.

    Args:
        label: Integer class label.

    Returns:
        Class name string.
    """
    for lbl, name in cfg.LABEL_MAP.values():
        if lbl == label:
            return name
    return cfg.COMMAND_MAP[label][1]


def _prepare(session: str) -> tuple[np.ndarray, np.ndarray]:
    """Load, preprocess and extract features for one session.

    Args:
        session: Session folder name.

    Returns:
        (feature matrix, label vector).
    """
    recs = [r for r in _quiet(discover_recordings) if r.session == session]
    x, y, _ = _quiet(preprocess_all, recs)
    feat = _quiet(extract_features, x)
    return feat, y


def _fit_cross_session(f_tr, y_tr):
    """Clone the saved pipeline architecture and fit it on the training session.

    Args:
        f_tr: Training features.
        y_tr: Training labels.

    Returns:
        The fitted cloned pipeline.
    """
    saved = joblib.load(cfg.MODEL_PATH)
    pipe = clone(saved)        # same steps + hyper-params, unfitted
    pipe.fit(f_tr, y_tr)
    return pipe


def per_artifact_report(pipe, f_te, y_te) -> tuple[dict, np.ndarray]:
    """Build per-class accuracy / confusion / confidence stats.

    Args:
        pipe: Fitted pipeline.
        f_te: Test features.
        y_te: Test labels.

    Returns:
        (stats dict keyed by label, confusion matrix rows=GT cols=Pred).
    """
    y_pred = pipe.predict(f_te)
    proba = pipe.predict_proba(f_te)
    cls_order = list(pipe.classes_)

    cm = np.zeros((len(_LABELS), len(_LABELS)), dtype=int)
    for t, p in zip(y_te, y_pred):
        cm[_LABELS.index(t), _LABELS.index(p)] += 1

    stats: dict[int, dict] = {}
    for c in _LABELS:
        mask = y_te == c
        n = int(mask.sum())
        preds = y_pred[mask]
        correct = int((preds == c).sum())
        # Top confusion target (most common wrong prediction).
        wrong = preds[preds != c]
        if wrong.size:
            vals, counts = np.unique(wrong, return_counts=True)
            conf_cls = int(vals[counts.argmax()])
            conf_pct = 100.0 * counts.max() / n
        else:
            conf_cls, conf_pct = None, 0.0
        # Mean confidence on correctly predicted epochs (proba of true class).
        col = cls_order.index(c)
        conf_correct = proba[mask][preds == c, col]
        avg_conf = float(conf_correct.mean()) if conf_correct.size else 0.0

        stats[c] = {
            "n": n, "correct": correct,
            "acc": 100.0 * correct / n if n else 0.0,
            "conf_cls": conf_cls, "conf_pct": conf_pct,
            "avg_conf": avg_conf,
        }
    return stats, cm


def _print_report(stats, cm) -> None:
    """Print the per-artifact accuracy report.

    Args:
        stats: Per-class stats from :func:`per_artifact_report`.
        cm: Confusion matrix.
    """
    line = "═" * 50
    print(line)
    print(" Per-Artifact Accuracy Report")
    print(" Train: Session1 | Test: Session2")
    print(line)
    for c in _LABELS:
        s = stats[c]
        char = cfg.COMMAND_MAP[c][0]
        print(f"\n {_class_name(c):<13s} [{char}]")
        print(f"   Epochs tested : {s['n']}")
        print(f"   Correct       : {s['correct']} ({s['acc']:.0f}%)")
        if s["conf_cls"] is not None:
            print(f"   Main confusion: → {_class_name(s['conf_cls'])} "
                  f"({s['conf_pct']:.0f}%)")
        else:
            print("   Main confusion: → none")
        print(f"   Avg confidence: {s['avg_conf']:.2f}")

    total = sum(s["n"] for s in stats.values())
    total_ok = sum(s["correct"] for s in stats.values())
    overall = 100.0 * total_ok / total if total else 0.0
    weakest = min(_LABELS, key=lambda c: stats[c]["acc"])

    # Most-confused unordered class pair from off-diagonal mass.
    best_pair, best_val = None, -1
    for i in range(len(_LABELS)):
        for j in range(i + 1, len(_LABELS)):
            v = cm[i, j] + cm[j, i]
            if v > best_val:
                best_val, best_pair = v, (_LABELS[i], _LABELS[j])
    pair_str = " ↔ ".join(cfg.COMMAND_MAP[l][0] for l in best_pair)

    print("\n" + line)
    print(f" Overall cross-session accuracy: {overall:.0f}%")
    print(f" Weakest class: {_class_name(weakest)} ({stats[weakest]['acc']:.0f}%)")
    print(f" Main confusion pair: {pair_str}")
    print(line)


def _print_feature_importance(pipe) -> None:
    """Print the top-3 LDA features per class.

    Args:
        pipe: Fitted pipeline (StandardScaler -> SelectKBest -> SMOTE -> LDA).
    """
    selector = pipe.named_steps["select"]
    lda = pipe.named_steps["clf"]
    selected = np.asarray(feature_names())[selector.get_support()]
    coef = lda.coef_                      # (n_classes, n_selected)

    print("\n Top 3 features per class (from LDA coefficients):")
    for row, c in enumerate(pipe.classes_):
        top = np.argsort(np.abs(coef[row]))[::-1][:3]
        names = ", ".join(selected[t] for t in top)
        print(f" {_class_name(int(c)):<13s} → {names}")


def main() -> None:
    """Run the cross-session per-artifact test and feature-importance report."""
    print("[test] preparing Session1 (train) and Session2 (test) ...")
    f_tr, y_tr = _prepare("Session1")
    f_te, y_te = _prepare("Session2")
    print(f"[test] train epochs={len(y_tr)}  test epochs={len(y_te)}")
    print("[test] fitting cloned best_model.pkl pipeline on Session1 "
          "(no retraining of a different model)\n")

    pipe = _fit_cross_session(f_tr, y_tr)
    stats, cm = per_artifact_report(pipe, f_te, y_te)
    _print_report(stats, cm)
    _print_feature_importance(pipe)


if __name__ == "__main__":
    main()
