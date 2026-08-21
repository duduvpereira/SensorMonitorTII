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
  popupOverlay: document.getElementById("popup-overlay"),
  popupTitle: document.getElementById("popup-title"),
  popupMessage: document.getElementById("popup-message"),
  popupCloseBtn: document.getElementById("popup-close-btn"),
};

const MAX_LOG_LINES = 500;
const GAUGE_ARC_LENGTH = 251.3;
const GAUGE_MAX_MSPS = 2.5;

let socket = null;
let connected = false;
let plot = null;
let plotXBuffer = [];
let pendingPlotSamples = null;
let rafId = null;

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

function updateCursorReadout(u) {
  const idx = u.cursor.idx;
  if (idx == null) {
    els.cursorX.textContent = "—";
    els.cursorY.textContent = "—";
    return;
  }
  
  const xv = u.data[0][idx];
  const yv = u.data[1][idx];
  
  els.cursorX.textContent = xv != null ? String(xv) : "—";
  els.cursorY.textContent = yv != null ? Math.round(yv).toLocaleString() : "—";
}

function createPlot(pointCount) {
  if (plot) {
    plot.destroy();
    plot = null;
  }
  
  els.plotArea.querySelectorAll(".uplot").forEach((n) => n.remove());
  if (els.plotPlaceholder) els.plotPlaceholder.style.display = "none";
  
  plotXBuffer = Array.from({ length: pointCount }, (_, i) => i);
  
  const opts = {
    width: els.plotArea.clientWidth,
    height: els.plotArea.clientHeight,
    legend: { show: false },
    cursor: { drag: { x: false, y: false } },
    scales: { x: { time: false } },
    axes: [
      { 
        stroke: "#94a3b8", 
        grid: { stroke: "#1e293b" }, 
        ticks: { stroke: "#334155" } 
      },
      { 
        stroke: "#94a3b8", 
        grid: { stroke: "#1e293b" }, 
        ticks: { stroke: "#334155" }, 
        size: 70, 
        values: (u, vals) => vals.map(fmtCompact) 
      },
    ],
    series: [
      {},
      { label: "Amplitude", stroke: "#3b82f6", width: 1, points: { show: false } },
    ],
    hooks: {
      setCursor: [(u) => updateCursorReadout(u)]
    },
  };
  
  plot = new uPlot(opts, [plotXBuffer, new Array(pointCount).fill(0)], els.plotArea);
}

function updatePlot(samples) {
  if (!samples || samples.length === 0) return;
  pendingPlotSamples = samples;
}

function renderLoop() {
  if (pendingPlotSamples) {
    const samples = pendingPlotSamples;
    pendingPlotSamples = null;
    
    if (!plot || plotXBuffer.length !== samples.length) {
      createPlot(samples.length);
    }
    plot.setData([plotXBuffer, samples]);
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
  pendingPlotSamples = null;
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

function handleFrame(msg) {
  appendLogLine(msg.log_line, !msg.is_valid);
  if (msg.plot_samples && msg.plot_samples.length > 0) {
    updatePlot(msg.plot_samples);
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