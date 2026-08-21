"""Tests for PlotThrottle."""

import pytest

from backend.app.plot_throttle import PlotThrottle


def test_first_call_always_emits():
    t = PlotThrottle(max_fps=30.0)
    assert t.should_emit(now=0.0) is True


def test_second_call_too_soon_is_blocked():
    t = PlotThrottle(max_fps=30.0)  # min interval ~0.0333s
    t.should_emit(now=0.0)
    # 10 ms later: too soon.
    assert t.should_emit(now=0.010) is False


def test_emits_again_after_interval():
    t = PlotThrottle(max_fps=30.0)
    t.should_emit(now=0.0)
    # 40 ms later: past the ~33 ms interval.
    assert t.should_emit(now=0.040) is True


def test_cadence_over_time():
    t = PlotThrottle(max_fps=10.0)  # 0.1 s interval
    emitted = [t.should_emit(now=i * 0.05) for i in range(6)]
    # At 0.05 s steps with a 0.1 s interval, every other call emits.
    assert emitted == [True, False, True, False, True, False]


def test_reset_restarts_cadence():
    t = PlotThrottle(max_fps=30.0)
    t.should_emit(now=0.0)
    t.reset()
    # After reset, the next call is treated as the first again.
    assert t.should_emit(now=0.001) is True


def test_invalid_fps_rejected():
    with pytest.raises(ValueError):
        PlotThrottle(max_fps=0.0)
    with pytest.raises(ValueError):
        PlotThrottle(max_fps=-5.0)