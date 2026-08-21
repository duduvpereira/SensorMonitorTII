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
  tabs: document.querySelectorAll(".tab"),
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
    ],
    hooks: {
      setCursor: [(u) => updateCursorReadout(u)]
    },
  };

  const initial = new Array(pointCount).fill(isFd ? FD_DB_RANGE[0] : 0);
  plot = new uPlot(opts, [plotXBuffer, initial], els.plotArea);
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
    plot.setData([plotXBuffer, values]);
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
      updatePlot(msg.spectrum_db, msg.spectrum_max_hz);
    }
  } else if (msg.plot_samples && msg.plot_samples.length > 0) {
    updatePlot(msg.plot_samples, null);
  }

  updateGauge(msg.sample_rate);
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
