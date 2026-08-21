"""Shared data models.

These dataclasses describe what a *processed* frame looks like as it flows out
of the WebSocket client and towards the buffer / frontend. Keeping them in one
place (instead of passing loose dicts around) gives every layer a typed,
self-documenting contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProcessedFrame:
    """The result of receiving and processing one raw frame from the uC.

    Attributes:
        frame_number: 1-based sequence number since the current connection
            started (resets on each new connection).
        timestamp: Wall-clock time the frame was received, formatted for the
            log line (e.g. "2026-08-20 18:00:00").
        sample_count: Number of int32 samples actually found in the frame.
        expected_samples: Number of samples a valid frame should contain.
        is_valid: True when sample_count == expected_samples. Drives the
            "red log line" requirement in the UI.
        frame_hash: XXH3_128 of the raw payload, as a 32-char hex string.
        sample_rate: Estimated samples/second measured at this frame, or None
            for the first frame (no interval to measure yet).
        plot_samples: Down-sampled samples for the real-time plot (never the
            full 20000 — see PlotDecimator). Empty if decimation was skipped.
        spectrum_db: Magnitudes in dBFS for the frequency-domain view, evenly
            spaced from DC to spectrum_max_hz. Empty unless the frontend is
            showing the FD tab — the FFT is only computed when someone is
            looking at it.
        spectrum_max_hz: Nyquist frequency the magnitudes span, so the
            frontend can rebuild the frequency axis without it being resent on
            every frame. None when no spectrum was computed.
        peak_hz: Where the tallest bin of the spectrum sits, accurate to
            within a single FFT bin. Left as None on any frame where no
            spectrum was computed.
        peak_db: How tall that bin is, in dBFS. Also None whenever peak_hz
            is None -- the two always arrive together.
        power_db: RMS power of the frame's raw samples, in dBFS. This one
            isn't gated by domain -- it comes from a cheap extra pass over
            samples the time-domain plot already reads, so it's filled in
            every frame. Only None when the frame had no parseable samples
            at all.
    """

    frame_number: int
    timestamp: str
    sample_count: int
    expected_samples: int
    is_valid: bool
    frame_hash: str
    sample_rate: float | None
    plot_samples: list[float] = field(default_factory=list)
    spectrum_db: list[float] = field(default_factory=list)
    spectrum_max_hz: float | None = None
    peak_hz: float | None = None
    peak_db: float | None = None
    power_db: float | None = None

    def to_log_line(self) -> str:
        """Formats the frame as the log line required by the challenge.

        Format: "[date_and_time]: frame_number | samples | hash"
        e.g. "[2026-08-20 18:00:00]: Frame 1 | 20000 | e2966f42...284ff9d"
        """
        return (
            f"[{self.timestamp}]: Frame {self.frame_number} | "
            f"{self.sample_count} | {self.frame_hash}"
        )

    def to_dict(self) -> dict:
        """Serialises the frame for transport to the frontend as JSON."""
        return {
            "frame_number": self.frame_number,
            "timestamp": self.timestamp,
            "sample_count": self.sample_count,
            "expected_samples": self.expected_samples,
            "is_valid": self.is_valid,
            "frame_hash": self.frame_hash,
            "sample_rate": self.sample_rate,
            "plot_samples": self.plot_samples,
            "spectrum_db": self.spectrum_db,
            "spectrum_max_hz": self.spectrum_max_hz,
            "peak_hz": self.peak_hz,
            "peak_db": self.peak_db,
            "power_db": self.power_db,
            "log_line": self.to_log_line(),
        }


@dataclass(frozen=True)
class ConnectionEvent:
    """A lifecycle event for the uC connection, surfaced to the frontend.

    The challenge requires popups when the connection cannot be established or
    drops mid-stream; this carries that information to the UI layer.

    Attributes:
        kind: One of "connected", "connect_failed", "disconnected".
        detail: Human-readable message (e.g. the exception text) for the popup.
    """

    kind: str
    detail: str = ""
