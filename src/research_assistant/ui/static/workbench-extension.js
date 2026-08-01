const wbFetch = window.fetch.bind(window);
const wbApi = async (path, options = {}) => {
  const response = await wbFetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.message || response.statusText);
  return payload;
};
const wbPost = (path, body) => wbApi(path, { method: "POST", body: JSON.stringify(body) });
const wbEl = (tag, attributes = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  for (const child of children) node.append(child?.nodeType ? child : document.createTextNode(String(child)));
  return node;
};
const wbField = (label, input) => wbEl("label", { class: "wbField" }, [wbEl("span", { text: label }), input]);
const wbInput = (value = "", placeholder = "") => wbEl("input", { value, placeholder });
const wbArea = (value = "", rows = 4) => {
  const area = wbEl("textarea", { rows });
  area.value = value;
  return area;
};
const wbButton = (text, handler, kind = "") => wbEl("button", { class: `wbButton ${kind}`, text, onclick: handler });
const wbPretty = (value) => JSON.stringify(value, null, 2);
const wbSplit = (value) => value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
const wbNumber = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;

function wbInstallCss() {
  if (document.querySelector("#ra-workbench-style")) return;
  document.head.append(wbEl("style", {
    id: "ra-workbench-style",
    text: `.wbDialog{width:min(1450px,98vw);height:min(940px,97vh);padding:0;background:#0b1220;color:#e5e7eb;border:1px solid #475569;border-radius:10px}.wbDialog::backdrop{background:#000c}.wbHeader{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #334155}.wbTabs{display:flex;gap:6px;flex-wrap:wrap;padding:9px 14px;border-bottom:1px solid #334155}.wbMain{height:calc(100% - 106px);padding:14px;overflow:auto}.wbGrid{display:grid;grid-template-columns:minmax(300px,.9fr) minmax(420px,1.3fr);gap:12px}.wbTriple{display:grid;grid-template-columns:repeat(3,minmax(240px,1fr));gap:12px}.wbCard{background:#111827;border:1px solid #334155;border-radius:8px;padding:11px;min-width:0}.wbField{display:grid;gap:4px;margin-bottom:8px;font-size:12px;color:#cbd5e1}.wbField input,.wbField textarea,.wbField select{background:#030712;color:#f8fafc;border:1px solid #475569;border-radius:4px;padding:7px;font:inherit}.wbActions{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}.wbButton{background:#1e3a5f;color:#fff;border:1px solid #64748b;border-radius:5px;padding:6px 9px;cursor:pointer}.wbButton.active,.wbButton.primary{background:#1d4ed8;border-color:#60a5fa}.wbButton.danger{background:#7f1d1d}.wbButton:disabled{opacity:.5;cursor:not-allowed}.wbOutput{white-space:pre-wrap;overflow:auto;max-height:580px;background:#030712;border:1px solid #1f2937;border-radius:5px;padding:9px;font:12px/1.45 ui-monospace,monospace}.wbTable{width:100%;border-collapse:collapse;font-size:12px}.wbTable th,.wbTable td{padding:6px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}.wbMuted{color:#94a3b8}.wbBadge{display:inline-block;padding:2px 5px;border-radius:4px;background:#1e293b;margin-right:4px}.wbRows{display:grid;gap:7px}.wbRow{border:1px solid #334155;border-radius:6px;padding:8px;background:#0f172a}.wbProtocolGrid{display:grid;grid-template-columns:repeat(2,minmax(310px,1fr));gap:12px}@media(max-width:950px){.wbGrid,.wbTriple,.wbProtocolGrid{grid-template-columns:1fr}}`,
  }));
}

const wbState = { tab: "protocols", capabilities: null, selectedArtifact: null, selectedSession: null };

function wbResultCard(title = "Result") {
  const output = wbEl("pre", { class: "wbOutput", text: "Ready." });
  return { card: wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: title }), output]), output };
}
function wbHandle(output, action) {
  return async () => {
    output.textContent = "Working…";
    try { output.textContent = wbPretty(await action()); }
    catch (error) { output.textContent = error.message; }
  };
}

