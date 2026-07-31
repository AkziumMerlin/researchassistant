const rawFetch = window.fetch.bind(window);
const SVG_NS = "http://www.w3.org/2000/svg";
const VIEW_STORAGE_KEY = "research-assistant.live-metric-views.v1";
const CHART_COLORS = [
  "#60a5fa", "#f59e0b", "#34d399", "#f472b6", "#a78bfa", "#22d3ee",
  "#fb7185", "#a3e635", "#facc15", "#c084fc", "#2dd4bf", "#fdba74",
];

const q = (selector, root = document) => root.querySelector(selector);
const qa = (selector, root = document) => [...root.querySelectorAll(selector)];

function node(tag, attributes = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") element.textContent = value;
    else if (key === "class") element.className = value;
    else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2), value);
    } else if (value !== null && value !== undefined) {
      element.setAttribute(key, String(value));
    }
  }
  for (const child of children) {
    element.append(child?.nodeType ? child : document.createTextNode(String(child)));
  }
  return element;
}

function svgNode(tag, attributes = {}, children = []) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") element.textContent = value;
    else element.setAttribute(key, String(value));
  }
  for (const child of children) element.append(child);
  return element;
}

async function api(path, options = {}) {
  const response = await rawFetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || response.statusText);
  return payload;
}

function parseValue(source) {
  try {
    return JSON.parse(source);
  } catch {
    return source;
  }
}

