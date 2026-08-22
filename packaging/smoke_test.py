"""Drives the real pipeline against an already-running instance (frozen
binary or plain `python packaging/launcher.py`) and asserts a real frame
comes back with the right shape.

A PyInstaller build succeeding and the resulting binary actually working are
two different claims -- this is what CI runs after starting the binary, to
prove the second one, not just the first.

Usage: python packaging/smoke_test.py [app_port] [uc_port]
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

TIMEOUT_S = 15


async def main(app_port: int, uc_port: int) -> int:
    uri = f"ws://127.0.0.1:{app_port}/ws"
    uc_url = f"ws://127.0.0.1:{uc_port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"action": "connect", "url": uc_url}))
        async with asyncio.timeout(TIMEOUT_S):
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("type") == "event" and msg.get("kind") == "connect_failed":
                    print("FAIL: connect_failed ->", msg.get("detail"), file=sys.stderr)
                    return 1
                if msg.get("type") == "frame":
                    assert msg["sample_count"] == 20000, msg
                    assert len(msg["frame_hash"]) == 32, msg
                    print(
                        "OK -- frame received:",
                        msg["sample_count"],
                        "samples, hash",
                        msg["frame_hash"],
                    )
                    return 0


if __name__ == "__main__":
    app_port = int(sys.argv[1]) if len(sys.argv) > 1 else 48000
    uc_port = int(sys.argv[2]) if len(sys.argv) > 2 else 48765
    try:
        sys.exit(asyncio.run(main(app_port, uc_port)))
    except TimeoutError:
        sys.exit(f"FAIL: no frame received within {TIMEOUT_S}s")
