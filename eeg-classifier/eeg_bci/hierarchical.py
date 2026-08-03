"""Production 2-stage hierarchical classifier (importable / picklable).

    Stage 1  (binary)  blink {S,O}  vs  muscle {C,L,R}   -- frontal/EOG + temporal/EMG channels
    Stage 2a (binary)  S vs O                            -- frontal + blink-peak feats
    Stage 2b (3-class) C vs L vs R                       -- temporal/EMG + EMG descriptors + asym

Each stage is the shipped pipeline StandardScaler -> SelectKBest(mi) -> SMOTE ->
RandomForest. A single 117-feature SUPERSET (baseline 93 + 8 blink-peak + 16 EMG
descriptors; DWT and TKEO excluded) is extracted once and each stage selects its
columns BY NAME, so there is no per-stage re-computation and -- crucially -- Stage
2b trains only on muscle epochs, so muscle features can never dilute the blink
decision (the flat-RF failure mode; see eval_newfeatures.py).

ROUTING TUNED FOR CROSS-SESSION (2026-06-29, eval_loso.py): the first cut lost
-1.9pt on Leave-One-Session-Out. Diagnosis (scratch ablation): (1) TKEO is
session-fragile -- its squared-amplitude energy wrecked bruxism_right across days,
so it is DROPPED from the superset; EMG descriptors (waveform-length / slope-sign /
Willison / CV) are kept (they help muscle classes cross-session). (2) Stage 1 with
frontal-only channels occasionally misrouted; adding the temporal/EMG channels
takes Stage-1 isolation accuracy 98% -> 100%. With both fixes the hierarchy matches
the flat RF on LOSO (85.1%) instead of regressing.

This module is the single source of truth for the class and the superset feature
config, so a pickled :class:`HierarchicalClassifier` in models/ unpickles the same
way under training, eval and inference.
"""

from __future__ import annotations

import contextlib
from functools import partial
from pathlib import Path

import joblib
import numpy as np
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.preprocessing import StandardScaler

from eeg_bci import config as cfg
from eeg_bci import features
from eeg_bci.train import build_classifiers

# Label groups.
BLINK_LABELS = (0, 1)           # S, O
MUSCLE_LABELS = (2, 3, 4)       # C, L, R

# Per-stage channel routing.
S1_FRONTAL = ["Fp1-Ref", "Fp2-Ref", "Fz-Ref", "F3-Ref", "F4-Ref"]   # EOG
S2B_MUSCLE = ["T3-Ref", "T4-Ref", "F7-Ref", "F8-Ref"]               # EMG

# Feature flags that define the 117-feature superset. DWT is dead weight and TKEO
# is session-fragile (see module docstring / eval_loso.py) -- both excluded.
_SUPERSET_FLAGS = {
    "DWT_FEATURES": False,
    "BLINK_PEAK_FEATURES": True,
    "TKEO_FEATURES": False,
    "EMG_DESCRIPTORS": True,
}


