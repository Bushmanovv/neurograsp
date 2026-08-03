"""Stratified 80/20 random-split evaluation (single-subject, per-session).

Combines ALL Session1 + Session2 epochs into one pool and evaluates with a
single stratified random split (80 % train / 20 % test). No GroupKFold and no
cross-session split: this is a single-subject BCI, so the target is per-session
generalization for the same person, not cross-subject transfer.

Pipeline per classifier (imbalanced-learn, so SMOTE only ever sees the training
split)::

    StandardScaler -> SelectKBest(mutual_info, k=50) -> SMOTE -> Classifier

All three classifiers are fit on the same 80 % split and scored on the same
held-out 20 %. The best (by macro-F1, tie-broken by accuracy) is reported in
full -- overall accuracy, per-class F1 and confusion matrix -- then refit on the
full Session1+Session2 pool and saved to ``config.MODEL_PATH``. This is the
number used going forward.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split

from eeg_bci import config as cfg
from eeg_bci.features import extract_features
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual
from eeg_bci.train import (
    _class_labels,
    _class_name,
    build_classifiers,
    build_pipeline,
    pick_best,
    save_model,
)

# Sessions pooled for the stratified split.
_SESSIONS = ("Session1", "Session2")
_TEST_SIZE = 0.20


def _load_pool() -> tuple[np.ndarray, np.ndarray]:
    """Load + preprocess + featurize the pooled Session1+Session2 epochs.

    Returns:
        Tuple ``(feat, y)`` -- feature matrix and integer label vector for every
        epoch across both sessions (the Random session is never scanned).
    """
    recs = [r for r in discover_recordings() if r.session in _SESSIONS]
    print(f"[strat] pooling {len(recs)} recordings from {', '.join(_SESSIONS)}")
    epochs, epochs_uv, y, _groups = preprocess_all_dual(recs)
    feat = extract_features(epochs, epochs_uv)
    return feat, y


def _print_metrics(name: str, y_te: np.ndarray, y_pred: np.ndarray) -> dict:
    """Print accuracy + per-class F1 for one classifier and return its scores.

    Args:
        name: Classifier name.
        y_te: True labels of the held-out test split.
        y_pred: Predicted labels.

    Returns:
        Mapping with ``accuracy``, ``macro_f1``, ``per_class_f1`` and ``y_pred``.
    """
    labels = _class_labels()
    acc = accuracy_score(y_te, y_pred)
    macro = f1_score(y_te, y_pred, labels=labels, average="macro")
    per_class = f1_score(y_te, y_pred, labels=labels, average=None)

    print(f"\n[strat] === {name} : stratified 80/20 split ===")
    print(f"    overall accuracy : {acc:.4f}")
    print(f"    macro-F1         : {macro:.4f}")
    print("    per-class F1:")
    for lbl, f1 in zip(labels, per_class):
        print(f"        label {lbl} ({_class_name(lbl):<13s}): {f1:.4f}")
    return {
        "accuracy": acc, "macro_f1": macro,
        "per_class_f1": per_class, "y_pred": y_pred,
    }


def _print_confusion(y_te: np.ndarray, y_pred: np.ndarray) -> None:
    """Print the confusion matrix (rows = ground truth, cols = predicted).

    Args:
        y_te: True labels of the held-out test split.
        y_pred: Predicted labels.
    """
    labels = _class_labels()
    cm = confusion_matrix(y_te, y_pred, labels=labels)
    chars = [cfg.COMMAND_MAP[l][0] for l in labels]

    print("\n Confusion matrix (rows=GT, cols=Pred)")
    print("        " + "".join(f"{c:>5}" for c in chars))
    for i, lbl in enumerate(labels):
        row = "".join(f"{cm[i, j]:>5}" for j in range(len(labels)))
        print(f"   {chars[i]} ({lbl}){row}")
    print("\n    legend: " + ", ".join(
        f"{cfg.COMMAND_MAP[l][0]}={_class_name(l)}" for l in labels
    ))


def run_stratified(test_size: float = _TEST_SIZE) -> None:
    """Run the full stratified-split retrain + evaluation and save the best model.

    Args:
        test_size: Fraction of epochs held out for the test split.
    """
    feat, y = _load_pool()

    x_tr, x_te, y_tr, y_te = train_test_split(
        feat, y,
        test_size=test_size,
        stratify=y,
        random_state=cfg.RANDOM_STATE,
    )
    print(f"\n[strat] stratified split: {x_tr.shape[0]} train / "
          f"{x_te.shape[0]} test epochs "
          f"({100 * (1 - test_size):.0f}/{100 * test_size:.0f})")
    print(f"[strat] train class counts: {np.bincount(y_tr)}")
    print(f"[strat] test  class counts: {np.bincount(y_te)}")

    results: dict[str, dict] = {}
    for name, clf in build_classifiers().items():
        pipe = build_pipeline(clf)
        pipe.fit(x_tr, y_tr)
        y_pred = pipe.predict(x_te)
        results[name] = _print_metrics(name, y_te, y_pred)

    best = pick_best(results)
    best_res = results[best]
    print("\n" + "═" * 60)
    print(f" HEADLINE — {best} on stratified 20% hold-out "
          f"(Session1+2 pooled)")
    print("═" * 60)
    print(f"    overall accuracy : {best_res['accuracy']:.4f}  "
          f"({100 * best_res['accuracy']:.1f}%)")
    print(f"    macro-F1         : {best_res['macro_f1']:.4f}")
    print("    per-class F1:")
    for lbl, f1 in zip(_class_labels(), best_res["per_class_f1"]):
        print(f"        label {lbl} ({_class_name(lbl):<13s}): {f1:.4f}")
    _print_confusion(y_te, best_res["y_pred"])

    # Deployment model: refit the winner on the FULL pooled data and save.
    print(f"\n[strat] refitting {best} on all {feat.shape[0]} pooled epochs ...")
    final_pipe = build_pipeline(build_classifiers()[best])
    final_pipe.fit(feat, y)
    out = save_model(final_pipe)
    print(f"[strat] saved {best} pipeline "
          f"(StandardScaler -> SelectKBest -> SMOTE -> {best}) to {out}")


if __name__ == "__main__":
    run_stratified()
