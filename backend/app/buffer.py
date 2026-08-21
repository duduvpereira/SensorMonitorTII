"""Frame ring buffer.

Sits between the WebSocket client (which produces processed frames at the uC's
rate, up to ~100/s) and the consumers (the plot, which only needs the latest
frame at ~30/s, and data export, which needs a short history).

A deque(maxlen=capacity) bounds memory automatically -- once full, each append
evicts the oldest frame. The buffer does no rate-limiting of its own; deciding
how often to read the latest frame for the plot is the consumer's job (the web
layer).

Thread/task-safety note: in this app the buffer is written and read from the
same asyncio event loop (no threads), so no locking is required. If it were
ever shared across threads, appends/reads would need a lock.
"""

from __future__ import annotations

from collections import deque

from .models import ProcessedFrame


class FrameRingBuffer:
    """A fixed-capacity ring buffer of ProcessedFrame objects."""

    def __init__(self, capacity: int) -> None:
        """Initialises the buffer.

        Args:
            capacity: Maximum number of frames to retain. Must be positive.
                Once full, each new append discards the oldest frame.

        Raises:
            ValueError: If capacity is not positive.
        """
        if capacity <= 0:
            raise ValueError("capacity must be a positive integer.")
        self._capacity = capacity
        self._frames: deque[ProcessedFrame] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        """The maximum number of frames the buffer can hold."""
        return self._capacity

    def __len__(self) -> int:
        """Current number of frames stored (0..capacity)."""
        return len(self._frames)

    def is_empty(self) -> bool:
        """True when no frames have been stored yet."""
        return len(self._frames) == 0

    def is_full(self) -> bool:
        """True when the buffer has reached capacity."""
        return len(self._frames) == self._capacity

    def append(self, frame: ProcessedFrame) -> None:
        """Adds a frame, discarding the oldest one if already at capacity."""
        self._frames.append(frame)

    def latest(self) -> ProcessedFrame | None:
        """Returns the most recently appended frame, or None if empty."""
        if not self._frames:
            return None
        return self._frames[-1]

    def snapshot(self, count: int | None = None) -> list[ProcessedFrame]:
        """Returns a list copy of the retained frames, oldest first.

        Args:
            count: If given, return at most the last ``count`` frames; if None,
                return everything currently held. Values <= 0 yield an empty
                list.

        Returns:
            A new list (safe for the caller to iterate while the buffer keeps
            changing).
        """
        if count is None:
            return list(self._frames)
        if count <= 0:
            return []
        if count >= len(self._frames):
            return list(self._frames)
        # deque doesn't support slicing; take the last `count` items.
        return list(self._frames)[-count:]

    def clear(self) -> None:
        """Drops all frames (e.g. when a new connection starts)."""
        self._frames.clear()
