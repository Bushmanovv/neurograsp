"""Stage 4 - training.

Pipeline per classifier (imbalanced-learn Pipeline so SMOTE only ever sees the
training fold):

    StandardScaler -> SelectKBest(mutual_info, k=50) -> SMOTE -> Classifier

Three classifiers are compared with 5-fold stratified CV using out-of-fold
predictions (``cross_val_predict``), so reported accuracy / macro-F1 / per-class
F1 are honest (the test fold is never resampled by SMOTE). The best pipeline
(by macro-F1, tie-broken by accuracy) is refit on all data and saved to
``config.MODEL_PATH``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import joblib
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from eeg_bci import config as cfg
from eeg_bci.features import extract_features, make_selector
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual


def build_classifiers() -> dict[str, object]:
    """Instantiate the three classifiers to compare.

    Returns:
        Mapping of model name -> unfitted estimator.
    """
    return {
        # Tuned 2026-06-18: class_weight + more trees. A bake-off vs gradient
        # boosting (XGBoost/LightGBM/HistGB) and voting/stacking ensembles found
        # those only beat RF on the leakage-prone stratified split; on the honest
        # cross-session test (train S1+S2 -> unseen S3) they were all WORSE, while
        # this tuned RF improved both (xS3 macro-F1 0.567 -> 0.585). RF kept.
        "RandomForest": RandomForestClassifier(
            n_estimators=600, max_features="sqrt", min_samples_leaf=1,
            class_weight="balanced_subsample",
            random_state=cfg.RANDOM_STATE, n_jobs=-1,
        ),
        "SVC-RBF": SVC(
            kernel="rbf", probability=True, random_state=cfg.RANDOM_STATE,
        ),
        "LDA": LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto"),
    }


def build_pipeline(clf: object) -> ImbPipeline:
    """Wrap a classifier in the full StandardScaler->SelectKBest->SMOTE->clf pipeline.

    Args:
        clf: An unfitted scikit-learn classifier.

    Returns:
        An imbalanced-learn :class:`Pipeline`.
    """
    return ImbPipeline([
        ("scaler", StandardScaler()),
        ("select", make_selector()),
        ("smote", SMOTE(random_state=cfg.RANDOM_STATE)),
        ("clf", clf),
    ])


def _class_labels() -> list[int]:
    """Return the sorted list of integer class labels (0-4).

    Returns:
        Sorted label indices from ``config.COMMAND_MAP``.
    """
    return sorted(cfg.COMMAND_MAP)


def _class_name(label: int) -> str:
    """Human-readable class name for a label index.

    Args:
        label: Integer class label.

    Returns:
        Class name from ``config.LABEL_MAP`` (falls back to the command action).
    """
    for lbl, name in cfg.LABEL_MAP.values():
        if lbl == label:
            return name
    return cfg.COMMAND_MAP[label][1]


def evaluate(
    feat: np.ndarray, y: np.ndarray, groups: np.ndarray
) -> dict[str, dict]:
    """Cross-validate every classifier (grouped by recording) and print metrics.

    Uses :class:`StratifiedGroupKFold` so epochs from one recording never appear
    in both train and test of a fold (no within-recording leakage), while still
    balancing the class distribution across folds.

    Args:
        feat: Feature matrix ``(n_epochs, 78)``.
        y: Integer label vector.
        groups: Per-epoch recording index.

    Returns:
        Mapping of model name -> {"accuracy", "macro_f1", "per_class_f1", "pipeline"}.
    """
    labels = _class_labels()
    cv = StratifiedGroupKFold(
        n_splits=cfg.CV_FOLDS, shuffle=True, random_state=cfg.RANDOM_STATE,
    )
    results: dict[str, dict] = {}

    for name, clf in build_classifiers().items():
        pipe = build_pipeline(clf)
        print(f"\n[train] === {name} : {cfg.CV_FOLDS}-fold StratifiedGroupKFold "
              f"(grouped by recording) ===")
        y_pred = cross_val_predict(
            pipe, feat, y, groups=groups, cv=cv, n_jobs=-1,
        )

        acc = accuracy_score(y, y_pred)
        macro = f1_score(y, y_pred, labels=labels, average="macro")
        per_class = f1_score(y, y_pred, labels=labels, average=None)

        print(f"    overall accuracy : {acc:.4f}")
        print(f"    macro-F1         : {macro:.4f}")
        print("    per-class F1:")
        for lbl, f1 in zip(labels, per_class):
            print(f"        label {lbl} ({_class_name(lbl):<13s}): {f1:.4f}")

        results[name] = {
            "accuracy": acc, "macro_f1": macro,
            "per_class_f1": per_class, "pipeline": pipe,
        }
    return results


def pick_best(results: dict[str, dict]) -> str:
    """Choose the best model by macro-F1, tie-broken by accuracy.

    Args:
        results: Output of :func:`evaluate`.

    Returns:
        The name of the winning model.
    """
    return max(
        results,
        key=lambda n: (results[n]["macro_f1"], results[n]["accuracy"]),
    )


def save_model(pipeline: ImbPipeline, path: str | Path = cfg.MODEL_PATH) -> Path:
    """Persist a fitted pipeline to disk, creating the parent dir if needed.

    Args:
        pipeline: A fitted imbalanced-learn pipeline.
        path: Destination ``.pkl`` path.

    Returns:
        The resolved path written to.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, out)
    return out.resolve()


