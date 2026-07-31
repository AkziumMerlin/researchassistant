const raPipelineFetch = window.fetch.bind(window);
const pApi = async (path, options = {}) => {
  const response = await raPipelineFetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || response.statusText);
  return payload;
};
const pEl = (tag, attributes = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child?.nodeType ? child : document.createTextNode(child));
  return node;
};
const pQ = (selector, root = document) => root.querySelector(selector);

function pipelineCss() {
  if (document.querySelector("#ra-pipeline-style")) return;
  document.head.append(
    pEl("style", {
      id: "ra-pipeline-style",
      text: `.raPipe{width:min(1250px,96vw);height:min(880px,94vh);background:#111827;color:#e5e7eb;border:1px solid #475569;border-radius:10px}.raPipe::backdrop{background:#000a}.raPipeH{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #334155}.raPipeTabs{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;border-bottom:1px solid #334155}.raPipeB{background:#1e3a5f;color:#fff;border:1px solid #64748b;padding:6px 9px;border-radius:5px;cursor:pointer}.raPipeB.active{border-color:#60a5fa;background:#1d4ed8}.raPipeMain{height:calc(100% - 108px);padding:14px;overflow:auto}.raPipeGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.raPipeCard{border:1px solid #334155;border-radius:7px;padding:10px;background:#0b1220}.raPipeField{display:grid;gap:5px;margin-bottom:9px}.raPipeField input,.raPipeField textarea,.raPipeField select{background:#030712;color:#eee;border:1px solid #475569;padding:7px}.raPipeTable{width:100%;border-collapse:collapse}.raPipeTable th,.raPipeTable td{padding:6px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}.raPipeCode{white-space:pre-wrap;background:#030712;padding:10px;overflow:auto}.raPipeError{color:#fca5a5;white-space:pre-wrap}.raPipeMuted{color:#94a3b8}.raPipeActions{display:flex;gap:5px;flex-wrap:wrap}`,
    }),
  );
}

const pipelineState = { tab: "recovery", jobs: [], assets: [] };

function setPipelineTab(dialog, tab) {
  pipelineState.tab = tab;
  dialog.querySelectorAll("[data-pipe-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.pipeTab === tab);
  });
  const main = pQ("#ra-pipeline-main", dialog);
  main.replaceChildren();
  ({ recovery: renderRecovery, cache: renderCache, assets: renderAssets, diagnostics: renderDiagnostics, publication: renderPublication }[tab])(main);
}

async function renderRecovery(root) {
  root.append(pEl("div", { class: "raPipeMuted", text: "Loading persistent jobs…" }));
  try {
    const payload = await pApi("/api/jobs");
    pipelineState.jobs = payload.jobs || [];
    root.replaceChildren(
      pEl("div", { class: "raPipeGrid" }, pipelineState.jobs.map((job) => {
        const workers = (job.runs || []).filter((run) => run.worker_alive || run.worker_pid).length;
        const adopt = pEl("button", {
          class: "raPipeB",
          text: "Adopt scheduler",
          onclick: async () => {
            adopt.disabled = true;
            try {
              await pApi(`/api/jobs/${encodeURIComponent(job.job_id)}/adopt`, { method: "POST", body: "{}" });
              await renderRecovery(root);
            } catch (error) {
              alert(error.message);
            } finally {
              adopt.disabled = false;
            }
          },
        });
        if (job.scheduler_alive || workers === 0 || ["completed", "failed", "cancelled"].includes(job.state)) adopt.disabled = true;
        return pEl("div", { class: "raPipeCard" }, [
          pEl("b", { text: job.job_id }),
          pEl("div", { text: `${job.state} · scheduler ${job.scheduler_alive ? "alive" : "stopped"}` }),
          pEl("div", { class: "raPipeMuted", text: `${workers} worker(s), ${(job.plan || {}).runs || 0} planned run(s)` }),
          pEl("div", { class: "raPipeActions" }, [adopt]),
        ]);
      })),
    );
  } catch (error) {
    root.replaceChildren(pEl("div", { class: "raPipeError", text: error.message }));
  }
}

