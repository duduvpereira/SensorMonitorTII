"use strict";

const els = {
  urlInput: document.getElementById("url-input"),
  connectBtn: document.getElementById("connect-btn"),
  statusBadge: document.getElementById("status-badge"),
  logBox: document.getElementById("log-box"),
  clearLogBtn: document.getElementById("clear-log-btn"),
  gaugeFill: document.getElementById("gauge-fill"),
  gaugeValue: document.getElementById("gauge-value"),
  plotArea: document.getElementById("plot-area"),
  plotPlaceholder: document.getElementById("plot-placeholder"),
  cursorX: document.getElementById("cursor-x"),
  cursorY: document.getElementById("cursor-y"),
  cursorXKey: document.getElementById("cursor-x-key"),
  cursorYKey: document.getElementById("cursor-y-key"),
  peakRow: document.getElementById("peak-row"),
  peakVal: document.getElementById("peak-val"),
  powerVal: document.getElementById("power-val"),
  tabs: document.querySelectorAll(".tab"),
  fdControls: document.getElementById("fd-controls"),
  holdToggleBtn: document.getElementById("hold-toggle-btn"),
  holdResetBtn: document.getElementById("hold-reset-btn"),
  popupOverlay: document.getElementById("popup-overlay"),
  popupTitle: document.getElementById("popup-title"),
  popupMessage: document.getElementById("popup-message"),
  popupCloseBtn: document.getElementById("popup-close-btn"),
};

const MAX_LOG_LINES = 500;
const GAUGE_ARC_LENGTH = 251.3;
const GAUGE_MAX_MSPS = 2.5;

// Fixed dBFS window for the frequency-domain plot. A spectrum auto-scaled per
// frame would bounce on every noise fluctuation; a fixed range keeps peaks
// comparable frame to frame, which is the whole point of watching a spectrum.
const FD_DB_RANGE = [-160, 0];

let socket = null;
let connected = false;
let plot = null;
let plotXBuffer = [];
let pendingPlot = null;
let rafId = null;

// "td" (time domain) or "fd" (frequency domain). The backend only computes the
// FFT while this is "fd", so it has to be told whenever the tab changes.
let currentDomain = "td";
// Domain the live uPlot instance was built for; a change forces a rebuild,
// since the two views have different axes, units and scales.
let plotDomain = null;

// Max-hold (spectrum-analyzer style): per-point highest magnitude seen since
// the toggle was last turned on or reset. Purely a frontend concern -- the
// backend has no notion of "since hold was enabled", it just streams frames.
let holdEnabled = false;
let holdData = null;

function backendWsUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws`;
}

function setStatus(text, cls) {
  els.statusBadge.textContent = text;
  els.statusBadge.className = `status-badge ${cls}`;
}

function setConnectedUI(isConnected) {
  connected = isConnected;
  els.connectBtn.textContent = isConnected ? "Disconnect" : "Connect";
  els.connectBtn.classList.toggle("connected", isConnected);
  els.urlInput.disabled = isConnected;
}

function showPopup(title, message) {
  els.popupTitle.textContent = title;
  els.popupMessage.textContent = message;
  els.popupOverlay.classList.remove("hidden");
}

function hidePopup() {
  els.popupOverlay.classList.add("hidden");
  if (!connected) {
    setStatus("Disconnected", "status-idle");
    setConnectedUI(false);
  }
}

function appendLogLine(text, isError) {
  const line = document.createElement("div");
  line.className = isError ? "log-line log-line-error" : "log-line";
  line.textContent = text;
  els.logBox.appendChild(line);
  
  while (els.logBox.childElementCount > MAX_LOG_LINES) {
    els.logBox.removeChild(els.logBox.firstChild);
  }
  
  els.logBox.scrollTop = els.logBox.scrollHeight;
}

function fmtCompact(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(0) + "k";
  return String(v);
}

function fmtHz(v) {
  if (v >= 1e6) return (v / 1e6).toFixed(2) + " MHz";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + " kHz";
  return Math.round(v) + " Hz";
}

function updateCursorReadout(u) {
  const idx = u.cursor.idx;
  if (idx == null) {
    els.cursorX.textContent = "—";
    els.cursorY.textContent = "—";
    return;
  }

  const xv = u.data[0][idx];
  const yv = u.data[1][idx];

  if (plotDomain === "fd") {
    els.cursorX.textContent = xv != null ? fmtHz(xv) : "—";
    els.cursorY.textContent = yv != null ? yv.toFixed(1) + " dBFS" : "—";
    return;
  }

  els.cursorX.textContent = xv != null ? String(xv) : "—";
  els.cursorY.textContent = yv != null ? Math.round(yv).toLocaleString() : "—";
}

function createPlot(pointCount, maxHz) {
  if (plot) {
    plot.destroy();
    plot = null;
  }

  els.plotArea.querySelectorAll(".uplot").forEach((n) => n.remove());
  if (els.plotPlaceholder) els.plotPlaceholder.style.display = "none";

  plotDomain = currentDomain;
  const isFd = plotDomain === "fd";

  // In FD the backend sends only the magnitudes; the frequency axis is
  // rebuilt here from the Nyquist limit, since it is identical on every frame
  // and resending it 30 times a second would be wasted bandwidth.
  const step = pointCount > 1 ? maxHz / (pointCount - 1) : 0;
  plotXBuffer = Array.from({ length: pointCount }, (_, i) => (isFd ? i * step : i));

  const axisStyle = {
    stroke: "#94a3b8",
    grid: { stroke: "#1e293b" },
    ticks: { stroke: "#334155" },
  };

  const opts = {
    width: els.plotArea.clientWidth,
    height: els.plotArea.clientHeight,
    legend: { show: false },
    cursor: { drag: { x: false, y: false } },
    scales: isFd
      ? { x: { time: false }, y: { range: FD_DB_RANGE } }
      : { x: { time: false } },
    axes: [
      isFd
        ? { ...axisStyle, values: (u, vals) => vals.map(fmtHz) }
        : { ...axisStyle },
      {
        ...axisStyle,
        size: 70,
        values: (u, vals) =>
          vals.map(isFd ? (v) => v + " dB" : fmtCompact),
      },
    ],
    series: [
      {},
      isFd
        ? { label: "Magnitude", stroke: "#22c55e", width: 1, points: { show: false } }
        : { label: "Amplitude", stroke: "#3b82f6", width: 1, points: { show: false } },
      // Third series only exists in FD: max-hold has no meaning against a
      // scrolling time-domain waveform, only against a spectrum.
      ...(isFd
        ? [{ label: "Max Hold", stroke: "#f59e0b", width: 1.5, dash: [5, 4], points: { show: false }, show: holdEnabled }]
        : []),
    ],
    hooks: {
      setCursor: [(u) => updateCursorReadout(u)]
    },
  };

  const floor = new Array(pointCount).fill(isFd ? FD_DB_RANGE[0] : 0);
  const initialData = [plotXBuffer, floor];
  if (isFd) {
    // Carry over an existing hold trace of the right shape (e.g. the user
    // switched back from TD); otherwise start flat at the floor.
    const holdMatches = holdData && holdData.length === pointCount;
    initialData.push(holdMatches ? holdData.slice() : new Array(pointCount).fill(FD_DB_RANGE[0]));
  }
  plot = new uPlot(opts, initialData, els.plotArea);
}

function updatePlot(values, maxHz) {
  if (!values || values.length === 0) return;
  pendingPlot = { values, maxHz };
}

function renderLoop() {
  if (pendingPlot) {
    const { values, maxHz } = pendingPlot;
    pendingPlot = null;

    // Rebuild when the point count changes or the user switched domains.
    if (!plot || plotDomain !== currentDomain || plotXBuffer.length !== values.length) {
      createPlot(values.length, maxHz);
    }
    const data = [plotXBuffer, values];
    if (plotDomain === "fd") {
      data.push(holdData && holdData.length === values.length ? holdData : values);
    }
    plot.setData(data);
  }
  rafId = requestAnimationFrame(renderLoop);
}

function startRenderLoop() {
  if (rafId == null) rafId = requestAnimationFrame(renderLoop);
}

function stopRenderLoop() {
  if (rafId != null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  pendingPlot = null;
}

function resizePlot() {
  if (plot) {
    plot.setSize({ 
      width: els.plotArea.clientWidth, 
      height: els.plotArea.clientHeight 
    });
  }
}

window.addEventListener("resize", resizePlot);

function updateGauge(sampleRateSps) {
  if (sampleRateSps == null) {
    els.gaugeValue.textContent = "—";
    els.gaugeFill.setAttribute("stroke-dashoffset", GAUGE_ARC_LENGTH);
    return;
  }
  
  const msps = sampleRateSps / 1e6;
  els.gaugeValue.textContent = msps.toFixed(2);
  
  const frac = Math.max(0, Math.min(1, msps / GAUGE_MAX_MSPS));
  const offset = GAUGE_ARC_LENGTH * (1 - frac);
  els.gaugeFill.setAttribute("stroke-dashoffset", offset);
  
  const nominalMsps = 2.0;
  const withinTolerance = Math.abs(msps - nominalMsps) <= 0.5;
  els.gaugeFill.style.stroke = withinTolerance ? "#22c55e" : "#3b82f6";
}

function resetGauge() {
  updateGauge(null);
}

// ----------------------------------------------------------------------------
// PEAK FREQUENCY (FD-only) AND RMS POWER READOUTS
// ----------------------------------------------------------------------------

function updatePeakReadout(peakHz, peakDb) {
  const known = peakHz != null && peakDb != null;
  els.peakVal.textContent = known ? `${fmtHz(peakHz)} @ ${peakDb.toFixed(1)} dBFS` : "—";
}

function updatePowerReadout(powerDb) {
  els.powerVal.textContent = powerDb != null ? `${powerDb.toFixed(1)} dBFS` : "—";
}

function resetReadouts() {
  // Both go back to placeholders whenever the stream isn't live.
  updatePeakReadout(null, null);
  updatePowerReadout(null);
}

// ----------------------------------------------------------------------------
// MAX-HOLD (FD only)
// ----------------------------------------------------------------------------

function updateHoldData(values) {
  if (!holdData || holdData.length !== values.length) {
    // First frame since enabling, a reset, or a point-count change: seed
    // from what's on screen rather than starting at the floor, so the trace
    // doesn't visibly "grow" from nothing on the very first frame.
    holdData = values.slice();
    return;
  }
  for (let i = 0; i < values.length; i++) {
    if (values[i] > holdData[i]) holdData[i] = values[i];
  }
}

function setHoldSeriesVisible(visible) {
  if (plot && plotDomain === "fd" && plot.series.length > 2) {
    plot.setSeries(2, { show: visible });
  }
}

function toggleHold() {
  holdEnabled = !holdEnabled;
  els.holdToggleBtn.textContent = holdEnabled ? "Hold: On" : "Hold: Off";
  els.holdToggleBtn.classList.toggle("btn-hold-on", holdEnabled);
  setHoldSeriesVisible(holdEnabled);
}

function resetHold() {
  holdData = null;
  if (plot && plotDomain === "fd") {
    // Immediate feedback instead of waiting for the next frame: drop the
    // trace back to the floor right away.
    const floor = new Array(plotXBuffer.length).fill(FD_DB_RANGE[0]);
    plot.setData([plotXBuffer, plot.data[1], floor]);
  }
}

function clearHold() {
  // Used when a connection ends: the next session should start the hold
  // trace fresh rather than carrying over magnitudes from a previous stream.
  holdData = null;
}

// ----------------------------------------------------------------------------
// DOMAIN (TD / FD) SWITCHING
// ----------------------------------------------------------------------------

function sendDomain() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ action: "set_domain", domain: currentDomain }));
  }
}

function setDomain(domain) {
  if (domain === currentDomain) return;
  currentDomain = domain;

  els.tabs.forEach((tab) => {
    tab.classList.toggle("tab-active", tab.dataset.tab === domain);
  });

  els.cursorXKey.textContent = domain === "fd" ? "Frequency" : "Index";
  els.cursorYKey.textContent = domain === "fd" ? "Magnitude" : "Amplitude";
  els.cursorX.textContent = "—";
  els.cursorY.textContent = "—";

  // A "peak frequency" is meaningless in TD, where there's no single
  // dominant tone to point at -- so hide the row outside of FD.
  els.peakRow.classList.toggle("hidden", domain !== "fd");
  updatePeakReadout(null, null);

  // Max-hold is an FD-only control; the toggle/reset state itself is left
  // alone so it's still armed the way the user left it when they come back.
  els.fdControls.classList.toggle("hidden", domain !== "fd");

  // Drop the current chart: the next frame in the new domain rebuilds it with
  // the right axes. Showing the old curve under new axis labels would be
  // actively misleading.
  if (plot) {
    plot.destroy();
    plot = null;
  }
  plotDomain = null;
  plotXBuffer = [];
  pendingPlot = null;
  if (els.plotPlaceholder) {
    els.plotPlaceholder.style.display = connected ? "none" : "";
  }

  sendDomain();
}

function handleFrame(msg) {
  // The log line goes up for every frame, in both domains — the spec requires
  // one entry per frame regardless of what the plot is showing.
  appendLogLine(msg.log_line, !msg.is_valid);

  if (currentDomain === "fd") {
    if (msg.spectrum_db && msg.spectrum_db.length > 0) {
      if (holdEnabled) updateHoldData(msg.spectrum_db);
      updatePlot(msg.spectrum_db, msg.spectrum_max_hz);
    }
    updatePeakReadout(msg.peak_hz, msg.peak_db);
  } else if (msg.plot_samples && msg.plot_samples.length > 0) {
    updatePlot(msg.plot_samples, null);
  }

  updateGauge(msg.sample_rate);
  updatePowerReadout(msg.power_db);
}

function handleEvent(msg) {
  switch (msg.kind) {
    case "connected":
      setStatus("Connected", "status-connected");
      setConnectedUI(true);
      startRenderLoop();
      break;
    case "connect_failed":
      setStatus("Error", "status-error");
      setConnectedUI(false);
      stopRenderLoop();
      closeSocket();
      showPopup("Connection failed", `Could not connect to the uC:\n${msg.detail}`);
      break;
    case "disconnected":
      setConnectedUI(false);
      stopRenderLoop();
      resetGauge();
      resetReadouts();
      clearHold();
      closeSocket();
      if (msg.detail !== "by user") {
        setStatus("Error", "status-error");
        showPopup("Connection lost", `The connection to the uC dropped:\n${msg.detail}`);
      } else {
        setStatus("Disconnected", "status-idle");
      }
      break;
    case "busy":
      setConnectedUI(false);
      stopRenderLoop();
      closeSocket();
      showPopup("Server busy", msg.detail || "Another client is already connected.");
      break;
    default:
      console.warn("Unknown event kind:", msg.kind);
  }
}

function openSocketAndConnect(ucUrl) {
  socket = new WebSocket(backendWsUrl());
  
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ action: "connect", url: ucUrl }));
    // The user may have selected FD before ever connecting; the backend starts
    // every stream in TD, so tell it which domain this session wants.
    sendDomain();
    setStatus("Connecting…", "status-idle");
  });
  
  socket.addEventListener("message", (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      console.error("Bad message from backend:", ev.data);
      return;
    }
    
    if (msg.type === "frame") {
      handleFrame(msg);
    } else if (msg.type === "event") {
      handleEvent(msg);
    }
  });
  
  socket.addEventListener("close", () => {
    if (connected) {
      setStatus("Disconnected", "status-idle");
      setConnectedUI(false);
    }
    socket = null;
  });
  
  socket.addEventListener("error", () => {
    console.error("Backend WebSocket error.");
  });
}

function closeSocket() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  socket = null;
}

function requestDisconnect() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ action: "disconnect" }));
  }
  setConnectedUI(false);
  setStatus("Disconnected", "status-idle");
  stopRenderLoop();
  resetGauge();
  resetReadouts();
  clearHold();
  closeSocket();
}

// ----------------------------------------------------------------------------
// EVENT LISTENERS
// ----------------------------------------------------------------------------

els.connectBtn.addEventListener("click", () => {
  if (connected) {
    requestDisconnect();
  } else {
    const ucUrl = els.urlInput.value.trim();
    if (!ucUrl) {
      showPopup("Missing URL", "Please enter the uC WebSocket URL.");
      return;
    }
    openSocketAndConnect(ucUrl);
  }
});

els.tabs.forEach((tab) => {
  tab.addEventListener("click", () => setDomain(tab.dataset.tab));
});

els.holdToggleBtn.addEventListener("click", toggleHold);
els.holdResetBtn.addEventListener("click", resetHold);

els.clearLogBtn.addEventListener("click", () => {
  els.logBox.innerHTML = "";
});

document.getElementById("export-btn").addEventListener("click", () => {
  const fmt = document.getElementById("export-format").value;
  const seconds = document.getElementById("export-seconds").value || 5;
  const url = `/export?fmt=${encodeURIComponent(fmt)}&seconds=${encodeURIComponent(seconds)}`;
  
  const a = document.createElement("a");
  a.href = url;
  a.download = fmt === "json" ? "sensor_export.json" : "sensor_export.csv";
  
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
});

els.popupCloseBtn.addEventListener("click", hidePopup);

els.popupOverlay.addEventListener("click", (ev) => {
  if (ev.target === els.popupOverlay) hidePopup();
});

// ----------------------------------------------------------------------------
// INITIALIZATION
// ----------------------------------------------------------------------------

setStatus("Disconnected", "status-idle");
setConnectedUI(false);
resetGauge();
resetReadouts();

// The uC URL depends on where the app runs (localhost vs. a compose service
// name), so the backend is the one that knows it. Fetch it instead of baking
// it into the markup.
const urlFromMarkup = els.urlInput.value;
fetch("/config")
  .then((r) => r.json())
  .then((cfg) => {
    // Only replace the value that came from the HTML. If the user already
    // started typing while this request was in flight, leave their input alone.
    if (cfg.default_uc_url && els.urlInput.value === urlFromMarkup) {
      els.urlInput.value = cfg.default_uc_url;
    }
  })
  .catch(() => {});
