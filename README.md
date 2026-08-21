# Sensor Monitor

![CI](https://github.com/duduvpereira/SensorMonitorTII/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Tests](https://img.shields.io/badge/tests-71%20passing-brightgreen)
![Lint](https://img.shields.io/badge/lint-ruff-D7FF64)

A web-based application that connects to a microcontroller (uC) over WebSocket,
collects a real-time sensor signal streamed at ~8 MB/s, validates and hashes
every frame, and visualises it in a browser GUI.

Built as a submission for the **TII-DERC Senior Software Engineer** technical
challenge.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Overview](#overview)
- [Architecture](#architecture)
- [Project Status](#project-status)
- [Requirements Traceability](#requirements-traceability)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Design Decisions & Assumptions](#design-decisions--assumptions)
- [Continuous Integration](#continuous-integration)

---

## Getting Started

### Prerequisites

- Python 3.12+
- (recommended) a virtual environment

### Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt   # runtime deps + pytest/ruff
```

To install only what the application itself needs, use
`pip install -r requirements.txt`.

### Run the application

Three steps — the mock uC, the backend, and the browser:

```bash
# 1. In one terminal: start the mock microcontroller
python -m mock_uc.server --fps 60 --port 8765

# 2. In another terminal: start the backend (FastAPI + Uvicorn)
python -m uvicorn backend.app.main:app --reload --port 8000

# 3. In a web browser: open the GUI
#    http://localhost:8000
```

In the GUI, enter the uC's WebSocket URL — `ws://127.0.0.1:8765` for the mock
(pre-filled), or `ws://<board-ip>:8765` for real hardware — and press
**Connect**. The plot, the per-frame log and the sample-rate gauge start
updating immediately; **Disconnect** stops the stream and re-enables the input.

Drop `--reload` when running outside development.

### Run the mock microcontroller

```bash
python -m mock_uc.server --fps 100 --port 8765
```

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `0.0.0.0` | bind address |
| `--port` | `8765` | bind port |
| `--fps` | `30` | frames/second; `--fps 100` reproduces the real board's 2 Msps |
| `--samples` | `20000` | samples per frame — set to something else (e.g. `19999`) to emit invalid frames on purpose and exercise the red log line |

Since each frame carries 20,000 samples, the rate shown on the gauge is
`fps ÷ 50` Msps: `--fps 30` → 0.60 Msps, `--fps 100` → 2.00 Msps (the value
specified for the real hardware).

### Run the tests

```bash
python -m pytest        # runs the full suite (71 tests)
python -m ruff check .  # lint
```

### Run the pipeline demo

With a mock uC already running, the real WebSocket client can be exercised
end-to-end — no browser or web server needed:

```bash
python -m mock_uc.server --fps 40 --port 8811   # terminal 1
python demo_pipeline.py                         # terminal 2, defaults to ws://127.0.0.1:8811
# or against a custom target:
python demo_pipeline.py ws://HOST:PORT
```

It prints, for a handful of received frames, exactly what the backend forwards
to the frontend: the spec-formatted log line, validity, estimated sample rate
and the decimated plot-point count — a quick way to confirm the whole pipeline
(parse → validate → hash → sample-rate → decimate) against a live source.

### Export received data

With a stream running, pick a format (CSV/JSON) and a window in seconds in the
log panel's toolbar and press **Export**. The same data is available directly
over HTTP:

```bash
curl -O -J "http://localhost:8000/export?fmt=csv&seconds=5"
curl -O -J "http://localhost:8000/export?fmt=json&seconds=5"
```

## Overview

A microcontroller on a LAN runs a WebSocket server. As soon as a client
connects, it starts streaming sensor data at 2 Msps: each WebSocket packet
(frame) carries **20,000 samples**, each an `int32` little-endian value —
roughly 8 MB/s, ~100 frames/second.

This application is the WebSocket **client**. It:

1. Connects to the uC's WebSocket server from a URL entered by the user.
2. Parses each binary frame into samples, validates the sample count, and
   computes an **XXH3_128** hash of the raw payload.
3. Estimates the sample rate from consecutive frame arrival times.
4. Streams the processed signal to a browser GUI for a real-time,
   oscilloscope-style time-domain plot, plus a per-frame log and a live
   sample-rate gauge.
5. Surfaces connection lifecycle events (failed / dropped) as popups.
6. Exports the most recently received data as CSV or JSON.

A **mock uC** (`mock_uc/`) is included so the whole pipeline can be built and
tested without physical hardware.

## Architecture

The backend acts as a WebSocket **client** to the uC and a WebSocket
**server** to the browser at the same time, on the same `asyncio` event loop:

```mermaid
flowchart LR
    subgraph Sensor Side
        S[Sensor] -->|2 Msps int32_le| UC[uC WebSocket Server<br/>or mock_uc]
    end

    subgraph Backend
        WS[WebSocket Client<br/>connects to uC]
        PIPE[Pipeline:<br/>parse → validate → hash → sample rate → decimate]
        SRV[FastAPI WebSocket Server<br/>serves the browser]
        WS --> PIPE --> SRV
    end

    subgraph Browser
        UI[Web GUI<br/>TD plot · log · gauge · popups]
    end

    UC -->|~8 MB/s, 20000 samples/frame| WS
    SRV -->|JSON: frame + log line + plot samples| UI
    UI -->|connect / disconnect| SRV
    UI -->|GET /export| SRV
```

Each incoming frame goes through a small pipeline of pure, independently
testable steps — parse the raw bytes, validate the sample count, hash the
payload, update the sample-rate estimate, and decimate the signal down to a
plot-friendly point count — before being pushed to the browser as JSON.

Every frame's metadata (log line, hash, validity, sample rate) is forwarded
unconditionally; only the heavy `plot_samples` array is gated by a 30 fps
throttle, so no log entry is ever lost while the plot stays smooth. Recent
frames are kept in a bounded ring buffer, which is what the export endpoint
reads from.

## Project Status

The application is **feature-complete for every mandatory requirement** and
runs end-to-end: mock uC → backend → browser, with live plot, per-frame log,
sample-rate gauge, connection popups and data export.

**Backend — signal processing core**
- [x] Project scaffolding: `pyproject.toml`, `pytest`, `ruff`, coverage config
- [x] Mock uC WebSocket server + synthetic signal generator (`mock_uc/`)
- [x] Binary frame parsing (`int32_le` → NumPy, zero-copy)
- [x] Frame validation (sample-count check → drives the "red log line")
- [x] XXH3_128 hashing of the raw payload
- [x] Sample-rate estimation (EMA-smoothed, per-frame)
- [x] Plot decimation (min/max, oscilloscope-style envelope)
- [x] Shared data models (`ProcessedFrame`, `ConnectionEvent`)
- [x] WebSocket client + streaming pipeline (`stream_frames`)
- [x] Ring buffer (`FrameRingBuffer`) for the most recent N processed frames
- [x] Plot throttle (`PlotThrottle`): caps plot updates at ~30/s without ever
      dropping a log line
- [x] Manual pipeline demo (`demo_pipeline.py`)

**Backend — service layer**
- [x] FastAPI app (`backend/app/main.py`): `/ws` endpoint relaying the uC
      stream to the browser, single-client guard, static file serving
- [x] `GET /export`: CSV/JSON dump of the last N seconds from the ring buffer

**Frontend**
- [x] Web GUI (HTML/CSS/vanilla JS): URL input, Connect/Disconnect, status badge
- [x] Real-time time-domain plot (uPlot, vendored offline)
- [x] Cursor read-out (sample index / amplitude under the pointer)
- [x] Per-frame log panel (red line on invalid frame count, capped at 500 lines)
- [x] Sample-rate gauge (SVG, Msps, green inside tolerance)
- [x] Popups for connection failure, mid-stream drop and "server busy"
- [x] Export controls (format + window in seconds)
- [ ] Frequency-domain (FFT) tab *(optional — tab present but disabled)*

**DevOps / Delivery**
- [x] CI: GitHub Actions running the full test suite with coverage on every push/PR
- [x] 71 unit + integration tests
- [ ] Dockerfile + docker-compose (backend + mock uC)
- [ ] Verified install/run on Ubuntu 24.04 / Fedora 42

## Requirements Traceability

Mapping the challenge's mandatory requirements to their implementation status:

| Requirement | Status | Implementation |
|---|---|---|
| Real-time time-domain plot | ✅ Done | `plot_decimator.py` + `PlotThrottle` → uPlot canvas in `frontend/app.js` |
| Per-frame log line, exact format | ✅ Done | `ProcessedFrame.to_log_line()` → log panel, one line per frame |
| URL input + Connect/Disconnect | ✅ Done | GUI connection bar → `/ws` `{"action": "connect"\|"disconnect", "url": ...}` |
| Popup on connection failure | ✅ Done | `ConnectionEvent(kind="connect_failed")` → modal |
| Popup on connection drop + re-enable Connect | ✅ Done | `ConnectionEvent(kind="disconnected")` → modal + `setConnectedUI(false)` |
| Sample-rate gauge, measured per frame | ✅ Done | `SampleRateEstimator` → SVG gauge in Msps |
| Validate sample count; red log line on mismatch | ✅ Done | `frame_validator.py` → `.log-line-error` |
| XXH3_128 hash of raw payload per frame | ✅ Done | `hashing.py` |
| Git commit history | ✅ Done | incremental commits, see `git log` |
| Runs on Ubuntu 24.04 / Fedora 42 or container | ⬜ Pending | Docker + Linux verification |
| *(optional)* Data export | ✅ Done | `export.py` + `GET /export` + GUI controls |
| *(optional)* Frequency-domain plot (FFT) | ⬜ Not started | FD tab present in the UI but disabled |

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend language | Python 3.12 | async-first, strong typing support, fast to iterate |
| Web framework | FastAPI + Uvicorn | native async WebSocket support on both client and server sides, needed to act as WS client (to the uC) and WS server (to the browser) simultaneously under a high-throughput stream |
| WebSocket client | `websockets` | connects to the uC as a client |
| Binary parsing | NumPy | zero-copy `int32_le` parsing and vectorised min/max decimation at ~100 frames/s |
| Hashing | `xxhash` (XXH3_128) | required by the spec, extremely fast on binary payloads |
| Frontend | HTML + CSS + vanilla JS | no framework overhead needed for the scope; keeps the app self-contained for offline LAN testing |
| Plot | uPlot (vendored offline) | lightweight, canvas-based, built for high-frequency real-time updates |
| Testing | pytest, pytest-asyncio, pytest-cov | unit + async pipeline testing with coverage |
| Static analysis | ruff | fast linting, single tool for style + common bugs |
| Mock hardware | Python `asyncio` WebSocket server | develop and test the full pipeline without physical hardware |
| CI | GitHub Actions | automated tests + coverage on every push/PR |

## Repository Structure

```
SensorMonitorTII/
├── backend/
│   ├── app/
│   │   ├── frame_parser.py      # raw bytes -> NumPy int32 samples
│   │   ├── frame_validator.py   # sample-count validation
│   │   ├── hashing.py           # XXH3_128 of the raw payload
│   │   ├── sample_rate.py       # EMA-smoothed sample-rate estimator
│   │   ├── plot_decimator.py    # min/max decimation for the plot
│   │   ├── models.py            # ProcessedFrame, ConnectionEvent
│   │   ├── buffer.py            # FrameRingBuffer, bounded frame history
│   │   ├── plot_throttle.py     # caps plot updates at ~30/s
│   │   ├── export.py            # CSV/JSON serialisation of buffered frames
│   │   ├── websocket_client.py  # connects to the uC, runs the full pipeline
│   │   └── main.py              # FastAPI app: /ws relay, /export, static frontend
│   └── tests/                   # one test module per backend module,
│                                 # plus integration tests against a live mock uC
├── frontend/
│   ├── index.html                # single-page GUI (served at /)
│   ├── app.js                    # WebSocket client, plot, log, gauge, popups
│   ├── style.css
│   └── vendor/                   # uPlot, bundled for offline/LAN use
├── mock_uc/
│   ├── server.py                 # mock uC: WebSocket server
│   └── signal_generator.py       # synthetic signal (sine tones + noise)
├── .github/
│   ├── workflows/ci.yml          # test + coverage CI pipeline
│   └── scripts/build_job_summary.py  # renders the CI job summary
├── demo_pipeline.py               # manual dev script: real client + mock uC, no web server
├── pyproject.toml                # pytest / coverage / ruff configuration
├── requirements.txt               # runtime dependencies
└── requirements-dev.txt           # + testing/lint dependencies
```

## Design Decisions & Assumptions

As permitted by the challenge conditions, assumptions made where the brief
was silent are documented here, together with the reasoning behind each
implementation decision:

1. **FastAPI over Flask.** The service must act as a WebSocket *client* (to
   the uC) and a WebSocket *server* (to the browser) at the same time, under
   a sustained ~8 MB/s stream. FastAPI's native `asyncio` support handles
   both roles on one event loop without extra runtime patching.

2. **NumPy for binary parsing.** `np.frombuffer` gives a zero-copy view of
   the raw payload as `int32_le` samples, keeping per-frame parsing cheap
   enough to sustain ~100 frames/second (measured: 0.10 ms per frame for the
   whole pipeline).

3. **Hash the raw payload, not the parsed samples.** The spec asks for an
   XXH3_128 hash of the *raw binary payload*. Hashing the bytes as received
   (rather than re-serialising parsed samples) avoids any dependency on
   endianness or parsing correctness and matches exactly what was received
   on the wire.

4. **Sample-count validation is a pure function.** `validate_frame()` takes
   only the payload and an expected count, and returns a small result
   object — no I/O, no logging side effects — so it is trivial to unit test
   and the "red log line" decision stays in one place.

5. **EMA-smoothed sample rate.** Frame arrival over a network is bursty;
   reporting the raw instantaneous rate would make the gauge jump around.
   An exponential moving average (configurable smoothing factor) keeps the
   reading stable while still reacting to real rate changes.

6. **Min/max decimation for the plot (oscilloscope technique).** Sending all
   20,000 samples per frame to the browser ~30–100 times/second is neither
   necessary nor smooth. Each frame is split into buckets and both the min
   and max of each bucket are kept, preserving the visual envelope (peaks
   and troughs) while cutting the point count by roughly 10x.

7. **Mock uC built first.** `mock_uc/` was implemented before the rest of
   the pipeline so that every downstream module could be developed and
   tested against a live, controllable WebSocket source — including an
   intentionally wrong `--samples` count, to exercise the "red log line"
   path without needing real hardware.

8. **Plotting library vendored offline.** The app is meant to be tested on a
   LAN without guaranteed internet access, so uPlot is bundled in
   `frontend/vendor/` rather than loaded from a CDN.

9. **Test-first, I/O-free modules.** Every processing step (parsing,
   validation, hashing, sample-rate estimation, decimation, export) is a pure
   function or small stateful class with no network or filesystem access,
   so each one is covered by fast, deterministic unit tests independent of
   the WebSocket plumbing.

10. **The pipeline knows nothing about the web framework.** `stream_frames()`
    is a plain `async` generator that yields `ProcessedFrame`/`ConnectionEvent`
    objects — it has no dependency on FastAPI or any web server. This lets it
    be driven by the FastAPI `/ws` route in production, by a plain test
    harness in `test_stream_integration.py`, and by `demo_pipeline.py`, all
    without changing the pipeline itself.

11. **Ring buffer, not an unbounded list.** `FrameRingBuffer` is a fixed-
    capacity `collections.deque` of `ProcessedFrame`s: O(1) append that
    evicts the oldest frame once full, so memory stays bounded no matter how
    long a connection stays open, while still keeping enough recent history
    for the "export last N seconds" feature. It intentionally does no
    rate-limiting itself — *when* to read the latest frame is the consumer's
    job, keeping the buffer a simple, fully-testable data structure with no
    timing behaviour.

12. **Throttle the plot, never the log.** The uC delivers up to ~100 frames/s,
    but redrawing the canvas that often would overwhelm the browser and look
    *less* smooth, since smoothness comes from a steady cadence rather than raw
    throughput. `PlotThrottle` caps the heavy `plot_samples` payload at 30
    updates/second; every frame still produces a full log message with its
    hash, sample count and rate, exactly as the spec requires. The throttle
    takes the current time as an argument instead of reading the clock, so its
    behaviour is fully deterministic under test.

13. **One frontend client at a time.** The challenge describes a single
    operator watching a single uC, so `/ws` guards against a second browser
    session (`_SingleClientGuard`) and replies with a `busy` event instead of
    silently multiplexing one uC stream across tabs — which would double the
    outbound bandwidth and make the "who owns the Connect button" question
    ambiguous.

14. **The uC stream runs as a cancellable task.** `/ws` keeps receiving browser
    commands while `_relay_uc_stream()` pumps data in an `asyncio.Task`, so a
    `disconnect` command (or a new `connect`) takes effect immediately rather
    than waiting for the current stream to end on its own.

15. **WebSocket compression disabled on both ends.** The `websockets` library
    negotiates `permessage-deflate` by default, which cost a measured **4 ms of
    CPU per 80 KB frame** — enough to cap the achievable rate at ~44 fps when
    60 was requested. Sensor data is essentially incompressible noise, so that
    CPU buys nothing. The extension is only used when *both* peers offer it, so
    the backend client declines it too, sparing the real uC the same cost.

16. **The mock paces frames against absolute deadlines.** Sleeping a fixed
    interval *after* sending yields a period of `work + interval`, which
    systematically undershoots the requested rate. The mock accumulates a
    deadline and sleeps only the remaining time, rebasing the schedule if it
    ever falls behind rather than repaying the debt as a burst of back-to-back
    frames — which would corrupt the very sample-rate estimate being measured.
    Result: `--fps 100` delivers 99.2 fps (1.98 Msps).

17. **Export ships the decimated signal, not the raw samples.** The buffer
    retains the ~2000 decimated points per frame rather than the raw 20,000, so
    memory stays bounded during long sessions. The spec itself notes the raw
    export "may be large" and suggests limiting it. CSV is flattened to one row
    per (frame, sample) pair so it opens in any spreadsheet; JSON keeps the
    nested per-frame arrays. Frames with no plot samples still emit a metadata
    row, so nothing disappears silently from the export.

## Continuous Integration

Every push and pull request runs the **Sensor Monitor CI** workflow
(`.github/workflows/ci.yml`) on `ubuntu-24.04`, as two independent jobs that
run in parallel.

### `lint` — ruff

Runs `ruff check .` with `--output-format=github`, so any finding appears as an
inline annotation on the offending line in the PR diff rather than buried in
the log. It is a separate job on purpose: a style slip fails its own check
without hiding the test results, and vice versa.

### `unit-tests` — pytest + coverage

1. **Checkout** the repository.
2. **Set up Python 3.12** with pip caching keyed on `requirements-dev.txt`.
3. **Install dependencies** from `requirements-dev.txt`.
4. **Run the full pytest suite with coverage**, producing a JUnit report
   (`test-results.xml`) and coverage reports in terminal, XML, JSON and HTML
   formats.
5. **Publish test results** to the PR/commit Checks tab via
   `dorny/test-reporter`.
6. **Build a job summary**: `.github/scripts/build_job_summary.py` reads the
   JUnit and coverage-JSON reports and renders a colour-coded Markdown
   summary (pass/fail badge, per-suite results table, per-file coverage
   table with a 🟢/🟡/🔴 traffic-light indicator) directly on the workflow
   run page.
7. **Upload artifacts**: the JUnit XML and the full coverage report
   (XML + JSON + HTML) are attached to the run for later inspection.

The coverage-JSON report is used (rather than the Cobertura XML) to key the
per-file table, since two source roots (`backend/app` and `mock_uc`) each
contain an `__init__.py` — the XML writer keys files by basename only and
the two would collide into a single, incorrect row.