async function renderCache(root) {
  const output = pEl("pre", { class: "raPipeCode", text: "Loading…" });
  const keep = pEl("input", { type: "number", min: "0", value: "10000" });
  const prune = pEl("button", {
    class: "raPipeB",
    text: "Prune",
    onclick: async () => {
      try {
        output.textContent = JSON.stringify(await pApi("/api/pipeline/cache/prune", {
          method: "POST",
          body: JSON.stringify({ keep_entries: Number(keep.value) }),
        }), null, 2);
      } catch (error) { output.textContent = error.message; }
    },
  });
  root.append(
    pEl("div", { class: "raPipeCard" }, [
      pEl("label", { class: "raPipeField" }, ["Keep newest entries", keep]),
      prune,
    ]),
    output,
  );
  try { output.textContent = JSON.stringify(await pApi("/api/pipeline/cache"), null, 2); }
  catch (error) { output.textContent = error.message; }
}

function assetTable(root, rows) {
  const table = pEl("table", { class: "raPipeTable" });
  table.innerHTML = "<thead><tr><th>Asset</th><th>Kind</th><th>Status</th><th>Run</th><th>Size</th><th>Actions</th></tr></thead>";
  const body = pEl("tbody");
  for (const asset of rows) {
    const actions = pEl("div", { class: "raPipeActions" });
    for (const [label, action] of [["Select", "select"], ["Release", "release"], [asset.pinned ? "Unpin" : "Pin", asset.pinned ? "unpin" : "pin"], ["Archive", "archive"]]) {
      actions.append(pEl("button", {
        class: "raPipeB",
        text: label,
        onclick: async () => {
          try {
            await pApi("/api/pipeline/assets/action", { method: "POST", body: JSON.stringify({ asset_id: asset.asset_id, action }) });
            await renderAssets(root);
          } catch (error) { alert(error.message); }
        },
      }));
    }
    const row = pEl("tr");
    row.append(
      pEl("td", {}, [pEl("b", { text: asset.name }), pEl("div", { class: "raPipeMuted", text: asset.asset_id })]),
      pEl("td", { text: asset.kind }),
      pEl("td", { text: `${asset.status}${asset.pinned ? " · pinned" : ""}` }),
      pEl("td", { text: asset.run_id || "—" }),
      pEl("td", { text: `${(asset.size / 1048576).toFixed(2)} MiB` }),
      pEl("td", {}, [actions]),
    );
    body.append(row);
  }
  table.append(body);
  return table;
}

async function renderAssets(root) {
  const controls = pEl("div", { class: "raPipeActions" });
  const search = pEl("input", { placeholder: "Search name, path, trial" });
  const refresh = pEl("button", { class: "raPipeB", text: "Refresh registry" });
  const load = pEl("button", { class: "raPipeB", text: "Filter" });
  const output = pEl("div", { class: "raPipeMuted", text: "Loading…" });
  controls.append(search, load, refresh);
  root.replaceChildren(controls, output);
  const reload = async () => {
    const query = new URLSearchParams({ limit: "2000" });
    if (search.value) query.set("search", search.value);
    const payload = await pApi(`/api/pipeline/assets?${query}`);
    pipelineState.assets = payload.assets || [];
    output.replaceChildren(assetTable(root, pipelineState.assets));
  };
  load.onclick = () => reload().catch((error) => { output.textContent = error.message; });
  refresh.onclick = async () => {
    try {
      await pApi("/api/pipeline/assets/refresh", { method: "POST", body: JSON.stringify({ artifact_root: "runs" }) });
      await reload();
    } catch (error) { output.textContent = error.message; }
  };
  try { await reload(); } catch (error) { output.textContent = error.message; }
}

