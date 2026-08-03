"""Stage 3 - channel-aware feature extraction (78 features per epoch).

Layout (78 = 20 + 20 + 38):

    Frontal  (Fp1-Ref, Fp2-Ref) : 10 features x 2 channels = 20
    Temporal (T3-Ref,  T4-Ref)  : 10 features x 2 channels = 20
    All 19 channels statistical : kurtosis + skewness        = 38

Per frontal/temporal channel the 10 features are:
    Time      : mean, std, RMS, zero-crossing-rate, peak-to-peak   (5)
    Bandpower : delta, theta, alpha, beta, gamma                   (5)

Note on the 78 count: the spec headline ("Extract 78 features per epoch") and
the enumerated feature names both imply 10 features/channel (5 time + 5 band).
The "12 features x 2 = 24" sub-line is an arithmetic slip (10+10 != 12); we
honour the stated total of 78. After extraction we run
``SelectKBest(mutual_info_classif, k=50)`` and assert zero NaN / zero Inf.
"""

from __future__ import annotations

from functools import partial

import numpy as np
import pywt
from scipy.signal import find_peaks, welch
from scipy.integrate import trapezoid
from scipy.stats import kurtosis, skew
from sklearn.feature_selection import SelectKBest, mutual_info_classif

from eeg_bci import config as cfg

# Volts -> microvolts, so feature magnitudes are numerically well-scaled.
_V_TO_UV = 1e6

# Small constant to avoid divide-by-zero in ratios.
_EPS = 1e-8

# Amplitude-invariant time features (raw mean & std removed in Step 2 - they
# encode recording identity, not the gesture).
_TIME_NAMES = ["rms", "zcr", "ptp"]
# Band names in fixed order (delta..gamma) from the config.
_BAND_NAMES = list(cfg.BANDS.keys())
# Hjorth parameter names.
_HJORTH_NAMES = ["hjorth_activity", "hjorth_mobility", "hjorth_complexity"]

# Names of the 11 features in one channel block, in extraction order.
_BLOCK_NAMES = (
    _TIME_NAMES
    + [f"bp_rel_{b}" for b in _BAND_NAMES]
    + _HJORTH_NAMES
)

# Indices into a channel block, used by the lateralization features.
_I_RMS = _BLOCK_NAMES.index("rms")
_I_PTP = _BLOCK_NAMES.index("ptp")
_I_BETA = _BLOCK_NAMES.index("bp_rel_beta")
_I_GAMMA = _BLOCK_NAMES.index("bp_rel_gamma")

# Lateralization fixes attempted for the C<->R confusion. Kept as toggles for
# reproducibility but DISABLED by default: the experiment in
# feature_fix_experiment.py showed they hurt bruxism_right (F1 0.33 -> 0.23-0.26)
# rather than helping, so the 93-feature baseline (all flags False) is best and
# is what models/best_model.pkl was trained on. The driver flips these at call
# time to reproduce each stage.
FIX1_ASYM_RATIOS = False       # add T4/T3 ratio + normalized-difference features
FIX2_DROP_TEMPORAL_RMS = False  # drop raw RMS from temporal blocks (keep frontal)
FIX3_LATERAL_INDEX = False      # add a discrete right/left/symmetric indicator

_LATERAL_NAMES = [
    "asym_ratio_rms", "asym_ratio_ptp", "asym_ratio_gamma", "asym_ratio_beta",
    "asym_norm_rms", "asym_norm_ptp",
]

