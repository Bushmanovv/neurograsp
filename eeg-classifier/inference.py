"""Real-time inference: stream an EDF and emit prosthetic-hand commands.

Deployment-faithful version of the pipeline. For each sliding window it runs an
ACTIVITY GATE first (frontal/temporal RMS in µV) and only classifies windows that
contain a gesture -- never rest -- because that is the task the gated model
(models/best_model_gated.pkl) was trained on (see eeg_bci/activity_gate.py and
eeg_bci/eval_gated.py). A 3-in-a-row finite-state machine debounces the
per-window predictions into a single confirmed command, which is sent to the
ESP32 hand firmware over UART as a Contract A label line (or simulated). While
idle it resends ``rest`` as a heartbeat so the firmware's fail-safe never trips.

Flow per file::

    Load EDF -> notch -> bandpass -> CAR (full signal, NO crop)
    slide 1.5 s window, 0.2 s step:
        activity = max(rms(frontal µV), rms(temporal µV))
        if activity < ACTIVITY_THRESHOLD:        -> rest, skip (reset FSM)
        feat = extract_epoch(z-scored window)    -> 93 features
        proba = gated_model.predict_proba(feat)
        if max(proba) < CONF_THRESH:             -> low-confidence, skip (reset FSM)
        if FSM sees FSM_THRESH identical in a row -> CONFIRM command, send label line

``--model`` selects the classifier behind the (identical) gate + confidence + FSM:
``dtw`` (default, best 91.7% LOSO) routes blink/muscle on features, classifies single
vs double blink by DTW waveform-shape matching (DTW-KNN) and muscle C/L/R on the raw
19-channel covariance (Riemannian); ``hybrid`` is the same but with a feature-based
blink stage; ``hierarchical`` is the all-feature 2-stage router; ``flat`` is the gated
RandomForest (93 features). All share this exact inference path (gate + joint-path
confidence + FSM), so they are directly comparable live.

The gate, preprocessing and FSM live here as importable helpers so run_test.py
reuses the exact same inference path on held-out data.

CLI::

    python inference.py --file path/to.edf [--model hybrid|hierarchical|flat]
                        [--port /dev/serial0] [--no-serial] [--quiet]
                        [--threshold 0.65] [--activity 20]

The serial port defaults to cfg.SERIAL_PORT (``$EEG_SERIAL_PORT`` or
``/dev/serial0`` on a Pi). The emitted label strings are Contract A, shared
with the ESP32 firmware (hand-firmware/include/contracts.h).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import joblib
import mne
import numpy as np

from eeg_bci import config as cfg
from eeg_bci import hierarchical
from eeg_bci.features import extract_epoch
from eeg_bci.preprocessing import filter_and_car, normalize_per_recording

mne.set_log_level("ERROR")

_V_TO_UV = 1e6
_UV_TO_V = 1e-6

# Sliding-window geometry (samples).
WINDOW_SAMPLES = int(round(cfg.WINDOW_SEC * cfg.SFREQ))
STEP_SAMPLES = int(round(cfg.STEP_SEC * cfg.SFREQ))

# Gate channel indices into the canonical montage.
_FRONTAL_IDX = [cfg.ALL_CH.index(c) for c in cfg.FRONTAL_CH]
_TEMPORAL_IDX = [cfg.ALL_CH.index(c) for c in cfg.TEMPORAL_CH]

# label index -> class name (all clinch stems share the name "clinch").
_LABEL_NAME = {lbl: name for (lbl, name) in cfg.LABEL_MAP.values()}


# --------------------------------------------------------------------------- #
# Activity gate
# --------------------------------------------------------------------------- #
def _rms(sig: np.ndarray) -> float:
    """Root-mean-square over every element of ``sig`` (channels pooled)."""
    return float(np.sqrt(np.mean(sig ** 2)))


def window_activity(window_uv: np.ndarray) -> float:
    """Activity score of one window: ``max(frontal RMS, temporal RMS)`` in µV.

    Label-agnostic (we do not yet know the gesture) version of the training-time
    gate in :mod:`eeg_bci.activity_gate`. Frontal RMS catches blinks, temporal
    RMS catches jaw gestures; the louder of the two decides "gesture present".

    Args:
        window_uv: Window in microvolts, shape ``(n_channels, n_samples)``,
            channels ordered as ``config.ALL_CH`` (filtered + CAR, NOT z-scored).

    Returns:
        Activity score in microvolts.
    """
    frontal_rms = _rms(window_uv[_FRONTAL_IDX])
    temporal_rms = _rms(window_uv[_TEMPORAL_IDX])
    return max(frontal_rms, temporal_rms)


# --------------------------------------------------------------------------- #
# Preprocessing (full signal, no crop)
# --------------------------------------------------------------------------- #
def load_edf(path: str | Path) -> mne.io.BaseRaw:
    """Read an EDF and reorder channels to the canonical montage.

    Args:
        path: Path to the ``.edf`` file.

    Returns:
        A preloaded raw object whose channels are ordered as ``config.ALL_CH``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If any canonical channel is missing (the feature/gate code
            indexes by position, so a partial montage would silently mis-align).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"EDF not found: {p.resolve()}")
    raw = mne.io.read_raw_edf(p, preload=True, verbose="ERROR")
    missing = [c for c in cfg.ALL_CH if c not in raw.ch_names]
    if missing:
        raise ValueError(
            f"{p.name} is missing channels {missing}; inference needs the full "
            f"19-channel montage ({cfg.ALL_CH}).")
    raw.reorder_channels(list(cfg.ALL_CH))
    return raw


