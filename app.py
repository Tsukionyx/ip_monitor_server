"""
IP Traffic Monitor
Ubuntu/Linux-focused Flask application.
SPDX-License-Identifier: GPL-2.0-only
"""

import os
import threading
from flask import Flask, jsonify, render_template_string, request
from scapy.all import get_if_list

from capture import CaptureManager

app = Flask(__name__)

capture_manager = CaptureManager()

HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IP Traffic Monitor</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1220;
      --panel: #111c2e;
      --panel2: #17243a;
      --line: #263650;
      --text: #e7edf7;
      --muted: #91a1b8;
      --accent: #5da9ff;
      --green: #39c98a;
      --red: #ff6b75;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--bg); color: var(--text);
      font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    .wrap { width: min(1120px, calc(100% - 32px)); margin: 36px auto; }
    header { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:24px; }
    h1 { margin:0; font-size: clamp(24px, 4vw, 32px); letter-spacing:-.03em; }
    .sub { color:var(--muted); margin-top:5px; }
    .status { display:flex; align-items:center; gap:9px; color:var(--muted); white-space:nowrap; }
    .dot { width:9px; height:9px; border-radius:50%; background:#718096; }
    .dot.on { background:var(--green); box-shadow:0 0 12px #39c98a88; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:20px; }
    .controls { display:grid; grid-template-columns: minmax(180px, 1fr) minmax(180px, 2fr) auto; gap:12px; align-items:end; }
    label { display:block; color:var(--muted); font-size:12px; margin-bottom:7px; }
    input, select {
      width:100%; min-height:42px; padding:9px 12px; color:var(--text);
      background:var(--panel2); border:1px solid var(--line); border-radius:9px;
    }
    button {
      min-height:42px; border:0; border-radius:9px; padding:0 17px;
      color:#07111f; background:var(--accent); font-weight:700; cursor:pointer;
    }
    button.secondary { color:var(--text); background:var(--panel2); border:1px solid var(--line); }
    button.danger { color:white; background:#b94350; }
    button:disabled { opacity:.45; cursor:not-allowed; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; }
    .metrics { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:16px 0; }
    .metric .name { color:var(--muted); font-size:13px; }
    .metric .value { font-size:30px; font-weight:750; margin-top:5px; font-variant-numeric:tabular-nums; }
    .chart-panel { min-height:360px; }
    .chart-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }
    h2 { font-size:17px; margin:0; }
    .hint { color:var(--muted); font-size:12px; }
    .chart-box { height:285px; position:relative; }
    .message { min-height:22px; color:var(--muted); font-size:13px; margin-top:12px; }
    .message.error { color:var(--red); }
    footer { color:var(--muted); font-size:12px; margin:18px 2px; }
    @media (max-width:760px) {
      .controls { grid-template-columns:1fr; }
      .metrics { grid-template-columns:1fr; }
      header { align-items:flex-start; flex-direction:column; }
      .metric .value { font-size:25px; }
      .wrap { margin-top:22px; }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>IP Traffic Monitor</h1>
      <div class="sub">Real-time IPv4 packet statistics · Flask + Scapy</div>
    </div>
    <div class="status"><span id="statusDot" class="dot"></span><span id="statusText">Stopped</span></div>
  </header>

  <section class="panel">
    <div class="controls">
      <div>
        <label for="iface">Network interface</label>
        <select id="iface"></select>
      </div>
      <div>
        <label for="filter">BPF filter (optional)</label>
        <input id="filter" type="text" placeholder="e.g. tcp, udp, port 443">
      </div>
      <div class="actions">
        <button id="startBtn">Start</button>
        <button id="stopBtn" class="danger" disabled>Stop</button>
        <button id="resetBtn" class="secondary">Reset</button>
      </div>
    </div>
    <div id="message" class="message">Select an interface and start packet capture.</div>
  </section>

  <section class="metrics">
    <div class="panel metric"><div class="name">Total packets</div><div id="totalPackets" class="value">0</div></div>
    <div class="panel metric"><div class="name">Unique source IPs</div><div id="uniqueIps" class="value">0</div></div>
    <div class="panel metric"><div class="name">Capture status</div><div id="captureState" class="value" style="font-size:22px">Stopped</div></div>
  </section>

  <section class="panel chart-panel">
    <div class="chart-head">
      <h2>Top 10 source IP addresses</h2>
      <span class="hint">Automatically refreshed every second</span>
    </div>
    <div class="chart-box"><canvas id="trafficChart"></canvas></div>
  </section>

  <footer>
    IPv4 only. Capture traffic only on networks and devices you are authorized to monitor.
  </footer>
</div>

<script>
const ifaceSelect = document.getElementById("iface");
const filterInput = document.getElementById("filter");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const resetBtn = document.getElementById("resetBtn");
const message = document.getElementById("message");

const chart = new Chart(document.getElementById("trafficChart"), {
  type: "bar",
  data: { labels: [], datasets: [{
    label: "Packets",
    data: [],
    backgroundColor: "rgba(93,169,255,.72)",
    borderColor: "#5da9ff",
    borderWidth: 1,
    borderRadius: 5
  }]},
  options: {
    responsive: true, maintainAspectRatio: false, indexAxis: "y",
    plugins: { legend: { display: false } },
    scales: {
      x: { beginAtZero: true, ticks: { color: "#91a1b8", precision: 0 }, grid: { color: "#263650" } },
      y: { ticks: { color: "#dbe6f5" }, grid: { display: false } }
    }
  }
});

function showMessage(text, isError=false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

async function api(url, options={}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

async function loadInterfaces() {
  try {
    const data = await api("/api/interfaces");
    ifaceSelect.innerHTML = "";
    for (const iface of data.interfaces) {
      const option = document.createElement("option");
      option.value = iface;
      option.textContent = iface;
      ifaceSelect.appendChild(option);
    }
    if (!data.interfaces.length) showMessage("No network interfaces were found.", true);
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function refreshStats() {
  try {
    const data = await api("/api/stats");
    document.getElementById("totalPackets").textContent = data.total_packets.toLocaleString();
    document.getElementById("uniqueIps").textContent = data.unique_ips.toLocaleString();
    document.getElementById("captureState").textContent = data.running ? "Running" : "Stopped";
    document.getElementById("statusText").textContent = data.running ? "Capturing" : "Stopped";
    document.getElementById("statusDot").classList.toggle("on", data.running);
    startBtn.disabled = data.running;
    stopBtn.disabled = !data.running;
    chart.data.labels = data.top_sources.map(item => item.ip);
    chart.data.datasets[0].data = data.top_sources.map(item => item.packets);
    chart.update("none");
    if (data.error) showMessage(data.error, true);
  } catch (error) {
    showMessage(error.message, true);
  }
}

startBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/start", {
      method: "POST",
      body: JSON.stringify({ iface: ifaceSelect.value, filter: filterInput.value.trim() })
    });
    showMessage(data.message);
    await refreshStats();
  } catch (error) { showMessage(error.message, true); }
});

stopBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/stop", { method: "POST" });
    showMessage(data.message);
    await refreshStats();
  } catch (error) { showMessage(error.message, true); }
});

