"""FastAPI application: the web layer that ties everything together.

Architecture — the backend is a WebSocket *server* to the browser and a
WebSocket *client* to the uC at the same time:

    Browser  --WS-->  FastAPI (/ws)  --WS-->  uC / mock
             <------  frontend<->backend  <------

Flow:
    1. Browser opens /ws and sends {"action": "connect", "url": "ws://uc:8765"}.
    2. Backend opens stream_frames() against that URL (the client layer).
    3. For every ProcessedFrame, the backend sends the log/metadata to the
       browser; the heavy plot_samples are included only when the time-based
       throttle allows, keeping the plot smooth without dropping any log line.
    4. ConnectionEvents (connected / connect_failed / disconnected) are relayed
       so the frontend can show popups and toggle the Connect button.
    5. Browser can send {"action": "disconnect"} to stop the stream.

Scope: one frontend client at a time (per the challenge's "one client, one
server" assumption). A second connection is rejected while one is active.
"""

from __future__ import annotations

import sys

# Checked before any third-party import: on too old an interpreter, pip
# either can't resolve numpy>=2.0 at all (aborting the whole install) or, if
# an unpinned older one slipped in some other way, things may still "work"
# but not as tested. Either way this is a clearer failure than a
# ModuleNotFoundError or a version-specific bug turning up later. Runs at
# import time since uvicorn imports this module rather than executing it.
if sys.version_info < (3, 12):  # noqa: UP036 -- deliberately reachable on old interpreters
    sys.exit(
        "Sensor Monitor requires Python 3.12+, but this interpreter is "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        "See README.md > Getting Started for how to install 3.12, or run "
        "with Docker instead: docker compose up --build"
    )

import asyncio  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .buffer import FrameRingBuffer  # noqa: E402
from .export import frames_to_csv, frames_to_json  # noqa: E402
from .models import ConnectionEvent, ProcessedFrame  # noqa: E402
from .plot_throttle import PlotThrottle  # noqa: E402
from .websocket_client import StreamOptions, stream_frames  # noqa: E402

# --- Configuration -----------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# Retain ~10 seconds of frames at the uC's ~100 fps for the optional export.
BUFFER_CAPACITY = 1000

# Cap the plot at 30 updates/second regardless of arrival rate.
PLOT_MAX_FPS = 30.0

# Target decimated points per plotted frame.
PLOT_POINTS = 2000

# Target points in the frequency-domain spectrum. Half of PLOT_POINTS because
# the FD view has no min/max pairing -- one point per frequency bucket.
SPECTRUM_POINTS = 1000

# Nominal uC frame rate (frames/second), used to translate "last N seconds"
# of the export request into a frame count against the buffer.
NOMINAL_FPS = 100

# URL the frontend's input box is pre-filled with. Overridable via environment
# so the same image works in both setups: under Docker Compose the mock uC is
# reachable by its service name, while a local run uses localhost.
DEFAULT_UC_URL = os.getenv("SENSOR_MONITOR_UC_URL", "ws://localhost:8765")


app = FastAPI(title="Sensor Monitor")

# Shared frame buffer. It lives at app scope (not inside the WebSocket handler)
# so the HTTP export endpoint can read the recently received frames. With the
# single-client assumption, one shared buffer is sufficient.
_buffer = FrameRingBuffer(capacity=BUFFER_CAPACITY)


