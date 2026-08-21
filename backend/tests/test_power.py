"""Tests for RMS power estimation."""

import numpy as np
import pytest

from backend.app.power import compute_power_dbfs


def test_full_scale_tone_is_near_0_dbfs():
    # RMS of a sine at the int32 ceiling is amplitude / sqrt(2), so it should
    # land roughly 3 dB under 0 dBFS -- and never above it.
    t = np.arange(20000, dtype=np.float64)
    tone = (2**31 - 1) * np.sin(2 * np.pi * 1000 * t / 2_000_000)
    db = compute_power_dbfs(tone.astype("<i4"))
    assert -4.0 < db < 0.0


def test_louder_signal_reads_higher():
    quiet = np.full(1000, 100, dtype="<i4")
    loud = np.full(1000, 1_000_000, dtype="<i4")
    assert compute_power_dbfs(loud) > compute_power_dbfs(quiet)


def test_silence_is_floored_not_infinite():
    assert compute_power_dbfs(np.zeros(20000, dtype="<i4")) == -200.0


def test_empty_input_returns_none():
    assert compute_power_dbfs(np.array([], dtype="<i4")) is None


def test_known_amplitude_matches_expected_dbfs():
    # A constant (DC) signal's RMS is just its own magnitude, so the expected
    # value reduces to 20*log10(1e6 / 2**31).
    samples = np.full(1000, 1_000_000, dtype="<i4")
    expected_db = 20 * np.log10(1_000_000 / 2**31)
    assert compute_power_dbfs(samples) == pytest.approx(expected_db, abs=0.01)
