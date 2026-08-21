"""Plot decimation.

A frame has 20000 samples; pushing all of them to the browser ~30 times a
second would overwhelm the plotting library, but naive decimation (every Nth
sample) hides spikes between the kept samples.

Min/max decimation avoids that: split the samples into buckets and keep both
the minimum and maximum of each, preserving the signal's visual envelope while
cutting the point count.
"""

from __future__ import annotations

import numpy as np


def decimate_minmax(samples: np.ndarray, target_points: int = 2000) -> list[float]:
    """Down-samples an array while preserving its visual min/max envelope.

    Args:
        samples: 1-D array of sample values.
        target_points: Approximate number of output points. The result has at
            most 2 points per bucket, so up to ~target_points values. Must be
            positive.

    Returns:
        A list of floats suitable for JSON transport to the plot. If the input
        is already smaller than target_points, it is returned as-is (converted
        to a list), since there is nothing to gain by decimating.
    """
    if target_points <= 0:
        raise ValueError("target_points must be positive.")

    n = len(samples)
    if n == 0:
        return []
    if n <= target_points:
        return samples.astype(float).tolist()

    # Each bucket yields a min and a max, so halve the target to stay near
    # target_points.
    n_buckets = max(1, target_points // 2)
    bucket_size = n // n_buckets

    # Trim to a length divisible by bucket_size so we can reshape cleanly; the
    # dropped tail is at most bucket_size-1 samples (visually negligible).
    trimmed = samples[: n_buckets * bucket_size]
    reshaped = trimmed.reshape(n_buckets, bucket_size)

    mins = reshaped.min(axis=1)
    maxs = reshaped.max(axis=1)

    # Interleave min,max per bucket so the plotted line preserves order.
    interleaved = np.empty(n_buckets * 2, dtype=float)
    interleaved[0::2] = mins
    interleaved[1::2] = maxs
    return interleaved.tolist()