# --------------------------------------------------------------------------- #
# Blink peak-count features (single vs double vs triple blink).
#
# Counts discrete blink deflections on the frontal channels (Fp1-Ref, Fp2-Ref)
# and times their inter-peak intervals, so single/double/triple blinks separate
# structurally instead of by gross amplitude.
#
# IMPORTANT: these features are computed on the RAW microvolt epoch (filtered +
# CAR, BEFORE per-recording z-scoring), threaded in as ``epoch_uv``. An earlier
# attempt on the z-scored signal failed because per-recording normalization
# rescales spiky EMG up to blink level. The Step-1 validation
# (blink_peak_v2_viz.py) on raw µV showed clean, monotonic ordering on
# |signal|: single < double < triple for peak count, inter-peak interval AND
# peak amplitude -- absolute counts are ~half the 1/2/3 ideal only because 2 s
# sliding windows dilute them, but the ordering (what the classifier uses) holds.
# Detection is on |signal| because many blinks are negative-going under CAR.
#
# RESULT (eval_6class.py, RandomForest, same 80/20 split): DISABLED by default.
# Validation ordering was clean, but as classifier features these gave only
# noise-level deltas on the targeted classes (S +0.024, T +0.008 on ~55-68 test
# epochs) while slightly hurting C/L/R and dropping overall 83.4% -> 82.8%. The
# S<->T confusion did not move (13/13). The existing 93 features (frontal
# kurtosis/skew/ptp/band-power) already encode multi-peak blink shape, so the
# explicit count is redundant. Kept as a reproducible toggle; flip True to
# re-add the 8 features (then use preprocess_all_dual to supply raw-µV epochs).
BLINK_PEAK_FEATURES = False      # add the 8 frontal blink peak features (93 -> 101)
BLINK_PEAK_HEIGHT_UV = 40.0      # min peak height (µV): real blink deflection
BLINK_PEAK_PROM_UV = 25.0        # must stand out from baseline (µV)
BLINK_PEAK_DIST_SEC = 0.20       # min 200 ms between blink peaks (eye-blink biology)
BLINK_PEAK_POLARITY = "abs"      # detect on |signal| (catches negative-going blinks)

_BLINK_PEAK_NAMES = [
    "fp1_n_peaks", "fp2_n_peaks",
    "fp1_ipi_mean", "fp2_ipi_mean",
    "fp1_ipi_std", "fp2_ipi_std",
    "fp1_peak_amp_mean", "fp2_peak_amp_mean",
]

# --------------------------------------------------------------------------- #
# Research-driven 2026-06-29 feature families (DWT / TKEO / EMG descriptors).
#
# All three are computed on the per-recording z-scored signal (the same ``sig``
# the existing blocks use), NOT raw µV: the pipeline's whole design is amplitude-
# invariance (raw mean/std were dropped because they encode recording identity),
# so any absolute-amplitude EMG/wavelet feature would re-leak the recording gain
# and hurt the honest cross-session/cross-recording numbers. Energies are turned
# into RELATIVE wavelet energy (sums to 1) and the WAMP/SSC thresholds are a
# fraction of each epoch's own std, keeping every new feature scale-robust.
#
# All default OFF so feature_names()/extract_epoch stay at the 93-feature
# baseline and models/best_model*.pkl remain valid. eval_newfeatures.py flips
# them per config to measure each family's delta on the GroupKFold dev protocol.
# --------------------------------------------------------------------------- #
DWT_FEATURES = False        # +108: 6 sub-bands x (rel-energy, MAV, std) x 6 channels
TKEO_FEATURES = False       # +12 : Teager-Kaiser energy (mean/std/max) x 4 muscle ch
EMG_DESCRIPTORS = False     # +16 : WL, SSC, WAMP, CV x 4 muscle channels

# DWT: Daubechies-4, 5 levels -> coeffs [cA5, cD5, cD4, cD3, cD2, cD1]. db4 is the
# common choice for transient EEG/EMG bursts (blink/clench/chew); 400-sample 2 s
# epochs support exactly level 5 for db4 (dwt_max_level(400, 'db4') == 5).
DWT_WAVELET = "db4"
DWT_LEVEL = 5
_DWT_BANDS = ["a5", "d5", "d4", "d3", "d2", "d1"]   # approx + detail sub-bands
DWT_CHANNELS = ["Fp1-Ref", "Fp2-Ref", "T3-Ref", "T4-Ref", "F7-Ref", "F8-Ref"]
# Keep ONLY the (scale-invariant) relative wavelet energy per band -- the feature
# the research note calls "key" -- dropping the amplitude-scaled MAV/std. Lets the
# DWT family be tested on its strongest, least-noisy subset (6 bands x 6 ch = 36).
DWT_RELENERGY_ONLY = False

