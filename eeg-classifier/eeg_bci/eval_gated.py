"""Activity-gated epoching experiment: does removing rest-window label noise help?

~48% of epochs are rest windows mislabeled with the recording's gesture class
(see activity_gate.py). This gates them out (recording-relative activity
threshold) and retrains the 6-class RandomForest on only the gesture-present
windows.

HONEST FRAMING: gating is applied to BOTH train and test, which redefines the
task from "classify every 2 s window" to "classify windows that contain a
gesture". That is the real deployment task -- the inference FSM only fires a
command on an active window, never during rest -- but it IS a different (easier,
cleaner) test set than the ungated baseline, so the two numbers are reported
side by side, each as a mean over 5 stratified splits (single-split variance is
~1.5% here). Features are extracted once; gating only selects rows.
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

from eeg_bci import config as cfg
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.features import extract_features
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual
from eeg_bci.train import (
    _class_labels, _class_name, build_classifiers, build_pipeline, save_model)

_SESSIONS = ("Session1", "Session2", "Session3")
_SEEDS = (42, 1, 7, 123, 2024)
_FRACS = (0.4, 0.5, 0.6)
_GATED_MODEL_PATH = "models/best_model_gated.pkl"


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _mean_eval(feat, y, seeds) -> tuple[float, float, np.ndarray, dict]:
    """Mean accuracy / macro-F1 / per-class-F1 over stratified splits.

    Returns (mean_acc, mean_macro, mean_per_class, seed42_pred_dict).
    """
    labels = _class_labels()
    accs, macros = [], []
    per = np.zeros(len(labels))
    seed42 = {}
    idx = np.arange(feat.shape[0])
    for seed in seeds:
        tr, te = train_test_split(idx, test_size=0.20, stratify=y, random_state=seed)
        pipe = build_pipeline(build_classifiers()["RandomForest"])
        pipe.fit(feat[tr], y[tr])
        pred = pipe.predict(feat[te])
        accs.append(accuracy_score(y[te], pred))
        macros.append(f1_score(y[te], pred, labels=labels, average="macro"))
        per += f1_score(y[te], pred, labels=labels, average=None)
        if seed == 42:
            seed42 = {"y_te": y[te], "pred": pred}
    return float(np.mean(accs)), float(np.mean(macros)), per / len(seeds), seed42


def run() -> None:
    recs = [r for r in discover_recordings() if r.session in _SESSIONS]
    X, Xuv, y, groups = preprocess_all_dual(recs)
    feat = _quiet(extract_features, X)
    scores = activity_scores(Xuv, y)
    print(f"[gate] {X.shape[0]} epochs, {feat.shape[1]} features\n")

    # Ungated baseline (task = every window).
    b_acc, b_macro, b_per, _ = _mean_eval(feat, y, _SEEDS)
    print(f"[gate] UNGATED baseline: acc={b_acc*100:.1f}%  macro-F1={b_macro:.3f}\n")

    # Sweep gate fractions.
    best = None
    for frac in _FRACS:
        keep = gate_mask(scores, y, groups, frac=frac)
        acc, macro, per, seed42 = _mean_eval(feat[keep], y[keep], _SEEDS)
        print(f"[gate] frac={frac}: kept {keep.sum():>4}/{len(keep)} "
              f"({100*keep.mean():.0f}%)  acc={acc*100:.1f}%  macro-F1={macro:.3f}")
        if best is None or macro > best["macro"]:
            best = {"frac": frac, "keep": keep, "acc": acc, "macro": macro,
                    "per": per, "seed42": seed42}

    # Report best fraction.
    labels = _class_labels()
    print("\n" + "═" * 56)
    print(f" Ungated vs activity-gated (frac={best['frac']}) — 6-class RF, "
          f"mean/5 splits")
    print("═" * 56)
    print(f" {'Metric':<16}{'Ungated':>12}{'Gated':>12}{'Delta':>12}")
    print("─" * 56)
    print(f" {'Accuracy':<16}{b_acc*100:>11.1f}%{best['acc']*100:>11.1f}%"
          f"{(best['acc']-b_acc)*100:>+11.1f}%")
    print(f" {'Macro-F1':<16}{b_macro:>12.3f}{best['macro']:>12.3f}"
          f"{best['macro']-b_macro:>+12.3f}")
    print("─" * 56)
    print(f" {'Per-class F1':<16}{'Ungated':>12}{'Gated':>12}{'Delta':>12}")
    for i, lbl in enumerate(labels):
        c = cfg.COMMAND_MAP[lbl][0]
        print(f"  {c} {_class_name(lbl):<13}{b_per[i]:>11.3f}{best['per'][i]:>12.3f}"
              f"{best['per'][i]-b_per[i]:>+12.3f}")
    print("═" * 56)

    _confusion(best["seed42"]["y_te"], best["seed42"]["pred"], best["frac"])

    if best["acc"] > b_acc:
        print(f"\n[gate] gating HELPS -> refit gated RF on all {best['keep'].sum()} "
              f"active epochs, save to {_GATED_MODEL_PATH}")
        final = build_pipeline(build_classifiers()["RandomForest"])
        final.fit(feat[best["keep"]], y[best["keep"]])
        out = save_model(final, _GATED_MODEL_PATH)
        print(f"[gate] saved gated model to {out} (inference must gate windows "
              f"by activity before predicting; ungated model kept at "
              f"{cfg.MODEL_PATH})")
    else:
        print("\n[gate] gating does NOT help; keeping the ungated model.")


def _confusion(y_te, y_pred, frac) -> None:
    labels = _class_labels()
    cm = confusion_matrix(y_te, y_pred, labels=labels)
    chars = [cfg.COMMAND_MAP[l][0] for l in labels]
    print(f"\n Gated confusion (frac={frac}, seed 42; rows=GT, cols=Pred)")
    print("        " + "".join(f"{c:>5}" for c in chars))
    for i, lbl in enumerate(labels):
        row = "".join(f"{cm[i, j]:>5}" for j in range(len(labels)))
        print(f"   {chars[i]} ({lbl}){row}")


if __name__ == "__main__":
    run()
