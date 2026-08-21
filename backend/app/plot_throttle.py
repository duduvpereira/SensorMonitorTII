"""Time-based plot throttling.

The uC streams frames at up to ~100/s, but redrawing the plot that often would
overwhelm the browser and, counter-intuitively, look *less* smooth: smoothness
is about a steady frame cadence over time, not raw throughput.

This throttle decouples the plot's render rate from the frame arrival rate.
Log lines are never throttled -- every frame still produces one -- only the
heavy plot payload is gated.

The timestamp is passed in (rather than read from the clock internally) so the
logic is fully deterministic under test.
"""

from __future__ import annotations


class PlotThrottle:
    """Decides when enough time has passed to emit another plot update."""

    def __init__(self, max_fps: float = 30.0) -> None:
        """Initialises the throttle.

        Args:
            max_fps: Maximum plot updates per second. Must be positive. The
                real uC arrival rate can be higher; the plot simply won't be
                refreshed faster than this.
        """
        if max_fps <= 0:
            raise ValueError("max_fps must be positive.")
        self._min_interval = 1.0 / max_fps
        self._last_emit: float | None = None

    def should_emit(self, now: float) -> bool:
        """Returns True if a plot update should be emitted at time ``now``.

        The first call always returns True (nothing has been plotted yet).
        Subsequent calls return True only once at least ``1 / max_fps`` seconds
        have elapsed since the last emitted update.

        Args:
            now: Current monotonic time in seconds (e.g. time.monotonic()).
        """
        if self._last_emit is None or (now - self._last_emit) >= self._min_interval:
            self._last_emit = now
            return True
        return False

    def reset(self) -> None:
        """Clears state so the next frame is treated as the first again."""
        self._last_emit = None