function wbProtocolCard(title, fields, actions) {
  const output = wbEl("pre", { class: "wbOutput", text: "Ready." });
  const card = wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: title })]);
  for (const field of fields) card.append(field);
  const controls = wbEl("div", { class: "wbActions" });
  for (const [label, handler] of actions(output)) controls.append(wbButton(label, wbHandle(output, handler), label.includes("Lock") || label.includes("Build") ? "primary" : ""));
  card.append(controls, output);
  return card;
}

function wbRenderProtocols(root) {
  const hpoName = wbInput("model-search");
  const base = wbInput("configs/experiment.yaml");
  const objective = wbInput("val/loss");
  const parameter = wbInput("components.model.params.width");
  const choices = wbInput("32,64,96");
  const trials = wbInput("50");
  const parallel = wbInput("4");
  const hpo = wbProtocolCard("Adaptive HPO", [
    wbField("Search name", hpoName), wbField("Base config", base), wbField("Validation metric", objective),
    wbField("Parameter path", parameter), wbField("Categorical values", choices),
    wbField("Maximum trials", trials), wbField("Parallelism", parallel),
  ], (out) => {
    const spec = () => ({
      name: hpoName.value, base_config: base.value, artifact_root: "runs",
      search_space: { [parameter.value]: { type: "categorical", choices: wbSplit(choices.value).map((v) => /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v) } },
      objectives: [{ metric: objective.value, split: "validation", direction: "minimize" }], sampler: "tpe",
      max_trials: wbNumber(trials.value, 50), parallelism: wbNumber(parallel.value, 4), seed: 0,
      startup_trials: 8, good_fraction: .25, plugins: [], launcher_overrides: [], config_overrides: [],
      asha: { enabled: true, resource_steps: [25, 50, 100, 200], reduction_factor: 3, grace_step: 25 },
    });
    return [
      ["Status", () => wbPost("/api/research/hpo/status", { spec: spec() })],
      ["Propose", () => wbPost("/api/research/hpo/propose", { spec: spec(), count: 1, launch: false })],
      ["Propose + launch", () => wbPost("/api/research/hpo/propose", { spec: spec(), count: wbNumber(parallel.value, 4), launch: true })],
      ["Step", () => wbPost("/api/research/hpo/step", { spec: spec() })],
    ];
  });

  const selectionName = wbInput("final-models");
  const selectionMetric = wbInput("val/loss");
  const targets = wbInput("test/loss");
  const group = wbInput("study_id,dataset,model");
  const seeds = wbInput("0,1,2");
  const selection = wbProtocolCard("Validation-only selection", [
    wbField("Lock name", selectionName), wbField("Selection metric", selectionMetric),
    wbField("Target metrics", targets), wbField("Group by", group), wbField("Required seeds", seeds),
  ], () => {
    const spec = () => ({ name: selectionName.value, artifact_root: "runs", selection_metric: selectionMetric.value,
      selection_split: "validation", target_metrics: wbSplit(targets.value), test_splits: ["test", "ood"], direction: "minimize",
      checkpoint_alignment: "same_step", group_by: wbSplit(group.value), required_seeds: wbSplit(seeds.value).map(Number),
      min_seeds: wbSplit(seeds.value).length, allowed_states: ["completed"], promote_checkpoints: true, strict_test_lock: true });
    return [["Preview", () => wbPost("/api/research/selection/preview", { spec: spec(), overwrite: false })],
      ["Create Lock", () => wbPost("/api/research/selection/lock", { spec: spec(), overwrite: false })]];
  });

  const statName = wbInput("paired-comparison");
  const statMetric = wbInput("test/loss");
  const statGroup = wbInput("model");
  const paired = wbInput("seed,dataset");
  const baseline = wbInput("KNO");
  const statistics = wbProtocolCard("Statistical comparison", [
    wbField("Report name", statName), wbField("Metric", statMetric), wbField("Compare groups by", statGroup),
    wbField("Pair by", paired), wbField("Baseline", baseline),
  ], () => {
    const spec = () => ({ name: statName.value, artifact_root: "runs", metric: statMetric.value, split: "test",
      direction: "minimize", group_by: statGroup.value, paired_by: wbSplit(paired.value), baseline: baseline.value || null,
      confidence: .95, bootstrap_samples: 5000, permutation_samples: 20000, correction: "holm", missing_pair_policy: "drop", seed: 0, max_runs: 10000 });
    return [["Analyze", () => wbPost("/api/research/statistics/run", { spec: spec() })],
      ["Build report", () => wbPost("/api/research/statistics/run", { spec: spec(), output_path: `reports/${statName.value}` })]];
  });

  const pubName = wbInput("paper-results");
  const reports = wbInput("reports/main-table");
  const selections = wbInput("final-models");
  const datasets = wbInput("");
  const compile = wbEl("input", { type: "checkbox" });
  const publication = wbProtocolCard("Publication bundle", [
    wbField("Bundle name", pubName), wbField("Reports", reports), wbField("Selection locks", selections),
    wbField("Dataset IDs", datasets), wbField("Compile PDF", compile),
  ], () => {
    const spec = () => ({ name: pubName.value, title: pubName.value, authors: [], artifact_root: "runs", study_ids: [], trial_ids: [], run_ids: [],
      reports: wbSplit(reports.value), asset_statuses: ["selected", "released"], include_all_artifacts: false, include_checkpoints: true,
      include_environment: true, template: "aaai", copy_mode: "hardlink", dataset_ids: wbSplit(datasets.value), selection_locks: wbSplit(selections.value),
      statistical_reports: [], bibliography: [], include_research_log: true, strict_consistency: true, compile_pdf: compile.checked });
    return [["Preview", () => wbPost("/api/research/publication/preview", { spec: spec() })],
      ["Build", () => wbPost("/api/research/publication/build", { spec: spec(), output_path: `publications/${pubName.value}` })]];
  });
  root.append(wbEl("div", { class: "wbProtocolGrid" }, [hpo, selection, statistics, publication]));
}

