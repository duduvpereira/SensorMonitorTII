"""Tests for plot_decimator."""

import numpy as np
import pytest

from backend.app.plot_decimator import decimate_minmax


def test_small_input_returned_asis():
    samples = np.array([1, 2, 3], dtype="<i4")
    assert decimate_minmax(samples, target_points=2000) == [1.0, 2.0, 3.0]


def test_empty_input():
    assert decimate_minmax(np.array([], dtype="<i4")) == []


def test_output_count_bounded_by_target():
    samples = np.arange(20000, dtype="<i4")
    out = decimate_minmax(samples, target_points=2000)
    # At most ~target_points values (2 per bucket, buckets = target//2).
    assert len(out) <= 2000
    assert len(out) > 0


def test_preserves_min_and_max_envelope():
    # A signal with a sharp spike must keep that spike in the output.
    samples = np.zeros(10000, dtype="<i4")
    samples[5000] = 999999  # single-sample peak
    samples[7000] = -999999  # single-sample trough
    out = decimate_minmax(samples, target_points=200)
    assert max(out) == 999999.0
    assert min(out) == -999999.0


def test_invalid_target_rejected():
    with pytest.raises(ValueError):
        decimate_minmax(np.arange(100, dtype="<i4"), target_points=0)


def test_output_is_json_serialisable_floats():
    samples = np.arange(5000, dtype="<i4")
    out = decimate_minmax(samples, target_points=500)
    assert all(isinstance(v, float) for v in out)