# TKEO / EMG descriptors target the muscle channels (temporal + inferior-frontal).
MUSCLE_CHANNELS = ["T3-Ref", "T4-Ref", "F7-Ref", "F8-Ref"]

# Dead-zone for Willison-amplitude / slope-sign-change counts, as a fraction of
# the epoch's own std (scale-robust on the z-scored signal).
EMG_THRESH_FRAC = 0.1


def _dwt_features(sig: np.ndarray) -> list[float]:
    """Relative wavelet energy + MAV + std per DWT sub-band for one channel.

    Args:
        sig: 1-D signal (samples,).

    Returns:
        ``3 * (DWT_LEVEL + 1)`` values: for each sub-band (cA5, cD5..cD1) the
        relative wavelet energy (energy / total energy), the mean-absolute
        coefficient value, and the coefficient std. Order matches
        ``_DWT_BANDS``.
    """
    coeffs = pywt.wavedec(sig, DWT_WAVELET, level=DWT_LEVEL)
    energies = [float(np.sum(c ** 2)) for c in coeffs]
    total = sum(energies) + _EPS
    out: list[float] = []
    for c, e in zip(coeffs, energies):
        out.append(e / total)                       # relative wavelet energy
        if not DWT_RELENERGY_ONLY:
            out.append(float(np.mean(np.abs(c))))   # mean absolute value
            out.append(float(np.std(c)))            # std of coefficients
    return out


def _tkeo(x: np.ndarray) -> np.ndarray:
    """Discrete Teager-Kaiser Energy Operator: ``x[n]^2 - x[n-1]*x[n+1]``."""
    return x[1:-1] ** 2 - x[:-2] * x[2:]


def _tkeo_features(sig: np.ndarray) -> list[float]:
    """Mean, std and max of the TKEO output for one muscle channel.

    TKEO amplifies abrupt amplitude+frequency increases (muscle-activation
    onsets), so its energy summary is meant to sharpen clinch/bruxism.

    Args:
        sig: 1-D signal (samples,).

    Returns:
        ``[tkeo_mean, tkeo_std, tkeo_max]``.
    """
    psi = _tkeo(sig)
    return [float(np.mean(psi)), float(np.std(psi)), float(np.max(psi))]


def _emg_descriptors(sig: np.ndarray) -> list[float]:
    """Four classic EMG time-domain descriptors for one muscle channel.

    Args:
        sig: 1-D signal (samples,).

    Returns:
        ``[wl, ssc, wamp, cv]`` -- waveform length (sum |Δx|), slope-sign-change
        count, Willison-amplitude count (|Δx| over a std-relative dead-zone), and
        coefficient of variation of the rectified signal (std/mean of ``|x|``;
        the raw mean is ~0 for the z-scored signal, so CV is taken on ``|x|``).
    """
    diff = np.diff(sig)
    thr = EMG_THRESH_FRAC * float(np.std(sig))
    wl = float(np.sum(np.abs(diff)))
    wamp = float(np.sum(np.abs(diff) > thr))
    d1, d2 = diff[:-1], diff[1:]
    ssc = float(np.sum((d1 * d2 < 0) & ((np.abs(d1) > thr) | (np.abs(d2) > thr))))
    rect = np.abs(sig)
    cv = float(np.std(rect) / (np.mean(rect) + _EPS))
    return [wl, ssc, wamp, cv]


