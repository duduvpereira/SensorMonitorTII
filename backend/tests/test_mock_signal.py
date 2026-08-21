"""Integration test: the mock generator's output must be parseable by the
backend parser and pass validation. This keeps the mock uC and the real
parsing path from drifting apart.
"""

from backend.app.frame_parser import EXPECTED_SAMPLES_PER_FRAME, parse_frame
from backend.app.frame_validator import validate_frame
from backend.app.hashing import hash_frame
from mock_uc.signal_generator import SignalGenerator


def test_generated_frame_has_expected_byte_length():
    gen = SignalGenerator(seed=42)
    frame = gen.next_frame()
    # frame is raw bytes, not samples; each int32_le sample is 4 bytes.
    assert len(frame) == EXPECTED_SAMPLES_PER_FRAME * 4


def test_generated_frame_parses_and_validates():
    gen = SignalGenerator(seed=42)
    frame = gen.next_frame()
    samples = parse_frame(frame)
    assert len(samples) == EXPECTED_SAMPLES_PER_FRAME
    assert validate_frame(frame).is_valid


def test_generated_frame_is_hashable():
    gen = SignalGenerator(seed=42)
    frame = gen.next_frame()
    assert len(hash_frame(frame)) == 32


def test_seeded_generator_is_reproducible():
    a = SignalGenerator(seed=7).next_frame()
    b = SignalGenerator(seed=7).next_frame()
    assert a == b


def test_phase_is_continuous_across_frames():
    # Two consecutive frames should differ (phase advances), i.e. the generator
    # is not just repeating the same block.
    gen = SignalGenerator(seed=1)
    first = gen.next_frame()
    second = gen.next_frame()
    assert first != second
