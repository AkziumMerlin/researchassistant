const rFetch = window.fetch.bind(window);
const rApi = async (path, options = {}) => {
  const response = await rFetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || response.statusText);
  return payload;
};
const rEl = (tag, attributes = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child?.nodeType ? child : document.createTextNode(child));
  return node;
};
const rQ = (selector, root = document) => root.querySelector(selector);
const rPretty = (value) => JSON.stringify(value, null, 2);

function researchCss() {
  if (document.querySelector("#ra-research-style")) return;
  document.head.append(rEl("style", {
    id: "ra-research-style",
    text: `.raResearch{width:min(1320px,97vw);height:min(920px,96vh);background:#111827;color:#e5e7eb;border:1px solid #475569;border-radius:10px}.raResearch::backdrop{background:#000b}.raRH{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #334155}.raRTabs{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;border-bottom:1px solid #334155}.raRB{background:#1e3a5f;color:#fff;border:1px solid #64748b;padding:6px 9px;border-radius:5px;cursor:pointer}.raRB.active{border-color:#60a5fa;background:#1d4ed8}.raRMain{height:calc(100% - 108px);padding:14px;overflow:auto}.raRGrid{display:grid;grid-template-columns:minmax(300px,1fr) minmax(360px,1.25fr);gap:12px}.raRCard{border:1px solid #334155;border-radius:7px;padding:10px;background:#0b1220}.raRField{display:grid;gap:5px;margin-bottom:9px}.raRField input,.raRField textarea,.raRField select{background:#030712;color:#eee;border:1px solid #475569;padding:7px}.raRCode{white-space:pre-wrap;background:#030712;padding:10px;overflow:auto;max-height:620px}.raRError{color:#fca5a5;white-space:pre-wrap}.raRMuted{color:#94a3b8}.raRActions{display:flex;gap:5px;flex-wrap:wrap}.raRTable{width:100%;border-collapse:collapse}.raRTable th,.raRTable td{padding:6px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}@media(max-width:850px){.raRGrid{grid-template-columns:1fr}}`,
  }));
}

const rState = { tab: "hpo" };

function jsonWorkbench(root, title, initial, actions) {
  const editor = rEl("textarea", { rows: "30" });
  editor.value = rPretty(initial);
  const output = rEl("pre", { class: "raRCode", text: "Ready." });
  const buttons = rEl("div", { class: "raRActions" });
  for (const [label, handler] of actions) {
    buttons.append(rEl("button", {
      class: "raRB",
      text: label,
      onclick: async () => {
        try {
          const value = JSON.parse(editor.value);
          output.textContent = rPretty(await handler(value));
        } catch (error) {
          output.textContent = error.message;
        }
      },
    }));
  }
  root.append(rEl("div", { class: "raRGrid" }, [
    rEl("div", { class: "raRCard" }, [
      rEl("h3", { text: title }),
      rEl("label", { class: "raRField" }, ["Specification (JSON)", editor]),
      buttons,
    ]),
    rEl("div", { class: "raRCard" }, [rEl("h3", { text: "Result" }), output]),
  ]));
}

function defaultHpo() {
  return {
    name: "model-search",
    base_config: "configs/experiment.yaml",
    artifact_root: "runs",
    search_space: {
      "components.model.params.width": { type: "categorical", choices: [32, 64, 96] },
      "stages.0.params.lr": { type: "float", low: 0.0001, high: 0.003, log: true },
    },
    objectives: [{ metric: "val/loss", split: "validation", direction: "minimize" }],
    sampler: "tpe",
    max_trials: 50,
    parallelism: 4,
    seed: 0,
    startup_trials: 8,
    good_fraction: 0.25,
    plugins: [],
    launcher_overrides: [],
    config_overrides: [],
    asha: { enabled: true, resource_steps: [25, 50, 100, 200], reduction_factor: 3, grace_step: 25 },
  };
}
function renderHpo(root) {
  jsonWorkbench(root, "Adaptive HPO", defaultHpo(), [
    ["Status", (spec) => rApi("/api/research/hpo/status", { method: "POST", body: rPretty({ spec }) })],
    ["Propose", (spec) => rApi("/api/research/hpo/propose", { method: "POST", body: rPretty({ spec, count: 1, launch: false }) })],
    ["Propose + launch", (spec) => rApi("/api/research/hpo/propose", { method: "POST", body: rPretty({ spec, count: spec.parallelism || 1, launch: true }) })],
    ["Step controller", (spec) => rApi("/api/research/hpo/step", { method: "POST", body: rPretty({ spec }) })],
  ]);
}

