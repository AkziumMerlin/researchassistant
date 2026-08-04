const RESEARCH_WORKSPACE_MARK = "researchAssistantWorkspaceV2";

const rwState = {
  tab: "runs",
  artifactRoot: "runs",
  runs: [],
  selectedRuns: new Set(),
  artifacts: [],
  selectedArtifacts: new Set(),
  assistantPlan: null,
};

async function rwApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function rwPost(path, value = {}) {
  return rwApi(path, { method: "POST", body: JSON.stringify(value) });
}

function rwNode(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
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

function rwInput(value = "", placeholder = "") {
  return rwNode("input", { value, placeholder });
}

function rwButton(text, handler, className = "") {
  return rwNode("button", {
    type: "button",
    class: `rwButton ${className}`,
    text,
    onclick: handler,
  });
}

function rwField(label, control) {
  return rwNode("label", { class: "rwField" }, [rwNode("span", { text: label }), control]);
}

function rwPretty(value) {
  return JSON.stringify(value, null, 2);
}

function rwSplit(value) {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function installResearchWorkspace() {
  if (document.getElementById("ra-research-workspace")) return;
  installResearchWorkspaceStyles();
  const dialog = buildResearchWorkspaceDialog();
  document.body.append(dialog);
  const actions = document.querySelector(".topbar-actions");
  const button = rwButton("Research", () => {
    dialog.showModal();
    setResearchWorkspaceTab(dialog, rwState.tab);
  });
  button.id = "ra-research-workspace-button";
  actions?.prepend(button);
  globalThis.__RA_LAYOUT__?.registerDialog("research-workspace", dialog, {
    width: "min(1560px,98vw)",
    height: "min(940px,96vh)",
  });
}

function buildResearchWorkspaceDialog() {
  const dialog = rwNode("dialog", {
    id: "ra-research-workspace",
    class: "rwDialog",
  });
  const header = rwNode("div", { class: "rwHeader" }, [
    rwNode("div", {}, [
      rwNode("span", {
        class: "rwEyebrow",
        text: "STUDIES · RUNS · ARTIFACTS · ANALYSIS",
      }),
      rwNode("h2", { text: "Research workspace" }),
    ]),
    rwButton("×", () => dialog.close(), "rwClose"),
  ]);
  const tabs = rwNode("div", { class: "rwTabs" });
  const labels = {
    runs: "Runs",
    artifacts: "Artifacts",
    notebooks: "Notebook context",
    execution: "Execution",
    capabilities: "Capabilities",
    plugins: "Plugins",
    assistant: "Assistant",
  };
  for (const [key, label] of Object.entries(labels)) {
    const button = rwButton(label, () => setResearchWorkspaceTab(dialog, key));
    button.dataset.rwTab = key;
    tabs.append(button);
  }
  dialog.append(header, tabs, rwNode("div", { class: "rwMain" }));
  return dialog;
}

async function setResearchWorkspaceTab(dialog, key) {
  rwState.tab = key;
  dialog.querySelectorAll("[data-rw-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.rwTab === key);
  });
  const root = dialog.querySelector(".rwMain");
  root.replaceChildren(rwNode("div", { class: "rwMuted", text: "Loading…" }));
  try {
    root.replaceChildren();
    await {
      runs: renderRuns,
      artifacts: renderArtifacts,
      notebooks: renderNotebookContexts,
      execution: renderExecution,
      capabilities: renderCapabilities,
      plugins: renderPlugins,
      assistant: renderAssistant,
    }[key](root);
  } catch (error) {
    root.replaceChildren(
      rwNode("pre", { class: "rwOutput rwError", text: error.message }),
    );
  }
}

async function renderRuns(root) {
  const artifactRoot = rwInput(rwState.artifactRoot, "runs");
  const search = rwInput("", "study, trial, run, model or dataset");
  const metric = rwInput("", "optional metric name");
  const stage = rwInput("", "optional stage");
  const groupBy = rwInput("study_id,trial_id", "study_id,trial_id,model,dataset");
  const list = rwNode("div", { class: "rwRunList" });
  const summary = rwNode("div", { class: "rwSummary", text: "Not loaded" });
  const output = rwNode("pre", {
    class: "rwOutput",
    text: "Select runs from any studies, then aggregate them explicitly.",
  });

  const load = async () => {
    rwState.artifactRoot = artifactRoot.value.trim() || "runs";
    const params = new URLSearchParams({
      artifact_root: rwState.artifactRoot,
      limit: "10000",
    });
    if (search.value.trim()) params.set("search", search.value.trim());
    const payload = await rwApi(`/api/workspace/runs?${params}`);
    rwState.runs = payload.runs || [];
    const available = new Set(rwState.runs.map((row) => row.run_id));
    rwState.selectedRuns = new Set(
      [...rwState.selectedRuns].filter((id) => available.has(id)),
    );
    summary.textContent = `${payload.total} run(s) · ${payload.studies.length} study/studies · ${rwState.selectedRuns.size} selected`;
    renderRunRows(list, output);
  };

  const aggregate = async () => {
    if (!rwState.selectedRuns.size) throw new Error("Select at least one run.");
    output.textContent = "Aggregating…";
    output.textContent = rwPretty(
      await rwPost("/api/workspace/runs/aggregate", {
        artifact_root: rwState.artifactRoot,
        run_ids: [...rwState.selectedRuns],
        metric: metric.value.trim() || null,
        stage: stage.value.trim() || null,
        group_by: rwSplit(groupBy.value),
      }),
    );
  };

  const controls = rwNode("div", { class: "rwToolbar" }, [
    rwField("Artifact root", artifactRoot),
    rwField("Search", search),
    rwButton(
      "Refresh",
      () => load().catch((error) => { output.textContent = error.message; }),
      "primary",
    ),
    rwButton("Clear selection", () => {
      rwState.selectedRuns.clear();
      renderRunRows(list, output);
      summary.textContent = `${rwState.runs.length} run(s) · 0 selected`;
    }),
  ]);
  root.append(
    controls,
    summary,
    rwNode("div", { class: "rwSplit" }, [
      rwNode("section", { class: "rwCard rwListCard" }, [list]),
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Cross-run aggregation" }),
        rwNode("p", {
          class: "rwMuted",
          text: "Selections may contain runs from different studies and trials. Only explicit run IDs are aggregated.",
        }),
        rwField("Metric", metric),
        rwField("Stage", stage),
        rwField("Group by", groupBy),
        rwButton(
          "Aggregate selected runs",
          () => aggregate().catch((error) => { output.textContent = error.message; }),
          "primary",
        ),
        output,
      ]),
    ]),
  );
  await load();
}

