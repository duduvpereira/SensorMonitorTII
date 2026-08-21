"""Tests for the FrameRingBuffer."""

import pytest

from backend.app.buffer import FrameRingBuffer
from backend.app.models import ProcessedFrame


def _frame(n: int) -> ProcessedFrame:
    """Builds a minimal ProcessedFrame tagged with frame_number n."""
    return ProcessedFrame(
        frame_number=n,
        timestamp="2026-08-20 18:00:00",
        sample_count=20000,
        expected_samples=20000,
        is_valid=True,
        frame_hash="0" * 32,
        sample_rate=None,
    )


def test_new_buffer_is_empty():
    buf = FrameRingBuffer(capacity=5)
    assert buf.is_empty()
    assert not buf.is_full()
    assert len(buf) == 0
    assert buf.latest() is None
    assert buf.snapshot() == []


def test_append_and_latest():
    buf = FrameRingBuffer(capacity=5)
    buf.append(_frame(1))
    buf.append(_frame(2))
    assert len(buf) == 2
    assert buf.latest().frame_number == 2
    assert not buf.is_empty()


def test_fills_to_capacity():
    buf = FrameRingBuffer(capacity=3)
    for i in range(1, 4):
        buf.append(_frame(i))
    assert buf.is_full()
    assert len(buf) == 3


def test_overwrites_oldest_when_full():
    buf = FrameRingBuffer(capacity=3)
    for i in range(1, 6):  # append 1,2,3,4,5 into capacity-3 buffer
        buf.append(_frame(i))
    # Only the last 3 (3,4,5) should remain, oldest first.
    numbers = [f.frame_number for f in buf.snapshot()]
    assert numbers == [3, 4, 5]
    assert buf.latest().frame_number == 5
    assert len(buf) == 3


def test_snapshot_returns_copy():
    buf = FrameRingBuffer(capacity=5)
    buf.append(_frame(1))
    snap = buf.snapshot()
    buf.append(_frame(2))
    # The earlier snapshot must not see the later append.
    assert [f.frame_number for f in snap] == [1]


def test_snapshot_with_count():
    buf = FrameRingBuffer(capacity=10)
    for i in range(1, 6):  # 1..5
        buf.append(_frame(i))
    assert [f.frame_number for f in buf.snapshot(count=2)] == [4, 5]
    assert [f.frame_number for f in buf.snapshot(count=100)] == [1, 2, 3, 4, 5]
    assert buf.snapshot(count=0) == []
    assert buf.snapshot(count=-1) == []


def test_clear():
    buf = FrameRingBuffer(capacity=5)
    buf.append(_frame(1))
    buf.append(_frame(2))
    buf.clear()
    assert buf.is_empty()
    assert buf.latest() is None


def test_capacity_property():
    buf = FrameRingBuffer(capacity=7)
    assert buf.capacity == 7


def test_invalid_capacity_rejected():
    with pytest.raises(ValueError):
        FrameRingBuffer(capacity=0)
    with pytest.raises(ValueError):
        FrameRingBuffer(capacity=-3)
