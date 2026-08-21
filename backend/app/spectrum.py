"""Frequency-domain analysis (FFT).

The challenge's optional requirement is a frequency-domain view of the same
signal. Three decisions shape this module:

1. The FFT runs on the *raw* 20000 samples, never on the decimated plot data.
   Min/max decimation deliberately distorts the waveform to preserve its
   visual envelope, which destroys its spectral content -- a spectrum computed
   from it would be meaningless. So the transform happens here, in the
   backend, where the raw frame still exists.

2. The frequency axis is derived from the sensor's *acquisition* rate (2 Msps
   per the spec), not from the measured frame-arrival rate. Bin spacing is a
   property of how fast the ADC sampled, and the mock uC can be throttled to
   any --fps while still synthesising a 2 Msps waveform. Using the arrival
   estimate here would move the tones around whenever delivery hiccupped.

3. Magnitudes are reported in dBFS (decibels relative to int32 full scale).
   The scale is bounded above by 0 dB, which keeps the plot's y-range stable
   instead of rescaling on every frame, and dB is what instrumentation
   software conventionally shows.
"""

from __future__ import annotations

import numpy as np

# Sensor acquisition rate from the challenge spec. See note 2 above.
NOMINAL_SAMPLE_RATE_HZ = 2_000_000

# int32 full scale, the 0 dBFS reference.
_FULL_SCALE = float(2**31)

# Clamp for silent bins; log10(0) would otherwise be -inf and break JSON.
_DB_FLOOR = -200.0


def compute_spectrum(
    samples: np.ndarray,
    sample_rate_hz: float = NOMINAL_SAMPLE_RATE_HZ,
    target_points: int = 1000,
) -> tuple[list[float], float]:
    """Computes a single-sided amplitude spectrum in dBFS.

    A Hann window is applied before the transform. Without it, a tone whose
    period does not divide the frame length evenly leaks energy across the
    whole spectrum (spectral leakage), burying everything else in skirts. The
    result is corrected for the window's coherent gain so peak heights still
    reflect the true tone amplitude.

    The 10001 bins produced from a 20000-sample frame are reduced by keeping
    the **maximum** of each bucket, not the mean. Averaging would flatten
    narrow peaks -- which are exactly the features a spectrum exists to show.

    Args:
        samples: 1-D array of raw sample values (not decimated).
        sample_rate_hz: Acquisition rate used to scale the frequency axis.
        target_points: Approximate number of output points. Must be positive.

    Returns:
        A tuple of (magnitudes_db, nyquist_hz). The magnitudes are evenly
        spaced from DC to nyquist_hz, so the frontend can rebuild the
        frequency axis linearly instead of receiving it on every frame.
        Returns ([], 0.0) for an empty or single-sample input.
    """
    if target_points <= 0:
        raise ValueError("target_points must be positive.")

    n = len(samples)
    if n < 2:
        return [], 0.0

    window = np.hanning(n)
    windowed = samples.astype(np.float64) * window

    # Single-sided amplitude: the factor 2 accounts for the discarded negative
    # frequencies, and dividing by the window sum undoes its coherent gain.
    spectrum = np.abs(np.fft.rfft(windowed)) * 2.0 / window.sum()

    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(spectrum / _FULL_SCALE)
    db = np.maximum(db, _DB_FLOOR)

    nyquist_hz = sample_rate_hz / 2.0
    return _decimate_peaks(db, target_points), nyquist_hz


def _decimate_peaks(db: np.ndarray, target_points: int) -> list[float]:
    """Reduces a spectrum to ~target_points, keeping each bucket's peak.

    Args:
        db: 1-D array of magnitudes in dB.
        target_points: Approximate number of output points.

    Returns:
        The reduced magnitudes as a list of floats. Returned unchanged (as a
        list) when the input is already at or below the target size.
    """
    n = len(db)
    if n <= target_points:
        return db.tolist()

    bucket_size = n // target_points

    # Trim to a length divisible by bucket_size so the array reshapes cleanly.
    # The dropped tail is at most bucket_size-1 bins at the very top of the
    # band, which is above anything of interest here.
    n_buckets = n // bucket_size
    reshaped = db[: n_buckets * bucket_size].reshape(n_buckets, bucket_size)
    return reshaped.max(axis=1).tolist()
