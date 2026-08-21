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
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import websockets

from .frame_parser import EXPECTED_SAMPLES_PER_FRAME, parse_frame
from .frame_validator import validate_frame
from .hashing import hash_frame
from .models import ConnectionEvent, ProcessedFrame
from .plot_decimator import decimate_minmax
from .power import compute_power_dbfs
from .sample_rate import SampleRateEstimator
from .spectrum import compute_spectrum


@dataclass
class StreamOptions:
    """Knobs the caller can change while a stream is already running.

    Deliberately mutable, unlike the frozen result models: the user can switch
    between the time- and frequency-domain tabs mid-stream, and re-opening the
    uC connection just to change what we compute would drop frames. The web
    layer holds one of these and flips `domain` when the browser asks.

    Attributes:
        domain: "td" for time domain (default) or "fd" for frequency domain.
            The FFT only runs while this is "fd", so nothing is spent on a
            view nobody is looking at.
    """

    domain: str = "td"


def _now_str() -> str:
    """Returns the current wall-clock time formatted for the log line."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def process_payload(
    payload: bytes,
    frame_number: int,
    estimator: SampleRateEstimator,
    plot_points: int,
    arrival_time: float | None = None,
    compute_fd: bool = False,
    spectrum_points: int = 1000,
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
        compute_fd: Whether to also compute the frequency-domain spectrum.
            Off by default so the FFT costs nothing while the user is on the
            time-domain tab.
        spectrum_points: Target number of points in the reduced spectrum.

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
    # The time-domain decimation always runs -- it is cheap, and the export
    # feature reads it back out of the ring buffer regardless of which tab the
    # user happens to be on.
    plot_samples: list[float] = []
    spectrum_db: list[float] = []
    spectrum_max_hz: float | None = None
    peak_hz: float | None = None
    peak_db: float | None = None
    power_db: float | None = None
    try:
        samples = parse_frame(payload)
        if samples.size:
            plot_samples = decimate_minmax(samples, target_points=plot_points)
            # Unlike the FFT below, power is cheap enough to compute
            # unconditionally -- there's no domain gate on it.
            power_db = compute_power_dbfs(samples)
            if compute_fd:
                spectrum_db, spectrum_max_hz, peak_hz, peak_db = compute_spectrum(
                    samples, target_points=spectrum_points
                )
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
        spectrum_db=spectrum_db,
        spectrum_max_hz=spectrum_max_hz,
        peak_hz=peak_hz,
        peak_db=peak_db,
        power_db=power_db,
    )


async def stream_frames(
    uri: str,
    plot_points: int = 2000,
    expected_samples: int = EXPECTED_SAMPLES_PER_FRAME,
    options: StreamOptions | None = None,
    spectrum_points: int = 1000,
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
        options: Live stream settings the caller may mutate mid-stream (which
            domain to compute). Defaults to time domain only.
        spectrum_points: Target point count for the frequency-domain spectrum.
    """
    estimator = SampleRateEstimator()
    if options is None:
        options = StreamOptions()

    try:
        # compression=None: decompressing permessage-deflate would burn CPU per
        # frame for no gain on incompressible sensor data, and the extension is
        # only used if *both* ends offer it -- declining here also spares the uC
        # the compression cost.
        connection = await websockets.connect(uri, max_size=None, compression=None)
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
            # Read the option per frame, not once up front: the user can switch
            # tabs at any moment and the change must take effect immediately.
            yield process_payload(
                payload,
                frame_number=frame_number,
                estimator=estimator,
                plot_points=plot_points,
                compute_fd=options.domain == "fd",
                spectrum_points=spectrum_points,
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
