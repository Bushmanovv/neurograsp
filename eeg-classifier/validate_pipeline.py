"""Pipeline validation - sanity-check every stage and report pass/fail.

Runs each stage of the EEG-BCI pipeline end to end and prints a single
pass/fail report. Uses the already-trained ``models/best_model.pkl`` (does not
retrain). Run with zero arguments::

    python validate_pipeline.py
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path

import numpy as np
import joblib

from eeg_bci import config as cfg


def _quiet(fn, *args, **kwargs):
    """Call ``fn`` while swallowing its stdout (keeps the report clean).

    Args:
        fn: Callable to invoke.
        *args: Positional arguments for ``fn``.
        **kwargs: Keyword arguments for ``fn``.

    Returns:
        Whatever ``fn`` returns.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _check_config() -> tuple[bool, str]:
    """Verify all expected config params are present and DATA_ROOT exists.

    Returns:
        (passed, detail message).
    """
    required = [
        "DATA_ROOT", "MODEL_PATH", "CROP_SECONDS", "SFREQ", "NOTCH_HZ",
        "BANDPASS_HZ", "EPOCH_SEC", "EPOCH_OVERLAP", "REJECT_UV", "WINDOW_SEC",
        "STEP_SEC", "FSM_THRESH", "SERIAL_BAUD", "SERIAL_PORT", "LABEL_MAP",
        "NOISY_FILES", "COMMAND_MAP", "FRONTAL_CH", "TEMPORAL_CH", "ALL_CH",
        "BANDS", "SELECT_K",
    ]
    missing = [p for p in required if not hasattr(cfg, p)]
    if missing:
        return False, f"missing params: {missing}"
    if not Path(cfg.DATA_ROOT).is_dir():
        return False, f"DATA_ROOT not found: {cfg.DATA_ROOT}"
    return True, "all params present, paths exist"


def _check_loader() -> tuple[bool, str, list]:
    """Verify the loader finds and labels every EDF file.

    Returns:
        (passed, detail, recordings list).
    """
    from eeg_bci.loader import discover_recordings

    recs = _quiet(discover_recordings)
    n_edf = sum(
        1 for s in Path(cfg.DATA_ROOT).glob("Session*")
        for _ in s.rglob("*") if _.suffix.lower() == ".edf"
    )
    ok = len(recs) == n_edf and n_edf > 0
    return ok, f"{len(recs)}/{n_edf} EDF files found and labeled", recs


def _check_preprocessing(recs) -> tuple[bool, str, np.ndarray, np.ndarray]:
    """Verify preprocessing yields consistent-shape epochs.

    Args:
        recs: Recordings from the loader.

    Returns:
        (passed, detail, X epochs, y labels).
    """
    from eeg_bci.preprocessing import preprocess_all

    x, y, _ = _quiet(preprocess_all, recs)
    n_samp = int(round(cfg.EPOCH_SEC * cfg.SFREQ))
    shape_ok = x.ndim == 3 and x.shape[1] == len(cfg.ALL_CH) and x.shape[2] == n_samp
    ok = shape_ok and x.shape[0] == y.shape[0]
    return ok, f"{x.shape[0]} epochs, shape {x.shape}, zero shape mismatch", x, y


def _check_features(x) -> tuple[bool, str, np.ndarray]:
    """Verify feature extraction produces a finite matrix matching the names.

    Args:
        x: Epoch array.

    Returns:
        (passed, detail, feature matrix).
    """
    from eeg_bci.features import extract_features, feature_names

    feat = _quiet(extract_features, x)
    n_names = len(feature_names())
    ok = (
        feat.shape[1] == n_names
        and not np.isnan(feat).any()
        and not np.isinf(feat).any()
    )
    return ok, f"{feat.shape} matrix, 0 NaN, 0 Inf", feat


def _check_train() -> tuple[bool, str, object]:
    """Verify the saved model exists and loads cleanly.

    Returns:
        (passed, detail, loaded pipeline or None).
    """
    path = Path(cfg.MODEL_PATH)
    if not path.is_file():
        return False, f"{cfg.MODEL_PATH} missing", None
    try:
        pipe = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        return False, f"load failed: {exc}", None
    return True, f"{cfg.MODEL_PATH} exists, loads clean", pipe


def _check_model_input(pipe, feat) -> tuple[bool, str]:
    """Verify extracted feature width matches what the pipeline expects.

    Args:
        pipe: Loaded pipeline (or None).
        feat: Extracted feature matrix (or None).

    Returns:
        (passed, detail).
    """
    from eeg_bci.features import feature_names

    if pipe is None or feat is None:
        return False, "skipped (model or features unavailable)"
    expected = getattr(pipe.steps[0][1], "n_features_in_", None)
    n_names = len(feature_names())
    ok = expected == n_names == feat.shape[1]
    return ok, f"pipeline expects {expected}, features provide {n_names}"


def _check_file(rel_path: str) -> tuple[bool, str]:
    """Check whether a pipeline module file exists yet.

    Args:
        rel_path: Path relative to the project root.

    Returns:
        (exists, detail).
    """
    if Path(rel_path).is_file():
        return True, "present"
    return False, "not built yet"


def main() -> None:
    """Run all stage checks and print the validation report."""
    line = "═" * 50
    print(line)
    print(" Pipeline Validation Report")
    print(line)

    results: list[tuple[str, bool, str]] = []

    ok, detail = _check_config()
    results.append(("config.py", ok, detail))

    recs = []
    try:
        ok, detail, recs = _check_loader()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"error: {exc}"
    results.append(("loader.py", ok, detail))

    x = y = feat = pipe = None
    try:
        ok, detail, x, y = _check_preprocessing(recs)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"error: {exc}"
    results.append(("preprocessing.py", ok, detail))

    try:
        ok, detail, feat = _check_features(x) if x is not None else (False, "skipped", None)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"error: {exc}"
    results.append(("features.py", ok, detail))

    try:
        ok, detail, pipe = _check_train()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"error: {exc}"
    results.append(("train.py", ok, detail))

    try:
        ok, detail = _check_model_input(pipe, feat)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"error: {exc}"
    results.append(("model input", ok, detail))

    ok, detail = _check_file("eeg_bci/inference.py")
    results.append(("inference.py", ok, detail))
    ok, detail = _check_file("run_test.py")
    results.append(("run_test.py", ok, detail))

    for name, passed, detail in results:
        mark = "✓" if passed else "✗"
        print(f" [{mark}] {name:<16s} — {detail}")

    n_pass = sum(1 for _, p, _ in results if p)
    print(line)
    print(f" Stages passing: {n_pass}/{len(results)}")
    print(line)


if __name__ == "__main__":
    main()