def _extra_feature_names() -> list[str]:
    """Names for the optional DWT / TKEO / EMG-descriptor families (in order)."""
    names: list[str] = []
    if DWT_FEATURES:
        for ch in DWT_CHANNELS:
            for b in _DWT_BANDS:
                names.append(f"{ch}_dwt_{b}_relenergy")
                if not DWT_RELENERGY_ONLY:
                    names += [f"{ch}_dwt_{b}_mav", f"{ch}_dwt_{b}_std"]
    if TKEO_FEATURES:
        for ch in MUSCLE_CHANNELS:
            names += [f"{ch}_tkeo_mean", f"{ch}_tkeo_std", f"{ch}_tkeo_max"]
    if EMG_DESCRIPTORS:
        for ch in MUSCLE_CHANNELS:
            names += [f"{ch}_emg_wl", f"{ch}_emg_ssc",
                      f"{ch}_emg_wamp", f"{ch}_emg_cv"]
    return names


def _extra_features(sig: np.ndarray) -> list[float]:
    """Compute the optional DWT / TKEO / EMG features for one epoch (``sig`` µV-z)."""
    feats: list[float] = []
    if DWT_FEATURES:
        for ch in DWT_CHANNELS:
            feats += _dwt_features(sig[_idx(ch)])
    if TKEO_FEATURES:
        for ch in MUSCLE_CHANNELS:
            feats += _tkeo_features(sig[_idx(ch)])
    if EMG_DESCRIPTORS:
        for ch in MUSCLE_CHANNELS:
            feats += _emg_descriptors(sig[_idx(ch)])
    return feats


def _time_features(sig: np.ndarray) -> list[float]:
    """Compute the amplitude-invariant time-domain features for one channel.

    Args:
        sig: 1-D signal (samples,).

    Returns:
        ``[rms, zero_crossing_rate, peak_to_peak]``.
    """
    rms = float(np.sqrt(np.mean(sig ** 2)))
    # Zero-crossing rate: fraction of adjacent samples with a sign change.
    zcr = float(np.mean(np.abs(np.diff(np.sign(sig))) > 0))
    ptp = float(np.ptp(sig))
    return [rms, zcr, ptp]


def _relative_band_powers(sig: np.ndarray) -> list[float]:
    """Compute *relative* band power in each EEG band via Welch's PSD.

    Each band's absolute power is divided by the total power across all bands,
    making the feature invariant to the recording's overall gain.

    Args:
        sig: 1-D signal (samples,).

    Returns:
        Relative band power for delta, theta, alpha, beta, gamma (sums to ~1).
    """
    nperseg = min(len(sig), 256)
    freqs, psd = welch(sig, fs=cfg.SFREQ, nperseg=nperseg)
    powers: list[float] = []
    for band in _BAND_NAMES:
        lo, hi = cfg.BANDS[band]
        idx = (freqs >= lo) & (freqs <= hi)
        power = float(trapezoid(psd[idx], freqs[idx])) if np.any(idx) else 0.0
        powers.append(power)
    total = sum(powers) + _EPS
    return [p / total for p in powers]


def _hjorth(sig: np.ndarray) -> list[float]:
    """Compute the three Hjorth parameters (mobility & complexity are amplitude-invariant).

    Args:
        sig: 1-D signal (samples,).

    Returns:
        ``[activity, mobility, complexity]``.
    """
    d1 = np.diff(sig)
    d2 = np.diff(d1)
    var0 = float(np.var(sig))
    var1 = float(np.var(d1))
    var2 = float(np.var(d2))
    activity = var0
    mobility = np.sqrt(var1 / (var0 + _EPS))
    mob_d1 = np.sqrt(var2 / (var1 + _EPS))
    complexity = mob_d1 / (mobility + _EPS)
    return [activity, float(mobility), float(complexity)]