async function wbRenderArtifacts(root) {
  const search = wbInput("", "filter by name, path, tag");
  const kind = wbInput("", "kind");
  const registerPath = wbInput("", "runs/.../prediction.json");
  const registerKind = wbInput("prediction", "kind");
  const selection = wbInput("", "0, :, 10:20");
  const compareRight = wbInput("", "right artifact ID");
  const output = wbEl("pre", { class: "wbOutput", text: "Select an artifact." });
  const list = wbEl("div", { class: "wbRows" });
  const load = async () => {
    const params = new URLSearchParams({ limit: "2000" });
    if (search.value) params.set("search", search.value);
    if (kind.value) params.set("kind", kind.value);
    const payload = await wbApi(`/api/workbench/artifacts?${params}`);
    list.replaceChildren(...(payload.artifacts || []).map((item) => wbEl("div", { class: "wbRow" }, [
      wbEl("b", { text: item.name }), wbEl("div", { class: "wbMuted", text: `${item.artifact_id} · ${item.kind} · ${item.path}` }),
      wbEl("span", { class: "wbBadge", text: (item.description?.shape ? JSON.stringify(item.description.shape) : item.description?.format || "file") }),
      wbButton("Select", async () => { wbState.selectedArtifact = item; output.textContent = wbPretty(await wbApi(`/api/workbench/artifacts/${item.artifact_id}`)); }),
    ])));
  };
  root.append(wbEl("div", { class: "wbGrid" }, [
    wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Scientific artifact catalog" }), wbField("Search", search), wbField("Kind", kind),
      wbEl("div", { class: "wbActions" }, [wbButton("Refresh", () => load().catch((e) => output.textContent = e.message)), wbButton("Discover runs/reports", wbHandle(output, async () => { const r = await wbPost("/api/workbench/artifacts/discover", { roots: ["runs", "reports"], limit: 10000 }); await load(); return r; }))]), list]),
    wbEl("div", { class: "wbRows" }, [
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Register" }), wbField("Path", registerPath), wbField("Kind", registerKind), wbButton("Register artifact", wbHandle(output, async () => { const r = await wbPost("/api/workbench/artifacts/register", { path: registerPath.value, kind: registerKind.value || null, dimensions: [], metadata: {}, tags: [] }); await load(); return r; }))]),
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Slice and compare" }), wbField("Slice selectors", selection), wbField("Compare selected with", compareRight), wbEl("div", { class: "wbActions" }, [
        wbButton("Slice selected", wbHandle(output, () => wbPost("/api/workbench/artifacts/slice", { artifact_id: wbState.selectedArtifact?.artifact_id || "", selection: wbSplit(selection.value), max_elements: 100000 }))),
        wbButton("Compare", wbHandle(output, () => wbPost("/api/workbench/artifacts/compare", { left_id: wbState.selectedArtifact?.artifact_id || "", right_id: compareRight.value }))),
      ]), output]),
    ]),
  ]));
  await load().catch((error) => output.textContent = error.message);
}

