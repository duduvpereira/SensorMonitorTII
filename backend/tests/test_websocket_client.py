"""Tests for the frame processing pipeline (process_payload) and models."""

import numpy as np

from backend.app.frame_parser import EXPECTED_SAMPLES_PER_FRAME
from backend.app.models import ProcessedFrame
from backend.app.sample_rate import SampleRateEstimator
from backend.app.websocket_client import process_payload


def _payload(n):
    return np.zeros(n, dtype="<i4").tobytes()


def test_process_valid_frame():
    est = SampleRateEstimator()
    pf = process_payload(
        _payload(EXPECTED_SAMPLES_PER_FRAME),
        frame_number=1,
        estimator=est,
        plot_points=2000,
        arrival_time=0.0,
    )
    assert pf.frame_number == 1
    assert pf.sample_count == EXPECTED_SAMPLES_PER_FRAME
    assert pf.is_valid
    assert len(pf.frame_hash) == 32
    assert pf.sample_rate is None  # first frame, no interval yet
    assert len(pf.plot_samples) > 0


def test_process_invalid_frame_count():
    est = SampleRateEstimator()
    pf = process_payload(
        _payload(19999),
        frame_number=2,
        estimator=est,
        plot_points=2000,
        arrival_time=0.0,
    )
    assert not pf.is_valid
    assert pf.sample_count == 19999


def test_sample_rate_appears_on_second_frame():
    est = SampleRateEstimator(smoothing=1.0)
    process_payload(_payload(20000), 1, est, 2000, arrival_time=0.0)
    pf2 = process_payload(_payload(20000), 2, est, 2000, arrival_time=0.01)
    assert pf2.sample_rate is not None
    assert pf2.sample_rate > 0


def test_corrupt_payload_still_processed_without_plot():
    # 5 bytes: not a whole number of int32 samples. Must not raise; it should
    # still be logged/validated but produce no plot samples.
    est = SampleRateEstimator()
    pf = process_payload(b"\x00\x00\x00\x00\x01", 1, est, 2000, arrival_time=0.0)
    assert not pf.is_valid
    assert pf.plot_samples == []


def test_log_line_format_matches_spec():
    pf = ProcessedFrame(
        frame_number=1,
        timestamp="2026-08-20 18:00:00",
        sample_count=20000,
        expected_samples=20000,
        is_valid=True,
        frame_hash="e2966f42b51a85b2e85f9562b284ff9d",
        sample_rate=2_000_000.0,
    )
    assert pf.to_log_line() == (
        "[2026-08-20 18:00:00]: Frame 1 | 20000 | e2966f42b51a85b2e85f9562b284ff9d"
    )


def test_to_dict_is_complete():
    pf = process_payload(_payload(20000), 1, SampleRateEstimator(), 2000, arrival_time=0.0)
    d = pf.to_dict()
    for key in (
        "frame_number",
        "timestamp",
        "sample_count",
        "expected_samples",
        "is_valid",
        "frame_hash",
        "sample_rate",
        "plot_samples",
        "spectrum_db",
        "spectrum_max_hz",
        "peak_hz",
        "peak_db",
        "power_db",
        "log_line",
    ):
        assert key in d


def test_spectrum_is_skipped_by_default():
    # The FFT must not run while the user is on the time-domain tab.
    pf = process_payload(_payload(20000), 1, SampleRateEstimator(), 2000, arrival_time=0.0)
    assert pf.spectrum_db == []
    assert pf.spectrum_max_hz is None
    assert pf.peak_hz is None
    assert pf.peak_db is None


def test_spectrum_is_computed_when_requested():
    pf = process_payload(
        _payload(20000),
        1,
        SampleRateEstimator(),
        2000,
        arrival_time=0.0,
        compute_fd=True,
        spectrum_points=500,
    )
    assert len(pf.spectrum_db) == 500
    assert pf.spectrum_max_hz == 1_000_000.0
    assert pf.peak_hz is not None
    assert pf.peak_db is not None
    # Time-domain data is still produced: the export reads it from the buffer
    # regardless of which tab is being shown.
    assert len(pf.plot_samples) > 0


def test_corrupt_payload_produces_no_spectrum():
    pf = process_payload(
        b"\x00\x00\x00\x00\x01",
        1,
        SampleRateEstimator(),
        2000,
        arrival_time=0.0,
        compute_fd=True,
    )
    assert pf.spectrum_db == []
    assert pf.spectrum_max_hz is None
    assert pf.peak_hz is None
    assert pf.peak_db is None
    assert pf.power_db is None


def test_power_is_computed_regardless_of_domain():
    # No compute_fd flag here -- power isn't gated by domain like the FFT is.
    pf = process_payload(_payload(20000), 1, SampleRateEstimator(), 2000, arrival_time=0.0)
    assert pf.power_db is not None


def test_silent_frame_reads_the_db_floor():
    pf = process_payload(_payload(20000), 1, SampleRateEstimator(), 2000, arrival_time=0.0)
    assert pf.power_db == -200.0


def test_louder_frame_has_higher_power():
    quiet_payload = np.full(20000, 100, dtype="<i4").tobytes()
    loud_payload = np.full(20000, 1_000_000, dtype="<i4").tobytes()
    est = SampleRateEstimator()
    quiet_pf = process_payload(quiet_payload, 1, est, 2000, arrival_time=0.0)
    loud_pf = process_payload(loud_payload, 2, est, 2000, arrival_time=0.01)
    assert loud_pf.power_db > quiet_pf.power_db