def blink_peaks_uv(sig_uv: np.ndarray) -> tuple[int, float, float, float]:
    """Detect blink peaks on one frontal channel in RAW microvolts.

    Args:
        sig_uv: 1-D frontal channel signal in microvolts (filtered + CAR, NOT
            z-scored).

    Returns:
        Tuple ``(n_peaks, ipi_mean, ipi_std, peak_amp_mean)``. Interval stats are
        0.0 when fewer than 2 peaks are found; ``peak_amp_mean`` is 0.0 when no
        peak is found. Detection runs on ``|signal|`` when
        ``BLINK_PEAK_POLARITY == "abs"`` (catches negative-going blinks).
    """
    x = np.abs(sig_uv) if BLINK_PEAK_POLARITY == "abs" else sig_uv
    distance = max(1, int(BLINK_PEAK_DIST_SEC * cfg.SFREQ))
    peaks, props = find_peaks(
        x,
        height=BLINK_PEAK_HEIGHT_UV,
        distance=distance,
        prominence=BLINK_PEAK_PROM_UV,
    )
    n = len(peaks)
    if n >= 2:
        ipi = np.diff(peaks) / cfg.SFREQ
        ipi_mean, ipi_std = float(np.mean(ipi)), float(np.std(ipi))
    else:
        ipi_mean = ipi_std = 0.0
    amp = float(np.mean(props["peak_heights"])) if n else 0.0
    return n, ipi_mean, ipi_std, amp


def blink_peak_features(fp1_uv: np.ndarray, fp2_uv: np.ndarray) -> list[float]:
    """Eight blink peak features for Fp1-Ref and Fp2-Ref (raw microvolts).

    Args:
        fp1_uv: Fp1-Ref channel signal in microvolts.
        fp2_uv: Fp2-Ref channel signal in microvolts.

    Returns:
        ``[fp1_n_peaks, fp2_n_peaks, fp1_ipi_mean, fp2_ipi_mean, fp1_ipi_std,
        fp2_ipi_std, fp1_peak_amp_mean, fp2_peak_amp_mean]`` (order matches
        ``_BLINK_PEAK_NAMES``).
    """
    n1, m1, s1, a1 = blink_peaks_uv(fp1_uv)
    n2, m2, s2, a2 = blink_peaks_uv(fp2_uv)
    return [float(n1), float(n2), m1, m2, s1, s2, a1, a2]


def _channel_block(sig: np.ndarray) -> list[float]:
    """Full 11-feature block (3 time + 5 relative-band + 3 Hjorth) for one channel.

    Args:
        sig: 1-D signal (samples,).

    Returns:
        List of 11 feature values, ordered as ``_BLOCK_NAMES``.
    """
    return _time_features(sig) + _relative_band_powers(sig) + _hjorth(sig)


def _idx(ch: str) -> int:
    """Index of a channel name within ``config.ALL_CH``.

    Args:
        ch: Channel name, e.g. ``"Fp1-Ref"``.

    Returns:
        Integer row index into an epoch's channel axis.
    """
    return cfg.ALL_CH.index(ch)


def _temporal_block_names() -> list[str]:
    """Block-feature names for temporal channels (RMS dropped if Fix 2 is on).

    Returns:
        Ordered list of block-feature names for T3/T4.
    """
    if FIX2_DROP_TEMPORAL_RMS:
        return [n for n in _BLOCK_NAMES if n != "rms"]
    return list(_BLOCK_NAMES)


def feature_names() -> list[str]:
    """Return all feature names in the exact extraction order.

    Layout: frontal blocks, temporal blocks, T4-T3 asymmetry indices, optional
    lateralization features (Fix 1), optional lateral index (Fix 3), then
    kurtosis+skew for all 19 channels.

    Returns:
        List of unique feature-name strings.
    """
    names: list[str] = []
    for ch in cfg.FRONTAL_CH:                       # frontal keeps RMS
        names += [f"{ch}_{n}" for n in _BLOCK_NAMES]
    if BLINK_PEAK_FEATURES:                          # frontal blink peak group
        names += list(_BLINK_PEAK_NAMES)
    temporal_names = _temporal_block_names()
    for ch in cfg.TEMPORAL_CH:
        names += [f"{ch}_{n}" for n in temporal_names]
    names += [f"asym_T4-T3_{n}" for n in _BLOCK_NAMES]
    if FIX1_ASYM_RATIOS:
        names += _LATERAL_NAMES
    if FIX3_LATERAL_INDEX:
        names.append("lateral_index")
    for ch in cfg.ALL_CH:
        names += [f"{ch}_kurtosis", f"{ch}_skew"]
    names += _extra_feature_names()
    return names


