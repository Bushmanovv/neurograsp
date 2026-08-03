"""Benchmark Riemannian pipelines vs the current best (flat RF / hierarchical).

Both honest protocols on the IDENTICAL gated epochs:
  * LOSO  (train S1+S2 -> test S3, plus 3-fold mean) -- the strict cross-session test.
  * 5-fold StratifiedGroupKFold by recording                -- the dev protocol.

Models:
  1. Flat RF (current)          -- 93 hand-crafted features, gated RF.
  2. Hierarchical (current)     -- 2-stage, 117-feat superset.
  3. Riemann TS + SVM           -- Covariances(oas) -> TangentSpace -> SVC(rbf).
  4. Riemann MDM                -- Covariances(oas) -> MDM.
  5. Riemann TS + SVM (tsupdate)-- recentres tangent space per batch (covariate shift).
  6. Hybrid                     -- hierarchy with Stage 2b (C/L/R) replaced by a
                                   Riemannian TS+SVM(tsupdate) on raw 19-ch covariance,
                                   where amplitude drift hurt the feature model most.

Riemannian models take the RAW filtered+CAR epoch tensor (all 19 channels); the
feature models take the per-recording z-scored features. Same gated rows for all.

Run:  python -m eeg_bci.eval_riemann
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold

from eeg_bci import config as cfg
from eeg_bci import features
from eeg_bci.activity_gate import activity_scores, gate_mask
from eeg_bci.hierarchical import (
    BLINK_LABELS, MUSCLE_LABELS, HierarchicalClassifier, RiemannHybridClassifier,
    extract_superset, superset_names)
from eeg_bci.loader import discover_recordings
from eeg_bci.preprocessing import preprocess_all_dual
from eeg_bci.riemann import build_mdm, build_ts_svm
from eeg_bci.train import build_classifiers, build_pipeline

_GATE_FRAC = 0.5
_LABELS = [0, 1, 2, 3, 4]
_COL_NAMES = ["S-F1", "O-F1", "C-F1", "L-F1", "R-F1"]


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# Globals populated in run() and read by the per-model fold predictors.
_G: dict = {}


def _metrics(y_true, y_pred):
    return (accuracy_score(y_true, y_pred),
            f1_score(y_true, y_pred, labels=_LABELS, average="macro"),
            f1_score(y_true, y_pred, labels=_LABELS, average=None))


# --- per-model fold predictors: (train_idx, test_idx) -> y_pred on test ------ #
def flat_fold(tr, te):
    m = build_pipeline(build_classifiers()["RandomForest"]).fit(_G["Fb"][tr], _G["y"][tr])
    return m.predict(_G["Fb"][te])


def hier_fold(tr, te):
    m = HierarchicalClassifier(_G["names"]).fit(_G["Fs"][tr], _G["y"][tr])
    return m.predict(_G["Fs"][te])


def _riemann_raw_fold(tr, te, pipe):
    m = pipe.fit(_G["Xuv"][tr], _G["y"][tr])
    return m.predict(_G["Xuv"][te])


def ts_svm_fold(tr, te):
    return _riemann_raw_fold(tr, te, build_ts_svm(tsupdate=False))


def mdm_fold(tr, te):
    return _riemann_raw_fold(tr, te, build_mdm())


def ts_svm_upd_fold(tr, te):
    return _riemann_raw_fold(tr, te, build_ts_svm(tsupdate=True))


def hybrid_fold(tr, te, tsupdate=False):
    """Hierarchy with a Riemannian Stage 2b (C/L/R) on raw 19-ch covariance.

    Stage 1 (blink/muscle) and Stage 2a (S/O) stay feature-based -- blinks are a
    temporal pattern covariance can't see. Stage 2b (C/L/R) becomes Riemannian,
    where amplitude drift broke the feature model.
    """
    Fs, y, Xuv, names = _G["Fs"], _G["y"], _G["Xuv"], _G["names"]
    h = HierarchicalClassifier(names)
    ytr = y[tr]
    h.s1.fit(Fs[tr][:, h.s1_cols], np.isin(ytr, MUSCLE_LABELS).astype(int))
    bl = np.isin(ytr, BLINK_LABELS)
    h.s2a.fit(Fs[tr][bl][:, h.s2a_cols], ytr[bl])
    mu = np.isin(ytr, MUSCLE_LABELS)
    s2b = build_ts_svm(tsupdate=tsupdate).fit(Xuv[tr][mu], ytr[mu])

    Fte, Xte = Fs[te], Xuv[te]
    branch = h.s1.predict(Fte[:, h.s1_cols])
    out = np.empty(len(te), dtype=int)
    bi, mi = np.where(branch == 0)[0], np.where(branch == 1)[0]
    if bi.size:
        out[bi] = h.s2a.predict(Fte[bi][:, h.s2a_cols])
    if mi.size:
        out[mi] = s2b.predict(Xte[mi])
    return out


def hybrid_ts_fold(tr, te):
    """Production hybrid (RiemannHybridClassifier, probability=True) -- verifies the
    shipped class reproduces the benchmark."""
    m = RiemannHybridClassifier(_G["names"]).fit(_G["Fs"][tr], _G["Xuv"][tr], _G["y"][tr])
    return m.predict(_G["Fs"][te], _G["Xuv"][te])


def hybrid_upd_fold(tr, te):
    return hybrid_fold(tr, te, tsupdate=True)


MODELS = [
    ("Flat RF (current)", flat_fold),
    ("Hierarchical (current)", hier_fold),
    ("Riemann TS + SVM", ts_svm_fold),
    ("Riemann MDM", mdm_fold),
    ("Riemann TS + SVM (tsupdate)", ts_svm_upd_fold),
    ("Hybrid (Riemann S2b, TS+SVM)", hybrid_ts_fold),
    ("Hybrid (Riemann S2b, tsupdate)", hybrid_upd_fold),
]


def _single_fold(tr, te, fn):
    return _metrics(_G["y"][te], fn(tr, te))


def _loso_mean(sessions, fn):
    accs, macs, per = [], [], np.zeros(5)
    for s in sessions:
        te = np.where(_G["sess"] == s)[0]
        tr = np.where(_G["sess"] != s)[0]
        a, m, p = _single_fold(tr, te, fn)
        accs.append(a); macs.append(m); per += p
    return np.mean(accs), np.mean(macs), per / len(sessions)


def _groupkfold(fn):
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=cfg.RANDOM_STATE)
    yt, yp = [], []
    for tr, te in cv.split(_G["Fs"], _G["y"], _G["g"]):
        yt.append(_G["y"][te]); yp.append(fn(tr, te))
    return _metrics(np.concatenate(yt), np.concatenate(yp))


def _table(title, rows):
    print("\n" + "=" * 78)
    print(f" {title}")
    print("=" * 78)
    print(f" {'Model':<30}{'Overall':>9}{'macroF1':>9}" +
          "".join(f"{c:>7}" for c in _COL_NAMES))
    print("-" * 78)
    for name, (acc, mac, per) in rows:
        print(f" {name:<30}{acc*100:>8.1f}%{mac:>9.3f}" +
              "".join(f"{per[l]:>7.3f}" for l in _LABELS))
    print("=" * 78)


def run() -> None:
    recs = discover_recordings()
    X, Xuv, y, groups = preprocess_all_dual(recs)
    sess = np.array([recs[g].session for g in groups])
    keep = gate_mask(activity_scores(Xuv, y), y, groups, frac=_GATE_FRAC)

    _G["names"] = superset_names()
    _G["y"] = y[keep]
    _G["g"] = groups[keep]
    _G["sess"] = sess[keep]
    _G["Xuv"] = Xuv[keep]                              # raw filtered+CAR epochs (volts)
    _G["Fs"] = _quiet(extract_superset, X[keep], Xuv[keep])   # 117 feats (hier)
    _G["Fb"] = _quiet(features.extract_features, X[keep])     # 93 feats (flat)

    print(f"\n[riemann] gated frac={_GATE_FRAC}: {keep.sum()} epochs, "
          f"raw tensor {tuple(_G['Xuv'].shape)}, class counts {np.bincount(_G['y'])}")
    sessions = sorted(np.unique(_G["sess"]))

    s3_rows, mean_rows, gkf_rows = [], [], []
    for name, fn in MODELS:
        te = np.where(_G["sess"] == "Session3")[0]
        tr = np.where(_G["sess"] != "Session3")[0]
        s3_rows.append((name, _single_fold(tr, te, fn)))
        mean_rows.append((name, _loso_mean(sessions, fn)))
        gkf_rows.append((name, _groupkfold(fn)))
        print(f"[riemann] {name:<30} done "
              f"(LOSO-S3 {s3_rows[-1][1][0]*100:.1f}%, "
              f"GKF {gkf_rows[-1][1][0]*100:.1f}%)")

    _table("LOSO  train S1+S2 -> test S3  (the requested fold)", s3_rows)
    _table("LOSO  3-fold MEAN (hold out each session)", mean_rows)
    _table("5-fold StratifiedGroupKFold by recording (dev protocol)", gkf_rows)


if __name__ == "__main__":
    run()
