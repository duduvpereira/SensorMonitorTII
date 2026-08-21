"""Integration tests for the FastAPI web layer (main.py).

Uses Starlette's TestClient, which drives the real /ws WebSocket endpoint in
process. A mock uC is started on an ephemeral port so the full path
(frontend WS -> backend -> uC WS -> pipeline -> frontend WS) is exercised.
"""

import asyncio
import threading

import websockets
from fastapi.testclient import TestClient

from backend.app.main import app
from mock_uc.signal_generator import SignalGenerator


class MockUC:
    """Runs the mock uC WebSocket server in a background thread for tests."""

    def __init__(self):
        self.port = None
        self._loop = None
        self._thread = None
        self._ready = threading.Event()

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self

    def __exit__(self, *exc):
        if self._loop:
            self._loop.call_soon_threadsafe(self._shutdown)
            if self._thread:
                self._thread.join(timeout=2)

    def _shutdown(self):
        # Cancel any in-flight handler tasks before stopping the loop, so it
        # doesn't complain about pending tasks being destroyed.
        for task in asyncio.all_tasks(self._loop):
            task.cancel()
        self._loop.stop()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())
        try:
            self._loop.run_forever()
        finally:
            # Let cancelled handler tasks finish unwinding before closing.
            pending = asyncio.all_tasks(self._loop)
            self._loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
            self._loop.close()

    async def _serve(self):
        async def handler(ws):
            gen = SignalGenerator(seed=1)
            try:
                while True:
                    await ws.send(gen.next_frame())
                    await asyncio.sleep(0.005)
            except websockets.ConnectionClosed:
                return

        server = await websockets.serve(handler, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self._ready.set()


def test_index_is_served():
    client = TestClient(app)
    resp = client.get("/")
    # The frontend index.html exists (even if minimal); should return 200.
    assert resp.status_code == 200


def test_connect_streams_frames_to_frontend():
    with MockUC() as uc:
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "connect", "url": f"ws://127.0.0.1:{uc.port}"})

            frames = []
            events = []
            # Collect a handful of messages.
            for _ in range(15):
                msg = ws.receive_json()
                if msg.get("type") == "frame":
                    frames.append(msg)
                elif msg.get("type") == "event":
                    events.append(msg)
                if len(frames) >= 3:
                    break

            # We must have seen the "connected" event first, then frames.
            assert any(e["kind"] == "connected" for e in events)
            assert len(frames) >= 3

            # Frame messages carry the required log line and metadata.
            first = frames[0]
            assert "log_line" in first
            assert first["sample_count"] == 20000
            assert first["is_valid"] is True
            assert len(first["frame_hash"]) == 32


def test_connect_failure_relays_event():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # Nothing listening on this port -> connect_failed event expected.
        ws.send_json({"action": "connect", "url": "ws://127.0.0.1:9"})
        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["kind"] == "connect_failed"


def test_disconnect_action_stops_stream():
    with MockUC() as uc:
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "connect", "url": f"ws://127.0.0.1:{uc.port}"})
            # Wait for at least one frame.
            got_frame = False
            for _ in range(15):
                msg = ws.receive_json()
                if msg.get("type") == "frame":
                    got_frame = True
                    break
            assert got_frame

            ws.send_json({"action": "disconnect"})
            # Drain until we see the user-initiated disconnect event.
            saw_disconnect = False
            for _ in range(30):
                msg = ws.receive_json()
                if msg.get("type") == "event" and msg.get("kind") == "disconnected":
                    saw_disconnect = True
                    break
            assert saw_disconnect