def preprocess_stream(raw: mne.io.BaseRaw) -> tuple[np.ndarray, np.ndarray]:
    """Notch -> bandpass -> CAR the full signal, returning µV and z-scored copies.

    Mirrors the dual-domain training preprocessing (``preprocess_recording_dual``)
    but without cropping or epoching: the activity gate needs raw microvolts while
    feature extraction needs the per-recording z-scored signal.

    Args:
        raw: Raw object with the canonical montage (modified in place).

    Returns:
        Tuple ``(data_uv, data_norm)``, each ``(n_channels, n_samples)``.
        ``data_uv`` is microvolts (for the gate); ``data_norm`` is per-recording
        z-scored (for :func:`eeg_bci.features.extract_epoch`).
    """
    filter_and_car(raw)
    data_uv = raw.get_data() * _V_TO_UV
    normalize_per_recording(raw)
    data_norm = raw.get_data()
    return data_uv, data_norm


# --------------------------------------------------------------------------- #
# Finite-state machine (debounce predictions into a confirmed command)
# --------------------------------------------------------------------------- #
class CommandFSM:
    """Confirm a command after ``n`` consecutive identical window predictions.

    Any break in the streak -- a rest window, a low-confidence window, or a
    different prediction -- resets the count, so a command only fires when the
    same gesture is held cleanly. Firing also resets, so holding the gesture
    longer does not re-fire every step.
    """

    def __init__(self, n: int = cfg.FSM_THRESH) -> None:
        self.n = n
        self.last: int | None = None
        self.count = 0

    def update(self, label: int) -> bool:
        """Feed one accepted prediction; return ``True`` if it confirms a command.

        Args:
            label: The predicted class label for this window.

        Returns:
            ``True`` exactly on the window that completes ``n`` in a row.
        """
        if label == self.last:
            self.count += 1
        else:
            self.last = label
            self.count = 1
        if self.count >= self.n:
            self.reset()
            return True
        return False

    def reset(self) -> None:
        """Clear the streak (called on a skipped window or after a command)."""
        self.last = None
        self.count = 0