resetBtn.addEventListener("click", async () => {
  try {
    await api("/api/reset", { method: "POST" });
    showMessage("Statistics have been reset.");
    await refreshStats();
  } catch (error) { showMessage(error.message, true); }
});

loadInterfaces();
refreshStats();
setInterval(refreshStats, 1000);
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/api/interfaces")
def api_interfaces():
    try:
        return jsonify({"interfaces": get_if_list()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/start")
def api_start():
    payload = request.get_json(silent=True) or {}
    iface = payload.get("iface", "")
    bpf_filter = payload.get("filter", "")

    if not iface:
        return jsonify({"error": "Select a network interface."}), 400

    try:
        available = get_if_list()
        if iface not in available:
            return jsonify({"error": "The selected network interface is unavailable."}), 400

        capture_manager.start(iface=iface, bpf_filter=bpf_filter)
        return jsonify({"message": f"Packet capture started on {iface}."})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/stop")
def api_stop():
    try:
        capture_manager.stop()
        return jsonify({"message": "Packet capture stopped."})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/reset")
def api_reset():
    capture_manager.reset()
    return jsonify({"message": "Statistics reset."})


@app.get("/api/stats")
def api_stats():
    return jsonify(capture_manager.get_stats())


if __name__ == "__main__":
    host = os.environ.get("IPTM_HOST", "0.0.0.0")
    port = int(os.environ.get("IPTM_PORT", "5000"))
    print(f"IP Traffic Monitor: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