async function renderDiagnostics(root) {
  const output = pEl("div", { class: "raPipeMuted", text: "Loading…" });
  root.append(output);
  try {
    const payload = await pApi("/api/pipeline/diagnostics?artifact_root=runs&limit=2000");
    const policy = pEl("pre", { class: "raPipeCode", text: JSON.stringify(payload.policy, null, 2) });
    const cards = pEl("div", { class: "raPipeGrid" }, (payload.findings || []).map((finding) => pEl("div", { class: "raPipeCard" }, [
      pEl("b", { text: `${finding.code} · ${finding.action}` }),
      pEl("div", { text: finding.message }),
      pEl("div", { class: "raPipeMuted", text: `${finding.run_id} · ${finding.timestamp}` }),
      pEl("pre", { class: "raPipeCode", text: JSON.stringify(finding.observed || {}, null, 2) }),
    ])));
    output.replaceChildren(pEl("h3", { text: "Policy" }), policy, pEl("h3", { text: `Findings (${payload.total || 0})` }), cards);
  } catch (error) { output.textContent = error.message; }
}

function defaultPublicationSpec() {
  return {
    name: "paper-results",
    title: "Research results",
    authors: [],
    artifact_root: "runs",
    study_ids: [], trial_ids: [], run_ids: [], reports: [],
    asset_statuses: ["selected", "released"],
    include_all_artifacts: false,
    include_checkpoints: true,
    include_environment: true,
    template: "generic",
    copy_mode: "hardlink",
  };
}

function renderPublication(root) {
  const spec = pEl("textarea", { rows: "22" });
  spec.value = JSON.stringify(defaultPublicationSpec(), null, 2);
  const outputPath = pEl("input", { value: "publications/paper-results" });
  const result = pEl("pre", { class: "raPipeCode" });
  const request = () => ({ spec: JSON.parse(spec.value), output_path: outputPath.value || null });
  const preview = pEl("button", {
    class: "raPipeB", text: "Preview", onclick: async () => {
      try { result.textContent = JSON.stringify(await pApi("/api/pipeline/publication/preview", { method: "POST", body: JSON.stringify(request()) }), null, 2); }
      catch (error) { result.textContent = error.message; }
    },
  });
  const build = pEl("button", {
    class: "raPipeB", text: "Build bundle", onclick: async () => {
      try { result.textContent = JSON.stringify(await pApi("/api/pipeline/publication/build", { method: "POST", body: JSON.stringify(request()) }), null, 2); }
      catch (error) { result.textContent = error.message; }
    },
  });
  root.append(
    pEl("label", { class: "raPipeField" }, ["Publication spec (JSON)", spec]),
    pEl("label", { class: "raPipeField" }, ["Output path", outputPath]),
    pEl("div", { class: "raPipeActions" }, [preview, build]),
    result,
  );
}

function pipelineDialog() {
  const dialog = pEl("dialog", { class: "raPipe", id: "ra-pipeline" });
  dialog.innerHTML = `<div class="raPipeH"><b>Research pipeline</b><button class="raPipeB" data-pipe-close>×</button></div><div class="raPipeTabs"></div><main class="raPipeMain" id="ra-pipeline-main"></main>`;
  const tabs = pQ(".raPipeTabs", dialog);
  for (const [key, label] of [["recovery", "Recovery"], ["cache", "Stage cache"], ["assets", "Assets"], ["diagnostics", "Diagnostics"], ["publication", "Publication"]]) {
    tabs.append(pEl("button", { class: "raPipeB", text: label, "data-pipe-tab": key, onclick: () => setPipelineTab(dialog, key) }));
  }
  pQ("[data-pipe-close]", dialog).onclick = () => dialog.close();
  document.body.append(dialog);
  setPipelineTab(dialog, "recovery");
  return dialog;
}

function pipelineMain() {
  if (document.querySelector("#ra-pipeline")) return;
  pipelineCss();
  const dialog = pipelineDialog();
  const actions = document.querySelector(".topbar-actions");
  if (actions) actions.prepend(pEl("button", { class: "button ghost", text: "Pipeline+", onclick: () => { dialog.showModal(); setPipelineTab(dialog, pipelineState.tab); } }));
}

document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", pipelineMain) : pipelineMain();