function renderRunRows(host, output) {
  const fragment = document.createDocumentFragment();
  for (const row of rwState.runs.slice(0, 10000)) {
    const checkbox = rwNode("input", { type: "checkbox" });
    checkbox.checked = rwState.selectedRuns.has(row.run_id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) rwState.selectedRuns.add(row.run_id);
      else rwState.selectedRuns.delete(row.run_id);
    });
    const inspect = rwButton("Inspect", async () => {
      output.textContent = rwPretty(
        await rwApi(
          `/api/workspace/runs/${encodeURIComponent(row.run_id)}?artifact_root=${encodeURIComponent(rwState.artifactRoot)}`,
        ),
      );
    });
    fragment.append(
      rwNode("div", { class: "rwRunRow" }, [
        checkbox,
        rwNode("div", { class: "rwRunIdentity" }, [
          rwNode("strong", { text: `${row.study_id} / ${row.run_id}` }),
          rwNode("span", {
            text: `${row.trial_id} · seed ${row.seed ?? "—"} · ${row.model || "model?"} · ${row.dataset || "data?"}`,
          }),
        ]),
        rwNode("span", { class: `rwState ${row.state}`, text: row.state }),
        inspect,
      ]),
    );
  }
  host.replaceChildren(fragment);
}

async function renderArtifacts(root) {
  const search = rwInput("", "name, path, kind, run or sample");
  const kind = rwInput("", "kind");
  const list = rwNode("div", { class: "rwArtifactList" });
  const output = rwNode("pre", {
    class: "rwOutput",
    text: "Select one artifact for lineage or two for numerical comparison.",
  });
  const selectionLabel = rwNode("div", { class: "rwSummary" });
  const refreshSelection = () => {
    selectionLabel.textContent = `${rwState.selectedArtifacts.size} artifact(s) selected`;
  };
  const load = async () => {
    const params = new URLSearchParams({ limit: "5000" });
    if (search.value.trim()) params.set("search", search.value.trim());
    if (kind.value.trim()) params.set("kind", kind.value.trim());
    const payload = await rwApi(`/api/workbench/artifacts?${params}`);
    rwState.artifacts = payload.artifacts || [];
    const fragment = document.createDocumentFragment();
    for (const item of rwState.artifacts) {
      const checkbox = rwNode("input", { type: "checkbox" });
      checkbox.checked = rwState.selectedArtifacts.has(item.artifact_id);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked && rwState.selectedArtifacts.size >= 2) {
          checkbox.checked = false;
          return;
        }
        if (checkbox.checked) rwState.selectedArtifacts.add(item.artifact_id);
        else rwState.selectedArtifacts.delete(item.artifact_id);
        refreshSelection();
      });
      fragment.append(
        rwNode("div", { class: "rwArtifactRow" }, [
          checkbox,
          rwNode("div", {}, [
            rwNode("strong", { text: item.name }),
            rwNode("div", { class: "rwMuted", text: `${item.kind} · ${item.path}` }),
            rwNode("div", {
              class: "rwTiny",
              text: `${item.run_id || "no run"} · ${item.sample_id || "no sample"} · ${formatArtifactShape(item.description)}`,
            }),
          ]),
          rwButton("Lineage", async () => {
            output.textContent = rwPretty(
              await rwApi(
                `/api/workspace/artifacts/${item.artifact_id}/lineage?artifact_root=${encodeURIComponent(rwState.artifactRoot)}`,
              ),
            );
          }),
        ]),
      );
    }
    list.replaceChildren(fragment);
    refreshSelection();
  };
  const compare = async () => {
    const ids = [...rwState.selectedArtifacts];
    if (ids.length !== 2) throw new Error("Select exactly two artifacts.");
    output.textContent = rwPretty(
      await rwPost("/api/workbench/artifacts/compare", {
        left_id: ids[0],
        right_id: ids[1],
        key: null,
      }),
    );
  };
  root.append(
    rwNode("div", { class: "rwToolbar" }, [
      rwField("Search", search),
      rwField("Kind", kind),
      rwButton(
        "Refresh",
        () => load().catch((error) => { output.textContent = error.message; }),
        "primary",
      ),
      rwButton("Discover runs/reports", async () => {
        await rwPost("/api/workbench/artifacts/discover", {
          roots: ["runs", "reports"],
          limit: 10000,
        });
        await load();
      }),
      rwButton("Compare selected", () => {
        compare().catch((error) => { output.textContent = error.message; });
      }),
    ]),
    selectionLabel,
    rwNode("div", { class: "rwSplit" }, [
      rwNode("section", { class: "rwCard rwListCard" }, [list]),
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Artifact detail" }),
        output,
      ]),
    ]),
  );
  await load();
}

