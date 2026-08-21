"""Tests for the frequency-domain analysis.

The key property is that a known tone lands on the right frequency bin with
roughly the right amplitude — if that holds, the window correction, the dBFS
reference and the frequency scaling are all consistent.
"""

import numpy as np
import pytest

from backend.app.spectrum import NOMINAL_SAMPLE_RATE_HZ, compute_spectrum


def _tone(freq_hz, amplitude=1_000_000, n=20000, rate=NOMINAL_SAMPLE_RATE_HZ):
    """Builds n samples of a pure sine at freq_hz, as int32 values."""
    t = np.arange(n, dtype=np.float64) / rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype("<i4")


def test_returns_requested_point_count():
    result = compute_spectrum(_tone(50_000), target_points=1000)
    assert len(result.magnitudes_db) == 1000


def test_nyquist_is_half_the_sample_rate():
    result = compute_spectrum(_tone(50_000))
    assert result.nyquist_hz == NOMINAL_SAMPLE_RATE_HZ / 2


def test_tone_lands_on_the_correct_frequency():
    target_points = 1000
    db, nyquist, _, _ = compute_spectrum(_tone(50_000), target_points=target_points)

    peak_index = int(np.argmax(db))
    hz_per_point = nyquist / (target_points - 1)
    peak_hz = peak_index * hz_per_point

    # Each output point covers a bucket of the spectrum, so the peak can only
    # be located to within one bucket width.
    assert abs(peak_hz - 50_000) <= hz_per_point


def test_tone_amplitude_matches_dbfs_reference():
    # A 1e6-amplitude tone against the int32 full-scale reference:
    # 20*log10(1e6 / 2**31) = -66.6 dBFS.
    db, *_ = compute_spectrum(_tone(50_000, amplitude=1_000_000))
    expected = 20 * np.log10(1_000_000 / 2**31)
    assert max(db) == pytest.approx(expected, abs=0.5)


def test_louder_tone_reads_higher():
    quiet, *_ = compute_spectrum(_tone(50_000, amplitude=100_000))
    loud, *_ = compute_spectrum(_tone(50_000, amplitude=1_000_000))
    assert max(loud) > max(quiet)


def test_two_tones_produce_two_peaks():
    samples = _tone(5_000) + _tone(200_000)
    db, nyquist, _, _ = compute_spectrum(samples, target_points=1000)
    arr = np.array(db)
    hz_per_point = nyquist / (len(db) - 1)

    # Both tones should stand well clear of the rest of the spectrum.
    peaks = sorted(int(i) * hz_per_point for i in arr.argsort()[-2:])
    assert abs(peaks[0] - 5_000) <= hz_per_point * 2
    assert abs(peaks[1] - 200_000) <= hz_per_point * 2


def test_silence_is_floored_not_infinite():
    # log10(0) is -inf, which would not survive JSON serialisation.
    db, *_ = compute_spectrum(np.zeros(20000, dtype="<i4"))
    assert all(np.isfinite(v) for v in db)


def test_peak_locates_a_single_tone_precisely():
    # Locating the peak happens before decimation, on the full-resolution
    # spectrum, so it should sit much closer to 50 kHz than a decimated
    # bucket's width would otherwise allow.
    result = compute_spectrum(_tone(50_000), target_points=200)
    full_res_bin_hz = result.nyquist_hz / (20000 // 2)
    assert abs(result.peak_hz - 50_000) <= full_res_bin_hz * 2


def test_peak_db_matches_the_spectrum_maximum():
    result = compute_spectrum(_tone(50_000, amplitude=1_000_000))
    assert result.peak_db == pytest.approx(max(result.magnitudes_db), abs=0.01)


def test_louder_tone_has_higher_peak_db():
    quiet_result = compute_spectrum(_tone(50_000, amplitude=100_000))
    loud_result = compute_spectrum(_tone(50_000, amplitude=1_000_000))
    assert loud_result.peak_db > quiet_result.peak_db


def test_empty_input_returns_empty():
    assert compute_spectrum(np.array([], dtype="<i4")) == ([], 0.0, 0.0, -200.0)


def test_single_sample_returns_empty():
    # One sample has no meaningful spectrum, and np.hanning(1) is degenerate.
    assert compute_spectrum(np.array([7], dtype="<i4")) == ([], 0.0, 0.0, -200.0)


def test_short_input_is_not_padded():
    # Fewer bins than requested points: return what there is, don't invent data.
    db, *_ = compute_spectrum(_tone(50_000, n=64), target_points=1000)
    assert len(db) == 64 // 2 + 1


def test_invalid_target_points_rejected():
    with pytest.raises(ValueError):
        compute_spectrum(_tone(50_000), target_points=0)