def _asymmetry(block_t4: list[float], block_t3: list[float]) -> list[float]:
    """Normalized asymmetry index ``(T4 - T3) / (|T4| + |T3|)`` per feature.

    Captures left/right lateralization (critical for bruxism_left vs _right).

    Args:
        block_t4: T4-Ref channel block (11 values).
        block_t3: T3-Ref channel block (11 values).

    Returns:
        List of 11 asymmetry indices in ``[-1, 1]``.
    """
    return [
        (a - b) / (abs(a) + abs(b) + _EPS)
        for a, b in zip(block_t4, block_t3)
    ]


def _lateralization(block_t4: list[float],
                    block_t3: list[float]) -> tuple[list[float], float]:
    """T4/T3 ratio and normalized-difference lateralization features (Fix 1).

    Ratios are more robust to amplitude scale than plain differences, and
    directly expose the T4>T3 (right) vs T3>T4 (left) signal that plain RMS
    masks.

    Args:
        block_t4: T4-Ref channel block.
        block_t3: T3-Ref channel block.

    Returns:
        Tuple ``(features, asym_norm_rms)`` where ``features`` is the 6-value
        list named by ``_LATERAL_NAMES`` and ``asym_norm_rms`` feeds Fix 3.
    """
    r4, r3 = block_t4[_I_RMS], block_t3[_I_RMS]
    p4, p3 = block_t4[_I_PTP], block_t3[_I_PTP]
    g4, g3 = block_t4[_I_GAMMA], block_t3[_I_GAMMA]
    b4, b3 = block_t4[_I_BETA], block_t3[_I_BETA]
    asym_norm_rms = (r4 - r3) / (r4 + r3 + _EPS)
    feats = [
        r4 / (r3 + _EPS),                       # asym_ratio_rms
        p4 / (p3 + _EPS),                       # asym_ratio_ptp
        g4 / (g3 + _EPS),                       # asym_ratio_gamma
        b4 / (b3 + _EPS),                       # asym_ratio_beta
        asym_norm_rms,                          # asym_norm_rms
        (p4 - p3) / (p4 + p3 + _EPS),           # asym_norm_ptp
    ]
    return feats, asym_norm_rms


def _drop_rms(block: list[float]) -> list[float]:
    """Return a channel block with the RMS value removed (Fix 2).

    Args:
        block: Full channel block.

    Returns:
        Block without its RMS element.
    """
    return [v for i, v in enumerate(block) if i != _I_RMS]


def extract_epoch(epoch: np.ndarray, epoch_uv: np.ndarray | None = None) -> np.ndarray:
    """Extract the full feature vector for a single epoch.

    Args:
        epoch: Array ``(n_channels, n_samples)`` (channels ordered as
            ``config.ALL_CH``; signal is per-recording z-scored upstream).
        epoch_uv: The SAME epoch in RAW microvolts (filtered + CAR, before
            z-scoring), used only by the blink peak features. Required when
            ``BLINK_PEAK_FEATURES`` is on, because those thresholds are in µV.

    Returns:
        1-D feature vector.
    """
    sig = epoch * _V_TO_UV
    feats: list[float] = []
    for ch in cfg.FRONTAL_CH:
        feats += _channel_block(sig[_idx(ch)])

    # Blink peak features run on the RAW µV frontal channels (the µV thresholds
    # in find_peaks only make sense before per-recording z-scoring).
    if BLINK_PEAK_FEATURES:
        if epoch_uv is None:
            raise ValueError(
                "BLINK_PEAK_FEATURES is on but epoch_uv (raw µV) was not "
                "provided; pass the un-normalized epoch via preprocess_all_dual.")
        uv = epoch_uv * _V_TO_UV
        feats += blink_peak_features(uv[_idx("Fp1-Ref")], uv[_idx("Fp2-Ref")])

    # Temporal blocks (keep T4 & T3 to build the asymmetry features).
    block_t4 = _channel_block(sig[_idx("T4-Ref")])
    block_t3 = _channel_block(sig[_idx("T3-Ref")])
    temporal_order = {"T4-Ref": block_t4, "T3-Ref": block_t3}
    for ch in cfg.TEMPORAL_CH:
        blk = temporal_order[ch]
        feats += _drop_rms(blk) if FIX2_DROP_TEMPORAL_RMS else blk
    feats += _asymmetry(block_t4, block_t3)

    lat_feats, asym_norm_rms = _lateralization(block_t4, block_t3)
    if FIX1_ASYM_RATIOS:
        feats += lat_feats
    if FIX3_LATERAL_INDEX:
        # 1 = right-dominant, 0 = left-dominant, 0.5 = symmetric.
        feats.append(
            1.0 if asym_norm_rms > 0.1
            else (0.0 if asym_norm_rms < -0.1 else 0.5)
        )

    for ch in cfg.ALL_CH:
        c = sig[_idx(ch)]
        feats.append(float(kurtosis(c)))
        feats.append(float(skew(c)))

    feats += _extra_features(sig)
    return np.asarray(feats, dtype=float)


