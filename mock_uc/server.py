"""Mock uC WebSocket server.

Fake uC so we can build/test the rest of the pipeline without the real
hardware. It just opens a WebSocket and blasts int32_le frames at whoever
connects.

    python -m mock_uc.server            # ws://0.0.0.0:8765
    python -m mock_uc.server --fps 100  # real board runs ~100 fps / 8 MB/s,
                                         # we default lower so dev laptops keep up
"""

from __future__ import annotations

import sys

# Checked before any third-party import: on too old an interpreter, pip
# either can't resolve numpy>=2.0 at all (aborting the whole install) or, if
# an unpinned older one slipped in some other way, things may still "work"
# but not as tested. Either way this is a clearer failure than a
# ModuleNotFoundError or a version-specific bug turning up later.
if sys.version_info < (3, 12):  # noqa: UP036 -- deliberately reachable on old interpreters
    sys.exit(
        "Sensor Monitor requires Python 3.12+, but this interpreter is "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        "See README.md > Getting Started for how to install 3.12, or run "
        "with Docker instead: docker compose up --build"
    )

import argparse  # noqa: E402
import asyncio  # noqa: E402
import contextlib  # noqa: E402
import errno  # noqa: E402
import time  # noqa: E402

import websockets  # noqa: E402

from .signal_generator import (  # noqa: E402
    EXPECTED_SAMPLES_PER_FRAME,
    SAMPLE_RATE_HZ,
    SignalGenerator,
)


async def _stream_frames(websocket, fps: float, samples_per_frame: int) -> None:
    """Streams synthetic frames to a connected client until it disconnects.

    Paced against absolute deadlines rather than by sleeping a fixed interval
    after each send. Generating and sending a frame costs real time, so
    "work, then sleep(interval)" yields a period of `work + interval` and
    consistently undershoots the target rate. Sleeping only until the next
    deadline subtracts the work already done and keeps the average on target.

    Args:
        websocket: The connected client's WebSocket, used to send frames.
        fps: Target frames per second. ``0`` disables the throttling sleep
            and sends as fast as possible.
        samples_per_frame: Number of int32 samples to generate per frame.
    """
    generator = SignalGenerator(samples_per_frame=samples_per_frame)
    interval = 1.0 / fps if fps > 0 else 0.0
    next_deadline = time.monotonic()

    try:
        while True:
            frame = generator.next_frame()
            await websocket.send(frame)
            if not interval:
                continue

            next_deadline += interval
            delay = next_deadline - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                # Can't keep up with the requested rate. Rebase the schedule
                # instead of accumulating debt, which would otherwise be
                # repaid as a burst of back-to-back frames.
                next_deadline = time.monotonic()
                await asyncio.sleep(0)
    except websockets.ConnectionClosed:
        return  # client dropped, nothing else to do


async def _handler(websocket, fps: float, samples_per_frame: int) -> None:
    """Handles one client connection: logs it, streams frames, logs the drop.

    Args:
        websocket: The connected client's WebSocket.
        fps: Target frames per second, forwarded to `_stream_frames`.
        samples_per_frame: Samples per frame, forwarded to `_stream_frames`.
    """
    client = getattr(websocket, "remote_address", "unknown")
    print(f"[mock_uc] client connected: {client}, streaming...")
    await _stream_frames(websocket, fps, samples_per_frame)
    print(f"[mock_uc] client disconnected: {client}")


async def main() -> None:
    """Parses CLI arguments and runs the mock uC server until interrupted.

    Reads ``--host``, ``--port``, ``--fps`` and ``--samples`` from the
    command line, then serves WebSocket connections indefinitely, streaming
    a fresh synthetic signal to each client that connects.
    """
    parser = argparse.ArgumentParser(description="Mock uC WebSocket server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Target frames per second (real uC is ~100).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=EXPECTED_SAMPLES_PER_FRAME,
        help="Samples per frame (default 20000, matching the spec).",
    )
    args = parser.parse_args()

    async def bound_handler(ws):
        await _handler(ws, args.fps, args.samples)

    # compression=None: `websockets` negotiates permessage-deflate by default,
    # which costs ~4 ms of CPU per 80 KB frame here. Sensor data is essentially
    # incompressible noise, so that CPU buys nothing and caps the achievable
    # frame rate. The real uC streams raw bytes too.
    try:
        server_cm = websockets.serve(
            bound_handler, args.host, args.port, max_size=None, compression=None
        )
        async with server_cm:
            # Only printed once the socket is actually bound -- if the port
            # is taken, the exception below fires before this ever prints.
            print(
                f"[mock_uc] listening on ws://{args.host}:{args.port} "
                f"({args.samples} samples/frame, {args.fps} fps target, "
                f"{SAMPLE_RATE_HZ} sps nominal)"
            )
            await asyncio.Future()  # run forever
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            sys.exit(
                f"[mock_uc] ERROR: port {args.port} is already in use.\n"
                "Another mock_uc.server is probably still running. Try:\n"
                '  pkill -f "mock_uc.server"\n'
                "or start this one on a different port:\n"
                f"  python -m mock_uc.server --port {args.port + 1}"
            )
        raise


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