function formatArtifactShape(description = {}) {
  if (description.shape) return `shape ${JSON.stringify(description.shape)}`;
  return description.format || "file";
}

async function renderNotebookContexts(root) {
  const label = rwInput("selected-run-analysis");
  const path = rwInput("notebooks/selected-run-analysis.ipynb");
  const kernel = rwInput("python3");
  const output = rwNode("pre", {
    class: "rwOutput",
    text: "A context records explicit run and artifact IDs and embeds them into a new notebook.",
  });
  const contexts = rwNode("div", { class: "rwRows" });
  const load = async () => {
    const payload = await rwApi("/api/workspace/notebook-contexts");
    contexts.replaceChildren(
      ...(payload.contexts || []).map((item) =>
        rwNode("div", { class: "rwContextRow" }, [
          rwNode("strong", { text: item.label }),
          rwNode("span", {
            class: "rwMuted",
            text: `${item.run_ids.length} runs · ${item.artifact_ids.length} artifacts`,
          }),
          item.notebook_path
            ? rwButton("Open", () => openNotebook(item.notebook_path))
            : rwNode("span"),
        ]),
      ),
    );
  };
  const create = async () => {
    const payload = await rwPost("/api/workspace/notebook-contexts", {
      artifact_root: rwState.artifactRoot,
      run_ids: [...rwState.selectedRuns],
      artifact_ids: [...rwState.selectedArtifacts],
      label: label.value.trim() || null,
      notebook_path: path.value.trim() || null,
      kernel_name: kernel.value.trim() || "python3",
    });
    output.textContent = rwPretty(payload);
    await load();
    if (payload.notebook_path) openNotebook(payload.notebook_path);
  };
  root.append(
    rwNode("div", { class: "rwSplit" }, [
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Create contextual notebook" }),
        rwNode("p", {
          class: "rwMuted",
          text: `${rwState.selectedRuns.size} run(s) and ${rwState.selectedArtifacts.size} artifact(s) currently selected.`,
        }),
        rwField("Label", label),
        rwField("Notebook path", path),
        rwField("Kernel", kernel),
        rwButton(
          "Create and open",
          () => create().catch((error) => { output.textContent = error.message; }),
          "primary",
        ),
        output,
      ]),
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Saved contexts" }),
        contexts,
      ]),
    ]),
  );
  await load();
}

