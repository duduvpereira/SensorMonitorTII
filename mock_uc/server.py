# Fake uC so we can build/test the rest of the pipeline without the real hardware.
# It just opens a WebSocket and blasts int32_le frames at whoever connects.
#
#   python -m mock_uc.server            # ws://0.0.0.0:8765
#   python -m mock_uc.server --fps 100  # real board runs ~100 fps / 8 MB/s,
#                                        # we default lower so dev laptops keep up

from __future__ import annotations

import argparse
import asyncio
import contextlib

import websockets

from .signal_generator import (
    EXPECTED_SAMPLES_PER_FRAME,
    SAMPLE_RATE_HZ,
    SignalGenerator,
)


async def _stream_frames(websocket, fps: float, samples_per_frame: int) -> None:
    generator = SignalGenerator(samples_per_frame=samples_per_frame)
    interval = 1.0 / fps if fps > 0 else 0.0

    try:
        while True:
            frame = generator.next_frame()
            await websocket.send(frame)
            if interval:
                await asyncio.sleep(interval)
    except websockets.ConnectionClosed:
        return  # client dropped, nothing else to do


async def _handler(websocket, fps: float, samples_per_frame: int) -> None:
    client = getattr(websocket, "remote_address", "unknown")
    print(f"[mock_uc] client connected: {client}, streaming...")
    await _stream_frames(websocket, fps, samples_per_frame)
    print(f"[mock_uc] client disconnected: {client}")


async def main() -> None:
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

    async with websockets.serve(bound_handler, args.host, args.port, max_size=None):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