@app.get("/")
async def index() -> FileResponse:
    """Serves the single-page frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/config")
async def config() -> dict:
    """Runtime settings the frontend reads on load.

    Keeps the deployment-specific uC URL out of the static HTML, so the same
    image works locally and under Docker Compose.
    """
    return {"default_uc_url": DEFAULT_UC_URL}


class _SingleClientGuard:
    """Ensures only one frontend WebSocket is served at a time."""

    def __init__(self) -> None:
        self._busy = False

    def acquire(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        return True

    def release(self) -> None:
        self._busy = False


_guard = _SingleClientGuard()


async def _relay_uc_stream(
    frontend_ws: WebSocket,
    uc_url: str,
    buffer: FrameRingBuffer,
    throttle: PlotThrottle,
    options: StreamOptions,
) -> None:
    """Pumps the uC stream to the frontend until it ends or is cancelled.

    Every frame updates the buffer and produces a JSON message; the plot
    payload is gated by the time throttle so the plot stays smooth. Connection
    events are forwarded verbatim for the UI popups.
    """
    buffer.clear()
    throttle.reset()

    async for item in stream_frames(
        uc_url,
        plot_points=PLOT_POINTS,
        options=options,
        spectrum_points=SPECTRUM_POINTS,
    ):
        if isinstance(item, ConnectionEvent):
            await frontend_ws.send_json(
                {"type": "event", "kind": item.kind, "detail": item.detail}
            )
            # A failed/closed connection ends the stream naturally.
            continue

        if isinstance(item, ProcessedFrame):
            buffer.append(item)
            message = item.to_dict()

            # Throttle only the heavy plot payloads; the log line always goes.
            if not throttle.should_emit(time.monotonic()):
                message["plot_samples"] = []
                message["spectrum_db"] = []

            message["type"] = "frame"
            await frontend_ws.send_json(message)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """The frontend-facing WebSocket endpoint."""
    await websocket.accept()

    if not _guard.acquire():
        await websocket.send_json(
            {"type": "event", "kind": "busy", "detail": "Another client is connected."}
        )
        await websocket.close()
        return

    throttle = PlotThrottle(max_fps=PLOT_MAX_FPS)
    options = StreamOptions()
    stream_task: asyncio.Task | None = None

    try:
        while True:
            command = await websocket.receive_json()
            action = command.get("action")

            if action == "connect":
                uc_url = command.get("url", "")
                if stream_task and not stream_task.done():
                    stream_task.cancel()
                stream_task = asyncio.create_task(
                    _relay_uc_stream(websocket, uc_url, _buffer, throttle, options)
                )

            elif action == "set_domain":
                # Mutating the shared options object is enough: the running
                # stream re-reads it on every frame, so the switch takes effect
                # on the next one without touching the uC connection.
                domain = command.get("domain")
                if domain in ("td", "fd"):
                    options.domain = domain

            elif action == "disconnect":
                if stream_task and not stream_task.done():
                    stream_task.cancel()
                    stream_task = None
                await websocket.send_json(
                    {"type": "event", "kind": "disconnected", "detail": "by user"}
                )

    except WebSocketDisconnect:
        # Browser closed the tab / navigated away.
        pass
    finally:
        if stream_task and not stream_task.done():
            stream_task.cancel()
        _guard.release()


@app.get("/export")
async def export(fmt: str = "csv", seconds: float = 5.0) -> Response:
    """Exports the most recently received frames as CSV or JSON.

    Query params:
        fmt: "csv" or "json" (defaults to csv).
        seconds: how many seconds of recent data to export (defaults to 5).
            Translated to a frame count via NOMINAL_FPS and clamped to what the
            buffer actually holds.

    Returns the file as an attachment so the browser downloads it. Exports the
    decimated samples + per-frame metadata currently in the buffer (see
    export.py for the rationale on decimated vs raw samples).
    """
    # Translate "last N seconds" into a frame count.
    frame_count = max(1, int(seconds * NOMINAL_FPS))
    frames = _buffer.snapshot(count=frame_count)

    if fmt == "json":
        body = frames_to_json(frames)
        media_type = "application/json"
        filename = "sensor_export.json"
    else:
        body = frames_to_csv(frames)
        media_type = "text/csv"
        filename = "sensor_export.csv"

    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Serve the rest of the frontend assets (app.js, style.css) at the root.
# Mounted last so it doesn't shadow the routes defined above.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")