function openNotebook(path) {
  if (globalThis.__RA_NOTEBOOKS__?.open) globalThis.__RA_NOTEBOOKS__.open(path);
  else {
    globalThis.dispatchEvent(
      new CustomEvent("ra-open-notebook", { detail: { path } }),
    );
  }
}

async function renderExecution(root) {
  const list = rwNode("div", { class: "rwRows" });
  const output = rwNode("pre", {
    class: "rwOutput",
    text: "Durable controls operate on persisted launch requests and worker process groups.",
  });
  const load = async () => {
    const payload = await rwApi("/api/launches");
    list.replaceChildren(
      ...(payload.launches || []).map((item) => {
        const actions = rwNode("div", { class: "rwActions" });
        if (item.recoverable || item.state === "orphaned") {
          actions.append(
            rwButton(
              "Adopt",
              () => launchAction(item.launch_id, "adopt", output, load),
              "primary",
            ),
          );
        }
        if (["failed", "cancelled", "orphaned"].includes(item.state)) {
          actions.append(
            rwButton("Retry", () =>
              launchAction(item.launch_id, "retry", output, load)),
          );
        }
        if (
          item.cancellable ||
          ["queued", "running", "adopting", "orphaned"].includes(item.state)
        ) {
          actions.append(
            rwButton(
              "Cancel",
              () => launchAction(item.launch_id, "cancel", output, load),
              "danger",
            ),
          );
        }
        return rwNode("div", { class: "rwLaunchRow" }, [
          rwNode("div", {}, [
            rwNode("strong", { text: item.launch_id }),
            rwNode("div", {
              class: "rwMuted",
              text: `${item.config_path} · ${item.artifact_root}`,
            }),
          ]),
          rwNode("span", { class: `rwState ${item.state}`, text: item.state }),
          rwNode("span", {
            class: "rwTiny",
            text:
              item.heartbeat_age_seconds == null
                ? "no heartbeat"
                : `heartbeat ${item.heartbeat_age_seconds.toFixed(1)}s ago`,
          }),
          actions,
        ]);
      }),
    );
  };
  root.append(
    rwNode("div", { class: "rwToolbar" }, [
      rwButton(
        "Refresh",
        () => load().catch((error) => { output.textContent = error.message; }),
        "primary",
      ),
      rwButton("Reconcile persisted state", async () => {
        output.textContent = rwPretty(
          await rwPost("/api/workspace/launches/reconcile"),
        );
        await load();
      }),
    ]),
    rwNode("div", { class: "rwSplit" }, [
      rwNode("section", { class: "rwCard rwListCard" }, [list]),
      rwNode("section", { class: "rwCard" }, [output]),
    ]),
  );
  await load();
}

async function launchAction(launchId, action, output, refresh) {
  if (action === "cancel" && !window.confirm(`Cancel launch ${launchId}?`)) return;
  output.textContent = "Working…";
  const body = action === "cancel" ? { force: false } : {};
  output.textContent = rwPretty(
    await rwPost(
      `/api/workspace/launches/${encodeURIComponent(launchId)}/${action}`,
      body,
    ),
  );
  await refresh();
}

