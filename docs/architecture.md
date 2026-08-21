# Architecture

How the pieces fit together and how they behave over time. See the
[main README](../README.md) for how to run the app; this is the deeper dive.

## System overview

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
        UI[Web GUI<br/>TD/FD plot · log · gauge · popups]
    end

    UC -->|~8 MB/s, 20000 samples/frame| WS
    SRV -->|JSON: frame + log line + plot samples / spectrum| UI
    UI -->|connect / disconnect / set_domain| SRV
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

## Connection Lifecycle

The flowchart above shows what flows where; this shows the *order* things
happen in — the part a static diagram of boxes and arrows can't capture,
like why a tab switch doesn't reconnect, and what makes a dropped connection
different from a user-requested disconnect:

```mermaid
sequenceDiagram
    actor User
    participant UI as Browser (app.js)
    participant BE as Backend (/ws)
    participant UC as uC / mock_uc

    User->>UI: click Connect
    UI->>BE: WS open + {"action":"connect","url":...}
    BE->>UC: WS connect

    alt uC reachable
        UC-->>BE: connection accepted
        BE-->>UI: event: connected
        UI-->>User: status "Connected", plot enabled

        loop every frame (~100/s)
            UC->>BE: binary frame (80 KB, 20000 int32_le)
            BE->>BE: parse → validate → hash →<br/>sample rate → decimate / FFT
            BE-->>UI: frame: log line + metadata +<br/>plot_samples or spectrum_db (throttled ~30 fps)
            UI-->>User: log line, gauge, plot update
        end

        opt user clicks the FD tab
            UI->>BE: {"action":"set_domain","domain":"fd"}
            Note over BE: StreamOptions.domain flips --<br/>no reconnect, takes effect next frame
        end

        alt user clicks Disconnect
            UI->>BE: {"action":"disconnect"}
            BE->>UC: close WS
            BE-->>UI: event: disconnected (by user)
            UI-->>User: status "Disconnected", no popup
        else uC drops mid-stream
            UC--xBE: connection closed
            BE-->>UI: event: disconnected (detail=reason)
            UI-->>User: popup "Connection lost"
        end

    else uC unreachable
        BE--xUC: connection refused / timeout
        BE-->>UI: event: connect_failed
        UI-->>User: popup "Connection failed"
    end
```

One case the diagram leaves out to stay readable: if a second browser tab
opens `/ws` while a stream is already active, the backend replies with a
single `busy` event and closes that socket immediately — the single-client
guard mentioned in the README's
[Design Decisions](../README.md#design-decisions--assumptions), enforced
before any `connect`/`disconnect` command is even read.

## See also

- [GUI Tour](gui-tour.md) — the same lifecycle above, as screenshots of the
  running app: both plot domains, max-hold, and every popup.
- More diagrams (frame-processing pipeline, data model) are planned here as
  the documentation grows.
