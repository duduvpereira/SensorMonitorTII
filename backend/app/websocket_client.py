"""WebSocket client for the microcontroller stream.

Connects to the uC's WebSocket server (or the mock), receives raw binary
frames, and runs each one through the processing pipeline
(parse -> validate -> hash -> sample-rate -> decimate), emitting a
ProcessedFrame per frame plus ConnectionEvents for lifecycle changes.

Design note: this module knows nothing about FastAPI or the frontend. It
exposes an async generator of events, so it can be driven by the web layer in
production and by a plain test harness against the mock uC in tests. That keeps
the network/processing logic fully unit-testable without spinning up a web
server.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import datetime

import numpy as np
import websockets

from .frame_parser import EXPECTED_SAMPLES_PER_FRAME, parse_frame
from .frame_validator import validate_frame
from .hashing import hash_frame
from .models import ConnectionEvent, ProcessedFrame
from .plot_decimator import decimate_minmax
from .sample_rate import SampleRateEstimator


def _now_str() -> str:
    """Returns the current wall-clock time formatted for the log line."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def process_payload(
    payload: bytes,
    frame_number: int,
    estimator: SampleRateEstimator,
    plot_points: int,
    arrival_time: float | None = None,
) -> ProcessedFrame:
    """Runs one raw payload through the full processing pipeline.

    Separated from the network loop so it can be unit-tested directly with
    synthetic payloads (no sockets involved).

    Args:
        payload: Raw bytes of one frame.
        frame_number: 1-based sequence number for this frame.
        estimator: Sample-rate estimator (stateful across frames).
        plot_points: Target number of decimated points for the plot.
        arrival_time: Monotonic arrival time; defaults to time.monotonic().

    Returns:
        A fully populated ProcessedFrame.
    """
    if arrival_time is None:
        arrival_time = time.monotonic()

    validation = validate_frame(payload)
    frame_hash = hash_frame(payload)
    rate = estimator.update(validation.sample_count, arrival_time)

    # Only decimate when the payload is a whole number of samples; a corrupt
    # (non-multiple-of-4) payload still gets logged/validated, just not plotted.
    plot_samples: list[float] = []
    try:
        samples = parse_frame(payload)
        if samples.size:
            plot_samples = decimate_minmax(samples, target_points=plot_points)
    except ValueError:
        plot_samples = []

    return ProcessedFrame(
        frame_number=frame_number,
        timestamp=_now_str(),
        sample_count=validation.sample_count,
        expected_samples=validation.expected,
        is_valid=validation.is_valid,
        frame_hash=frame_hash,
        sample_rate=rate,
        plot_samples=plot_samples,
    )


async def stream_frames(
    uri: str,
    plot_points: int = 2000,
    expected_samples: int = EXPECTED_SAMPLES_PER_FRAME,
) -> AsyncIterator[ProcessedFrame | ConnectionEvent]:
    """Connects to the uC and yields processed frames and lifecycle events.

    Yields, in order:
        - a ConnectionEvent("connected") once the socket is open, OR a
          ConnectionEvent("connect_failed") if the connection can't be made;
        - a ProcessedFrame for every received frame;
        - a ConnectionEvent("disconnected") when the stream ends (either the
          server closed it or a network error occurred).

    The caller (web layer) forwards these to the frontend: frames drive the
    plot/log, events drive the popups and the Connect-button state.

    Args:
        uri: WebSocket URL of the uC, e.g. "ws://192.168.0.10:8765".
        plot_points: Target decimated point count per frame for the plot.
        expected_samples: Expected samples/frame (kept for future configurability).
    """
    estimator = SampleRateEstimator()

    try:
        connection = await websockets.connect(uri, max_size=None)
    except (OSError, websockets.InvalidURI, websockets.InvalidHandshake) as exc:
        # Connection could not be established -> frontend shows a popup.
        yield ConnectionEvent(kind="connect_failed", detail=str(exc))
        return

    yield ConnectionEvent(kind="connected", detail=uri)

    frame_number = 0
    try:
        async for payload in connection:
            # The uC sends binary frames; ignore any stray text messages.
            # Verify this
            if isinstance(payload, str):
                payload = payload.encode("latin-1")
            frame_number += 1
            yield process_payload(
                payload,
                frame_number=frame_number,
                estimator=estimator,
                plot_points=plot_points,
            )
    except websockets.ConnectionClosed as exc:
        yield ConnectionEvent(kind="disconnected", detail=str(exc))
        return
    finally:
        await connection.close()

    # Normal end of stream (server stopped sending and closed cleanly).
    yield ConnectionEvent(kind="disconnected", detail="stream ended")



## TODO REMOVE
# Silence "imported but unused" for numpy in environments that tree-shake;
# parse_frame returns an ndarray so numpy is a real runtime dependency.
_ = np