function parseAxes(source) {
  const result = {};
  for (const raw of source.split(/\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const split = line.indexOf("=");
    if (split < 1) throw new Error(`Expected path=[values]: ${line}`);
    const path = line.slice(0, split).trim();
    const values = parseValue(line.slice(split + 1));
    if (!Array.isArray(values) || values.length === 0) {
      throw new Error(`Matrix ${path} must be a non-empty array`);
    }
    result[path] = values;
  }
  return result;
}

function addStageComponents(payload, source) {
  for (const raw of source.split(/\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const split = line.indexOf("=");
    const key = line.slice(0, split);
    const dot = key.indexOf(".");
    if (split < 1 || dot < 1) throw new Error(`Expected stage.component={...}: ${line}`);
    const stageName = key.slice(0, dot);
    const componentKind = key.slice(dot + 1);
    const stage = (payload.stages || []).find((candidate) => candidate.name === stageName);
    const value = parseValue(line.slice(split + 1));
    if (!stage || !value?.type) throw new Error(`Invalid stage override: ${line}`);
    (stage.components ??= {})[componentKind] = value;
  }
}

window.fetch = async (input, options = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url === "/api/config/create" && String(options.method || "GET").toUpperCase() === "POST") {
    try {
      const payload = JSON.parse(options.body || "{}");
      payload.matrix = parseAxes(q("#ra-matrix")?.value || "");
      addStageComponents(payload, q("#ra-stage-components")?.value || "");
      options = { ...options, body: JSON.stringify(payload) };
    } catch (error) {
      return new Response(JSON.stringify({ detail: error.message }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }
  }
  return rawFetch(input, options);
};

function installStyles() {
  document.head.append(node("style", {
    text: `
      .raX{width:min(1440px,98vw);height:min(940px,96vh);background:#111827;color:#e5e7eb;border:1px solid #475569;border-radius:10px;padding:0}
      .raX::backdrop{background:#000a}.raH{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid #334155}
      .raG{display:grid;grid-template-columns:310px 1fr;height:calc(100% - 55px)}.raS,.raM{padding:12px;overflow:auto}.raS{border-right:1px solid #334155}
      .raF{display:grid;gap:6px;margin-bottom:9px}.raF input,.raF textarea,.raF select,.raInline input,.raInline select{background:#0b1220;color:#eee;border:1px solid #475569;padding:7px;border-radius:4px}
      .raB{background:#1e3a5f;color:#fff;border:1px solid #64748b;padding:6px 9px;border-radius:5px;cursor:pointer}.raB:disabled{opacity:.45;cursor:not-allowed}.raB.active{border-color:#60a5fa;background:#1d4ed8}
      .raC{padding:8px;border:1px solid #334155;margin:6px 0;cursor:pointer;border-radius:6px;white-space:pre-wrap}.raC.sel{border-color:#60a5fa;background:#172554}
      .raP{white-space:pre-wrap;background:#030712;padding:10px;min-height:220px;overflow:auto;border-radius:6px}.raT{width:100%;border-collapse:collapse;font-size:12px}.raT td,.raT th{padding:6px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}.raT th{position:sticky;top:0;background:#111827;z-index:1}
      .raA{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}.raA img{width:100%;height:140px;object-fit:contain;background:#000}.raE{color:#fca5a5;white-space:pre-wrap}.raMuted{color:#94a3b8}.raGood{color:#86efac}.raWarn{color:#fde68a}.raBad{color:#fca5a5}
      .raCreator{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.raTabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.raInline{display:flex;align-items:end;gap:8px;flex-wrap:wrap}.raInline label{display:grid;gap:4px;font-size:12px}
      .raLiveControls{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:8px;padding:10px;border:1px solid #334155;border-radius:8px;background:#0b1220}.raWide{grid-column:span 2}.raMetrics{display:flex;gap:6px;flex-wrap:wrap;padding:8px 0}.raMetricChoice{display:flex;align-items:center;gap:5px;padding:4px 7px;border:1px solid #334155;border-radius:999px;font-size:12px;background:#111827}
      .raCards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}.raCard{border:1px solid #334155;border-radius:8px;padding:9px;background:#0b1220}.raCard strong{display:block;font-size:18px;margin-top:3px}.raCharts{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:10px}.raChart{border:1px solid #334155;border-radius:8px;padding:10px;background:#0b1220;min-width:0}.raChart h4{margin:0 0 5px}.raChart svg{width:100%;height:auto;display:block}.raLegend{display:flex;gap:8px;flex-wrap:wrap;font-size:11px}.raLegendItem{display:flex;align-items:center;gap:4px}.raSwatch{width:10px;height:3px;border-radius:2px}.raRunTable{max-height:340px;overflow:auto;border:1px solid #334155;border-radius:8px;margin-top:10px}.raRunId{font-family:monospace;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.raStatus{font-weight:600}.raStatus.running,.raStatus.queued,.raStatus.pending{color:#86efac}.raStatus.failed,.raStatus.interrupted,.raStatus.cancelled{color:#fca5a5}.raStatus.completed{color:#93c5fd}
      .raEmpty{padding:25px;text-align:center;color:#94a3b8;border:1px dashed #475569;border-radius:8px}.raToolbar{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:8px 0}.raSpacer{flex:1}.raSmall{font-size:11px}.raViewSave{display:flex;gap:5px;align-items:end}.raViewSave input,.raViewSave select{min-width:140px}
      @media(max-width:1000px){.raG{grid-template-columns:260px 1fr}.raLiveControls{grid-template-columns:repeat(3,1fr)}.raCharts{grid-template-columns:1fr}}
      @media(max-width:760px){.raG{grid-template-columns:1fr}.raS{display:none}.raLiveControls{grid-template-columns:1fr}.raWide{grid-column:auto}.raCreator{grid-template-columns:1fr}}
    `,
  }));
}

function installCreatorExtensions() {
  const section = q("#config-dialog .creator-section");
  if (!section || q("#ra-matrix")) return;
  const wrapper = node("div", { class: "raCreator" });
  wrapper.innerHTML = `
    <label class="field wide"><span>Matrix axes</span><textarea id="ra-matrix" rows="3" placeholder="components.model.params.width=[64,128]"></textarea></label>
    <label class="field wide"><span>Stage-local components</span><textarea id="ra-stage-components" rows="3" placeholder='test.data={"type":"project/data","params":{}}'></textarea></label>
  `;
  section.append(wrapper);
}

const state = {
  jobs: [],
  job: null,
  detail: null,
  run: null,
  view: "live",
  timer: null,
  dialog: null,
  live: {
    cursor: {},
    panels: new Map(),
    catalog: null,
    selectedMetrics: new Set(),
    requestKey: "",
    paused: false,
    busy: false,
    response: null,
  },
};

function splitList(value) {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const numeric = Number(value);
  const absolute = Math.abs(numeric);
  if ((absolute > 0 && absolute < 1e-3) || absolute >= 1e4) return numeric.toExponential(3);
  return numeric.toLocaleString(undefined, { maximumSignificantDigits: 5 });
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "—";
  let remaining = Math.max(0, Math.round(Number(seconds)));
  const days = Math.floor(remaining / 86400); remaining %= 86400;
  const hours = Math.floor(remaining / 3600); remaining %= 3600;
  const minutes = Math.floor(remaining / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function loadSavedViews() {
  try {
    const parsed = JSON.parse(localStorage.getItem(VIEW_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function storeSavedViews(views) {
  localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(views));
}

function createJobsDialog() {
  const dialog = node("dialog", { class: "raX", id: "ra-jobs" });
  dialog.innerHTML = `
    <div class="raH"><b>Persistent jobs and live metrics</b><button class="raB" data-close>×</button></div>
    <div class="raG">
      <aside class="raS">
        <form id="ra-start">
          <label class="raF">Config<input id="ra-config" value="configs/experiment.yaml"></label>
          <label class="raF">Artifact root<input id="ra-root" value="runs"></label>
          <label class="raF">Overrides<textarea id="ra-overrides" rows="3"></textarea></label>
          <button class="raB">Start</button> <button class="raB" type="button" id="ra-refresh">Refresh</button>
          <div class="raE" id="ra-error"></div>
        </form>
        <div id="ra-list"></div>
      </aside>
      <main class="raM">
        <div id="ra-summary" class="raMuted">Select a job.</div>
        <div class="raToolbar">
          <button class="raB" id="ra-cancel">Cancel</button>
          <button class="raB" id="ra-recover">Recover</button>
          <span class="raSpacer"></span>
          <label class="raInline">Run <select id="ra-run"></select></label>
        </div>
        <div class="raTabs">
          <button class="raB" data-view="live">Live metrics</button>
          <button class="raB" data-view="logs">Logs</button>
          <button class="raB" data-view="latest">Latest values</button>
          <button class="raB" data-view="artifacts">Artifacts</button>
        </div>
        <div id="ra-body"></div>
      </main>
    </div>
  `;
  document.body.append(dialog);
  state.dialog = dialog;
  q("[data-close]", dialog).onclick = () => dialog.close();
  q("#ra-refresh", dialog).onclick = () => refreshJobs();
  q("#ra-start", dialog).onsubmit = startJob;
  q("#ra-cancel", dialog).onclick = () => jobAction("cancel");
  q("#ra-recover", dialog).onclick = () => jobAction("recover");
  q("#ra-run", dialog).onchange = (event) => {
    state.run = event.target.value;
    renderCurrentView(true);
  };
  qa("[data-view]", dialog).forEach((button) => {
    button.onclick = () => setView(button.dataset.view);
  });
  dialog.addEventListener("close", stopPolling);
  return dialog;
}

function renderJobList() {
  const list = q("#ra-list");
  list.replaceChildren(...state.jobs.map((job) => node("div", {
    class: `raC ${job.job_id === state.job ? "sel" : ""}`,
    text: `${job.job_id}\n${job.state} · ${job.plan?.runs || 0} runs\n${job.config_path || ""}`,
    onclick: () => selectJob(job.job_id),
  })));
}

async function refreshJobs() {
  try {
    state.jobs = (await api("/api/jobs")).jobs;
    renderJobList();
  } catch (error) {
    q("#ra-error").textContent = error.message;
  }
}

async function startJob(event) {
  event.preventDefault();
  try {
    const payload = {
      config_path: q("#ra-config").value,
      artifact_root: q("#ra-root").value,
      resume: true,
      overrides: q("#ra-overrides").value.split(/\n/).filter(Boolean),
      launcher_overrides: [],
    };
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    await refreshJobs();
    await selectJob(job.job_id);
  } catch (error) {
    q("#ra-error").textContent = error.message;
  }
}

function updateDetailUi() {
  const detail = state.detail;
  if (!detail) return;
  q("#ra-summary").textContent = `${detail.job_id} · ${detail.state} · scheduler ${detail.scheduler_alive ? "alive" : "stopped"}`;
  const runSelect = q("#ra-run");
  const prior = state.run;
  runSelect.replaceChildren(...(detail.runs || []).map((run) => node("option", {
    value: run.run_id,
    text: `${run.run_id} · ${run.state}`,
  })));
  const runIds = (detail.runs || []).map((run) => run.run_id);
  state.run = runIds.includes(prior) ? prior : (runIds[0] || null);
  runSelect.value = state.run || "";
  q("#ra-cancel").disabled = detail.state === "completed";
  q("#ra-recover").disabled = Boolean(detail.scheduler_alive) || detail.recorded_state === "completed";
  renderJobList();
}

async function loadJobDetail() {
  if (!state.job) return;
  state.detail = await api(`/api/jobs/${encodeURIComponent(state.job)}`);
  updateDetailUi();
}

function resetLive() {
  state.live.cursor = {};
  state.live.panels.clear();
  state.live.requestKey = "";
  state.live.response = null;
}

async function selectJob(jobId) {
  state.job = jobId;
  resetLive();
  await loadJobDetail();
  await refreshJobs();
  await setView("live", true);
}

async function jobAction(action) {
  if (!state.job) return;
  try {
    await api(`/api/jobs/${encodeURIComponent(state.job)}/${action}`, { method: "POST", body: "{}" });
    await loadJobDetail();
    if (state.view === "live") await livePoll(true);
  } catch (error) {
    q("#ra-body").textContent = error.message;
  }
}

function setView(view, force = false) {
  if (!force && state.view === view) return;
  state.view = view;
  qa("[data-view]", state.dialog).forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  return renderCurrentView(true);
}

async function renderCurrentView(force = false) {
  if (!state.job) {
    q("#ra-body").replaceChildren(node("div", { class: "raEmpty", text: "Select a job." }));
    return;
  }
  try {
    if (state.view === "live") {
      ensureLiveView();
      await livePoll(force);
    } else if (state.view === "logs") {
      await renderLogs();
    } else if (state.view === "latest") {
      await renderLatestValues();
    } else if (state.view === "artifacts") {
      await renderArtifacts();
    }
  } catch (error) {
    q("#ra-body").replaceChildren(node("div", { class: "raE", text: error.message }));
  }
}

function ensureLiveView() {
  const body = q("#ra-body");
  if (q("#ra-live", body)) return;
  const root = node("div", { id: "ra-live" });
  root.innerHTML = `
    <div class="raLiveControls">
      <label class="raF raWide">Search run/config<input id="ra-live-search" placeholder="run id, model, assignment, parameter"></label>
      <label class="raF">Trial<select id="ra-live-trial"><option value="">All trials</option></select></label>
      <label class="raF">Model<select id="ra-live-model"><option value="">All models</option></select></label>
      <label class="raF">Dataset<select id="ra-live-dataset"><option value="">All datasets</option></select></label>
      <label class="raF">Group lines by<select id="ra-live-group"><option value="run_id">run</option><option value="seed">seed</option><option value="model">model</option><option value="trial_id">trial</option></select></label>
      <label class="raF">Y scale<select id="ra-live-scale"><option value="linear">linear</option><option value="log">log</option></select></label>
      <label class="raF">Stages<input id="ra-live-stages" placeholder="fit,test"></label>
      <label class="raF">States<input id="ra-live-states" placeholder="running,completed"></label>
      <label class="raF"><span>Scope</span><span><input id="ra-live-active" type="checkbox" checked> active runs only</span></label>
      <div class="raF raWide"><span>Metrics</span><div id="ra-live-metrics" class="raMetrics"></div></div>
      <div class="raF"><span>Refresh</span><div><button class="raB" id="ra-live-apply">Apply</button> <button class="raB" id="ra-live-pause" type="button">Pause</button></div></div>
      <div class="raF raWide"><span>Saved view</span><div class="raViewSave"><select id="ra-live-saved"><option value="">Select…</option></select><input id="ra-live-name" placeholder="view name"><button class="raB" id="ra-live-save" type="button">Save</button><button class="raB" id="ra-live-delete" type="button">Delete</button></div></div>
    </div>
    <div id="ra-live-error" class="raE"></div>
    <div id="ra-live-cards" class="raCards"></div>
    <div id="ra-live-charts" class="raCharts"></div>
    <div id="ra-live-runs" class="raRunTable"></div>
  `;
  body.replaceChildren(root);
  q("#ra-live-apply").onclick = (event) => { event.preventDefault(); resetLive(); livePoll(true); };
  q("#ra-live-pause").onclick = () => {
    state.live.paused = !state.live.paused;
    q("#ra-live-pause").textContent = state.live.paused ? "Resume" : "Pause";
    q("#ra-live-pause").classList.toggle("active", state.live.paused);
    if (!state.live.paused) livePoll(false);
  };
  q("#ra-live-save").onclick = saveLiveView;
  q("#ra-live-delete").onclick = deleteLiveView;
  q("#ra-live-saved").onchange = loadLiveView;
  renderSavedViews();
}

function setSelectOptions(selector, values, emptyLabel) {
  const select = q(selector);
  if (!select) return;
  const current = select.value;
  select.replaceChildren(node("option", { value: "", text: emptyLabel }), ...values.map((value) => node("option", { value, text: value })));
  if (values.includes(current)) select.value = current;
}

function renderMetricChoices(catalog, selectedMetrics) {
  const container = q("#ra-live-metrics");
  if (!container) return;
  container.replaceChildren(...(catalog.metrics || []).map((metric) => {
    const checkbox = node("input", { type: "checkbox", value: metric });
    checkbox.checked = selectedMetrics.has(metric);
    checkbox.onchange = () => {
      if (checkbox.checked) state.live.selectedMetrics.add(metric);
      else state.live.selectedMetrics.delete(metric);
    };
    return node("label", { class: "raMetricChoice" }, [checkbox, metric]);
  }));
}

function renderLiveCatalog(catalog, selectedMetrics) {
  state.live.catalog = catalog;
  setSelectOptions("#ra-live-trial", catalog.trials || [], "All trials");
  setSelectOptions("#ra-live-model", catalog.models || [], "All models");
  setSelectOptions("#ra-live-dataset", catalog.datasets || [], "All datasets");
  renderMetricChoices(catalog, selectedMetrics);
}

function readLiveSpec() {
  return {
    metrics: [...state.live.selectedMetrics],
    stages: splitList(q("#ra-live-stages")?.value || ""),
    kinds: ["progress"],
    states: splitList(q("#ra-live-states")?.value || ""),
    trial_ids: q("#ra-live-trial")?.value ? [q("#ra-live-trial").value] : [],
    run_ids: [],
    models: q("#ra-live-model")?.value ? [q("#ra-live-model").value] : [],
    datasets: q("#ra-live-dataset")?.value ? [q("#ra-live-dataset").value] : [],
    splits: [],
    search: q("#ra-live-search")?.value || "",
    active_only: Boolean(q("#ra-live-active")?.checked),
    group_by: q("#ra-live-group")?.value || "run_id",
    aggregate: "mean",
    uncertainty: (q("#ra-live-group")?.value || "run_id") === "run_id" ? "none" : "std",
    max_points: 800,
    max_series: 80,
    y_scale: q("#ra-live-scale")?.value || "linear",
  };
}

function requestKey(spec) {
  return JSON.stringify(spec);
}

async function livePoll(force = false) {
  if (!state.job || state.live.busy || state.live.paused) return;
  ensureLiveView();
  const spec = readLiveSpec();
  const key = requestKey(spec);
  if (force || key !== state.live.requestKey) {
    state.live.requestKey = key;
    state.live.cursor = {};
    state.live.panels.clear();
  }
  state.live.busy = true;
  q("#ra-live-error").textContent = "";
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(state.job)}/live-metrics`, {
      method: "POST",
      body: JSON.stringify({ ...spec, cursor: state.live.cursor }),
    });
    const dashboard = result.dashboard;
    state.live.cursor = dashboard.cursor || {};
    if (state.live.selectedMetrics.size === 0 && dashboard.selected_metrics?.length) {
      state.live.selectedMetrics = new Set(dashboard.selected_metrics);
    }
    renderLiveCatalog(dashboard.catalog || {}, state.live.selectedMetrics);
    for (const panel of dashboard.panels || []) state.live.panels.set(panel.metric, panel);
    state.live.response = { ...dashboard, refresh: result.refresh };
    renderLiveDashboard();
  } catch (error) {
    q("#ra-live-error").textContent = error.message;
  } finally {
    state.live.busy = false;
  }
}

function stateCard(label, value, className = "") {
  return node("div", { class: `raCard ${className}` }, [node("span", { class: "raMuted", text: label }), node("strong", { text: value })]);
}

function renderLiveCards(response) {
  const summary = response.summary || {};
  const states = summary.states || {};
  const indexed = response.refresh?.events_indexed || 0;
  const cards = [
    stateCard("visible runs", String(summary.runs || 0)),
    stateCard("job runs", String(summary.job_runs || 0)),
    stateCard("running", String((states.running || 0) + (states.queued || 0) + (states.pending || 0)), "raGood"),
    stateCard("completed", String(states.completed || 0)),
    stateCard("failed/interrupted", String((states.failed || 0) + (states.interrupted || 0) + (states.cancelled || 0)), "raBad"),
    stateCard("new indexed events", String(indexed)),
  ];
  q("#ra-live-cards").replaceChildren(...cards);
}

function chartTransform(chart, yScale) {
  const all = (chart.series || []).flatMap((series) => series.points.map((point) => ({ ...point, series: series.name })));
  const valid = all.filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)) && (yScale !== "log" || Number(point.y) > 0));
  if (!valid.length) return null;
  const xValues = valid.map((point) => Number(point.x));
  const yValues = valid.flatMap((point) => [point.y, point.lower, point.upper].map(Number)).filter((value) => Number.isFinite(value) && (yScale !== "log" || value > 0));
  const xMin = Math.min(...xValues), xMax = Math.max(...xValues);
  const rawYMin = Math.min(...yValues), rawYMax = Math.max(...yValues);
  const transformY = (value) => yScale === "log" ? Math.log10(Math.max(Number(value), Number.MIN_VALUE)) : Number(value);
  let yMin = transformY(rawYMin), yMax = transformY(rawYMax);
  if (xMin === xMax) { /* handled by scale denominator */ }
  if (yMin === yMax) { yMin -= 0.5; yMax += 0.5; }
  return { xMin, xMax, rawYMin, rawYMax, yMin, yMax, transformY };
}

function renderChartPanel(panel) {
  const chart = panel.chart;
  const yScale = chart.spec?.y_scale || "linear";
  const card = node("section", { class: "raChart" });
  card.append(node("h4", { text: panel.metric }));
  const transform = chartTransform(chart, yScale);
  if (!transform) {
    card.append(node("div", { class: "raEmpty", text: "No matching points yet." }));
    return card;
  }
  const width = 900, height = 300, left = 72, right = 18, top = 18, bottom = 48;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const xScale = (value) => left + ((Number(value) - transform.xMin) / (transform.xMax - transform.xMin || 1)) * plotWidth;
  const yProject = (value) => top + (1 - (transform.transformY(value) - transform.yMin) / (transform.yMax - transform.yMin || 1)) * plotHeight;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": panel.metric });
  svg.append(svgNode("line", { x1: left, y1: top, x2: left, y2: height - bottom, stroke: "#64748b" }));
  svg.append(svgNode("line", { x1: left, y1: height - bottom, x2: width - right, y2: height - bottom, stroke: "#64748b" }));
  for (let tick = 0; tick <= 4; tick += 1) {
    const y = top + (tick / 4) * plotHeight;
    const transformed = transform.yMax - (tick / 4) * (transform.yMax - transform.yMin);
    const value = yScale === "log" ? 10 ** transformed : transformed;
    svg.append(svgNode("line", { x1: left, y1: y, x2: width - right, y2: y, stroke: "#334155", "stroke-dasharray": "3 4" }));
    svg.append(svgNode("text", { x: left - 8, y: y + 4, fill: "#94a3b8", "text-anchor": "end", "font-size": 11, text: formatNumber(value) }));
  }
  svg.append(svgNode("text", { x: left, y: height - 18, fill: "#94a3b8", "font-size": 11, text: formatNumber(transform.xMin) }));
  svg.append(svgNode("text", { x: width - right, y: height - 18, fill: "#94a3b8", "text-anchor": "end", "font-size": 11, text: formatNumber(transform.xMax) }));

  (chart.series || []).forEach((series, index) => {
    const color = CHART_COLORS[index % CHART_COLORS.length];
    const points = series.points.filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)) && (yScale !== "log" || Number(point.y) > 0));
    if (!points.length) return;
    const hasBand = points.some((point) => Number(point.lower) !== Number(point.upper));
    if (hasBand) {
      const upper = points.filter((point) => yScale !== "log" || Number(point.upper) > 0).map((point) => `${xScale(point.x)},${yProject(point.upper)}`);
      const lower = [...points].reverse().filter((point) => yScale !== "log" || Number(point.lower) > 0).map((point) => `${xScale(point.x)},${yProject(point.lower)}`);
      if (upper.length && lower.length) svg.append(svgNode("polygon", { points: [...upper, ...lower].join(" "), fill: color, opacity: 0.12 }));
    }
    const pathData = points.map((point, position) => `${position ? "L" : "M"}${xScale(point.x).toFixed(2)},${yProject(point.y).toFixed(2)}`).join(" ");
    svg.append(svgNode("path", { d: pathData, fill: "none", stroke: color, "stroke-width": 2, "vector-effect": "non-scaling-stroke" }));
    if (points.length <= 80) {
      for (const point of points) {
        const circle = svgNode("circle", { cx: xScale(point.x), cy: yProject(point.y), r: 2.5, fill: color });
        circle.append(svgNode("title", { text: `${series.name}\nstep ${formatNumber(point.x)}\n${formatNumber(point.y)}` }));
        svg.append(circle);
      }
    }
  });
  card.append(svg);
  const legend = node("div", { class: "raLegend" });
  const visibleSeries = (chart.series || []).slice(0, 20);
  visibleSeries.forEach((series, index) => legend.append(node("span", { class: "raLegendItem" }, [
    node("span", { class: "raSwatch", style: `background:${CHART_COLORS[index % CHART_COLORS.length]}` }),
    series.name,
  ])));
  if ((chart.series || []).length > visibleSeries.length) legend.append(node("span", { class: "raMuted", text: `+${chart.series.length - visibleSeries.length} series` }));
  card.append(legend);
  if (chart.truncated) card.append(node("div", { class: "raWarn raSmall", text: `Showing ${chart.series_count} of ${chart.series_total} series.` }));
  return card;
}

function renderLiveCharts(response) {
  const selected = response.selected_metrics || [];
  const panels = selected.map((metric) => state.live.panels.get(metric)).filter(Boolean);
  const container = q("#ra-live-charts");
  if (!panels.length) {
    container.replaceChildren(node("div", { class: "raEmpty", text: selected.length ? "Waiting for matching metric events." : "No metrics have been indexed for this job yet." }));
    return;
  }
  container.replaceChildren(...panels.map(renderChartPanel));
}

function resourceSummary(resources, gpu) {
  const entries = Object.entries(resources || {});
  const preferred = entries.find(([name]) => /gpu.*memory|memory.*gpu|vram|peak.*memory/i.test(name)) || entries.find(([name]) => /gpu|memory/i.test(name));
  if (preferred) return `${preferred[0]}=${formatNumber(preferred[1])}`;
  if (gpu && typeof gpu === "object") {
    const label = gpu.index ?? gpu.device ?? gpu.uuid ?? gpu.name;
    const memory = gpu.memory_used_mb ?? gpu.used_memory_mb ?? gpu.peak_memory_mb;
    if (label !== undefined && memory !== undefined) return `GPU ${label} · ${formatNumber(memory)} MiB`;
    if (label !== undefined) return `GPU ${label}`;
  }
  return "—";
}

function openRunView(runId, view) {
  state.run = runId;
  q("#ra-run").value = runId;
  setView(view, true);
}

function renderRunTable(response) {
  const metrics = (response.selected_metrics || []).slice(0, 4);
  const table = node("table", { class: "raT" });
  const head = node("tr");
  ["state", "run", "trial / seed", "model", "step", "ETA", ...metrics, "GPU/resource", "open"].forEach((label) => head.append(node("th", { text: label })));
  table.append(head);
  for (const run of response.runs || []) {
    const row = node("tr");
    row.append(node("td", { class: `raStatus ${run.state}`, text: run.state }));
    row.append(node("td", { class: "raRunId", title: run.run_id, text: run.run_id }));
    row.append(node("td", { text: `${run.trial_id}\nseed=${run.seed ?? "—"}` }));
    row.append(node("td", { text: run.model || "—" }));
    row.append(node("td", { text: run.step === null || run.step === undefined ? "—" : `${run.step_kind || "step"} ${formatNumber(run.step)}${run.total_steps ? ` / ${run.total_steps}` : ""}` }));
    row.append(node("td", { text: formatDuration(run.eta_seconds) }));
    for (const metric of metrics) row.append(node("td", { text: formatNumber(run.metrics?.[metric]?.value) }));
    row.append(node("td", { class: "raSmall", text: resourceSummary(run.resources, run.gpu) }));
    const actions = node("td");
    actions.append(node("button", { class: "raB", text: "logs", onclick: () => openRunView(run.run_id, "logs") }));
    actions.append(" ");
    actions.append(node("button", { class: "raB", text: "artifacts", onclick: () => openRunView(run.run_id, "artifacts") }));
    row.append(actions);
    table.append(row);
  }
  const container = q("#ra-live-runs");
  if (!(response.runs || []).length) container.replaceChildren(node("div", { class: "raEmpty", text: "No runs match the current scope." }));
  else container.replaceChildren(table);
}

function renderLiveDashboard() {
  const response = state.live.response;
  if (!response) return;
  renderLiveCards(response);
  renderLiveCharts(response);
  renderRunTable(response);
}

function currentViewPayload() {
  return {
    search: q("#ra-live-search")?.value || "",
    trial: q("#ra-live-trial")?.value || "",
    model: q("#ra-live-model")?.value || "",
    dataset: q("#ra-live-dataset")?.value || "",
    group: q("#ra-live-group")?.value || "run_id",
    scale: q("#ra-live-scale")?.value || "linear",
    stages: q("#ra-live-stages")?.value || "",
    states: q("#ra-live-states")?.value || "",
    active: Boolean(q("#ra-live-active")?.checked),
    metrics: [...state.live.selectedMetrics],
  };
}

function applyViewPayload(payload) {
  q("#ra-live-search").value = payload.search || "";
  q("#ra-live-trial").value = payload.trial || "";
  q("#ra-live-model").value = payload.model || "";
  q("#ra-live-dataset").value = payload.dataset || "";
  q("#ra-live-group").value = payload.group || "run_id";
  q("#ra-live-scale").value = payload.scale || "linear";
  q("#ra-live-stages").value = payload.stages || "";
  q("#ra-live-states").value = payload.states || "";
  q("#ra-live-active").checked = payload.active !== false;
  state.live.selectedMetrics = new Set(payload.metrics || []);
  renderMetricChoices(state.live.catalog || { metrics: [] }, state.live.selectedMetrics);
  resetLive();
  livePoll(true);
}

function renderSavedViews() {
  const select = q("#ra-live-saved");
  if (!select) return;
  const views = loadSavedViews();
  const current = select.value;
  select.replaceChildren(node("option", { value: "", text: "Select…" }), ...Object.keys(views).sort().map((name) => node("option", { value: name, text: name })));
  if (views[current]) select.value = current;
}

function saveLiveView() {
  const name = q("#ra-live-name").value.trim();
  if (!name) {
    q("#ra-live-error").textContent = "Enter a view name.";
    return;
  }
  const views = loadSavedViews();
  views[name] = currentViewPayload();
  storeSavedViews(views);
  renderSavedViews();
  q("#ra-live-saved").value = name;
  q("#ra-live-error").textContent = "";
}

function loadLiveView() {
  const name = q("#ra-live-saved").value;
  if (!name) return;
  const view = loadSavedViews()[name];
  if (view) applyViewPayload(view);
}

function deleteLiveView() {
  const name = q("#ra-live-saved").value;
  if (!name) return;
  const views = loadSavedViews();
  delete views[name];
  storeSavedViews(views);
  renderSavedViews();
}

async function renderLogs() {
  if (!state.run) {
    q("#ra-body").replaceChildren(node("div", { class: "raEmpty", text: "No run is available." }));
    return;
  }
  const root = node("div");
  const controls = node("div", { class: "raToolbar" });
  const source = node("select");
  source.append(node("option", { value: "worker", text: "worker" }), node("option", { value: "scheduler", text: "scheduler" }));
  controls.append(node("label", { class: "raInline" }, ["Source ", source]));
  controls.append(node("button", { class: "raB", text: "Refresh", onclick: async () => load() }));
  const output = node("pre", { class: "raP" });
  root.append(controls, output);
  q("#ra-body").replaceChildren(root);
  async function load() {
    const query = source.value === "worker" ? `source=worker&run_id=${encodeURIComponent(state.run)}` : "source=scheduler";
    const page = await api(`/api/jobs/${encodeURIComponent(state.job)}/logs?${query}&tail=true&limit=131072`);
    output.textContent = page.text;
    output.scrollTop = output.scrollHeight;
  }
  source.onchange = load;
  await load();
}

async function renderLatestValues() {
  if (!state.run) {
    q("#ra-body").replaceChildren(node("div", { class: "raEmpty", text: "No run is available." }));
    return;
  }
  const payload = await api(`/api/jobs/${encodeURIComponent(state.job)}/metrics?run_id=${encodeURIComponent(state.run)}&limit=1000`);
  const table = node("table", { class: "raT" });
  const head = node("tr");
  ["metric", "value", "step", "stage", "sequence"].forEach((label) => head.append(node("th", { text: label })));
  table.append(head);
  for (const [name, event] of Object.entries(payload.latest || {})) {
    const row = node("tr");
    [name, formatNumber(event.value), event.step ?? "—", event.stage || "—", event.sequence ?? "—"].forEach((value) => row.append(node("td", { text: String(value) })));
    table.append(row);
  }
  q("#ra-body").replaceChildren(table);
}

async function renderArtifacts() {
  if (!state.run) {
    q("#ra-body").replaceChildren(node("div", { class: "raEmpty", text: "No run is available." }));
    return;
  }
  const payload = await api(`/api/jobs/${encodeURIComponent(state.job)}/artifacts?run_id=${encodeURIComponent(state.run)}`);
  const gallery = node("div", { class: "raA" });
  for (const artifact of payload.artifacts) {
    const card = node("div", { class: "raC" });
    const url = `/api/jobs/${encodeURIComponent(state.job)}/artifacts/file?run_id=${encodeURIComponent(state.run)}&path=${encodeURIComponent(artifact.path)}`;
    if (artifact.preview === "image") card.append(node("img", { src: url, alt: artifact.path }));
    card.append(node("div", { text: `${artifact.semantic_kind || artifact.preview} · ${artifact.path}` }));
    card.onclick = () => window.open(url, "_blank", "noopener");
    gallery.append(card);
  }
  q("#ra-body").replaceChildren(gallery);
}

function startPolling() {
  stopPolling();
  state.timer = setInterval(async () => {
    if (!state.dialog?.open || !state.job) return;
    try {
      await loadJobDetail();
      if (state.view === "live" && !state.live.paused) await livePoll(false);
    } catch (error) {
      if (q("#ra-live-error")) q("#ra-live-error").textContent = error.message;
    }
  }, 3000);
}

function stopPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

function createAdvancedChartDialog() {
  const dialog = node("dialog", { class: "raX", id: "ra-charts" });
  dialog.innerHTML = `
    <div class="raH"><b>Advanced charts</b><button class="raB" data-close>×</button></div>
    <div class="raM">
      <form id="ra-chart">
        <label class="raF">Type<select id="ra-type"><option>scatter</option><option>histogram</option><option>heatmap</option><option>composite</option></select></label>
        <label class="raF">Artifact root<input id="ra-chart-root" value="runs"></label>
        <label class="raF">Metric<input id="ra-metric"></label>
        <label class="raF">X metric<input id="ra-x"></label>
        <label class="raF">Y metric<input id="ra-y"></label>
        <label class="raF">Panels JSON<textarea id="ra-panels">[]</textarea></label>
        <button class="raB">Build</button>
      </form>
      <pre class="raP" id="ra-chart-out"></pre>
    </div>
  `;
  document.body.append(dialog);
  q("[data-close]", dialog).onclick = () => dialog.close();
  q("#ra-chart", dialog).onsubmit = async (event) => {
    event.preventDefault();
    try {
      const chartType = q("#ra-type").value;
      const payload = {
        name: "ui-chart",
        artifact_root: q("#ra-chart-root").value,
        chart_type: chartType,
        filters: {},
        metric: q("#ra-metric").value || null,
        x_metric: q("#ra-x").value || null,
        y_metric: q("#ra-y").value || null,
        panels: chartType === "composite" ? JSON.parse(q("#ra-panels").value) : [],
      };
      q("#ra-chart-out").textContent = JSON.stringify((await api("/api/analytics/advanced", { method: "POST", body: JSON.stringify(payload) })).chart, null, 2);
    } catch (error) {
      q("#ra-chart-out").textContent = error.message;
    }
  };
  return dialog;
}

function main() {
  installStyles();
  installCreatorExtensions();
  const jobs = createJobsDialog();
  const charts = createAdvancedChartDialog();
  const actions = q(".topbar-actions");
  if (actions) {
    actions.prepend(node("button", { class: "button ghost", text: "Charts+", onclick: () => charts.showModal() }));
    actions.prepend(node("button", {
      class: "button ghost",
      text: "Jobs+",
      onclick: async () => {
        jobs.showModal();
        await refreshJobs();
        if (state.job) await loadJobDetail();
        startPolling();
      },
    }));
  }
}

document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", main) : main();
