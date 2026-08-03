"""6-class retrain + 5-class-vs-6-class comparison on the stratified 80/20 split.

The blink class was split: previously BLINK01 (single) and BLINK03 (multiple)
were both label 1 (single_blink), which muddied the S vs O boundary. Now
BLINK03 is its own class, triple_blink (label 2), so every blink type is a pure
class.

Same stratified 80/20 split (random_state=42, Session1+2 pooled) as
eval_stratified.py, so the per-class F1 is directly comparable to the old
5-class numbers. All three classifiers are fit; the best (macro-F1, tie-broken
by accuracy) is reported, compared against the old baseline, and refit on the
full pool + saved to config.MODEL_PATH.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
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

_SESSIONS = ("Session1", "Session2", "Session3")
_TEST_SIZE = 0.20

# 6-class baseline WITHOUT blink peak features (RandomForest, same 80/20 split),
# keyed by class NAME. The blink peak features are evaluated as the delta on top
# of this; S and T are the classes they target (double vs triple blink).
_OLD_F1 = {
    "double_blink": 0.652,
    "single_blink": 0.885,
    "triple_blink": 0.721,
    "clinch": 0.916,
    "bruxism_left": 0.737,
    "bruxism_right": 0.755,
}
_OLD_ACC = 0.834
_BASELINE_LABEL = "6-class no-peak"


def _load_pool() -> tuple[np.ndarray, np.ndarray]:
    """Preprocess + featurize the pooled Session1+2 epochs (6-class labels)."""
    recs = [r for r in discover_recordings() if r.session in _SESSIONS]
    print(f"[6cls] pooling {len(recs)} recordings from {', '.join(_SESSIONS)}")
    epochs, epochs_uv, y, _g = preprocess_all_dual(recs)
    feat = extract_features(epochs, epochs_uv)
    return feat, y


def _print_epoch_counts(y: np.ndarray) -> None:
    """Print the per-class epoch counts (Step 2 of the request)."""
    print("\n" + "═" * 34)
    print(f" {'Class':<16}{'Epochs':>10}")
    print("─" * 34)
    for lbl in _class_labels():
        name = _class_name(lbl)
        tag = "  <- new" if name == "triple_blink" else ""
        print(f" {name:<16}{int(np.sum(y == lbl)):>10}{tag}")
    print("─" * 34)
    print(f" {'Total':<16}{len(y):>10}")
    print("═" * 34)


def _evaluate_all(x_tr, x_te, y_tr, y_te) -> dict[str, dict]:
    """Fit every classifier on the split and collect F1 / accuracy / preds."""
    labels = _class_labels()
    results: dict[str, dict] = {}
    for name, clf in build_classifiers().items():
        pipe = build_pipeline(clf)
        pipe.fit(x_tr, y_tr)
        y_pred = pipe.predict(x_te)
        acc = accuracy_score(y_te, y_pred)
        macro = f1_score(y_te, y_pred, labels=labels, average="macro")
        per_class = f1_score(y_te, y_pred, labels=labels, average=None)
        print(f"\n[6cls] === {name} ===  acc={acc:.4f}  macro-F1={macro:.4f}")
        for lbl, f1 in zip(labels, per_class):
            print(f"        label {lbl} ({_class_name(lbl):<13s}): {f1:.4f}")
        results[name] = {
            "accuracy": acc, "macro_f1": macro,
            "per_class_f1": per_class, "y_pred": y_pred,
        }
    return results


def _print_comparison(best: str, res: dict, y_te: np.ndarray) -> None:
    """Print the 5-class-vs-6-class comparison table for the best model."""
    labels = _class_labels()
    new_f1 = {_class_name(l): f1 for l, f1 in zip(labels, res["per_class_f1"])}
    char = {_class_name(l): cfg.COMMAND_MAP[l][0] for l in labels}

    print("\n" + "═" * 52)
    print(f" {_BASELINE_LABEL} vs +blink-peak — same 80/20 split [{best}]")
    print("═" * 52)
    print(f" {'Class':<16}{'Base F1':>8}{'New F1':>8}{'Delta':>9}")
    print("─" * 52)
    order = [_class_name(l) for l in labels]   # active taxonomy, in label order
    for name in order:
        c = char.get(name, "?")
        new = new_f1[name]
        if name in _OLD_F1:
            old = _OLD_F1[name]
            print(f" {c} {name:<14}{old:>8.3f}{new:>8.3f}{new - old:>+9.3f}")
        else:
            print(f" {c} {name:<14}{'—':>8}{new:>8.3f}{'(new)':>9}")
    print("─" * 52)
    new_acc = res["accuracy"]
    print(f" {'Overall':<16}{_OLD_ACC * 100:>7.1f}%{new_acc * 100:>7.1f}%"
          f"{(new_acc - _OLD_ACC) * 100:>+8.1f}%")
    print("═" * 52)


def _print_confusion(res: dict, y_te: np.ndarray) -> None:
    """Confusion matrix (rows=GT, cols=Pred) for the best model."""
    labels = _class_labels()
    cm = confusion_matrix(y_te, res["y_pred"], labels=labels)
    chars = [cfg.COMMAND_MAP[l][0] for l in labels]
    print("\n Confusion matrix (rows=GT, cols=Pred)")
    print("        " + "".join(f"{c:>5}" for c in chars))
    for i, lbl in enumerate(labels):
        row = "".join(f"{cm[i, j]:>5}" for j in range(len(labels)))
        print(f"   {chars[i]} ({lbl}){row}")
    print("\n    legend: " + ", ".join(
        f"{cfg.COMMAND_MAP[l][0]}={_class_name(l)}" for l in labels))


def run() -> None:
    feat, y = _load_pool()
    _print_epoch_counts(y)

    x_tr, x_te, y_tr, y_te = train_test_split(
        feat, y, test_size=_TEST_SIZE, stratify=y, random_state=cfg.RANDOM_STATE)
    print(f"\n[6cls] stratified split: {x_tr.shape[0]} train / "
          f"{x_te.shape[0]} test epochs (80/20)")

    results = _evaluate_all(x_tr, x_te, y_tr, y_te)
    best = pick_best(results)
    print(f"\n[6cls] best model: {best} "
          f"(macro-F1={results[best]['macro_f1']:.4f}, "
          f"acc={results[best]['accuracy']:.4f})")

    _print_comparison(best, results[best], y_te)
    _print_confusion(results[best], y_te)

    print(f"\n[6cls] refitting {best} on all {feat.shape[0]} pooled epochs ...")
    final = build_pipeline(build_classifiers()[best])
    final.fit(feat, y)
    out = save_model(final)
    print(f"[6cls] saved {best} pipeline to {out}")


if __name__ == "__main__":
    run()