# --------------------------------------------------------------------------- #
# Serial link to the ESP32 hand firmware (Contract A)
# --------------------------------------------------------------------------- #
# CONTRACT A -- shared with the ESP32 hand firmware's include/contracts.h
# (VALID_LABELS) and tools/fake_pi.py. The label STRINGS written here are the
# wire contract: one lower_snake_case label per line, `\n`-terminated, 8N1 at
# cfg.SERIAL_BAUD. The firmware logs+ignores any string not in VALID_LABELS, so
# a typo fails SILENTLY (the hand just does nothing). If either side's label set
# changes, cfg.CONTRACT_A_LABELS here and VALID_LABELS there MUST be updated
# together. The five gesture labels are the classifier's own class names
# (cfg.LABEL_MAP), so they cannot drift from the model; `rest` is the idle
# label and link heartbeat.
class SerialSender:
    """Write Contract A label lines to the ESP32 over UART, or simulate.

    Also owns the idle heartbeat: :meth:`maybe_heartbeat` resends ``rest`` when
    ``cfg.REST_HEARTBEAT_SEC`` has elapsed since the last write, so the
    firmware's 3 s fail-safe never trips during no-gesture periods.
    """

    def __init__(self, port: str | None, baud: int = cfg.SERIAL_BAUD,
                 enabled: bool = True, *, clock=time.monotonic) -> None:
        self.ser = None
        self._clock = clock            # injectable for deterministic testing
        self._last_send: float | None = None
        if not enabled:
            print(f"[serial] --no-serial: simulation mode (labels printed only)")
            return
        try:
            import serial  # pyserial; imported lazily so --no-serial needs no dep
            # 8N1 is pyserial's default (bytesize=8, parity=N, stopbits=1),
            # matching the firmware's SERIAL_8N1 -- set explicitly to be safe.
            self.ser = serial.Serial(
                port, baud, timeout=1,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE)
            print(f"[serial] opened {port} @ {baud} baud 8N1 (Contract A)")
        except Exception as exc:  # noqa: BLE001 - any failure -> simulate
            print(f"[serial] no port available ({type(exc).__name__}: {exc}); "
                  f"simulation mode")
            self.ser = None

    def send_label(self, label: str) -> None:
        """Write one Contract A label as its own line (``label + "\\n"``, UTF-8).

        Labels are pure ASCII, so UTF-8 is byte-identical to the firmware's and
        fake_pi.py's ASCII encoding. Guards against sending a label the firmware
        would silently ignore.
        """
        if label not in cfg.CONTRACT_A_LABELS:
            raise ValueError(
                f"{label!r} is not a Contract A label {sorted(cfg.CONTRACT_A_LABELS)}; "
                f"the ESP32 firmware would log and ignore it")
        line = f"{label}\n"
        if self.ser is None:
            print(f"        [SIM] would send: {line!r}")
        else:
            self.ser.write(line.encode("utf-8"))
        self._last_send = self._clock()

    def maybe_heartbeat(self) -> bool:
        """Resend ``rest`` if the heartbeat interval has elapsed (or none sent yet).

        Called on every window that does NOT fire a gesture command. Returns
        ``True`` if a heartbeat was actually sent this call.
        """
        now = self._clock()
        if self._last_send is None or (now - self._last_send) >= cfg.REST_HEARTBEAT_SEC:
            self.send_label(cfg.REST_LABEL)
            return True
        return False

    def close(self) -> None:
        """Close the serial port if one is open."""
        if self.ser is not None:
            self.ser.close()


# --------------------------------------------------------------------------- #
# Model predictors -- uniform .classify(window_norm, window_uv) -> (label, conf)
#
# Both wrap a loaded model so the streaming loop, gate, confidence gate and FSM
# are identical regardless of which model is used. The flat predictor extracts the
# 93-feature vector and reads max predict_proba; the hierarchical predictor
# extracts the 129-feature superset (blink-peak feats need raw µV) and reads the
# joint path probability P(branch)*P(class|branch).
# --------------------------------------------------------------------------- #
class FlatPredictor:
    """The activity-gated flat pipeline (models/best_model_gated.pkl)."""

    kind = "flat"

    def __init__(self, model):
        self.model = model
        classes = getattr(model, "classes_", None)
        if classes is None:                          # imblearn Pipeline fallback
            classes = model.steps[-1][1].classes_
        self.classes = classes

    def classify(self, window_norm: np.ndarray, window_uv: np.ndarray):
        feat = extract_epoch(window_norm).reshape(1, -1)
        proba = self.model.predict_proba(feat)[0]
        j = int(np.argmax(proba))
        return int(self.classes[j]), float(proba[j])


