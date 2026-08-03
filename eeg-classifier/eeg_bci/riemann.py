"""Riemannian-geometry pipelines (covariance-based, amplitude-drift invariant).

These classify on the per-epoch inter-channel COVARIANCE matrix rather than
hand-crafted amplitude features. The affine-invariant Riemannian metric is exactly
invariant to a global congruent transform ``C -> A C A^T``; a session-to-session
amplitude rescaling is the special case ``A = s*I``, which the metric cancels --
the property that should make this robust to the day-to-day drift that broke the
TKEO/amplitude features (see eval_loso.py).

Input is the RAW filtered+CAR epoch tensor ``(n_epochs, n_channels, n_times)`` in
volts (NOT the per-recording z-scored signal -- z-scoring per channel would distort
the covariance structure these methods rely on). All 19 channels are used.

``estimator='oas'`` (Oracle Approximating Shrinkage) is required, not just "robust":
CAR makes the sample covariance rank-deficient (rank 18 of 19), so the plain SCM is
only positive *semi*-definite; OAS shrinks toward scaled identity, restoring a
strictly SPD matrix that TangentSpace/MDM need.

Builders (opt-in model options; current models untouched):
    build_ts_svm(tsupdate=False) -- Covariances(oas) -> TangentSpace(riemann) -> SVC(rbf)
    build_mdm()                  -- Covariances(oas) -> MDM(riemann)  (minimum-distance-to-mean)
``tsupdate=True`` re-centres the tangent space on each transform batch, correcting
covariate shift between the train and the unseen test session automatically.
"""

from __future__ import annotations

from pyriemann.classification import MDM
from pyriemann.estimation import Covariances
from pyriemann.tangentspace import TangentSpace
from sklearn.pipeline import make_pipeline
from sklearn.svm import SVC

from eeg_bci import config as cfg

# Covariance estimator: OAS shrinkage -> strictly SPD even after CAR.
COV_ESTIMATOR = "oas"
RIEMANN_METRIC = "riemann"


def build_ts_svm(tsupdate: bool = False, probability: bool = False):
    """Covariances(oas) -> TangentSpace(riemann) -> SVC(rbf, balanced).

    Args:
        tsupdate: If ``True``, recompute the tangent-space reference on each
            transform batch (unsupervised recentering), which corrects amplitude/
            covariance covariate shift between train and the held-out session.
            NOTE: fragile on small/heterogeneous test batches (collapses on the
            GroupKFold dev protocol); default off -- plain TS+SVM is robust on both.
        probability: If ``True``, enable ``predict_proba`` (Platt scaling) -- needed
            for the inference confidence gate; off for plain benchmarking.

    Returns:
        An unfitted scikit-learn pipeline taking raw epochs ``(n, ch, t)``. The raw
        epochs MUST be in the same amplitude units at train and predict time (the
        tangent-space reference is fit in the training units; a unit mismatch shifts
        every tangent vector and breaks predictions).
    """
    return make_pipeline(
        Covariances(estimator=COV_ESTIMATOR),
        TangentSpace(metric=RIEMANN_METRIC, tsupdate=tsupdate),
        SVC(kernel="rbf", class_weight="balanced", probability=probability,
            random_state=cfg.RANDOM_STATE),
    )


def build_mdm():
    """Covariances(oas) -> MDM(riemann): minimum distance to the Riemannian mean.

    The simplest, most robust Riemannian classifier -- one geometric mean per
    class, assign the nearest. No tangent-space projection, nothing to overfit.

    Returns:
        An unfitted scikit-learn pipeline taking raw epochs ``(n, ch, t)``.
    """
    return make_pipeline(
        Covariances(estimator=COV_ESTIMATOR),
        MDM(metric=RIEMANN_METRIC),
    )
