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


def test_config_exposes_default_uc_url():
    """The frontend pre-fills its URL box from here, so the same build works
    both locally and under Docker Compose (where the mock is a service name).
    """
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    url = resp.json()["default_uc_url"]
    assert url.startswith("ws://")


def test_set_domain_fd_adds_spectrum_to_frames():
    """Clicking the FD tab must make the backend start attaching a spectrum,
    without dropping the uC connection or the log stream.
    """
    with MockUC() as uc:
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "connect", "url": f"ws://127.0.0.1:{uc.port}"})
            ws.send_json({"action": "set_domain", "domain": "fd"})

            spectra = []
            for _ in range(40):
                msg = ws.receive_json()
                if msg.get("type") == "frame" and msg.get("spectrum_db"):
                    spectra.append(msg)
                    break

            assert spectra, "no frame carried a spectrum after switching to FD"
            frame = spectra[0]
            assert len(frame["spectrum_db"]) > 0
            assert frame["spectrum_max_hz"] == 1_000_000.0
            assert frame["peak_hz"] is not None
            assert frame["peak_db"] is not None
            assert frame["power_db"] is not None
            # The log line keeps flowing regardless of the selected domain.
            assert "log_line" in frame


def test_unknown_domain_is_ignored():
    """A bogus domain value must not break the stream or the options object."""
    with MockUC() as uc:
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "connect", "url": f"ws://127.0.0.1:{uc.port}"})
            ws.send_json({"action": "set_domain", "domain": "nonsense"})

            got_frame = False
            for _ in range(20):
                msg = ws.receive_json()
                if msg.get("type") == "frame":
                    got_frame = True
                    # Still time domain: no spectrum computed.
                    assert msg["spectrum_db"] == []
                    break
            assert got_frame


def test_export_csv_endpoint():
    client = TestClient(app)
    resp = client.get("/export?fmt=csv&seconds=5")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert "sensor_export.csv" in resp.headers["content-disposition"]
    # Body should at least contain the CSV header row.
    assert "frame_number" in resp.text


def test_export_json_endpoint():
    client = TestClient(app)
    resp = client.get("/export?fmt=json&seconds=5")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "sensor_export.json" in resp.headers["content-disposition"]
    body = resp.json()
    assert "frame_count" in body
    assert "frames" in body