function defaultDataset() {
  return {
    name: "benchmark",
    version: "1",
    source: "data/benchmark",
    description: "",
    files: { include: ["**/*"], exclude: [], required_extensions: [], min_files: 1, max_files: null },
    splits: { train: ["train/**"], validation: ["validation/**"], test: ["test/**"] },
    preprocessing: [],
    schema: {},
    metadata: {},
    snapshot: true,
  };
}
async function renderDatasets(root) {
  const top = rEl("div", { class: "raRActions" });
  const refresh = rEl("button", { class: "raRB", text: "Refresh list" });
  const output = rEl("div", { class: "raRCard", text: "Loading…" });
  top.append(refresh);
  root.append(top, output);
  const load = async () => {
    const payload = await rApi("/api/research/datasets?limit=2000");
    const rows = payload.datasets || [];
    const table = rEl("table", { class: "raRTable" });
    table.innerHTML = "<thead><tr><th>Dataset</th><th>Version</th><th>Files</th><th>Snapshot</th><th>Validation</th></tr></thead>";
    const body = rEl("tbody");
    for (const row of rows) {
      const validate = rEl("button", {
        class: "raRB", text: "Validate", onclick: async () => {
          validate.textContent = "…";
          try { validate.textContent = (await rApi("/api/research/datasets/validate", { method: "POST", body: rPretty({ dataset_id: row.dataset_id }) })).valid ? "Valid" : "Invalid"; }
          catch (error) { validate.textContent = error.message; }
        },
      });
      const tr = rEl("tr");
      tr.append(
        rEl("td", {}, [rEl("b", { text: row.name }), rEl("div", { class: "raRMuted", text: row.dataset_id })]),
        rEl("td", { text: row.version }),
        rEl("td", { text: String(row.file_count) }),
        rEl("td", { text: row.snapshot ? "immutable" : "reference" }),
        rEl("td", {}, [validate]),
      );
      body.append(tr);
    }
    table.append(body);
    output.replaceChildren(table);
  };
  refresh.onclick = () => load().catch((error) => { output.textContent = error.message; });
  const register = rEl("div", { class: "raRCard" });
  root.prepend(register);
  jsonWorkbench(register, "Register dataset snapshot", defaultDataset(), [
    ["Register", async (spec) => {
      const result = await rApi("/api/research/datasets/register", { method: "POST", body: rPretty({ spec }) });
      await load();
      return result;
    }],
  ]);
  await load().catch((error) => { output.textContent = error.message; });
}

function defaultSelection() {
  return {
    name: "final-models",
    artifact_root: "runs",
    selection_metric: "val/loss",
    selection_split: "validation",
    target_metrics: ["test/loss"],
    test_splits: ["test", "ood"],
    direction: "minimize",
    checkpoint_alignment: "same_step",
    group_by: ["study_id", "dataset", "model"],
    required_seeds: [0, 1, 2],
    min_seeds: 3,
    allowed_states: ["completed"],
    promote_checkpoints: true,
    strict_test_lock: true,
  };
}
function renderSelection(root) {
  jsonWorkbench(root, "Validation-only selection", defaultSelection(), [
    ["Preview", (spec) => rApi("/api/research/selection/preview", { method: "POST", body: rPretty({ spec, overwrite: false }) })],
    ["Create immutable lock", (spec) => rApi("/api/research/selection/lock", { method: "POST", body: rPretty({ spec, overwrite: false }) })],
  ]);
  const evaluation = rEl("div", { class: "raRCard" });
  const name = rEl("input", { placeholder: "selection name or lock path" });
  const out = rEl("input", { value: "reports/selection" });
  const result = rEl("pre", { class: "raRCode" });
  evaluation.append(
    rEl("h3", { text: "Open test evaluation from lock" }),
    rEl("label", { class: "raRField" }, ["Selection lock", name]),
    rEl("label", { class: "raRField" }, ["Output", out]),
    rEl("button", {
      class: "raRB", text: "Evaluate selected runs", onclick: async () => {
        try { result.textContent = rPretty(await rApi("/api/research/selection/evaluate", { method: "POST", body: rPretty({ name_or_path: name.value, output_path: out.value }) })); }
        catch (error) { result.textContent = error.message; }
      },
    }),
    result,
  );
  root.append(evaluation);
}

function defaultStatistics() {
  return {
    name: "paired-comparison",
    artifact_root: "runs",
    metric: "test/loss",
    split: "test",
    direction: "minimize",
    group_by: "model",
    paired_by: ["seed", "dataset"],
    confidence: 0.95,
    bootstrap_samples: 5000,
    permutation_samples: 20000,
    correction: "holm",
    missing_pair_policy: "drop",
    seed: 0,
    max_runs: 10000,
  };
}
function renderStatistics(root) {
  jsonWorkbench(root, "Statistical analysis", defaultStatistics(), [
    ["Analyze", (spec) => rApi("/api/research/statistics/run", { method: "POST", body: rPretty({ spec }) })],
    ["Build report", (spec) => rApi("/api/research/statistics/run", { method: "POST", body: rPretty({ spec, output_path: `reports/${spec.name}` }) })],
  ]);
}

