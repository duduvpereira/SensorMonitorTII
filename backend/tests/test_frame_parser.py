"""Tests for frame_parser."""

import numpy as np
import pytest

from backend.app.frame_parser import (
    EXPECTED_SAMPLES_PER_FRAME,
    count_samples,
    parse_frame,
)


def _make_payload(values):
    return np.array(values, dtype="<i4").tobytes()


def test_parse_frame_roundtrips_values():
    payload = _make_payload([0, 1, -1, 2_000_000, -2_000_000])
    samples = parse_frame(payload)
    assert samples.dtype == np.dtype("<i4")
    assert samples.tolist() == [0, 1, -1, 2_000_000, -2_000_000]


def test_parse_frame_is_little_endian():
    # 1 as int32_le is 01 00 00 00.
    payload = bytes([0x01, 0x00, 0x00, 0x00])
    assert parse_frame(payload).tolist() == [1]


def test_parse_frame_rejects_non_multiple_of_four():
    # 5 bytes is not a whole number of int32 samples.
    with pytest.raises(ValueError):
        parse_frame(b"\x00\x00\x00\x00\x01")


def test_parse_frame_empty_payload():
    assert parse_frame(b"").tolist() == []


def test_count_samples_matches_length():
    payload = _make_payload(list(range(100)))
    assert count_samples(payload) == 100


def test_count_samples_full_frame():
    payload = _make_payload([0] * EXPECTED_SAMPLES_PER_FRAME)
    assert count_samples(payload) == EXPECTED_SAMPLES_PER_FRAME
