"""Per-frame RMS power estimation.

Expressed in dBFS (decibels relative to int32 full scale) so it lines up with
the frequency-domain magnitudes over in spectrum.py -- 0 dB means "clipping"
in both views. Unlike the spectrum, this is computed for every frame no
matter which tab is active: it's just one extra pass over samples that were
already pulled out for the time-domain plot, not a second FFT.
"""

from __future__ import annotations

import numpy as np

# int32 full scale -- the 0 dBFS reference, shared with spectrum.py so the two
# readouts stay directly comparable.
_FULL_SCALE = float(2**31)

# Floor applied to a silent frame. Without it, log10(0) is -inf and the value
# can't survive a round trip through JSON.
_DB_FLOOR = -200.0


def compute_power_dbfs(samples: np.ndarray) -> float | None:
    """RMS power of one frame's raw samples, expressed in dBFS.

    Args:
        samples: 1-D array of raw sample values (not decimated).

    Returns:
        RMS power in dBFS, clamped at _DB_FLOOR when the frame is silent.
        None for an empty frame, since there's nothing to measure.
    """
    if not samples.size:
        return None

    mean_square = np.mean(samples.astype(np.float64) ** 2)
    rms = float(np.sqrt(mean_square))
    if rms <= 0.0:
        return _DB_FLOOR

    db = 20.0 * np.log10(rms / _FULL_SCALE)
    return float(max(db, _DB_FLOOR))
