"""Tests for sample_rate."""

import pytest

from backend.app.sample_rate import SampleRateEstimator


def test_first_frame_returns_none():
    est = SampleRateEstimator()
    assert est.update(20000, timestamp=1.0) is None


def test_second_frame_computes_rate():
    est = SampleRateEstimator(smoothing=1.0)  # no smoothing
    est.update(20000, timestamp=0.0)
    # 20000 samples over 0.01 s => 2_000_000 sps.
    rate = est.update(20000, timestamp=0.01)
    assert rate == pytest.approx(2_000_000.0)


def test_smoothing_blends_estimates():
    est = SampleRateEstimator(smoothing=0.5)
    est.update(20000, timestamp=0.0)
    first = est.update(20000, timestamp=0.01)  # 2_000_000
    # Next interval is twice as long => instantaneous 1_000_000.
    second = est.update(20000, timestamp=0.03)
    # EMA with 0.5: 0.5*1_000_000 + 0.5*2_000_000 = 1_500_000.
    assert first == pytest.approx(2_000_000.0)
    assert second == pytest.approx(1_500_000.0)


def test_zero_interval_is_ignored():
    est = SampleRateEstimator(smoothing=1.0)
    est.update(20000, timestamp=1.0)
    est.update(20000, timestamp=1.01)  # establishes a rate
    # Same timestamp => interval 0 => return last known estimate, no div-by-zero.
    rate = est.update(20000, timestamp=1.01)
    assert rate == pytest.approx(2_000_000.0)


def test_reset_clears_state():
    est = SampleRateEstimator()
    est.update(20000, timestamp=0.0)
    est.update(20000, timestamp=0.01)
    est.reset()
    # After reset, the next frame is treated as the first again.
    assert est.update(20000, timestamp=5.0) is None


def test_invalid_smoothing_rejected():
    with pytest.raises(ValueError):
        SampleRateEstimator(smoothing=0.0)
    with pytest.raises(ValueError):
        SampleRateEstimator(smoothing=1.5)