@contextlib.contextmanager
def superset_flags():
    """Temporarily set ``features`` globals to the superset config, then restore.

    Production-safe: restoring on exit means the flat 93-feature path (and the
    saved flat model) keep working in the same process.
    """
    saved = {k: getattr(features, k) for k in _SUPERSET_FLAGS}
    try:
        for k, v in _SUPERSET_FLAGS.items():
            setattr(features, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(features, k, v)


def superset_names() -> list[str]:
    """Feature names of the 129-feature superset, in extraction order."""
    with superset_flags():
        return features.feature_names()


def extract_superset(epochs: np.ndarray, epochs_uv: np.ndarray) -> np.ndarray:
    """Extract the 129-feature superset for a stack of epochs (needs raw-µV too)."""
    with superset_flags():
        return features.extract_features(epochs, epochs_uv)


def extract_superset_epoch(epoch_norm: np.ndarray,
                           epoch_uv: np.ndarray) -> np.ndarray:
    """Extract the 129-feature superset for ONE epoch (z-scored + raw-µV, volts)."""
    with superset_flags():
        return features.extract_epoch(epoch_norm, epoch_uv)


def _feature_groups(names) -> dict[str, np.ndarray]:
    """Partition the superset feature indices into routable groups.

    Groups: ``frontal`` (Fp1/Fp2/Fz/F3/F4 block + kurt/skew), ``blink`` (blink-peak
    feats), ``mus_base`` (T3/T4/F7/F8 block + kurt/skew), ``emg`` (EMG descriptors),
    ``asym`` (T4-T3 asymmetry). Order within a group follows extraction order.
    """
    g = {"frontal": [], "blink": [], "mus_base": [], "emg": [], "asym": []}
    for i, nm in enumerate(names):
        if nm.startswith("fp1_") or nm.startswith("fp2_"):
            g["blink"].append(i)
        elif "_emg_" in nm:
            g["emg"].append(i)
        elif nm.startswith("asym_"):
            g["asym"].append(i)
        elif any(nm.startswith(c + "_") for c in S1_FRONTAL):
            g["frontal"].append(i)
        elif any(nm.startswith(c + "_") for c in S2B_MUSCLE):
            g["mus_base"].append(i)
    return {k: np.asarray(v, dtype=int) for k, v in g.items()}


def _stage_pipe(n_cols: int) -> ImbPipeline:
    """Shipped pipeline with ``k`` capped to the stage's feature count."""
    k = min(cfg.SELECT_K, n_cols)
    selector = SelectKBest(
        partial(mutual_info_classif, discrete_features=False,
                random_state=cfg.RANDOM_STATE),
        k=k)
    return ImbPipeline([
        ("scaler", StandardScaler()),
        ("select", selector),
        ("smote", SMOTE(random_state=cfg.RANDOM_STATE)),
        ("clf", build_classifiers()["RandomForest"]),
    ])


class HierarchicalClassifier:
    """Stage-1 blink/muscle router over Stage-2a (S/O) and Stage-2b (C/L/R).

    Bundles the three fitted pipelines and the column-routing indices, so a
    single pickled instance carries the whole model. Construct with the superset
    feature names (:func:`superset_names`); ``fit``/``predict`` take the
    129-feature superset matrix.
    """

    def __init__(self, names: list[str]):
        self.names = list(names)
        g = _feature_groups(names)
        # Stage 1: frontal/EOG + temporal/EMG raw channels (-> 100% routing).
        self.s1_cols = np.concatenate([g["frontal"], g["mus_base"]])
        # Stage 2a: frontal + blink-peak feats (pure S-vs-O).
        self.s2a_cols = np.concatenate([g["frontal"], g["blink"]])
        # Stage 2b: muscle channels + asymmetry + EMG descriptors (NO TKEO).
        self.s2b_cols = np.concatenate([g["mus_base"], g["asym"], g["emg"]])
        self.s1 = _stage_pipe(len(self.s1_cols))
        self.s2a = _stage_pipe(len(self.s2a_cols))
        self.s2b = _stage_pipe(len(self.s2b_cols))

    def fit(self, F: np.ndarray, y: np.ndarray) -> "HierarchicalClassifier":
        grp = np.isin(y, MUSCLE_LABELS).astype(int)         # 0 blink, 1 muscle
        self.s1.fit(F[:, self.s1_cols], grp)
        bl = np.isin(y, BLINK_LABELS)
        self.s2a.fit(F[bl][:, self.s2a_cols], y[bl])
        mu = np.isin(y, MUSCLE_LABELS)
        self.s2b.fit(F[mu][:, self.s2b_cols], y[mu])
        return self

    def predict(self, F: np.ndarray) -> np.ndarray:
        return self.predict_path(F)[0]

    def predict_path(self, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict labels and a per-sample confidence along the decision path.

        Confidence is the JOINT probability of the chosen path,
        ``P(branch) * P(class | branch)`` -- the model's probability of the final
        class, the hierarchical analogue of the flat model's max ``predict_proba``
        (so the existing ``CONF_THRESH`` still applies).

        Returns:
            Tuple ``(labels, confidences)`` each length ``F.shape[0]``.
        """
        n = F.shape[0]
        labels = np.empty(n, dtype=int)
        conf = np.empty(n, dtype=float)
        p1 = self.s1.predict_proba(F[:, self.s1_cols])
        bi = np.argmax(p1, axis=1)
        p_branch = p1[np.arange(n), bi]
        branch = self.s1.classes_[bi]                       # 0 blink / 1 muscle
        for val, stage, cols in ((0, self.s2a, self.s2a_cols),
                                 (1, self.s2b, self.s2b_cols)):
            idx = np.where(branch == val)[0]
            if idx.size:
                p2 = stage.predict_proba(F[idx][:, cols])
                j = np.argmax(p2, axis=1)
                labels[idx] = stage.classes_[j]
                conf[idx] = p_branch[idx] * p2[np.arange(idx.size), j]
        return labels, conf


class RiemannHybridClassifier:
    """Hierarchy with a Riemannian Stage 2b (muscle C/L/R on raw 19-ch covariance).

    Stage 1 (blink/muscle) and Stage 2a (S/O) stay feature-based -- blinks are a
    TEMPORAL pattern that covariance can't see -- and take the 117-feature superset
    ``F``. Stage 2b (C/L/R) is a Riemannian ``Covariances(oas) -> TangentSpace ->
    SVC`` on the RAW filtered+CAR epoch tensor ``(n, 19, n_times)``, where the
    affine-invariant metric cancels the day-to-day amplitude drift that broke the
    feature/TKEO model (muscle F1 0.82-0.94 -> ~0.98 cross-session; see eval_riemann.py).

    Best model on every protocol (LOSO mean 89.5% vs 85.1% for flat/hierarchical).
    ``fit``/``predict`` take BOTH the feature matrix and the raw epoch tensor, which
    MUST be in the SAME amplitude units (volts) at train and inference time.
    """

    def __init__(self, names: list[str]):
        from eeg_bci.riemann import build_ts_svm  # local import avoids a cycle
        self.names = list(names)
        g = _feature_groups(names)
        self.s1_cols = np.concatenate([g["frontal"], g["mus_base"]])
        self.s2a_cols = np.concatenate([g["frontal"], g["blink"]])
        self.s1 = _stage_pipe(len(self.s1_cols))
        self.s2a = _stage_pipe(len(self.s2a_cols))
        # No tsupdate (fragile); probability=True for the inference confidence gate.
        self.s2b = build_ts_svm(tsupdate=False, probability=True)

    def fit(self, F: np.ndarray, epochs_raw: np.ndarray,
            y: np.ndarray) -> "RiemannHybridClassifier":
        self.s1.fit(F[:, self.s1_cols], np.isin(y, MUSCLE_LABELS).astype(int))
        bl = np.isin(y, BLINK_LABELS)
        self.s2a.fit(F[bl][:, self.s2a_cols], y[bl])
        mu = np.isin(y, MUSCLE_LABELS)
        self.s2b.fit(epochs_raw[mu], y[mu])
        return self

    def predict(self, F: np.ndarray, epochs_raw: np.ndarray) -> np.ndarray:
        return self.predict_path(F, epochs_raw)[0]

    def predict_path(self, F: np.ndarray,
                     epochs_raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Labels + joint path confidence ``P(branch)*P(class|branch)`` (see
        :meth:`HierarchicalClassifier.predict_path`)."""
        n = F.shape[0]
        labels = np.empty(n, dtype=int)
        conf = np.empty(n, dtype=float)
        p1 = self.s1.predict_proba(F[:, self.s1_cols])
        bi = np.argmax(p1, axis=1)
        p_branch = p1[np.arange(n), bi]
        branch = self.s1.classes_[bi]
        bl = np.where(branch == 0)[0]
        mu = np.where(branch == 1)[0]
        if bl.size:
            p2 = self.s2a.predict_proba(F[bl][:, self.s2a_cols])
            j = np.argmax(p2, axis=1)
            labels[bl] = self.s2a.classes_[j]
            conf[bl] = p_branch[bl] * p2[np.arange(bl.size), j]
        if mu.size:
            p3 = self.s2b.predict_proba(epochs_raw[mu])
            j = np.argmax(p3, axis=1)
            labels[mu] = self.s2b.classes_[j]
            conf[mu] = p_branch[mu] * p3[np.arange(mu.size), j]
        return labels, conf


# --------------------------------------------------------------------------- #
# DTW Stage 2a (blink S/O by waveform SHAPE) -- breaks the blink ceiling where
# every counting method failed (see eval_dtw_blink.py). Stage 2a becomes a
# DTW-KNN on the frontal blink waveform; Stage 1 + Riemannian Stage 2b unchanged.
# --------------------------------------------------------------------------- #
DTW_WF_CHANNELS = ["Fp1-Ref", "Fp2-Ref", "Fz-Ref"]   # frontal/EOG, averaged
DTW_DOWNSAMPLE = 4                                    # 400 -> 100 pts (~50 Hz)
DTW_RADIUS = 10                                       # Sakoe-Chiba band
DTW_K = 5


def blink_waveform(epochs_raw: np.ndarray) -> np.ndarray:
    """Per-epoch amplitude-invariant blink SHAPE for the DTW Stage 2a.

    Args:
        epochs_raw: ``(n, n_channels, n_times)`` filtered+CAR epochs (any scale;
            normalised per-epoch below, so volts or µV both work).

    Returns:
        ``(n, n_times//DTW_DOWNSAMPLE, 1)`` mean(Fp1,Fp2,Fz), downsampled, then
        z-scored per epoch (``TimeSeriesScalerMeanVariance``).
    """
    from tslearn.preprocessing import TimeSeriesScalerMeanVariance
    idx = [cfg.ALL_CH.index(c) for c in DTW_WF_CHANNELS]
    W = epochs_raw[:, idx, :].mean(axis=1)[:, ::DTW_DOWNSAMPLE]
    return TimeSeriesScalerMeanVariance().fit_transform(W[..., None])


class DtwRiemannHybridClassifier:
    """Best model (91.7% LOSO): Stage 1 features, Stage 2a DTW-KNN (blink shape),
    Stage 2b Riemannian (muscle covariance).

    ``RiemannHybridClassifier`` with Stage 2a swapped from a feature RF to a
    DTW-KNN on the blink waveform -- shape-matching separates single vs double
    where counting failed on the contaminated single-blink data. ``fit``/``predict``
    take the feature superset ``F``, the blink ``waveforms`` (:func:`blink_waveform`)
    and the raw epoch tensor (volts, for Stage 2b -- same-units rule as the Riemann
    hybrid).
    """

    def __init__(self, names: list[str]):
        from tslearn.neighbors import KNeighborsTimeSeriesClassifier
        from eeg_bci.riemann import build_ts_svm
        self.names = list(names)
        g = _feature_groups(names)
        self.s1_cols = np.concatenate([g["frontal"], g["mus_base"]])
        self.s1 = _stage_pipe(len(self.s1_cols))
        self.s2a = KNeighborsTimeSeriesClassifier(
            n_neighbors=DTW_K, metric="dtw",
            metric_params={"sakoe_chiba_radius": DTW_RADIUS}, n_jobs=-1)
        self.s2b = build_ts_svm(tsupdate=False, probability=True)

    def fit(self, F, waveforms, epochs_raw, y) -> "DtwRiemannHybridClassifier":
        self.s1.fit(F[:, self.s1_cols], np.isin(y, MUSCLE_LABELS).astype(int))
        bl = np.isin(y, BLINK_LABELS)
        self.s2a.fit(waveforms[bl], y[bl])
        mu = np.isin(y, MUSCLE_LABELS)
        self.s2b.fit(epochs_raw[mu], y[mu])
        return self

    def predict(self, F, waveforms, epochs_raw) -> np.ndarray:
        return self.predict_path(F, waveforms, epochs_raw)[0]

    def predict_path(self, F, waveforms, epochs_raw):
        """Labels + joint path confidence ``P(branch)*P(class|branch)``; the blink
        branch's class probability is the DTW-KNN neighbour fraction."""
        n = F.shape[0]
        labels = np.empty(n, dtype=int)
        conf = np.empty(n, dtype=float)
        p1 = self.s1.predict_proba(F[:, self.s1_cols])
        bi = np.argmax(p1, axis=1)
        p_branch = p1[np.arange(n), bi]
        branch = self.s1.classes_[bi]
        bl = np.where(branch == 0)[0]
        mu = np.where(branch == 1)[0]
        if bl.size:
            p2 = self.s2a.predict_proba(waveforms[bl])
            j = np.argmax(p2, axis=1)
            labels[bl] = self.s2a.classes_[j]
            conf[bl] = p_branch[bl] * p2[np.arange(bl.size), j]
        if mu.size:
            p3 = self.s2b.predict_proba(epochs_raw[mu])
            j = np.argmax(p3, axis=1)
            labels[mu] = self.s2b.classes_[j]
            conf[mu] = p_branch[mu] * p3[np.arange(mu.size), j]
        return labels, conf


def save(model, path: str | Path = cfg.HIER_MODEL_PATH) -> Path:
    """Persist a fitted hierarchical / hybrid model (all stages + routing)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out)
    return out.resolve()


def load(path: str | Path = cfg.HIER_MODEL_PATH):
    """Load a fitted hierarchical / hybrid model from disk."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"model not found: {p.resolve()} -- train it with "
            f"`python -m eeg_bci.train_hierarchical` (or train_hybrid).")
    return joblib.load(p)