def run_training() -> Path:
    """Run the full Stage-4 training and save the best model.

    Returns:
        Path to the saved model file.
    """
    print("[train] Stage 1-2-3: loading, preprocessing, feature extraction")
    recs = discover_recordings()
    epochs, epochs_uv, y, groups = preprocess_all_dual(recs)
    feat = extract_features(epochs, epochs_uv)

    results = evaluate(feat, y, groups)

    best = pick_best(results)
    print(f"\n[train] best model: {best} "
          f"(macro-F1={results[best]['macro_f1']:.4f}, "
          f"accuracy={results[best]['accuracy']:.4f})")
    print(f"[train] reason: highest macro-F1 across the {cfg.CV_FOLDS}-fold CV "
          f"(macro-F1 chosen over accuracy because the classes are imbalanced)")

    # Refit the winning pipeline on ALL data before saving.
    print(f"[train] refitting {best} on all {feat.shape[0]} epochs ...")
    best_pipe = results[best]["pipeline"]
    best_pipe.fit(feat, y)
    out = save_model(best_pipe)
    print(f"[train] saved {best} pipeline "
          f"(StandardScaler -> SelectKBest -> SMOTE -> {best}) to {out}")
    return out


def run_cross_session(train_session: str = "Session1",
                      test_session: str = "Session2") -> None:
    """Honest cross-session test: train on one session, test on the other.

    No epoch mixing - the entire test session is unseen during training. Prints
    per-class F1, accuracy and macro-F1 for every classifier.

    Args:
        train_session: Session folder name used for training.
        test_session: Session folder name used for testing.
    """
    labels = _class_labels()
    recs = discover_recordings()
    train_recs = [r for r in recs if r.session == train_session]
    test_recs = [r for r in recs if r.session == test_session]

    print(f"\n[xsession] TRAIN={train_session} ({len(train_recs)} recs)  "
          f"TEST={test_session} ({len(test_recs)} recs)")
    x_tr, x_tr_uv, y_tr, _ = preprocess_all_dual(train_recs)
    x_te, x_te_uv, y_te, _ = preprocess_all_dual(test_recs)
    f_tr = extract_features(x_tr, x_tr_uv)
    f_te = extract_features(x_te, x_te_uv)

    for name, clf in build_classifiers().items():
        pipe = build_pipeline(clf)
        pipe.fit(f_tr, y_tr)
        y_pred = pipe.predict(f_te)
        acc = accuracy_score(y_te, y_pred)
        macro = f1_score(y_te, y_pred, labels=labels, average="macro")
        per_class = f1_score(y_te, y_pred, labels=labels, average=None)
        print(f"\n[xsession] === {name} ===")
        print(f"    accuracy : {acc:.4f}    macro-F1 : {macro:.4f}")
        for lbl, f1 in zip(labels, per_class):
            print(f"        label {lbl} ({_class_name(lbl):<13s}): {f1:.4f}")


if __name__ == "__main__":
    import sys

    if "--cross-session" in sys.argv:
        run_cross_session()
    else:
        run_training()
