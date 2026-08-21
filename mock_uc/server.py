"""Mock uC WebSocket server.

Fake uC so we can build/test the rest of the pipeline without the real
hardware. It just opens a WebSocket and blasts int32_le frames at whoever
connects.

    python -m mock_uc.server            # ws://0.0.0.0:8765
    python -m mock_uc.server --fps 100  # real board runs ~100 fps / 8 MB/s,
                                         # we default lower so dev laptops keep up
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time

import websockets

from .signal_generator import (
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

    print(
        f"[mock_uc] listening on ws://{args.host}:{args.port} "
        f"({args.samples} samples/frame, {args.fps} fps target, "
        f"{SAMPLE_RATE_HZ} sps nominal)"
    )

    async def bound_handler(ws):
        await _handler(ws, args.fps, args.samples)

    # compression=None: `websockets` negotiates permessage-deflate by default,
    # which costs ~4 ms of CPU per 80 KB frame here. Sensor data is essentially
    # incompressible noise, so that CPU buys nothing and caps the achievable
    # frame rate. The real uC streams raw bytes too.
    async with websockets.serve(
        bound_handler, args.host, args.port, max_size=None, compression=None
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
