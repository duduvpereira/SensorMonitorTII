"""Tests for frame_validator."""

import numpy as np

from backend.app.frame_parser import EXPECTED_SAMPLES_PER_FRAME
from backend.app.frame_validator import validate_frame


def _payload_with_samples(n):
    return np.zeros(n, dtype="<i4").tobytes()


def test_valid_frame_is_accepted():
    payload = _payload_with_samples(EXPECTED_SAMPLES_PER_FRAME)
    result = validate_frame(payload)
    assert result.is_valid
    assert result.sample_count == EXPECTED_SAMPLES_PER_FRAME
    assert result.expected == EXPECTED_SAMPLES_PER_FRAME


def test_short_frame_is_invalid():
    payload = _payload_with_samples(EXPECTED_SAMPLES_PER_FRAME - 1)
    result = validate_frame(payload)
    assert not result.is_valid
    assert result.sample_count == EXPECTED_SAMPLES_PER_FRAME - 1


def test_long_frame_is_invalid():
    payload = _payload_with_samples(EXPECTED_SAMPLES_PER_FRAME + 500)
    result = validate_frame(payload)
    assert not result.is_valid
    assert result.sample_count == EXPECTED_SAMPLES_PER_FRAME + 500


def test_custom_expected_count():
    payload = _payload_with_samples(100)
    result = validate_frame(payload, expected=100)
    assert result.is_valid


def test_empty_frame_is_invalid_against_default():
    result = validate_frame(b"")
    assert not result.is_valid
    assert result.sample_count == 0
