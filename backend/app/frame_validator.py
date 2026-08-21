"""Frame validation.

The challenge requires validating the total number of samples per frame: if a
frame's sample count differs from the expected value, its log line must be
flagged (rendered red in the UI). This module isolates that decision so it can
be unit-tested without any I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from .frame_parser import EXPECTED_SAMPLES_PER_FRAME, count_samples


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a single frame's sample count."""

    sample_count: int
    expected: int
    is_valid: bool


def validate_frame(payload: bytes, expected: int = EXPECTED_SAMPLES_PER_FRAME) -> ValidationResult:
    """Validates that a frame contains the expected number of samples.

    Args:
        payload: Raw bytes of one WebSocket frame.
        expected: Expected sample count (defaults to the spec's 20000).

    Returns:
        A ValidationResult carrying the actual count, the expected count, and
        whether they match. The caller (logging layer) uses ``is_valid`` to
        decide whether the log line should be marked as an error.
    """
    actual = count_samples(payload)
    return ValidationResult(
        sample_count=actual,
        expected=expected,
        is_valid=(actual == expected),
    )