async function wbRenderLifecycle(root) {
  const path = wbInput("runs/", "workspace-relative result path");
  const reason = wbInput("", "reason");
  const force = wbEl("input", { type: "checkbox" });
  const trashId = wbInput("", "trash ID");
  const days = wbInput("30");
  const output = wbEl("pre", { class: "wbOutput", text: "Ready." });
  const state = wbEl("pre", { class: "wbOutput" });
  const refresh = async () => state.textContent = wbPretty(await wbApi("/api/workbench/lifecycle"));
  const action = (endpoint, body) => wbHandle(output, async () => { const result = await wbPost(endpoint, body()); await refresh(); return result; });
  root.append(wbEl("div", { class: "wbGrid" }, [
    wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Result lifecycle" }), wbField("Path", path), wbField("Reason", reason), wbField("Force protected trash", force),
      wbEl("div", { class: "wbActions" }, [
        wbButton("Protection", wbHandle(output, () => wbApi(`/api/workbench/lifecycle/protection?path=${encodeURIComponent(path.value)}`))),
        wbButton("Pin", action("/api/workbench/lifecycle/pin", () => ({ path: path.value, reason: reason.value || null }))),
        wbButton("Unpin", action("/api/workbench/lifecycle/unpin", () => ({ path: path.value }))),
        wbButton("Archive", action("/api/workbench/lifecycle/archive", () => ({ path: path.value, reason: reason.value || null }))),
        wbButton("Trash", action("/api/workbench/lifecycle/trash", () => ({ path: path.value, reason: reason.value || null, force: force.checked })), "danger"),
      ]), output]),
    wbEl("div", { class: "wbRows" }, [
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Restore and garbage collection" }), wbField("Trash ID", trashId), wbField("Older than days", days), wbEl("div", { class: "wbActions" }, [
        wbButton("Restore", action("/api/workbench/lifecycle/restore", () => ({ trash_id: trashId.value, overwrite: false }))),
        wbButton("GC preview", action("/api/workbench/lifecycle/gc", () => ({ older_than_days: wbNumber(days.value, 30), dry_run: true }))),
        wbButton("Apply GC", action("/api/workbench/lifecycle/gc", () => ({ older_than_days: wbNumber(days.value, 30), dry_run: false })), "danger"),
      ])]),
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "State and quota" }), state]),
    ]),
  ]));
  await refresh().catch((error) => state.textContent = error.message);
}

async function wbRenderAnalysis(root) {
  const script = wbInput("scripts/analysis.py");
  const args = wbInput("", "one argument per comma or line");
  const cwd = wbInput(".");
  const python = wbInput(wbState.capabilities?.python || "python");
  const profile = wbEl("input", { type: "checkbox" });
  const trusted = Boolean(wbState.capabilities?.trusted_dev);
  const output = wbEl("pre", { class: "wbOutput", text: "Ready." });
  const sessions = wbEl("div", { class: "wbRows" });
  const load = async () => {
    const payload = await wbApi("/api/workbench/analysis/sessions");
    sessions.replaceChildren(...(payload.sessions || []).map((item) => wbEl("div", { class: "wbRow" }, [
      wbEl("b", { text: `${item.label} · ${item.state}` }), wbEl("div", { class: "wbMuted", text: `${item.session_id} · PID ${item.pid}` }),
      wbEl("div", { class: "wbActions" }, [
        wbButton("Logs", wbHandle(output, async () => (await wbApi(`/api/workbench/analysis/sessions/${item.session_id}/logs`)).content)),
        wbButton("Status", wbHandle(output, () => wbApi(`/api/workbench/analysis/sessions/${item.session_id}`))),
        wbButton("Stop", wbHandle(output, async () => { const r = await wbPost("/api/workbench/analysis/stop", { session_id: item.session_id }); await load(); return r; }), "danger"),
      ]),
    ])));
  };
  root.append(wbEl("div", { class: "wbGrid" }, [
    wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Detached analysis" }), wbField("Python script", script), wbField("Arguments", args), wbField("Working directory", cwd), wbField("Python interpreter", python), wbField("cProfile", profile), wbEl("div", { class: "wbActions" }, [
      (() => { const button = wbButton("Start", wbHandle(output, async () => { const r = await wbPost("/api/workbench/analysis/script", { script: script.value, args: wbSplit(args.value), cwd: cwd.value, python: python.value, profile: profile.checked }); await load(); return r; }), "primary"); button.disabled = !trusted; return button; })(),
      wbButton("Refresh", () => load().catch((e) => output.textContent = e.message)),
    ]), output]),
    wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Sessions" }), sessions]),
  ]));
  if (!trusted) output.textContent = "Starting arbitrary analysis scripts requires RA_TRUSTED_DEV=1. Existing sessions and logs remain readable.";
  await load().catch((error) => output.textContent = error.message);
}