async function renderCapabilities(root) {
  const payload = await rwApi("/api/workspace/capabilities");
  const table = rwNode("table", { class: "rwTable" });
  table.innerHTML = "<thead><tr><th>Capability</th><th>Domain</th><th>CLI</th><th>API</th><th>UI</th><th>Stability</th></tr></thead>";
  const body = rwNode("tbody");
  for (const item of payload.capabilities) {
    body.append(
      rwNode("tr", {}, [
        rwNode("td", {}, [
          rwNode("strong", { text: item.title }),
          rwNode("div", { class: "rwTiny", text: item.capability_id }),
        ]),
        rwNode("td", { text: item.domain }),
        rwNode("td", { text: item.cli }),
        rwNode("td", { text: item.api }),
        rwNode("td", { text: item.ui }),
        rwNode("td", { text: item.stability }),
      ]),
    );
  }
  table.append(body);
  root.append(
    rwNode("div", {
      class: "rwSummary",
      text: `${payload.capabilities.length} declared capabilities · parity complete: ${payload.complete}`,
    }),
    rwNode("section", { class: "rwCard" }, [table]),
  );
}

async function renderPlugins(root) {
  const payload = await rwApi("/api/workspace/plugins");
  const diagnostics = rwNode(
    "div",
    { class: "rwRows" },
    (payload.diagnostics || []).map((item) =>
      rwNode("div", { class: "rwPluginRow" }, [
        rwNode("strong", { text: item.provider }),
        rwNode("span", { class: `rwState ${item.state}`, text: item.state }),
        rwNode("div", { class: "rwMuted", text: item.message }),
        item.contract
          ? rwNode("pre", { class: "rwMiniOutput", text: rwPretty(item.contract) })
          : rwNode("span"),
      ]),
    ),
  );
  const migrations = rwNode("pre", {
    class: "rwOutput",
    text: rwPretty(payload.migrations),
  });
  root.append(
    rwNode("div", { class: "rwSplit" }, [
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Plugin compatibility" }),
        diagnostics,
      ]),
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Schema migrations" }),
        migrations,
      ]),
    ]),
  );
}

async function renderAssistant(root) {
  const goal = rwNode("textarea", {
    rows: "8",
    placeholder:
      "Describe the research question or operation. The assistant can only emit typed, validated actions.",
  });
  const allowWrites = rwNode("input", { type: "checkbox" });
  const planOutput = rwNode("pre", { class: "rwOutput", text: "No plan yet." });
  const resultOutput = rwNode("pre", {
    class: "rwOutput",
    text: "Plan results will appear here.",
  });
  const request = () => ({
    goal: goal.value,
    artifact_root: rwState.artifactRoot,
    run_ids: [...rwState.selectedRuns],
    artifact_ids: [...rwState.selectedArtifacts],
    allow_writes: allowWrites.checked,
  });
  const plan = async () => {
    rwState.assistantPlan = await rwPost(
      "/api/workspace/assistant/plan",
      request(),
    );
    planOutput.textContent = rwPretty(rwState.assistantPlan);
  };
  const apply = async () => {
    if (!rwState.assistantPlan) throw new Error("Create and review a plan first.");
    resultOutput.textContent = rwPretty(
      await rwPost("/api/workspace/assistant/apply", {
        request: request(),
        plan: rwState.assistantPlan,
      }),
    );
  };
  root.append(
    rwNode("div", { class: "rwSplit" }, [
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Typed research planner" }),
        rwNode("p", {
          class: "rwMuted",
          text: "The fallback planner does not launch experiments or execute shell commands. Project plugins may provide a model-backed planner with the same schema.",
        }),
        rwField("Goal", goal),
        rwNode("label", { class: "rwCheck" }, [
          allowWrites,
          rwNode("span", { text: "Allow explicitly declared workspace writes" }),
        ]),
        rwNode("div", { class: "rwActions" }, [
          rwButton(
            "Create plan",
            () => plan().catch((error) => { planOutput.textContent = error.message; }),
            "primary",
          ),
          rwButton("Apply reviewed plan", () => {
            apply().catch((error) => { resultOutput.textContent = error.message; });
          }),
        ]),
        planOutput,
      ]),
      rwNode("section", { class: "rwCard" }, [
        rwNode("h3", { text: "Execution results" }),
        resultOutput,
      ]),
    ]),
  );
}

