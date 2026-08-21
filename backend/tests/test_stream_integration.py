"""Integration test: stream_frames against a live mock uC server.

Spins up the mock uC in-process on an ephemeral port, connects the real
client, and asserts the ordered event sequence: connected -> frames -> (client
closes) . Also covers the connect-failure path against a dead port.
"""

import asyncio

import pytest
import websockets

from backend.app.models import ConnectionEvent, ProcessedFrame
from backend.app.websocket_client import StreamOptions, stream_frames
from mock_uc.signal_generator import SignalGenerator


async def _mock_handler(websocket):
    gen = SignalGenerator(seed=1)
    try:
        while True:
            await websocket.send(gen.next_frame())
            await asyncio.sleep(0.01)
    except websockets.ConnectionClosed:
        return


@pytest.mark.asyncio
async def test_stream_receives_and_processes_frames():
    async with websockets.serve(_mock_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}"

        events = []
        async for event in stream_frames(uri, plot_points=500):
            events.append(event)
            # Stop after we've seen the connect + a few frames.
            frames = [e for e in events if isinstance(e, ProcessedFrame)]
            if len(frames) >= 3:
                break

    # First event must be the "connected" lifecycle event.
    assert isinstance(events[0], ConnectionEvent)
    assert events[0].kind == "connected"

    frames = [e for e in events if isinstance(e, ProcessedFrame)]
    assert len(frames) >= 3
    # Frame numbers are sequential starting at 1.
    assert [f.frame_number for f in frames[:3]] == [1, 2, 3]
    # All frames from the mock are valid 20000-sample frames.
    assert all(f.is_valid for f in frames)
    assert all(len(f.frame_hash) == 32 for f in frames)
    # Sample rate is None on the first frame, present afterwards.
    assert frames[0].sample_rate is None
    assert frames[1].sample_rate is not None


@pytest.mark.asyncio
async def test_connect_failure_emits_event():
    # Port 1 is privileged/closed; connection must fail fast with an event.
    events = []
    async for event in stream_frames("ws://127.0.0.1:1", plot_points=500):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], ConnectionEvent)
    assert events[0].kind == "connect_failed"

@pytest.mark.asyncio
async def test_mid_stream_drop_emits_disconnected():
    """A uC that closes the connection mid-stream must surface a
    'disconnected' event after the frames it did send — this is what drives
    the frontend's "connection lost" popup and re-enables the Connect button.
    """

    async def dropping_handler(websocket):
        # Send exactly 3 frames, then close the connection abruptly.
        gen = SignalGenerator(seed=1)
        for _ in range(3):
            await websocket.send(gen.next_frame())
            await asyncio.sleep(0.005)
        await websocket.close()

    async with websockets.serve(dropping_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}"

        events = []
        async for event in stream_frames(uri, plot_points=500):
            events.append(event)

    kinds = [e.kind for e in events if isinstance(e, ConnectionEvent)]
    frames = [e for e in events if isinstance(e, ProcessedFrame)]

    # Sequence: connected -> (some frames) -> disconnected.
    assert kinds[0] == "connected"
    assert "disconnected" in kinds
    assert len(frames) == 3
    # The disconnected event must come AFTER the frames.
    assert isinstance(events[-1], ConnectionEvent)
    assert events[-1].kind == "disconnected"


@pytest.mark.asyncio
async def test_domain_switch_takes_effect_mid_stream():
    """Flipping StreamOptions.domain while the stream runs must change what is
    computed, without reconnecting to the uC. This is what happens when the
    user clicks the FD tab: the web layer mutates the shared options object.
    """
    options = StreamOptions()  # starts in "td"

    async with websockets.serve(_mock_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}"

        td_frames, fd_frames = [], []
        async for event in stream_frames(uri, plot_points=500, options=options):
            if not isinstance(event, ProcessedFrame):
                continue

            if options.domain == "td":
                td_frames.append(event)
                if len(td_frames) >= 2:
                    options.domain = "fd"  # user clicked the FD tab
            else:
                fd_frames.append(event)
                if len(fd_frames) >= 2:
                    break

    # Before the switch: the FFT never ran, yet power still shows up on every
    # frame -- it doesn't care which domain is selected.
    assert all(f.spectrum_db == [] for f in td_frames)
    assert all(f.spectrum_max_hz is None for f in td_frames)
    assert all(f.peak_hz is None for f in td_frames)
    assert all(f.power_db is not None for f in td_frames)

    # After the switch: spectrum and peak show up too, and the time-domain
    # data keeps flowing regardless -- neither the log nor the export cares
    # which tab is selected.
    assert all(len(f.spectrum_db) > 0 for f in fd_frames)
    assert all(f.spectrum_max_hz == 1_000_000.0 for f in fd_frames)
    assert all(f.peak_hz is not None for f in fd_frames)
    assert all(len(f.plot_samples) > 0 for f in fd_frames)
    assert all(f.power_db is not None for f in fd_frames)