async function wbRenderWorkspaces(root) {
  const name = wbInput("research-project");
  const path = wbInput(wbState.capabilities?.workspace || "");
  const python = wbInput(wbState.capabilities?.python || "python");
  const conda = wbInput(wbState.capabilities?.conda_prefix || "");
  const ssh = wbInput("", "user@server");
  const inspect = wbInput(wbState.capabilities?.python || "python");
  const output = wbEl("pre", { class: "wbOutput", text: "Ready." });
  const list = wbEl("div", { class: "wbRows" });
  const envs = wbEl("pre", { class: "wbOutput", text: "Loading…" });
  const load = async () => {
    const payload = await wbApi("/api/workbench/workspaces");
    list.replaceChildren(...(payload.workspaces || []).map((item) => wbEl("div", { class: "wbRow" }, [wbEl("b", { text: item.name }), wbEl("div", { text: item.path }), wbEl("div", { class: "wbMuted", text: `${item.python}${item.conda_env ? ` · ${item.conda_env}` : ""}${item.ssh_target ? ` · ${item.ssh_target}` : ""}` })])));
  };
  root.append(wbEl("div", { class: "wbGrid" }, [
    wbEl("div", { class: "wbRows" }, [
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Workspace catalog" }), wbField("Name", name), wbField("Path", path), wbField("Python", python), wbField("Conda environment", conda), wbField("SSH target", ssh), wbEl("div", { class: "wbActions" }, [wbButton("Add", wbHandle(output, async () => { const r = await wbPost("/api/workbench/workspaces", { name: name.value, path: path.value, python: python.value || null, conda_env: conda.value || null, ssh_target: ssh.value || null }); await load(); return r; }), "primary"), wbButton("Refresh", () => load())]), output]),
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Saved workspaces" }), list]),
    ]),
    wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Conda and interpreter" }), wbField("Inspect interpreter", inspect), wbButton("Inspect", wbHandle(envs, () => wbPost("/api/workbench/environments/inspect", { python: inspect.value }))), envs]),
  ]));
  await Promise.all([load(), wbApi("/api/workbench/environments").then((value) => envs.textContent = wbPretty(value))]).catch((error) => output.textContent = error.message);
}