function installResearchWorkspaceStyles() {
  if (document.getElementById("ra-research-workspace-styles")) return;
  const style = document.createElement("style");
  style.id = "ra-research-workspace-styles";
  style.textContent = `
    .rwDialog{width:min(1560px,98vw);height:min(940px,96vh);padding:0;overflow:hidden;background:#09120f;color:#dce9e3;border:1px solid #40584d;border-radius:9px}
    .rwDialog::backdrop{background:#000c}.rwHeader{display:flex;justify-content:space-between;align-items:center;padding:11px 15px;border-bottom:1px solid #30443b}.rwHeader h2{margin:2px 0 0}.rwEyebrow{font-size:10px;letter-spacing:.09em;color:#82998e}
    .rwTabs{display:flex;gap:5px;flex-wrap:wrap;padding:8px 13px;border-bottom:1px solid #30443b}.rwTabs .active{background:#245c45;border-color:#79cda7}.rwMain{height:calc(100% - 112px);min-height:0;overflow:auto;padding:12px}
    .rwToolbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:7px;align-items:end;margin-bottom:9px}.rwField{display:grid;gap:4px;font-size:11px;color:#a9bbb2}.rwField input,.rwField textarea{min-width:0;background:#050c09;color:inherit;border:1px solid #40584d;border-radius:5px;padding:7px}
    .rwButton{border:1px solid #436052;border-radius:5px;background:#14231d;color:inherit;padding:6px 9px;cursor:pointer}.rwButton.primary{background:#235d45;border-color:#6ebc97}.rwButton.danger{background:#602626;border-color:#b76767}.rwClose{font-size:20px;padding:2px 9px}
    .rwSplit{display:grid;grid-template-columns:minmax(420px,1.15fr) minmax(360px,.85fr);gap:10px;min-height:0}.rwCard{min-width:0;background:#0d1914;border:1px solid #30443b;border-radius:7px;padding:10px}.rwListCard{padding:0;overflow:hidden}.rwRunList,.rwArtifactList{max-height:690px;overflow:auto;scrollbar-gutter:stable}.rwRows{display:grid;gap:6px;max-height:680px;overflow:auto}
    .rwRunRow{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;gap:8px;align-items:center;padding:7px 9px;border-bottom:1px solid #26382f}.rwRunIdentity{display:grid;gap:2px}.rwRunIdentity span,.rwTiny{font-size:10px;color:#80958a}.rwArtifactRow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:start;padding:8px;border-bottom:1px solid #26382f}
    .rwOutput{white-space:pre-wrap;overflow:auto;max-height:610px;background:#030806;border:1px solid #26382f;border-radius:5px;padding:8px;font:11px/1.4 ui-monospace,monospace}.rwMiniOutput{white-space:pre-wrap;max-height:150px;overflow:auto;font-size:10px}.rwError{color:#ff9b9b}.rwMuted{color:#879b91;font-size:11px}.rwSummary{padding:7px 9px;margin-bottom:8px;background:#0d1914;border:1px solid #30443b;border-radius:6px;font-size:11px}
    .rwState{display:inline-block;padding:2px 6px;border-radius:999px;background:#26382f;font-size:10px}.rwState.completed,.rwState.compatible{background:#1e6043}.rwState.running,.rwState.adopting{background:#315a7d}.rwState.failed,.rwState.incompatible{background:#743535}.rwState.orphaned,.rwState.legacy{background:#765d28}.rwActions{display:flex;gap:5px;flex-wrap:wrap}.rwLaunchRow,.rwContextRow,.rwPluginRow{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center;border:1px solid #30443b;border-radius:6px;padding:8px}
    .rwTable{width:100%;border-collapse:collapse;font-size:11px}.rwTable th,.rwTable td{padding:7px;border-bottom:1px solid #30443b;text-align:left}.rwCheck{display:flex;gap:7px;align-items:center;margin:8px 0;font-size:11px}
    @media(max-width:980px){.rwSplit{grid-template-columns:1fr}.rwRunList,.rwArtifactList{max-height:420px}.rwDialog{width:99vw;height:98vh}}
  `;
  document.head.append(style);
}

if (!globalThis[RESEARCH_WORKSPACE_MARK]) {
  globalThis[RESEARCH_WORKSPACE_MARK] = true;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installResearchWorkspace, { once: true });
  } else {
    installResearchWorkspace();
  }
}
