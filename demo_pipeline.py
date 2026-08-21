"""Manual demo: run the full processing pipeline against a running mock uC.

This is a developer/reviewer convenience script (not part of the automated
test suite). It connects the real websocket_client to a mock uC and prints,
for each frame, exactly what the backend would forward to the frontend: the
spec-formatted log line plus validation, estimated sample rate, and how many
decimated points the plot would receive.

Usage:
    1. In one terminal:   python -m mock_uc.server --fps 40 --port 8811
    2. In another:        python demo_pipeline.py                  # uses 8811
       or:                python demo_pipeline.py ws://HOST:PORT   # custom uC
"""

import asyncio
import sys

from backend.app.models import ConnectionEvent, ProcessedFrame
from backend.app.websocket_client import stream_frames

DEFAULT_URI = "ws://127.0.0.1:8811"
FRAMES_TO_SHOW = 5


async def run(uri: str) -> None:
    print(f"Connecting to {uri} ...")
    shown = 0
    async for event in stream_frames(uri, plot_points=2000):
        if isinstance(event, ConnectionEvent):
            print(f">>> EVENT: {event.kind}  ({event.detail})")
            if event.kind == "connect_failed":
                print("    (is the mock uC running? see step 1 in this file's docstring)")
                return
        elif isinstance(event, ProcessedFrame):
            shown += 1
            rate = (
                f"{event.sample_rate / 1e6:.2f} Msps"
                if event.sample_rate is not None
                else "measuring..."
            )
            print(event.to_log_line())
            print(
                f"    -> valid={event.is_valid} | rate={rate} | "
                f"plot_points={len(event.plot_samples)}"
            )
            if shown >= FRAMES_TO_SHOW:
                print(f"\nShown {FRAMES_TO_SHOW} frames. Pipeline works. Exiting.")
                return


if __name__ == "__main__":
    import contextlib

    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URI
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(target))