class HierPredictor:
    """The 2-stage hierarchical router (models/hierarchical_model.pkl)."""

    kind = "hierarchical"

    def __init__(self, model: "hierarchical.HierarchicalClassifier"):
        self.model = model

    def classify(self, window_norm: np.ndarray, window_uv: np.ndarray):
        # Blink-peak features need the window in raw µV-as-volts (extract scales
        # by 1e6 internally), so convert the µV gate window back to volts.
        feat = hierarchical.extract_superset_epoch(
            window_norm, window_uv * _UV_TO_V).reshape(1, -1)
        labels, conf = self.model.predict_path(feat)
        return int(labels[0]), float(conf[0])


class HybridPredictor:
    """Hierarchy with a Riemannian Stage 2b (models/hybrid_model.pkl) -- the default.

    Stage 1/2a are feature-based (117-feat superset); Stage 2b classifies the raw
    19-channel covariance. The raw window MUST be in VOLTS (the units the Riemannian
    tangent space was fit in) -- the gate window is in µV, so convert it.
    """

    kind = "hybrid"

    def __init__(self, model: "hierarchical.RiemannHybridClassifier"):
        self.model = model

    def classify(self, window_norm: np.ndarray, window_uv: np.ndarray):
        window_v = window_uv * _UV_TO_V
        feat = hierarchical.extract_superset_epoch(window_norm, window_v).reshape(1, -1)
        epoch_raw = window_v[np.newaxis, :, :]          # (1, n_ch, n_times), volts
        labels, conf = self.model.predict_path(feat, epoch_raw)
        return int(labels[0]), float(conf[0])


class DtwHybridPredictor:
    """Hybrid with a DTW-KNN Stage 2a (models/dtw_hybrid_model.pkl) -- the default.

    Stage 1 features + Stage 2a DTW-KNN on the blink waveform + Stage 2b Riemannian
    muscle covariance. Needs the feature superset (Stage 1), the per-window blink
    waveform (Stage 2a; z-scored per window, so scale-free) and the raw window in
    VOLTS (Stage 2b -- the Riemann same-units rule).
    """

    kind = "dtw"

    def __init__(self, model: "hierarchical.DtwRiemannHybridClassifier"):
        self.model = model

    def classify(self, window_norm: np.ndarray, window_uv: np.ndarray):
        window_v = window_uv * _UV_TO_V
        feat = hierarchical.extract_superset_epoch(window_norm, window_v).reshape(1, -1)
        wave = hierarchical.blink_waveform(window_uv[np.newaxis, :, :])   # (1, sz, 1)
        epoch_raw = window_v[np.newaxis, :, :]          # (1, n_ch, n_times), volts
        labels, conf = self.model.predict_path(feat, wave, epoch_raw)
        return int(labels[0]), float(conf[0])


