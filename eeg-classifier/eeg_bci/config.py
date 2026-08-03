"""Central configuration for the EEG-BCI pipeline.

ALL tunable parameters live here. No other module should hardcode paths,
sampling rates, frequency bands, label mappings, or serial settings.
Import what you need, e.g. ``from eeg_bci import config as cfg``.
"""

import os

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
DATA_ROOT        = r"DATA"                       # root folder scanned for Session*
MODEL_PATH       = r"models/best_model.pkl"      # ungated pipeline (classify every window)
GATED_MODEL_PATH = r"models/best_model_gated.pkl"  # activity-gated flat pipeline (inference --model flat)
HIER_MODEL_PATH  = r"models/hierarchical_model.pkl"  # 2-stage hierarchical model (inference --model hierarchical)
HYBRID_MODEL_PATH = r"models/hybrid_model.pkl"     # hierarchy w/ Riemannian Stage 2b (inference --model hybrid)
DTW_HYBRID_MODEL_PATH = r"models/dtw_hybrid_model.pkl"  # hybrid + DTW Stage 2a (inference --model dtw, DEFAULT; best 91.7% LOSO)

# --------------------------------------------------------------------------- #
# Signal / acquisition
# --------------------------------------------------------------------------- #
CROP_SECONDS = 40            # skip the first 40 s of every recording
SFREQ        = 200           # sampling frequency (Hz) of the EEG device
NOTCH_HZ     = 50.0          # mains notch frequency (Hz)
BANDPASS_HZ  = (1.0, 45.0)   # band-pass filter cutoffs (Hz)

# --------------------------------------------------------------------------- #
# Epoching / artifact rejection
# --------------------------------------------------------------------------- #
EPOCH_SEC     = 2.0          # epoch length (s)
EPOCH_OVERLAP = 0.5          # fractional overlap between consecutive epochs
REJECT_UV     = 500          # reject an epoch if any channel exceeds this (µV)

# --------------------------------------------------------------------------- #
# Real-time inference
# --------------------------------------------------------------------------- #
# MUST equal EPOCH_SEC: the gated model is trained on EPOCH_SEC-long epochs, and
# a shorter inference window skews predictions (1.5s read double-blink as triple).
WINDOW_SEC = 2.0             # sliding-window length (s) -- matches training epochs
STEP_SEC   = 0.2             # sliding-window step (s)
FSM_THRESH = 3               # consecutive identical predictions to fire a command
CONF_THRESH = 0.60           # min predict_proba to accept a window (override: --threshold)

# Activity gate (inference): a window is a gesture (not rest) only if the louder
# of its frontal (Fp1/Fp2) and temporal (T3/T4) RMS exceeds this, in microvolts.
# Label-agnostic absolute version of activity_gate.py (which is recording-relative
# and label-aware for training). Calibrated on the filtered+CAR signal: true rest
# windows sit at ~7-13 µV, active gestures at ~30-200 µV (blinks loudest), so 20 µV
# keeps the active ~50% and drops rest -- matching the training gate's keep-rate.
ACTIVITY_THRESHOLD = 20.0    # µV RMS

# --------------------------------------------------------------------------- #
# Serial link to the ESP32 hand firmware (Contract A)
# --------------------------------------------------------------------------- #
# The classifier now streams to the InMoov ESP32 hand over UART, NOT to a
# bench Arduino. It emits one lower_snake_case label per line (`\n`-terminated)
# on 8N1 at SERIAL_BAUD -- see CONTRACT_A_LABELS below and the shared contract
# in the firmware repo (hand-firmware/include/contracts.h, VALID_LABELS).
SERIAL_BAUD = 115200
# On a Raspberry Pi 5 the ESP32 link is the GPIO UART, typically /dev/serial0
# (a symlink to /dev/ttyAMA0). Override for other hosts, e.g.
#   EEG_SERIAL_PORT=/dev/ttyUSB0 python inference.py ...   (USB-serial on Linux)
#   EEG_SERIAL_PORT=COM3         python inference.py ...   (Windows bench test)
SERIAL_PORT = os.environ.get("EEG_SERIAL_PORT", "/dev/serial0")

# Contract A: the exact label strings the ESP32 firmware accepts. Any other
# string is logged and silently ignored by the firmware, so these MUST stay
# byte-for-byte identical to VALID_LABELS in hand-firmware/include/contracts.h
# (and tools/fake_pi.py). The five gesture labels are exactly the class names
# in LABEL_MAP below, so a gesture is sent as its own class name -- this cannot
# drift from the model. `rest` is the idle/no-gesture label and link heartbeat.
REST_LABEL = "rest"
CONTRACT_A_LABELS = frozenset({
    "single_blink", "double_blink", "clinch",
    "bruxism_left", "bruxism_right", REST_LABEL,
})

# Idle heartbeat: when no gesture is being emitted, resend `rest` at least this
# often (seconds) so the firmware's 3000 ms FAILSAFE_TIMEOUT_MS never trips
# during normal idle periods. Kept well under 3 s with margin.
REST_HEARTBEAT_SEC = 1.2

# --------------------------------------------------------------------------- #
# Label mapping: file stem -> (label index, class name)
# --------------------------------------------------------------------------- #
# 5-gesture taxonomy (2026-06-18): cleaned up from the old 6-class. Dropped
# triple_blink (the S<->T confusion) and the heterogeneous clinch mega-class --
# clinch is now ONLY bilateral clench; bilateral-bruxism (was mislabeled clinch)
# and clinch-left/right are excluded so each gesture is one pure, separable class.
# Recordings whose canonical stem is not listed here are skipped by the loader.
LABEL_MAP = {
    "BLINK02":       (0, "double_blink"),   # S - start/confirm
    "BLINK01":       (1, "single_blink"),   # O - open hand
    "GLENCHDOUBLE":  (2, "clinch"),         # C - close hand (bilateral clench only)
    "BRUXESLEFT":    (3, "bruxism_left"),   # L - rotate left
    "BRUXESRIGHT":   (4, "bruxism_right"),  # R - rotate right
}

# File stems that are known to be noisy: load them anyway but flag with [WARN].
NOISY_FILES = {"BLINK01", "BRUXESRIGHT"}

# --------------------------------------------------------------------------- #
# Command mapping: label index -> (Arduino char, human-readable action)
# --------------------------------------------------------------------------- #
COMMAND_MAP = {
    0: ("S", "start/confirm"),
    1: ("O", "open hand"),
    2: ("C", "close hand"),
    3: ("L", "rotate left"),
    4: ("R", "rotate right"),
}

# --------------------------------------------------------------------------- #
# Channel groups (channel-aware feature extraction)
# --------------------------------------------------------------------------- #
FRONTAL_CH  = ["Fp1-Ref", "Fp2-Ref"]
TEMPORAL_CH = ["T3-Ref", "T4-Ref"]

# Full 19-channel montage of the device, in acquisition order.
ALL_CH = [
    "Fp1-Ref", "Fp2-Ref", "Fz-Ref", "F8-Ref", "F7-Ref", "F4-Ref", "F3-Ref",
    "C4-Ref", "C3-Ref", "O2-Ref", "P3-Ref", "Cz-Ref", "O1-Ref", "P4-Ref",
    "Pz-Ref", "T6-Ref", "T5-Ref", "T4-Ref", "T3-Ref",
]

# Named EEG frequency bands (Hz) used for band-power features.
BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta":  (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

# Feature-selection: keep the k best features (mutual information).
SELECT_K = 50

# Cross-validation folds for training.
CV_FOLDS = 5

RANDOM_STATE = 42