async function wbRenderDeveloper(root) {
  const trusted = Boolean(wbState.capabilities?.trusted_dev);
  const output = wbEl("pre", { class: "wbOutput", text: trusted ? "Trusted developer mode is enabled." : "Read-only developer inspection. Set RA_TRUSTED_DEV=1 before `ra ui` to enable writes and tasks." });
  const query = wbInput("", "search text");
  const pattern = wbInput("*.py");
  const branch = wbInput("agent/my-change");
  const commitMessage = wbInput("Update project");
  const paths = wbInput("src/,tests/");
  const tasks = wbEl("div", { class: "wbRows" });
  const readonly = wbEl("div", { class: "wbActions" }, [
    wbButton("Diagnostics", wbHandle(output, () => wbApi("/api/workbench/dev/diagnostics"))),
    wbButton("Git status", wbHandle(output, () => wbApi("/api/workbench/dev/git/status"))),
    wbButton("Git diff", wbHandle(output, () => wbPost("/api/workbench/dev/git/diff", { staged: false, path: null }))),
    wbButton("Git log", wbHandle(output, () => wbApi("/api/workbench/dev/git/log?limit=50"))),
    wbButton("Branches", wbHandle(output, () => wbApi("/api/workbench/dev/git/branches"))),
  ]);
  const writes = wbEl("div", { class: "wbActions" }, [
    wbButton("Create branch", wbHandle(output, () => wbPost("/api/workbench/dev/git/branch", { name: branch.value, start_point: null })), "primary"),
    wbButton("Commit explicit paths", wbHandle(output, () => wbPost("/api/workbench/dev/git/commit", { message: commitMessage.value, paths: wbSplit(paths.value), push: false }))),
    wbButton("Push branch", wbHandle(output, () => wbPost("/api/workbench/dev/git/push", {}))),
  ]);
  for (const button of writes.children) button.disabled = !trusted;
  root.append(wbEl("div", { class: "wbGrid" }, [
    wbEl("div", { class: "wbRows" }, [
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Git and diagnostics" }), readonly, wbField("New branch", branch), wbField("Commit message", commitMessage), wbField("Commit paths", paths), writes]),
      wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Project search" }), wbField("Query", query), wbField("File pattern", pattern), wbButton("Search", wbHandle(output, () => wbPost("/api/workbench/dev/search", { query: query.value, root: ".", pattern: pattern.value || "*", case_sensitive: false, max_results: 1000 }))), output]),
    ]),
    wbEl("div", { class: "wbCard" }, [wbEl("h3", { text: "Saved tasks (.ra/tasks.yaml)" }), tasks]),
  ]));
  try {
    const payload = await wbApi("/api/workbench/dev/tasks");
    tasks.replaceChildren(...(payload.tasks || []).map((task) => {
      const run = wbButton("Run", wbHandle(output, () => wbPost("/api/workbench/dev/tasks/run", { name: task.name })), "primary");
      run.disabled = !trusted;
      return wbEl("div", { class: "wbRow" }, [wbEl("b", { text: task.name }), wbEl("div", { text: task.description || task.script || "" }), run]);
    }));
  } catch (error) { tasks.textContent = error.message; }
}

const wbRenderers = { protocols: wbRenderProtocols, artifacts: wbRenderArtifacts, lifecycle: wbRenderLifecycle, analysis: wbRenderAnalysis, workspaces: wbRenderWorkspaces, developer: wbRenderDeveloper };
async function wbSetTab(dialog, key) {
  wbState.tab = key;
  dialog.querySelectorAll("[data-wb-tab]").forEach((button) => button.classList.toggle("active", button.dataset.wbTab === key));
  const root = dialog.querySelector(".wbMain");
  root.replaceChildren(wbEl("div", { class: "wbMuted", text: "Loading…" }));
  try { root.replaceChildren(); await wbRenderers[key](root); }
  catch (error) { root.replaceChildren(wbEl("pre", { class: "wbOutput", text: error.message })); }
}
function wbDialog() {
  const dialog = wbEl("dialog", { class: "wbDialog", id: "ra-workbench" });
  const tabs = wbEl("div", { class: "wbTabs" });
  const labels = { protocols: "Protocols", artifacts: "Artifacts", lifecycle: "Lifecycle", analysis: "Analysis", workspaces: "Workspaces", developer: "Developer" };
  for (const [key, label] of Object.entries(labels)) tabs.append(wbButton(label, () => wbSetTab(dialog, key)));
  [...tabs.children].forEach((button, index) => button.dataset.wbTab = Object.keys(labels)[index]);
  dialog.append(wbEl("div", { class: "wbHeader" }, [wbEl("div", {}, [wbEl("h2", { text: "Research Workbench" }), wbEl("div", { class: "wbMuted", text: "Protocols, scientific artifacts, lifecycle, analysis, environments and trusted development" })]), wbButton("Close", () => dialog.close())]), tabs, wbEl("div", { class: "wbMain" }));
  document.body.append(dialog);
  return dialog;
}
async function wbMain() {
  if (document.querySelector("#ra-workbench")) return;
  wbInstallCss();
  try { wbState.capabilities = await wbApi("/api/workbench/capabilities"); }
  catch (error) { console.error("Research Workbench unavailable", error); return; }
  const dialog = wbDialog();
  const actions = document.querySelector(".topbar-actions");
  const button = wbEl("button", { class: "button ghost", text: "Workbench", onclick: () => { dialog.showModal(); wbSetTab(dialog, wbState.tab); } });
  if (actions) actions.prepend(button); else document.body.prepend(button);
  wbSetTab(dialog, "protocols");
}
document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", wbMain) : wbMain();
