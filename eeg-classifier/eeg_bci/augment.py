"""Physiologically-motivated EEG epoch augmentation (single-subject BCI).

The data wall here is NOT the number of epochs (sliding windows give thousands)
but the number of *independent recordings* (~2 per minority class). So the model
never sees the natural session-to-session variability a real BCI must survive:
amplitude drift, gesture-latency jitter, electrode-gain changes and baseline
noise. Each augmentation below simulates ONE of those nuisance factors, turning a
real epoch into a family of plausible "what this gesture could have looked like
in another session" variants -- WITHOUT changing the gesture identity (label).

All transforms act on a z-scored epoch ``(n_channels, n_samples)`` and are
label-preserving. They are only ever applied to TRAINING epochs (see
eval_augmented.py), so reported test accuracy stays honest.
"""

from __future__ import annotations

import numpy as np

from eeg_bci import config as cfg

# Default augmentation strengths (kept conservative so identity is preserved).
JITTER_SIGMA = 0.08          # additive Gaussian noise std (z-units): sensor noise
SCALE_RANGE = (0.85, 1.15)   # global gain: electrode-impedance / session gain
SHIFT_SEC = 0.10             # max temporal jitter (s): gesture-onset latency
WARP_KNOTS = 4               # control points for smooth amplitude drift
WARP_SIGMA = 0.12            # amplitude-drift strength around 1.0


def jitter(ep: np.ndarray, rng: np.random.Generator,
           sigma: float = JITTER_SIGMA) -> np.ndarray:
    """Add Gaussian sensor noise (models amplifier / electrode noise)."""
    return ep + rng.normal(0.0, sigma, size=ep.shape)


def scale(ep: np.ndarray, rng: np.random.Generator,
          rng_lo_hi: tuple[float, float] = SCALE_RANGE) -> np.ndarray:
    """Apply a single random gain to the whole epoch (session/electrode gain)."""
    return ep * rng.uniform(*rng_lo_hi)


def time_shift(ep: np.ndarray, rng: np.random.Generator,
               max_shift_sec: float = SHIFT_SEC) -> np.ndarray:
    """Circularly shift in time (models gesture-onset latency jitter)."""
    max_shift = max(1, int(max_shift_sec * cfg.SFREQ))
    return np.roll(ep, int(rng.integers(-max_shift, max_shift + 1)), axis=1)


def magnitude_warp(ep: np.ndarray, rng: np.random.Generator,
                   n_knots: int = WARP_KNOTS,
                   sigma: float = WARP_SIGMA) -> np.ndarray:
    """Multiply by a smooth random envelope (models slow amplitude drift).

    A cubic-ish curve is built by linearly interpolating ``n_knots`` random
    control points ~N(1, sigma); the same envelope is applied to every channel
    so cross-channel structure (the discriminative part) is preserved.
    """
    n = ep.shape[1]
    knots = rng.normal(1.0, sigma, n_knots)
    xk = np.linspace(0, n - 1, n_knots)
    curve = np.interp(np.arange(n), xk, knots)
    return ep * curve


_TRANSFORMS = (jitter, scale, time_shift, magnitude_warp)


def augment_epoch(ep: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Produce one augmented variant by composing a random subset of transforms.

    Args:
        ep: z-scored epoch ``(n_channels, n_samples)``.
        rng: NumPy random generator.

    Returns:
        A new augmented epoch (same shape, same label).
    """
    out = ep.copy()
    # Apply each transform independently with prob 0.5 (at least one applied).
    chosen = [t for t in _TRANSFORMS if rng.random() < 0.5]
    if not chosen:
        chosen = [rng.choice(_TRANSFORMS)]
    for t in chosen:
        out = t(out, rng)
    return out


def augment_set(
    epochs: np.ndarray, y: np.ndarray, *, n_aug: int = 3, seed: int = cfg.RANDOM_STATE
) -> tuple[np.ndarray, np.ndarray]:
    """Create ``n_aug`` augmented copies of every epoch (label-preserving).

    Args:
        epochs: z-scored epochs ``(n_epochs, n_channels, n_samples)``.
        y: integer labels.
        n_aug: number of augmented variants per real epoch.
        seed: RNG seed.

    Returns:
        Tuple ``(X_aug, y_aug)`` with ``n_aug * n_epochs`` synthetic epochs.
    """
    rng = np.random.default_rng(seed)
    out = np.empty((epochs.shape[0] * n_aug, *epochs.shape[1:]), dtype=epochs.dtype)
    y_out = np.empty(epochs.shape[0] * n_aug, dtype=y.dtype)
    k = 0
    for i in range(epochs.shape[0]):
        for _ in range(n_aug):
            out[k] = augment_epoch(epochs[i], rng)
            y_out[k] = y[i]
            k += 1
    return out, y_out
