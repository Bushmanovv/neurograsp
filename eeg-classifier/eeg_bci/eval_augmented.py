"""Augmentation experiment: does synthesizing "extra sessions" help?

Compares the 6-class RandomForest with and without physiologically-motivated
augmentation (eeg_bci.augment), under an honest protocol:

    1. Preprocess -> z-scored epochs X, labels y.
    2. Stratified 80/20 split at the EPOCH level (multiple seeds, because the
       single-split number has ~1.5% variance on this small dataset).
    3. Augmentation is applied to the TRAIN epochs only; the synthetic epochs are
       appended to the real train set. The TEST set is always real epochs, so the
       reported accuracy is not inflated by augmentation.
    4. Feature extraction + the usual Scaler->SelectKBest->SMOTE->RF pipeline.

Reports per-seed and mean+/-std accuracy/macro-F1 for baseline vs augmented, the
per-class F1 (averaged over seeds), and the seed-42 confusion matrix. If
augmentation helps the mean, the final model is refit on ALL real+augmented data
and saved to config.MODEL_PATH.
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

from eeg_bci import config as cfg
from eeg_bci.augment import augment_set
from eeg_bci.features import extract_features
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all
from eeg_bci.train import _class_labels, _class_name, build_classifiers, build_pipeline, save_model

_SESSIONS = ("Session1", "Session2")
_SEEDS = (42, 1, 7, 123, 2024)
_N_AUG = 3


def _quiet(fn, *a, **k):
    """Call fn while swallowing its stdout (feature/preproc chatter)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _fit_eval(feat_tr, y_tr, feat_te, y_te) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Fit a fresh RF pipeline and return (acc, macro_f1, per_class_f1, y_pred)."""
    labels = _class_labels()
    pipe = build_pipeline(build_classifiers()["RandomForest"])
    pipe.fit(feat_tr, y_tr)
    y_pred = pipe.predict(feat_te)
    acc = accuracy_score(y_te, y_pred)
    macro = f1_score(y_te, y_pred, labels=labels, average="macro")
    per = f1_score(y_te, y_pred, labels=labels, average=None)
    return acc, macro, per, y_pred


def run() -> None:
    recs = [r for r in discover_recordings() if r.session in _SESSIONS]
    X, y, _g = preprocess_all(recs)
    feat_real = _quiet(extract_features, X)
    n_lbl = len(_class_labels())
    print(f"[aug] {X.shape[0]} real epochs, {feat_real.shape[1]} features, "
          f"n_aug={_N_AUG} per train epoch")

    rows = []                                            # (seed, base, aug) accs
    base_per = np.zeros(n_lbl)
    aug_per = np.zeros(n_lbl)
    seed42 = {}
    idx = np.arange(X.shape[0])

    for seed in _SEEDS:
        tr, te = train_test_split(
            idx, test_size=0.20, stratify=y, random_state=seed)
        feat_te, y_te = feat_real[te], y[te]

        # Baseline: real train only.
        b_acc, b_macro, b_per, _ = _fit_eval(feat_real[tr], y[tr], feat_te, y_te)

        # Augmented: real train + synthetic variants of the real train epochs.
        X_aug, y_aug = augment_set(X[tr], y[tr], n_aug=_N_AUG, seed=seed)
        feat_aug = _quiet(extract_features, X_aug)
        feat_tr = np.vstack([feat_real[tr], feat_aug])
        y_tr = np.concatenate([y[tr], y_aug])
        a_acc, a_macro, a_per, a_pred = _fit_eval(feat_tr, y_tr, feat_te, y_te)

        rows.append((seed, b_acc, b_macro, a_acc, a_macro))
        base_per += b_per
        aug_per += a_per
        if seed == 42:
            seed42 = {"y_te": y_te, "pred": a_pred}
        print(f"[aug] seed {seed:>4}: base acc={b_acc:.4f} F1={b_macro:.4f}  ->  "
              f"aug acc={a_acc:.4f} F1={a_macro:.4f}")

    base_per /= len(_SEEDS)
    aug_per /= len(_SEEDS)
    b_accs = np.array([r[1] for r in rows]); a_accs = np.array([r[3] for r in rows])
    b_f1s = np.array([r[2] for r in rows]); a_f1s = np.array([r[4] for r in rows])

    print("\n" + "═" * 56)
    print(" Augmentation impact — mean over "
          f"{len(_SEEDS)} stratified splits")
    print("═" * 56)
    print(f" {'Metric':<14}{'Baseline':>14}{'Augmented':>14}{'Delta':>10}")
    print("─" * 56)
    print(f" {'Accuracy':<14}{b_accs.mean()*100:>12.1f}% {a_accs.mean()*100:>12.1f}% "
          f"{(a_accs.mean()-b_accs.mean())*100:>+8.1f}%")
    print(f" {'  std':<14}{b_accs.std()*100:>12.1f}% {a_accs.std()*100:>12.1f}%")
    print(f" {'Macro-F1':<14}{b_f1s.mean():>13.3f} {a_f1s.mean():>13.3f} "
          f"{a_f1s.mean()-b_f1s.mean():>+9.3f}")
    print("─" * 56)
    print(f" {'Per-class F1':<14}{'Base':>14}{'Aug':>14}{'Delta':>10}")
    for i, lbl in enumerate(_class_labels()):
        c = cfg.COMMAND_MAP[lbl][0]
        print(f"  {c} {_class_name(lbl):<11}{base_per[i]:>13.3f} {aug_per[i]:>13.3f} "
              f"{aug_per[i]-base_per[i]:>+9.3f}")
    print("═" * 56)

    _confusion(seed42["y_te"], seed42["pred"])

    improved = a_accs.mean() > b_accs.mean()
    print(f"\n[aug] augmentation {'HELPS' if improved else 'does NOT help'} "
          f"the mean accuracy.")
    if improved:
        print(f"[aug] refitting final RF on ALL real+augmented epochs ...")
        X_aug_all, y_aug_all = augment_set(X, y, n_aug=_N_AUG, seed=cfg.RANDOM_STATE)
        feat_all = np.vstack([feat_real, _quiet(extract_features, X_aug_all)])
        y_all = np.concatenate([y, y_aug_all])
        final = build_pipeline(build_classifiers()["RandomForest"])
        final.fit(feat_all, y_all)
        out = save_model(final)
        print(f"[aug] saved augmented RF to {out}")
    else:
        print("[aug] keeping the existing (non-augmented) model.")


def _confusion(y_te: np.ndarray, y_pred: np.ndarray) -> None:
    labels = _class_labels()
    cm = confusion_matrix(y_te, y_pred, labels=labels)
    chars = [cfg.COMMAND_MAP[l][0] for l in labels]
    print("\n Augmented confusion (seed 42; rows=GT, cols=Pred)")
    print("        " + "".join(f"{c:>5}" for c in chars))
    for i, lbl in enumerate(labels):
        row = "".join(f"{cm[i, j]:>5}" for j in range(len(labels)))
        print(f"   {chars[i]} ({lbl}){row}")


if __name__ == "__main__":
    run()