def load_predictor(kind: str = "dtw", path: str | Path | None = None):
    """Build a predictor for the chosen model.

    Args:
        kind: ``"dtw"`` (default; DTW Stage 2a + Riemannian Stage 2b, best 91.7%
            LOSO), ``"hybrid"`` (Riemannian Stage 2b, feature Stage 2a),
            ``"hierarchical"`` (all-feature router) or ``"flat"`` (gated RF).
        path: Optional model-file override.

    Returns:
        A predictor exposing ``classify(window_norm, window_uv)``.

    Raises:
        FileNotFoundError: If the model file is missing.
        ValueError: If ``kind`` is unknown.
    """
    if kind == "dtw":
        p = Path(path or cfg.DTW_HYBRID_MODEL_PATH)
        model = hierarchical.load(p)
        print(f"[model] DTW-hybrid (Stage1 {len(model.s1_cols)}f / Stage2a DTW-KNN "
              f"k={model.s2a.n_neighbors} / Stage2b Riemann): {p}")
        return DtwHybridPredictor(model)
    if kind == "flat":
        p = Path(path or cfg.GATED_MODEL_PATH)
        if not p.exists():
            raise FileNotFoundError(
                f"gated model not found: {p.resolve()} -- train it with "
                f"`python -m eeg_bci.eval_gated`")
        print(f"[model] flat gated pipeline: {p}")
        return FlatPredictor(joblib.load(p))
    if kind == "hierarchical":
        p = Path(path or cfg.HIER_MODEL_PATH)
        model = hierarchical.load(p)
        print(f"[model] hierarchical router (Stage1 {len(model.s1_cols)}f, "
              f"Stage2a {len(model.s2a_cols)}f, Stage2b {len(model.s2b_cols)}f): {p}")
        return HierPredictor(model)
    if kind == "hybrid":
        p = Path(path or cfg.HYBRID_MODEL_PATH)
        model = hierarchical.load(p)
        print(f"[model] hybrid router (Stage1 {len(model.s1_cols)}f, "
              f"Stage2a {len(model.s2a_cols)}f, Stage2b Riemann TS+SVM): {p}")
        return HybridPredictor(model)
    raise ValueError(
        f"unknown --model {kind!r} (expected 'dtw', 'hybrid', 'hierarchical' or 'flat')")


def class_name(label: int) -> str:
    """Human-readable class name for a label index."""
    return _LABEL_NAME.get(label, cfg.COMMAND_MAP[label][1])


# --------------------------------------------------------------------------- #
# Core streaming loop
# --------------------------------------------------------------------------- #
def stream_windows(data_uv: np.ndarray, data_norm: np.ndarray, predictor,
                   *, start: int = 0, stop: int | None = None):
    """Yield per-window inference results over a (sub)range of a signal.

    Applies the activity gate, feature extraction and confidence gate to every
    sliding window; the FSM is left to the caller so run_test.py can reuse this.

    Args:
        data_uv: Microvolt signal ``(n_channels, n_samples)`` for the gate.
        data_norm: Z-scored signal (same shape) for feature extraction.
        predictor: Flat or hierarchical predictor with
            ``classify(window_norm, window_uv) -> (label, conf)``.
        start: First sample index to consider.
        stop: One-past-last sample index (defaults to the full length).

    Yields:
        Dict per window with keys ``t`` (s), ``activity`` (µV), ``status``
        (``"rest"`` / ``"low_conf"`` / ``"ok"``), and for non-rest windows
        ``label``, ``conf``, ``name``.
    """
    n = data_uv.shape[1] if stop is None else stop
    for s in range(start, n - WINDOW_SAMPLES + 1, STEP_SAMPLES):
        t = s / cfg.SFREQ
        win_uv = data_uv[:, s:s + WINDOW_SAMPLES]
        activity = window_activity(win_uv)
        if activity < cfg.ACTIVITY_THRESHOLD:
            yield {"t": t, "activity": activity, "status": "rest"}
            continue
        label, conf = predictor.classify(data_norm[:, s:s + WINDOW_SAMPLES], win_uv)
        status = "ok" if conf >= cfg.CONF_THRESH else "low_conf"
        yield {"t": t, "activity": activity, "status": status,
               "label": label, "conf": conf, "name": class_name(label)}


def _fmt_window(res: dict) -> str:
    """Format the standard '[t=..s] window -> name (conf: ..)' line."""
    return (f"[t={res['t']:04.1f}s] window → {res['name']:<14}"
            f"(conf: {res['conf']:.2f})")


