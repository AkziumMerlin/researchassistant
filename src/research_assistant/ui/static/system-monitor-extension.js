const monitorFetch = window.fetch.bind(window);

async function monitorApi(path, options = {}) {
  const response = await monitorFetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.message || response.statusText);
  return payload;
}

function monitorElement(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (value !== null && value !== undefined) {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of children) {
    node.append(child?.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function monitorButton(text, handler, className = "") {
  return monitorElement("button", {
    class: `raMonitorButton ${className}`.trim(),
    type: "button",
    text,
    onclick: handler,
  });
}

function formatBytes(value) {
  const number = Number(value || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let scaled = Math.max(0, number);
  let index = 0;
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  const digits = index === 0 ? 0 : scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
  return `${scaled.toFixed(digits)} ${units[index]}`;
}

function formatMb(value) {
  const number = Number(value || 0);
  return number >= 1024 ? `${(number / 1024).toFixed(number >= 10240 ? 0 : 1)} GiB` : `${number.toFixed(0)} MiB`;
}

function formatPercent(value, digits = 1) {
  const number = Number(value || 0);
  return `${number.toFixed(digits)}%`;
}

function formatDuration(value) {
  let seconds = Math.max(0, Math.floor(Number(value || 0)));
  const days = Math.floor(seconds / 86400);
  seconds %= 86400;
  const hours = Math.floor(seconds / 3600);
  seconds %= 3600;
  const minutes = Math.floor(seconds / 60);
  seconds %= 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatRate(value) {
  return `${formatBytes(value)}/s`;
}

function clamp(value, minimum = 0, maximum = 100) {
  return Math.min(maximum, Math.max(minimum, Number(value || 0)));
}

const monitorState = {
  dialog: null,
  overview: null,
  gpuGrid: null,
  processBody: null,
  processMeta: null,
  detail: null,
  detailBody: null,
  status: null,
  search: null,
  scope: null,
  sort: null,
  interval: null,
  pause: null,
  timer: null,
  paused: false,
  polling: false,
  active: false,
  snapshot: null,
  histories: new Map(),
  searchTimer: null,
};

function installMonitorStyles() {
  if (document.querySelector("#ra-system-monitor-styles")) return;
  document.head.append(monitorElement("style", {
    id: "ra-system-monitor-styles",
    text: `
      .raMonitorDialog{width:min(1760px,98vw);height:min(1050px,96vh);padding:0;border:1px solid #475569;border-radius:10px;background:#080d16;color:#e5e7eb;overflow:hidden}
      .raMonitorDialog::backdrop{background:#000b}
      .raMonitorLayout{height:100%;display:grid;grid-template-rows:auto auto auto minmax(0,1fr) auto}
      .raMonitorHeader{display:flex;align-items:center;gap:9px;padding:9px 12px;border-bottom:1px solid #273449;background:#0c1422;min-width:0}
      .raMonitorHeaderTitle{font-weight:700;white-space:nowrap}
      .raMonitorControls{display:flex;align-items:center;gap:7px;min-width:0;flex:1;flex-wrap:wrap}
      .raMonitorControls input,.raMonitorControls select{background:#050912;color:#f8fafc;border:1px solid #475569;border-radius:5px;padding:6px 8px;font:12px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace}
      .raMonitorControls input{min-width:180px;flex:1;max-width:420px}
      .raMonitorButton{background:#172033;color:#f8fafc;border:1px solid #475569;border-radius:5px;padding:6px 9px;cursor:pointer;white-space:nowrap}
      .raMonitorButton:hover{background:#24324a}.raMonitorButton.primary{background:#1d4ed8;border-color:#60a5fa}.raMonitorButton.danger{background:#7f1d1d;border-color:#b91c1c}.raMonitorButton.warn{background:#713f12;border-color:#a16207}.raMonitorButton:disabled{opacity:.5;cursor:not-allowed}
      .raMonitorOverview{display:grid;grid-template-columns:repeat(6,minmax(150px,1fr));gap:7px;padding:8px 10px;background:#090f1a;border-bottom:1px solid #273449}
      .raMonitorCard{border:1px solid #334155;border-radius:7px;background:#0f1726;padding:8px 9px;min-width:0;display:grid;grid-template-rows:auto auto 30px;gap:3px}
      .raMonitorCardHeader{display:flex;justify-content:space-between;gap:8px;color:#94a3b8;font:11px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;text-transform:uppercase;letter-spacing:.04em}
      .raMonitorCardValue{font:600 20px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .raMonitorCardSub{color:#94a3b8;font:11px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .raMonitorSpark{width:100%;height:30px;overflow:visible}.raMonitorSpark path.area{fill:#2563eb33}.raMonitorSpark path.line{fill:none;stroke:#60a5fa;stroke-width:1.6;vector-effect:non-scaling-stroke}
      .raMonitorGpuGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:7px;padding:8px 10px;border-bottom:1px solid #273449;max-height:245px;overflow:auto;background:#070c14}
      .raMonitorGpuCard{border:1px solid #334155;border-radius:7px;background:#0e1624;padding:8px;display:grid;gap:6px;min-width:0}
      .raMonitorGpuHeader{display:flex;justify-content:space-between;align-items:start;gap:8px}.raMonitorGpuName{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.raMonitorGpuIndex{color:#93c5fd;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}
      .raMonitorBarRow{display:grid;grid-template-columns:55px minmax(0,1fr) 64px;align-items:center;gap:6px;color:#cbd5e1;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}
      .raMonitorBar{height:7px;border-radius:999px;background:#1f2937;overflow:hidden}.raMonitorBarFill{height:100%;background:#3b82f6;border-radius:inherit}.raMonitorBarFill.memory{background:#8b5cf6}.raMonitorBarFill.power{background:#f59e0b}
      .raMonitorGpuMeta{display:flex;gap:12px;flex-wrap:wrap;color:#94a3b8;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}
      .raMonitorNoGpu{grid-column:1/-1;padding:8px;color:#94a3b8;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}
      .raMonitorProcessArea{min-height:0;overflow:auto;background:#050911}
      .raMonitorTable{width:100%;border-collapse:separate;border-spacing:0;font:12px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;table-layout:fixed}
      .raMonitorTable thead{position:sticky;top:0;z-index:2;background:#111827}.raMonitorTable th{color:#94a3b8;text-align:left;padding:6px 7px;border-bottom:1px solid #334155;font-weight:600}.raMonitorTable td{padding:5px 7px;border-bottom:1px solid #172033;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .raMonitorTable tbody tr{cursor:pointer}.raMonitorTable tbody tr:hover{background:#172033}.raMonitorTable tbody tr.raManaged{background:#0f2340}.raMonitorTable tbody tr.raManaged:hover{background:#17345c}
      .raMonitorTable .num{text-align:right;font-variant-numeric:tabular-nums}.raMonitorTable .pid{width:65px}.raMonitorTable .ra{width:145px}.raMonitorTable .user{width:92px}.raMonitorTable .cpu{width:72px}.raMonitorTable .mem{width:86px}.raMonitorTable .gpu{width:82px}.raMonitorTable .state{width:55px}.raMonitorTable .threads{width:58px}.raMonitorTable .runtime{width:75px}.raMonitorTable .actions{width:44px;text-align:center}
      .raMonitorBadge{display:inline-flex;align-items:center;max-width:100%;padding:1px 5px;border:1px solid #3b82f6;border-radius:999px;color:#bfdbfe;background:#1e3a5f;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.raMonitorBadge.foreign{border-color:#475569;color:#cbd5e1;background:#1f2937}
      .raMonitorFooter{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:5px 10px;border-top:1px solid #273449;background:#0c1422;color:#94a3b8;font:11px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace}
      .raMonitorDetail{position:absolute;right:14px;top:62px;bottom:38px;width:min(680px,52vw);z-index:5;display:grid;grid-template-rows:auto minmax(0,1fr);background:#0a111d;border:1px solid #475569;border-radius:8px;box-shadow:0 20px 45px #000a;overflow:hidden}.raMonitorDetail[hidden]{display:none}
      .raMonitorDetailHeader{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #334155;background:#111827}.raMonitorDetailTitle{font-weight:650;min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .raMonitorDetailBody{overflow:auto;padding:10px;display:grid;gap:10px;align-content:start}.raMonitorDetailGrid{display:grid;grid-template-columns:145px minmax(0,1fr);gap:4px 10px;font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}.raMonitorDetailGrid dt{color:#94a3b8}.raMonitorDetailGrid dd{margin:0;overflow-wrap:anywhere}
      .raMonitorSignalRow{display:flex;gap:6px;flex-wrap:wrap}.raMonitorLog{display:grid;gap:4px}.raMonitorLogHeader{display:flex;justify-content:space-between;gap:8px;color:#cbd5e1;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}.raMonitorLog pre{margin:0;max-height:300px;overflow:auto;padding:8px;border:1px solid #334155;border-radius:5px;background:#030712;color:#d1d5db;font:11px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
      @media(max-width:1150px){.raMonitorOverview{grid-template-columns:repeat(3,minmax(150px,1fr))}.raMonitorDetail{width:min(720px,80vw)}}
      @media(max-width:760px){.raMonitorDialog{width:100vw;height:100vh;max-width:none;max-height:none;border-radius:0}.raMonitorOverview{grid-template-columns:repeat(2,minmax(140px,1fr))}.raMonitorDetail{inset:52px 6px 32px 6px;width:auto}.raMonitorHeader{align-items:stretch;flex-direction:column}}
    `,
  }));
}

function historyPush(key, value, limit = 90) {
  const history = monitorState.histories.get(key) || [];
  history.push(Number(value || 0));
  while (history.length > limit) history.shift();
  monitorState.histories.set(key, history);
  return history;
}

function sparkline(values, maximum = null) {
  const width = 240;
  const height = 30;
  const safe = values.length ? values : [0];
  const max = Math.max(1, maximum ?? Math.max(...safe));
  const points = safe.map((value, index) => {
    const x = safe.length === 1 ? width : index * width / (safe.length - 1);
    const y = height - clamp(value, 0, max) / max * height;
    return [x, y];
  });
  const line = points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const svg = monitorElement("svg", { class: "raMonitorSpark", viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none" });
  svg.append(monitorElement("path", { class: "area", d: area }));
  svg.append(monitorElement("path", { class: "line", d: line }));
  return svg;
}

function metricCard(title, value, subtitle, historyKey, historyValue, maximum = 100) {
  const history = historyPush(historyKey, historyValue);
  return monitorElement("div", { class: "raMonitorCard" }, [
    monitorElement("div", { class: "raMonitorCardHeader" }, [
      monitorElement("span", { text: title }),
      monitorElement("span", { text: subtitle }),
    ]),
    monitorElement("div", { class: "raMonitorCardValue", text: value }),
    sparkline(history, maximum),
  ]);
}

function barRow(label, percent, value, className = "") {
  const fill = monitorElement("div", { class: `raMonitorBarFill ${className}`.trim() });
  fill.style.width = `${clamp(percent)}%`;
  return monitorElement("div", { class: "raMonitorBarRow" }, [
    monitorElement("span", { text: label }),
    monitorElement("div", { class: "raMonitorBar" }, [fill]),
    monitorElement("span", { class: "num", text: value }),
  ]);
}

function renderOverview(snapshot) {
  const host = snapshot.host || {};
  const memory = host.memory || {};
  const disk = host.disk || {};
  const network = host.network || {};
  monitorState.overview.replaceChildren(
    metricCard("CPU", formatPercent(host.cpu_percent), `${host.cpu_count || 0} cores`, "host.cpu", host.cpu_percent),
    metricCard("Memory", formatBytes(memory.used_bytes), `${formatPercent(memory.percent)} of ${formatBytes(memory.total_bytes)}`, "host.memory", memory.percent),
    metricCard("Load", Number(host.load_1 || 0).toFixed(2), `${Number(host.load_5 || 0).toFixed(2)} / ${Number(host.load_15 || 0).toFixed(2)}`, "host.load", host.load_1, Math.max(1, host.cpu_count || 1)),
    metricCard("Swap", formatBytes(memory.swap_used_bytes), `${formatPercent(memory.swap_percent)} of ${formatBytes(memory.swap_total_bytes)}`, "host.swap", memory.swap_percent),
    metricCard("Workspace disk", formatBytes(disk.free_bytes), `${formatPercent(disk.percent)} used`, "host.disk", disk.percent),
    metricCard("Network", `↓ ${formatRate(network.receive_bytes_per_second)}`, `↑ ${formatRate(network.transmit_bytes_per_second)}`, "host.network", Number(network.receive_bytes_per_second || 0) + Number(network.transmit_bytes_per_second || 0), null),
  );
}

function renderGpus(snapshot) {
  const devices = snapshot.gpus?.devices || [];
  monitorState.gpuGrid.replaceChildren();
  if (!devices.length) {
    monitorState.gpuGrid.append(monitorElement("div", {
      class: "raMonitorNoGpu",
      text: snapshot.gpus?.error || "No NVIDIA GPUs detected",
    }));
    return;
  }
  for (const gpu of devices) {
    historyPush(`gpu.${gpu.uuid}.util`, gpu.utilization_percent);
    historyPush(`gpu.${gpu.uuid}.memory`, gpu.memory_percent);
    const card = monitorElement("div", { class: "raMonitorGpuCard" }, [
      monitorElement("div", { class: "raMonitorGpuHeader" }, [
        monitorElement("div", { class: "raMonitorGpuName", text: gpu.name, title: gpu.uuid }),
        monitorElement("div", { class: "raMonitorGpuIndex", text: `GPU ${gpu.index}` }),
      ]),
      barRow("GPU", gpu.utilization_percent, formatPercent(gpu.utilization_percent, 0)),
      barRow("Memory", gpu.memory_percent, `${formatMb(gpu.memory_used_mb)} / ${formatMb(gpu.memory_total_mb)}`, "memory"),
      barRow("Power", gpu.power_percent, gpu.power_watts == null ? "n/a" : `${Number(gpu.power_watts).toFixed(0)} W`, "power"),
      monitorElement("div", { class: "raMonitorGpuMeta" }, [
        monitorElement("span", { text: gpu.temperature_c == null ? "temperature n/a" : `${Number(gpu.temperature_c).toFixed(0)} °C` }),
        monitorElement("span", { text: `${gpu.process_count || 0} compute processes` }),
        monitorElement("span", { text: gpu.pci_bus_id || "" }),
      ]),
    ]);
    monitorState.gpuGrid.append(card);
  }
}

function raLabel(process) {
  const ra = process.ra;
  if (!ra) return monitorElement("span", { class: "raMonitorBadge foreign", text: process.gpu_memory_mb > 0 ? "foreign GPU" : "—" });
  const label = ra.run_id || ra.launch_id || ra.role || "RA";
  return monitorElement("span", { class: "raMonitorBadge", text: label, title: JSON.stringify(ra, null, 2) });
}

function renderProcesses(snapshot) {
  monitorState.processBody.replaceChildren();
  for (const process of snapshot.processes || []) {
    const row = monitorElement("tr", {
      class: process.ra ? "raManaged" : "",
      onclick: () => openProcessDetail(process.pid),
      title: process.command,
    });
    const gpuIndices = (process.gpus || []).map((item) => item.gpu_index).filter((value) => value !== null && value !== undefined);
    row.append(
      monitorElement("td", { class: "pid num", text: process.pid }),
      monitorElement("td", { class: "ra" }, [raLabel(process)]),
      monitorElement("td", { class: "user", text: process.user }),
      monitorElement("td", { class: "cpu num", text: formatPercent(process.cpu_percent) }),
      monitorElement("td", { class: "mem num", text: formatBytes(process.memory_rss_bytes) }),
      monitorElement("td", { class: "gpu num", text: process.gpu_memory_mb > 0 ? `${formatMb(process.gpu_memory_mb)}${gpuIndices.length ? ` · ${gpuIndices.join(",")}` : ""}` : "—" }),
      monitorElement("td", { class: "state", text: process.state }),
      monitorElement("td", { class: "threads num", text: process.threads }),
      monitorElement("td", { class: "runtime num", text: formatDuration(process.runtime_seconds) }),
      monitorElement("td", { class: "command", text: process.command }),
      monitorElement("td", { class: "actions", text: "›" }),
    );
    monitorState.processBody.append(row);
  }
  monitorState.processMeta.textContent = `${snapshot.processes?.length || 0} of ${snapshot.process_total || 0} processes${snapshot.process_truncated ? " · truncated" : ""}`;
}

function detailPair(term, value) {
  return [monitorElement("dt", { text: term }), monitorElement("dd", { text: value == null || value === "" ? "—" : String(value) })];
}

async function sendProcessSignal(pid, signalName) {
  if (!window.confirm(`Send SIG${signalName} to process ${pid}?`)) return;
  setMonitorStatus(`Sending SIG${signalName} to ${pid}…`);
  try {
    await monitorApi(`/api/system-monitor/processes/${encodeURIComponent(pid)}/signal`, {
      method: "POST",
      body: JSON.stringify({ signal: signalName }),
    });
    setMonitorStatus(`SIG${signalName} sent to ${pid}`);
    setTimeout(() => pollMonitor(true), 250);
  } catch (error) {
    setMonitorStatus(error.message);
  }
}

async function openProcessDetail(pid) {
  monitorState.detail.hidden = false;
  monitorState.detailBody.replaceChildren(monitorElement("div", { text: "Loading process details…" }));
  try {
    const payload = await monitorApi(`/api/system-monitor/processes/${encodeURIComponent(pid)}`);
    const process = payload.process || {};
    monitorState.detail.querySelector(".raMonitorDetailTitle").textContent = `${process.name || "process"} · PID ${pid}`;
    const list = monitorElement("dl", { class: "raMonitorDetailGrid" });
    const ra = process.ra || {};
    const pairs = [
      ...detailPair("Command", process.command),
      ...detailPair("User", `${process.user} (${process.uid})`),
      ...detailPair("Parent PID", process.ppid),
      ...detailPair("State", process.state),
      ...detailPair("CPU", formatPercent(process.cpu_percent)),
      ...detailPair("Resident memory", formatBytes(process.memory_rss_bytes)),
      ...detailPair("Virtual memory", formatBytes(process.virtual_memory_bytes)),
      ...detailPair("GPU memory", process.gpu_memory_mb > 0 ? formatMb(process.gpu_memory_mb) : "—"),
      ...detailPair("Threads", process.threads),
      ...detailPair("Runtime", formatDuration(process.runtime_seconds)),
      ...detailPair("RA role", ra.role),
      ...detailPair("Run", ra.run_id),
      ...detailPair("Study", ra.study_id),
      ...detailPair("Trial", ra.trial_id),
      ...detailPair("Stage", ra.stage),
      ...detailPair("Run state", ra.state),
      ...detailPair("Run directory", ra.run_dir),
    ];
    list.append(...pairs);
    const content = [list];
    if (process.signalable) {
      content.push(monitorElement("div", { class: "raMonitorSignalRow" }, [
        monitorButton("SIGINT", () => sendProcessSignal(pid, "INT")),
        monitorButton("SIGTERM", () => sendProcessSignal(pid, "TERM"), "warn"),
        monitorButton("SIGSTOP", () => sendProcessSignal(pid, "STOP")),
        monitorButton("SIGCONT", () => sendProcessSignal(pid, "CONT")),
        monitorButton("SIGKILL", () => sendProcessSignal(pid, "KILL"), "danger"),
      ]));
    }
    for (const log of payload.logs || []) {
      content.push(monitorElement("section", { class: "raMonitorLog" }, [
        monitorElement("div", { class: "raMonitorLogHeader" }, [
          monitorElement("span", { text: log.label }),
          monitorElement("span", { text: log.path }),
        ]),
        monitorElement("pre", { text: log.tail || "[empty]" }),
      ]));
    }
    monitorState.detailBody.replaceChildren(...content);
  } catch (error) {
    monitorState.detailBody.replaceChildren(monitorElement("div", { text: error.message }));
  }
}

function setMonitorStatus(text) {
  if (monitorState.status) monitorState.status.textContent = text;
}

function snapshotUrl() {
  const params = new URLSearchParams({
    limit: "500",
    sort: monitorState.sort.value,
    scope: monitorState.scope.value,
  });
  const search = monitorState.search.value.trim();
  if (search) params.set("search", search);
  return `/api/system-monitor/snapshot?${params}`;
}

async function pollMonitor(force = false) {
  if (!monitorState.active || monitorState.paused || monitorState.polling) return;
  monitorState.polling = true;
  if (force || !monitorState.snapshot) setMonitorStatus("Sampling host…");
  try {
    const snapshot = await monitorApi(snapshotUrl());
    monitorState.snapshot = snapshot;
    renderOverview(snapshot);
    renderGpus(snapshot);
    renderProcesses(snapshot);
    const sampled = new Date(snapshot.timestamp).toLocaleTimeString();
    setMonitorStatus(`${snapshot.host?.hostname || "host"} · sampled ${sampled} in ${Number(snapshot.sample_duration_seconds || 0).toFixed(2)}s`);
  } catch (error) {
    setMonitorStatus(error.message);
  } finally {
    monitorState.polling = false;
    scheduleMonitorPoll();
  }
}

function scheduleMonitorPoll() {
  clearTimeout(monitorState.timer);
  if (!monitorState.active || monitorState.paused) return;
  const interval = Math.max(500, Number(monitorState.interval.value || 2000));
  monitorState.timer = setTimeout(() => pollMonitor(), interval);
}

function toggleMonitorPause() {
  monitorState.paused = !monitorState.paused;
  monitorState.pause.textContent = monitorState.paused ? "Resume" : "Pause";
  if (monitorState.paused) {
    clearTimeout(monitorState.timer);
    setMonitorStatus("Paused");
  } else {
    pollMonitor(true);
  }
}

function buildMonitorDialog() {
  const dialog = monitorElement("dialog", { class: "raMonitorDialog", id: "ra-system-monitor-dialog" });
  const search = monitorElement("input", { placeholder: "Filter PID, user, command, run…", type: "search" });
  const scope = monitorElement("select", {}, [
    monitorElement("option", { value: "all", text: "All processes" }),
    monitorElement("option", { value: "user", text: "My processes" }),
    monitorElement("option", { value: "gpu", text: "GPU processes" }),
    monitorElement("option", { value: "ra", text: "ResearchAssistant" }),
  ]);
  const sort = monitorElement("select", {}, [
    monitorElement("option", { value: "cpu", text: "Sort: CPU" }),
    monitorElement("option", { value: "memory", text: "Sort: memory" }),
    monitorElement("option", { value: "gpu", text: "Sort: GPU memory" }),
    monitorElement("option", { value: "runtime", text: "Sort: runtime" }),
    monitorElement("option", { value: "pid", text: "Sort: PID" }),
  ]);
  const interval = monitorElement("select", {}, [
    monitorElement("option", { value: "1000", text: "1 s" }),
    monitorElement("option", { value: "2000", text: "2 s", selected: "selected" }),
    monitorElement("option", { value: "5000", text: "5 s" }),
    monitorElement("option", { value: "10000", text: "10 s" }),
  ]);
  const pause = monitorButton("Pause", toggleMonitorPause);
  const refresh = monitorButton("Refresh", () => pollMonitor(true));
  const close = monitorButton("Close", () => dialog.close());
  const overview = monitorElement("div", { class: "raMonitorOverview" });
  const gpuGrid = monitorElement("div", { class: "raMonitorGpuGrid" });
  const processBody = monitorElement("tbody");
  const processMeta = monitorElement("span", { text: "No sample" });
  const status = monitorElement("span", { text: "Not connected" });
  const detailBody = monitorElement("div", { class: "raMonitorDetailBody" });
  const detail = monitorElement("aside", { class: "raMonitorDetail", hidden: "hidden" }, [
    monitorElement("div", { class: "raMonitorDetailHeader" }, [
      monitorElement("div", { class: "raMonitorDetailTitle", text: "Process" }),
      monitorButton("Close", () => { detail.hidden = true; }),
    ]),
    detailBody,
  ]);
  const table = monitorElement("table", { class: "raMonitorTable" }, [
    monitorElement("thead", {}, [monitorElement("tr", {}, [
      monitorElement("th", { class: "pid num", text: "PID" }),
      monitorElement("th", { class: "ra", text: "ResearchAssistant" }),
      monitorElement("th", { class: "user", text: "User" }),
      monitorElement("th", { class: "cpu num", text: "CPU" }),
      monitorElement("th", { class: "mem num", text: "RAM" }),
      monitorElement("th", { class: "gpu num", text: "GPU" }),
      monitorElement("th", { class: "state", text: "S" }),
      monitorElement("th", { class: "threads num", text: "Thr" }),
      monitorElement("th", { class: "runtime num", text: "Time" }),
      monitorElement("th", { class: "command", text: "Command" }),
      monitorElement("th", { class: "actions", text: "" }),
    ])]),
    processBody,
  ]);
  const processArea = monitorElement("div", { class: "raMonitorProcessArea" }, [table, detail]);
  const layout = monitorElement("div", { class: "raMonitorLayout" }, [
    monitorElement("div", { class: "raMonitorHeader" }, [
      monitorElement("div", { class: "raMonitorHeaderTitle", text: "System Monitor" }),
      monitorElement("div", { class: "raMonitorControls" }, [search, scope, sort, interval, pause, refresh]),
      close,
    ]),
    overview,
    gpuGrid,
    processArea,
    monitorElement("div", { class: "raMonitorFooter" }, [status, processMeta]),
  ]);
  dialog.append(layout);
  dialog.addEventListener("close", () => {
    monitorState.active = false;
    clearTimeout(monitorState.timer);
  });
  search.addEventListener("input", () => {
    clearTimeout(monitorState.searchTimer);
    monitorState.searchTimer = setTimeout(() => pollMonitor(true), 250);
  });
  scope.addEventListener("change", () => pollMonitor(true));
  sort.addEventListener("change", () => pollMonitor(true));
  interval.addEventListener("change", scheduleMonitorPoll);
  document.body.append(dialog);
  Object.assign(monitorState, {
    dialog, overview, gpuGrid, processBody, processMeta, detail, detailBody,
    status, search, scope, sort, interval, pause,
  });
  return dialog;
}

async function openSystemMonitor() {
  const dialog = monitorState.dialog || buildMonitorDialog();
  monitorState.active = true;
  monitorState.paused = false;
  monitorState.pause.textContent = "Pause";
  if (!dialog.open) dialog.showModal();
  await pollMonitor(true);
}

function installSystemMonitor() {
  if (document.querySelector("#ra-system-monitor-dialog")) return;
  installMonitorStyles();
  buildMonitorDialog();
  const actions = document.querySelector(".topbar-actions");
  const button = monitorElement("button", {
    class: "button ghost",
    text: "Monitor",
    title: "CPU, memory, GPU and process monitor",
    onclick: openSystemMonitor,
  });
  if (actions) actions.prepend(button);
  else document.body.prepend(button);
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.shiftKey && event.code === "KeyM") {
      event.preventDefault();
      openSystemMonitor();
    }
  });
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", installSystemMonitor)
  : installSystemMonitor();
