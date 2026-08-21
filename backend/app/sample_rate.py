"""Sample-rate estimation.

The challenge requires displaying an estimated sample rate, measured at every
frame. The rate is derived from how many samples arrived between two frame
timestamps:

    rate = samples_in_current_frame / (t_now - t_previous)

To avoid a jumpy readout (frame arrival is bursty over a network), an optional
exponential moving average smooths the instantaneous estimate. The estimator
is intentionally stateful but tiny, and takes the timestamp as an argument so
it can be tested deterministically without touching the real clock.
"""

from __future__ import annotations


class SampleRateEstimator:
    """Estimates samples-per-second from successive frame arrivals."""

    def __init__(self, smoothing: float = 0.3) -> None:
        """Initialises the estimator.

        Args:
            smoothing: EMA factor in [0, 1]. 1.0 disables smoothing (report the
                raw instantaneous rate); lower values smooth more heavily.
        """
        if not 0.0 < smoothing <= 1.0:
            raise ValueError("smoothing must be in the interval (0, 1].")
        self._smoothing = smoothing
        self._last_timestamp: float | None = None
        self._smoothed_rate: float | None = None

    def update(self, sample_count: int, timestamp: float) -> float | None:
        """Registers a frame arrival and returns the current rate estimate.

        Args:
            sample_count: Number of samples in the frame that just arrived.
            timestamp: Monotonic arrival time in seconds (e.g. time.monotonic()).

        Returns:
            The estimated sample rate in samples/second, or ``None`` for the
            very first frame (no previous timestamp to measure an interval
            against). Non-positive or zero intervals are ignored and return the
            last known estimate, guarding against division by zero.
        """
        previous = self._last_timestamp
        self._last_timestamp = timestamp

        if previous is None:
            return None

        interval = timestamp - previous
        if interval <= 0:
            return self._smoothed_rate

        instantaneous = sample_count / interval

        if self._smoothed_rate is None:
            self._smoothed_rate = instantaneous
        else:
            self._smoothed_rate = (
                self._smoothing * instantaneous
                + (1.0 - self._smoothing) * self._smoothed_rate
            )
        return self._smoothed_rate

    def reset(self) -> None:
        """Clears state so a new connection starts estimating from scratch."""
        self._last_timestamp = None
        self._smoothed_rate = None