def extract_features(
    epochs: np.ndarray, epochs_uv: np.ndarray | None = None
) -> np.ndarray:
    """Extract features for a stack of epochs.

    Args:
        epochs: Array ``(n_epochs, n_channels, n_samples)`` z-scored (volts).
        epochs_uv: The same stack in RAW microvolts (volts, pre-normalization),
            required when ``BLINK_PEAK_FEATURES`` is on.

    Returns:
        Feature matrix ``(n_epochs, n_features)``. Asserts no NaN / Inf.
    """
    n = epochs.shape[0]
    names = feature_names()
    out = np.empty((n, len(names)), dtype=float)
    for i in range(n):
        uv = epochs_uv[i] if epochs_uv is not None else None
        out[i] = extract_epoch(epochs[i], uv)
    print(f"[features] extracted {out.shape[1]} features for {n} epochs "
          f"-> {out.shape}")
    assert out.shape[1] == len(names), "feature count mismatch vs names"
    assert not np.isnan(out).any(), "NaN detected in feature matrix"
    assert not np.isinf(out).any(), "Inf detected in feature matrix"
    print("[features] assertion passed: zero NaN, zero Inf")
    return out


def make_selector() -> SelectKBest:
    """Build a ``SelectKBest`` using mutual information (reproducible).

    Returns:
        An unfitted :class:`~sklearn.feature_selection.SelectKBest`.
    """
    score_func = partial(
        mutual_info_classif, discrete_features=False,
        random_state=cfg.RANDOM_STATE,
    )
    return SelectKBest(score_func=score_func, k=cfg.SELECT_K)


def select_features(
    feat: np.ndarray, y: np.ndarray
) -> tuple[SelectKBest, np.ndarray]:
    """Fit ``SelectKBest(k=50)`` and print the top-10 features with scores.

    Args:
        feat: Feature matrix ``(n_epochs, 78)``.
        y: Integer label vector.

    Returns:
        Tuple ``(fitted_selector, transformed_features)``.
    """
    selector = make_selector()
    transformed = selector.fit_transform(feat, y)
    names = np.asarray(feature_names())
    scores = selector.scores_

    order = np.argsort(scores)[::-1]
    print(f"[features] SelectKBest(mutual_info_classif, k={cfg.SELECT_K}) "
          f"-> kept {transformed.shape[1]} features")
    print("[features] top 10 features by mutual information:")
    for rank, j in enumerate(order[:10], start=1):
        print(f"    {rank:2d}. {names[j]:<24s} {scores[j]:.4f}")
    return selector, transformed


if __name__ == "__main__":
    from eeg_bci.loader import discover_recordings
    from eeg_bci.preprocessing import preprocess_all

    recs = discover_recordings()
    X, Y = preprocess_all(recs)
    F = extract_features(X)
    select_features(F, Y)