def stream_file(path: str | Path, predictor, sender: SerialSender, *,
                quiet: bool = False) -> list[dict]:
    """Stream one EDF end to end, printing windows and firing confirmed commands.

    Args:
        path: EDF file to stream.
        predictor: Flat or hierarchical predictor (see :func:`load_predictor`).
        sender: Serial sender (real or simulated).
        quiet: If ``True``, print only confirmed commands.

    Returns:
        List of confirmed-command dicts ``{"t", "label", "char", "action",
        "name", "conf"}`` in fire order.
    """
    raw = load_edf(path)
    data_uv, data_norm = preprocess_stream(raw)
    dur = data_uv.shape[1] / cfg.SFREQ
    print(f"[stream] {Path(path).name}: {dur:.1f}s, "
          f"{(data_uv.shape[1] - WINDOW_SAMPLES) // STEP_SAMPLES + 1} windows "
          f"({cfg.WINDOW_SEC}s/{cfg.STEP_SEC}s), model={predictor.kind}, "
          f"gate>{cfg.ACTIVITY_THRESHOLD:g}µV  conf>{cfg.CONF_THRESH:.2f}\n")

    fsm = CommandFSM()
    confirmed: list[dict] = []
    for res in stream_windows(data_uv, data_norm, predictor):
        if res["status"] == "rest":
            fsm.reset()
            sender.maybe_heartbeat()          # keep the link alive during idle
            if not quiet:
                print(f"[t={res['t']:04.1f}s] --- rest{'':<15}(skipped)")
            continue
        if res["status"] == "low_conf":
            fsm.reset()
            sender.maybe_heartbeat()
            if not quiet:
                print(_fmt_window(res) + "  ✗ low-conf (skipped)")
            continue

        fired = fsm.update(res["label"])
        char, action = cfg.COMMAND_MAP[res["label"]]
        if fired:
            # res["name"] == class_name(label) == the Contract A gesture label.
            label = res["name"]
            sender.send_label(label)
            confirmed.append({"t": res["t"], "label": res["label"], "char": char,
                              "action": action, "name": label,
                              "conf": res["conf"]})
            line = (f"[t={res['t']:04.1f}s] ✓ COMMAND: {label} — {action}"
                    f"  (conf {res['conf']:.2f})") if quiet else (
                    _fmt_window(res) + f"  ✓ COMMAND: {label} — {action}")
            print(line)
        else:
            sender.maybe_heartbeat()          # gesture not yet confirmed -> idle
            if not quiet:
                print(_fmt_window(res))

    _print_summary(confirmed)
    return confirmed


def _print_summary(confirmed: list[dict]) -> None:
    """Print the closing list of confirmed commands."""
    print("\n" + "─" * 48)
    print(f" {len(confirmed)} command(s) confirmed")
    print("─" * 48)
    for c in confirmed:
        print(f"  [t={c['t']:05.1f}s]  {c['name']:<14} → {c['action']}")
    print("─" * 48)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_argparser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    p = argparse.ArgumentParser(
        description="Stream an EDF through the activity-gated BCI and emit commands.")
    p.add_argument("--file", required=True, help="EDF file to stream")
    p.add_argument("--model", choices=("dtw", "hybrid", "hierarchical", "flat"),
                   default="dtw",
                   help="dtw: DTW Stage2a + Riemann Stage2b (default; best 91.7%% LOSO); "
                        "hybrid: Riemann Stage2b only; hierarchical: all-feature; flat: gated RF")
    p.add_argument("--port", default=cfg.SERIAL_PORT,
                   help=f"ESP32 UART serial port (default {cfg.SERIAL_PORT}; "
                        f"or set $EEG_SERIAL_PORT)")
    p.add_argument("--no-serial", action="store_true",
                   help="simulation mode: never open a port, print sends")
    p.add_argument("--quiet", action="store_true",
                   help="show only confirmed commands (hide rest/window lines)")
    p.add_argument("--threshold", type=float, default=cfg.CONF_THRESH,
                   help=f"confidence threshold (default {cfg.CONF_THRESH})")
    p.add_argument("--activity", type=float, default=cfg.ACTIVITY_THRESHOLD,
                   help=f"activity-gate µV threshold (default {cfg.ACTIVITY_THRESHOLD:g})")
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = build_argparser().parse_args(argv)

    # Apply runtime overrides on the config so all helpers see one source.
    cfg.CONF_THRESH = args.threshold
    cfg.ACTIVITY_THRESHOLD = args.activity

    predictor = load_predictor(args.model)
    sender = SerialSender(args.port, enabled=not args.no_serial)
    try:
        stream_file(args.file, predictor, sender, quiet=args.quiet)
    finally:
        sender.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