async function renderJournal(root) {
  const create = rEl("div", { class: "raRCard" });
  const title = rEl("input", { placeholder: "Hypothesis title" });
  const statement = rEl("textarea", { rows: "4", placeholder: "Falsifiable statement" });
  const expected = rEl("textarea", { rows: "3", placeholder: "Expected outcome" });
  const criteria = rEl("textarea", { rows: "3", placeholder: "Decision criteria" });
  const output = rEl("pre", { class: "raRCode" });
  create.append(
    rEl("h3", { text: "New hypothesis" }),
    rEl("label", { class: "raRField" }, ["Title", title]),
    rEl("label", { class: "raRField" }, ["Statement", statement]),
    rEl("label", { class: "raRField" }, ["Expected outcome", expected]),
    rEl("label", { class: "raRField" }, ["Decision criteria", criteria]),
    rEl("button", {
      class: "raRB", text: "Create", onclick: async () => {
        try {
          output.textContent = rPretty(await rApi("/api/research/hypotheses", {
            method: "POST",
            body: rPretty({ title: title.value, statement: statement.value, expected_outcome: expected.value || null, decision_criteria: criteria.value || null, status: "active", tags: [] }),
          }));
          await load();
        } catch (error) { output.textContent = error.message; }
      },
    }),
    output,
  );
  const list = rEl("div", { class: "raRCard", text: "Loading…" });
  root.append(rEl("div", { class: "raRGrid" }, [create, list]));
  const load = async () => {
    const payload = await rApi("/api/research/hypotheses?limit=1000");
    list.replaceChildren(
      rEl("h3", { text: `Hypotheses (${(payload.hypotheses || []).length})` }),
      ...(payload.hypotheses || []).map((item) => rEl("div", { class: "raRCard" }, [
        rEl("b", { text: `${item.title} · ${item.status}` }),
        rEl("div", { text: item.statement }),
        rEl("div", { class: "raRMuted", text: `${item.hypothesis_id} · evidence ${(item.evidence || []).length} · decisions ${(item.decisions || []).length}` }),
        item.conclusion ? rEl("div", { text: item.conclusion }) : rEl("span"),
      ])),
    );
  };
  await load().catch((error) => { list.textContent = error.message; });
}

function defaultPublication() {
  return {
    name: "paper-results",
    title: "Research results",
    authors: [],
    artifact_root: "runs",
    study_ids: [],
    trial_ids: [],
    run_ids: [],
    reports: [],
    asset_statuses: ["selected", "released"],
    include_all_artifacts: false,
    include_checkpoints: true,
    include_environment: true,
    template: "aaai",
    copy_mode: "hardlink",
    dataset_ids: [],
    selection_locks: [],
    statistical_reports: [],
    bibliography: [],
    include_research_log: true,
    strict_consistency: true,
    compile_pdf: false,
    claims: [],
  };
}
function renderPublicationFull(root) {
  jsonWorkbench(root, "Full publication bundle", defaultPublication(), [
    ["Preview", (spec) => rApi("/api/research/publication/preview", { method: "POST", body: rPretty({ spec }) })],
    ["Build", (spec) => rApi("/api/research/publication/build", { method: "POST", body: rPretty({ spec, output_path: `publications/${spec.name}` }) })],
  ]);
}

function setResearchTab(dialog, tab) {
  rState.tab = tab;
  dialog.querySelectorAll("[data-research-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.researchTab === tab);
  });
  const main = rQ("#ra-research-main", dialog);
  main.replaceChildren();
  const renderer = {
    hpo: renderHpo,
    datasets: renderDatasets,
    selection: renderSelection,
    statistics: renderStatistics,
    journal: renderJournal,
    publication: renderPublicationFull,
  }[tab];
  Promise.resolve(renderer(main)).catch((error) => {
    main.replaceChildren(rEl("div", { class: "raRError", text: error.message }));
  });
}

function researchDialog() {
  const dialog = rEl("dialog", { class: "raResearch", id: "ra-research" });
  dialog.innerHTML = `<div class="raRH"><b>End-to-end research</b><button class="raRB" data-research-close>×</button></div><div class="raRTabs"></div><main class="raRMain" id="ra-research-main"></main>`;
  const tabs = rQ(".raRTabs", dialog);
  for (const [key, label] of [["hpo", "Adaptive HPO"], ["datasets", "Datasets"], ["selection", "Selection"], ["statistics", "Statistics"], ["journal", "Hypotheses"], ["publication", "Publication"]]) {
    tabs.append(rEl("button", { class: "raRB", text: label, "data-research-tab": key, onclick: () => setResearchTab(dialog, key) }));
  }
  rQ("[data-research-close]", dialog).onclick = () => dialog.close();
  document.body.append(dialog);
  setResearchTab(dialog, "hpo");
  return dialog;
}

function researchMain() {
  if (document.querySelector("#ra-research")) return;
  researchCss();
  const dialog = researchDialog();
  const actions = document.querySelector(".topbar-actions");
  if (actions) actions.prepend(rEl("button", { class: "button ghost", text: "Research+", onclick: () => { dialog.showModal(); setResearchTab(dialog, rState.tab); } }));
}

document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", researchMain) : researchMain();
