import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import "monaco-editor/esm/vs/basic-languages/css/css.contribution.js";
import "monaco-editor/esm/vs/basic-languages/html/html.contribution.js";
import "monaco-editor/esm/vs/basic-languages/ini/ini.contribution.js";
import "monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution.js";
import "monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution.js";
import "monaco-editor/esm/vs/basic-languages/python/python.contribution.js";
import "monaco-editor/esm/vs/basic-languages/shell/shell.contribution.js";
import "monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution.js";
import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution.js";
import "monaco-editor/esm/vs/editor/browser/coreCommands.js";
import "monaco-editor/esm/vs/editor/contrib/bracketMatching/browser/bracketMatching.js";
import "monaco-editor/esm/vs/editor/contrib/clipboard/browser/clipboard.js";
import "monaco-editor/esm/vs/editor/contrib/comment/browser/comment.js";
import "monaco-editor/esm/vs/editor/contrib/contextmenu/browser/contextmenu.js";
import "monaco-editor/esm/vs/editor/contrib/find/browser/findController.js";
import "monaco-editor/esm/vs/editor/contrib/folding/browser/folding.js";
import "monaco-editor/esm/vs/editor/contrib/fontZoom/browser/fontZoom.js";
import "monaco-editor/esm/vs/editor/contrib/indentation/browser/indentation.js";
import "monaco-editor/esm/vs/editor/contrib/linesOperations/browser/linesOperations.js";
import "monaco-editor/esm/vs/editor/contrib/multicursor/browser/multicursor.js";
import "monaco-editor/esm/vs/editor/contrib/wordOperations/browser/wordOperations.js";
import "monaco-editor/esm/vs/base/browser/ui/codicons/codicon/codicon.css";
import "./styles.css";

self.MonacoEnvironment = {
  getWorker() {
    return new EditorWorker();
  },
};

const state = {
  bootstrap: null,
  editor: null,
  activePath: null,
  buffers: new Map(),
  files: [],
  stageCounter: 0,
  analyticsCatalog: null,
  loadedChartSpec: null,
  loadedTableSpec: null,
  launches: [],
  selectedLaunchId: null,
  selectedRunId: null,
  launchPollTimer: null,
  launchRefreshPending: false,
  checkpoints: [],
  selectedCheckpointPath: null,
  currentTableLatex: "",
  currentEvaluationLatex: "",
};

const elements = Object.fromEntries(
  [
    "workspace-name",
    "file-count",
    "file-filter",
    "file-tree",
    "component-count",
    "component-filter",
    "registry-list",
    "tabs",
    "empty-state",
    "editor",
    "output-panel",
    "output-title",
    "output-content",
    "clear-output",
    "new-file-button",
    "new-config-button",
    "experiments-button",
    "checkpoints-button",
    "analytics-button",
    "project-button",
    "empty-create-button",
    "validate-button",
    "save-button",
    "active-language",
    "cursor-position",
    "save-status",
    "config-dialog",
    "config-form",
    "close-config-dialog",
    "cancel-config-button",
    "creator-path",
    "creator-name",
    "creator-seeds",
    "creator-description",
    "creator-tags",
    "creator-components",
    "creator-stages",
    "creator-accelerator",
    "creator-devices",
    "creator-memory",
    "creator-artifacts",
    "creator-error",
    "add-stage-button",
    "inspect-dialog",
    "close-inspect-dialog",
    "inspect-path",
    "inspect-overrides",
    "inspect-manifests",
    "run-inspection",
    "inspect-rendered",
    "inspect-plan",
    "inspect-error",
    "experiments-dialog",
    "close-experiments-dialog",
    "remote-session-note",
    "launch-form",
    "launch-config",
    "launch-policy",
    "launch-overrides",
    "launch-policy-overrides",
    "launch-artifacts",
    "launch-resume",
    "launch-plan-preview",
    "launch-error",
    "launch-submit",
    "refresh-launches",
    "launch-list",
    "launch-detail",
    "checkpoints-dialog",
    "close-checkpoints-dialog",
    "checkpoint-root",
    "refresh-checkpoints",
    "checkpoint-summary",
    "checkpoint-list",
    "inference-form",
    "inference-checkpoint",
    "checkpoint-detail",
    "inference-config",
    "inference-splits",
    "inference-device",
    "inference-artifacts",
    "inference-predict",
    "inference-overrides",
    "inference-policy",
    "inference-policy-overrides",
    "inference-preview",
    "checkpoint-error",
    "preview-inference",
    "start-inference",
    "analytics-dialog",
    "close-analytics-dialog",
    "analytics-root",
    "refresh-analytics",
    "rebuild-analytics",
    "analytics-summary",
    "analytics-error",
    "analytics-overview-tab",
    "analytics-evaluation-tab",
    "analytics-builders-tab",
    "analytics-overview-panel",
    "analytics-evaluation-panel",
    "analytics-builders-panel",
    "active-filter-count",
    "filter-studies",
    "filter-trials",
    "filter-models",
    "filter-datasets",
    "filter-splits",
    "filter-states",
    "clear-analytics-filters",
    "overview-stage",
    "overview-metric",
    "overview-trials",
    "overview-limit",
    "refresh-overview",
    "run-catalog-summary",
    "overview-runs-count",
    "overview-runs",
    "overview-summary",
    "overview-resources",
    "evaluation-selection-metric",
    "evaluation-target-metric",
    "evaluation-stage",
    "evaluation-selection-split",
    "evaluation-target-split",
    "evaluation-direction",
    "evaluation-alignment",
    "evaluation-group-primary",
    "evaluation-group-secondary",
    "evaluation-max-runs",
    "evaluation-precision",
    "evaluation-table-direction",
    "evaluation-name",
    "evaluation-label",
    "evaluation-caption",
    "evaluation-output",
    "run-evaluation",
    "copy-evaluation-latex",
    "export-evaluation",
    "evaluation-selected-count",
    "evaluation-eligible-count",
    "evaluation-excluded-count",
    "evaluation-group-count",
    "evaluation-provenance",
    "evaluation-groups",
    "evaluation-runs",
    "evaluation-latex",
    "report-spec-path",
    "report-spec-kind",
    "load-report-spec",
    "chart-name",
    "chart-metric",
    "chart-stage",
    "chart-kind",
    "chart-type",
    "chart-group",
    "chart-aggregate",
    "chart-uncertainty",
    "chart-scale",
    "chart-points",
    "chart-series",
    "chart-title",
    "chart-formats",
    "chart-output",
    "preview-chart",
    "export-chart",
    "chart-preview",
    "table-name",
    "table-metric",
    "table-stage",
    "table-row",
    "table-column",
    "table-aggregate",
    "table-direction",
    "table-precision",
    "table-rows",
    "table-columns",
    "table-label",
    "table-caption",
    "table-output",
    "preview-table",
    "copy-table-latex",
    "export-table",
    "table-visual-preview",
    "table-preview",
    "project-dialog",
    "close-project-dialog",
    "project-diagnostics",
    "initialize-project",
    "project-result",
    "project-error",
  ].map((id) => [id, document.getElementById(id)]),
);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const payload = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) {
    const error = new Error(payload.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function languageFor(path) {
  const lower = path.toLowerCase();
  const filename = lower.split("/").at(-1);
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.endsWith(".sh") || filename === "dockerfile") return "shell";
  if (lower.endsWith(".html")) return "html";
  if (lower.endsWith(".css")) return "css";
  if (lower.endsWith(".js") || lower.endsWith(".mjs")) return "javascript";
  if (lower.endsWith(".ts")) return "typescript";
  if (lower.endsWith(".toml")) return "ini";
  return "plaintext";
}

function isConfigPath(path) {
  return Boolean(path && /\.ya?ml$/i.test(path));
}

function displayError(error, title = "Error") {
  setOutput(title, error.message || String(error), "error");
}

function setOutput(title, content, kind = "neutral") {
  elements["output-title"].textContent = title;
  elements["output-content"].textContent = content;
  elements["output-panel"].dataset.kind = kind;
}

function bufferDirty(buffer) {
  return buffer.model.getValue() !== buffer.savedContent;
}

function renderTabs() {
  const tabs = elements.tabs;
  tabs.replaceChildren();
  for (const [path, buffer] of state.buffers) {
    const tab = document.createElement("button");
    tab.className = `tab ${path === state.activePath ? "active" : ""}`;
    tab.type = "button";
    tab.role = "tab";
    tab.dataset.path = path;
    tab.setAttribute("aria-selected", String(path === state.activePath));

    const name = document.createElement("span");
    name.className = "tab-name";
    name.textContent = path.split("/").at(-1);
    name.title = path;
    const dirty = document.createElement("span");
    dirty.className = "dirty-indicator";
    dirty.textContent = bufferDirty(buffer) ? "●" : "";
    const close = document.createElement("span");
    close.className = "tab-close";
    close.textContent = "×";
    close.title = `Close ${path}`;
    close.addEventListener("click", (event) => {
      event.stopPropagation();
      closeBuffer(path);
    });
    tab.append(name, dirty, close);
    tab.addEventListener("click", () => activateBuffer(path));
    tabs.append(tab);
  }
}

function updateEditorState() {
  const buffer = state.activePath ? state.buffers.get(state.activePath) : null;
  const dirty = buffer ? bufferDirty(buffer) : false;
  elements["save-button"].disabled = !buffer || !dirty;
  elements["validate-button"].disabled = !buffer || !isConfigPath(state.activePath);
  elements["save-status"].textContent = !buffer
    ? "No file open"
    : dirty
      ? "Modified"
      : buffer.isNew
        ? "New file"
        : "Saved";
  elements["active-language"].textContent = buffer
    ? languageFor(state.activePath)
    : "plain text";
  renderTabs();
}

function activateBuffer(path) {
  const buffer = state.buffers.get(path);
  if (!buffer) return;
  if (state.activePath && state.activePath !== path) {
    const previous = state.buffers.get(state.activePath);
    if (previous) previous.viewState = state.editor.saveViewState();
  }
  state.activePath = path;
  state.editor.setModel(buffer.model);
  if (buffer.viewState) state.editor.restoreViewState(buffer.viewState);
  elements["empty-state"].hidden = true;
  elements.editor.hidden = false;
  state.editor.focus();
  updateEditorState();
}

function addBuffer(path, content, revision = null, isNew = false) {
  if (state.buffers.has(path)) {
    activateBuffer(path);
    return state.buffers.get(path);
  }
  const uri = monaco.Uri.from({ scheme: "file", path: `/${path}` });
  const existing = monaco.editor.getModel(uri);
  if (existing) existing.dispose();
  const model = monaco.editor.createModel(content, languageFor(path), uri);
  const buffer = { path, model, revision, savedContent: content, isNew, viewState: null };
  model.onDidChangeContent(() => {
    if (state.activePath === path) updateEditorState();
  });
  state.buffers.set(path, buffer);
  activateBuffer(path);
  return buffer;
}

function closeBuffer(path) {
  const buffer = state.buffers.get(path);
  if (!buffer) return;
  if (bufferDirty(buffer) && !window.confirm(`Discard unsaved changes in ${path}?`)) return;
  const paths = [...state.buffers.keys()];
  const index = paths.indexOf(path);
  buffer.model.dispose();
  state.buffers.delete(path);
  if (state.activePath === path) {
    const next = paths[index + 1] || paths[index - 1];
    state.activePath = null;
    if (next && state.buffers.has(next)) {
      activateBuffer(next);
    } else {
      state.editor.setModel(null);
      elements["empty-state"].hidden = false;
      elements.editor.hidden = true;
      updateEditorState();
    }
  } else {
    renderTabs();
  }
}

async function openFile(path) {
  if (state.buffers.has(path)) {
    activateBuffer(path);
    return;
  }
  try {
    const file = await api(`/api/files?path=${encodeURIComponent(path)}`);
    addBuffer(file.path, file.content, file.revision, false);
  } catch (error) {
    displayError(error, `Cannot open ${path}`);
  }
}

async function saveActive() {
  const buffer = state.activePath ? state.buffers.get(state.activePath) : null;
  if (!buffer || !bufferDirty(buffer)) return;
  elements["save-button"].disabled = true;
  elements["save-status"].textContent = "Saving…";
  try {
    const result = await api(`/api/files?path=${encodeURIComponent(buffer.path)}`, {
      method: "PUT",
      body: JSON.stringify({ content: buffer.model.getValue(), revision: buffer.revision }),
    });
    buffer.revision = result.revision;
    buffer.savedContent = buffer.model.getValue();
    if (buffer.isNew) {
      buffer.isNew = false;
      state.files.push({
        path: buffer.path,
        name: buffer.path.split("/").at(-1),
        kind: "file",
        size: result.size,
        editable: true,
      });
      renderFiles();
    }
    setOutput("Saved", `${buffer.path}\n${result.size} bytes`, "success");
  } catch (error) {
    displayError(error, error.status === 409 ? "Save conflict" : "Save failed");
  } finally {
    updateEditorState();
  }
}

function overrideLines(value) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

function openConfigInspector() {
  const buffer = state.activePath ? state.buffers.get(state.activePath) : null;
  if (!buffer || !isConfigPath(buffer.path)) return;
  elements["inspect-path"].value = buffer.path;
  elements["inspect-error"].textContent = "";
  elements["inspect-rendered"].textContent = "Run the inspector to render the composed configuration.";
  elements["inspect-plan"].textContent = "No compiled plan yet.";
  elements["inspect-dialog"].showModal();
}

async function inspectActiveConfig() {
  const buffer = state.activePath ? state.buffers.get(state.activePath) : null;
  if (!buffer || !isConfigPath(buffer.path)) return;
  elements["inspect-error"].textContent = "";
  elements["run-inspection"].disabled = true;
  elements["run-inspection"].textContent = "Compiling…";
  try {
    const result = await api("/api/config/inspect", {
      method: "POST",
      body: JSON.stringify({
        path: buffer.path,
        content: buffer.model.getValue(),
        overrides: overrideLines(elements["inspect-overrides"].value),
        include_manifests: elements["inspect-manifests"].checked,
      }),
    });
    elements["inspect-rendered"].textContent = result.rendered;
    elements["inspect-plan"].textContent = JSON.stringify(
      {
        experiment: result.experiment,
        ...result.plan,
        ...(result.manifests ? { manifests: result.manifests } : {}),
      },
      null,
      2,
    );
    setOutput(
      "Valid experiment",
      `${result.experiment}\n${result.plan.runs} run(s) · ${result.plan.trials} trial(s)`,
      "success",
    );
  } catch (error) {
    elements["inspect-error"].textContent = error.message || String(error);
  } finally {
    elements["run-inspection"].disabled = false;
    elements["run-inspection"].textContent = "Compose and inspect";
  }
}

function renderFiles() {
  const query = elements["file-filter"].value.trim().toLowerCase();
  const visible = state.files
    .filter((entry) => !query || entry.path.toLowerCase().includes(query))
    .sort((left, right) => left.path.localeCompare(right.path));
  elements["file-count"].textContent = String(
    state.files.filter((entry) => entry.kind === "file").length,
  );
  const tree = elements["file-tree"];
  tree.replaceChildren();
  for (const entry of visible) {
    const item = document.createElement(entry.kind === "file" ? "button" : "div");
    item.className = `tree-item ${entry.kind}`;
    item.style.setProperty("--depth", String(entry.path.split("/").length - 1));
    item.dataset.path = entry.path;
    item.title = entry.path;
    item.setAttribute("role", "treeitem");
    const icon = document.createElement("span");
    icon.className = "tree-icon";
    icon.textContent = entry.kind === "directory" ? "▾" : fileIcon(entry.path);
    const label = document.createElement("span");
    label.textContent = entry.name;
    item.append(icon, label);
    if (entry.kind === "file") {
      item.type = "button";
      if (entry.editable === false) item.classList.add("muted");
      item.addEventListener("click", () => openFile(entry.path));
    }
    tree.append(item);
  }
}

function fileIcon(path) {
  if (/\.py$/i.test(path)) return "Py";
  if (/\.ya?ml$/i.test(path)) return "Y";
  if (/\.json$/i.test(path)) return "{}";
  if (/\.md$/i.test(path)) return "M";
  return "·";
}

function renderRegistry() {
  const query = elements["component-filter"].value.trim().toLowerCase();
  const specs = state.bootstrap.components.filter((spec) => {
    const haystack = `${spec.kind} ${spec.name} ${spec.description} ${spec.provider}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  elements["component-count"].textContent = String(state.bootstrap.components.length);
  const list = elements["registry-list"];
  list.replaceChildren();
  for (const spec of specs) {
    const details = document.createElement("details");
    details.className = "registry-card";
    const summary = document.createElement("summary");
    const heading = document.createElement("span");
    heading.className = "registry-name";
    heading.textContent = spec.name;
    const kind = document.createElement("span");
    kind.className = "kind-badge";
    kind.textContent = spec.kind;
    summary.append(heading, kind);
    const body = document.createElement("div");
    body.className = "registry-body";
    const description = document.createElement("p");
    description.textContent = spec.description || "No description.";
    const provider = document.createElement("code");
    provider.textContent = spec.provider;
    body.append(description, provider);
    const properties = spec.schema.properties || {};
    const required = new Set(spec.schema.required || []);
    for (const [name, schema] of Object.entries(properties)) {
      const field = document.createElement("div");
      field.className = "registry-field";
      field.textContent = `${name}${required.has(name) ? " *" : ""} · ${schemaType(schema)}`;
      field.title = schema.description || "";
      body.append(field);
    }
    details.append(summary, body);
    list.append(details);
  }
}

function schemaType(schema) {
  if (schema.enum) return schema.enum.join(" | ");
  if (schema.type) return Array.isArray(schema.type) ? schema.type.join(" | ") : schema.type;
  if (schema.anyOf) return schema.anyOf.map((item) => item.type || "value").join(" | ");
  return "value";
}

function openNewFile() {
  const path = window.prompt("New file path, relative to the workspace:", "notes.md")?.trim();
  if (!path) return;
  if (state.files.some((entry) => entry.path === path)) {
    setOutput("File exists", `Open ${path} from the explorer instead.`, "error");
    return;
  }
  addBuffer(path, "", null, true);
}

function componentSpecs() {
  return state.bootstrap.components.filter((spec) => !["stage", "launcher"].includes(spec.kind));
}

function stageSpecs() {
  return state.bootstrap.components.filter((spec) => spec.kind === "stage");
}

function specByName(kind, name) {
  return state.bootstrap.components.find((spec) => spec.kind === kind && spec.name === name);
}

function renderCreatorComponents() {
  const host = elements["creator-components"];
  host.replaceChildren();
  const kinds = [...new Set(componentSpecs().map((spec) => spec.kind))].sort();
  for (const kind of kinds) {
    const item = document.createElement("div");
    item.className = "creator-item component-item";
    item.dataset.kind = kind;
    const top = document.createElement("div");
    top.className = "creator-item-top";
    const label = document.createElement("label");
    label.className = "field grow";
    const title = document.createElement("span");
    title.textContent = kind;
    const select = document.createElement("select");
    select.className = "component-type";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "Not configured";
    select.append(none);
    for (const spec of componentSpecs().filter((candidate) => candidate.kind === kind)) {
      const option = document.createElement("option");
      option.value = spec.name;
      option.textContent = spec.name;
      select.append(option);
    }
    label.append(title, select);
    top.append(label);
    const params = document.createElement("div");
    params.className = "schema-fields";
    select.addEventListener("change", () => {
      renderSchemaFields(specByName(kind, select.value), params);
      item.classList.toggle("selected", Boolean(select.value));
    });
    item.append(top, params);
    host.append(item);
  }
}

function addStageRow(defaultSpec = null) {
  const specs = stageSpecs();
  if (!specs.length) return;
  state.stageCounter += 1;
  const item = document.createElement("div");
  item.className = "creator-item stage-item selected";
  item.dataset.stageId = String(state.stageCounter);
  const top = document.createElement("div");
  top.className = "creator-item-top stage-top";

  const nameLabel = document.createElement("label");
  nameLabel.className = "field";
  const nameTitle = document.createElement("span");
  nameTitle.textContent = "Stage name";
  const nameInput = document.createElement("input");
  nameInput.className = "stage-name";
  nameLabel.append(nameTitle, nameInput);

  const typeLabel = document.createElement("label");
  typeLabel.className = "field grow";
  const typeTitle = document.createElement("span");
  typeTitle.textContent = "Registered type";
  const select = document.createElement("select");
  select.className = "stage-type";
  for (const spec of specs) {
    const option = document.createElement("option");
    option.value = spec.name;
    option.textContent = spec.name;
    select.append(option);
  }
  if (defaultSpec) select.value = defaultSpec.name;
  typeLabel.append(typeTitle, select);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "icon-button remove-stage";
  remove.textContent = "×";
  remove.title = "Remove stage";
  remove.addEventListener("click", () => item.remove());
  top.append(nameLabel, typeLabel, remove);

  const needsLabel = document.createElement("label");
  needsLabel.className = "field";
  const needsTitle = document.createElement("span");
  needsTitle.textContent = "Dependencies (comma-separated)";
  const needsInput = document.createElement("input");
  needsInput.className = "stage-needs";
  const priorNames = [...elements["creator-stages"].querySelectorAll(".stage-name")]
    .map((input) => input.value.trim())
    .filter(Boolean);
  needsInput.value = priorNames.at(-1) || "";
  needsLabel.append(needsTitle, needsInput);

  const params = document.createElement("div");
  params.className = "schema-fields";
  const syncSpec = () => {
    const spec = specByName("stage", select.value);
    if (!nameInput.value.trim()) nameInput.value = spec.name.split("/").at(-1).replaceAll("-", "_");
    renderSchemaFields(spec, params);
  };
  select.addEventListener("change", syncSpec);
  item.append(top, needsLabel, params);
  elements["creator-stages"].append(item);
  syncSpec();
}

function renderSchemaFields(spec, host) {
  host.replaceChildren();
  if (!spec) return;
  const properties = spec.schema.properties || {};
  const required = new Set(spec.schema.required || []);
  for (const [name, schema] of Object.entries(properties)) {
    const label = document.createElement("label");
    label.className = "field schema-field";
    label.dataset.name = name;
    label.dataset.schema = JSON.stringify(schema);
    label.dataset.required = String(required.has(name));
    const title = document.createElement("span");
    title.textContent = `${name}${required.has(name) ? " *" : ""}`;
    if (schema.description) title.title = schema.description;
    const input = schemaInput(schema, required.has(name));
    label.append(title, input);
    host.append(label);
  }
}

function schemaInput(schema, required) {
  let input;
  if (schema.enum) {
    input = document.createElement("select");
    for (const value of schema.enum) {
      const option = document.createElement("option");
      option.value = JSON.stringify(value);
      option.textContent = String(value);
      input.append(option);
    }
    input.dataset.encodedEnum = "true";
  } else if (schema.type === "boolean") {
    input = document.createElement("select");
    for (const value of [true, false]) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = String(value);
      input.append(option);
    }
  } else {
    input = document.createElement("input");
    if (schema.type === "integer" || schema.type === "number") {
      input.type = "number";
      input.step = schema.type === "integer" ? "1" : "any";
      if (schema.minimum !== undefined) input.min = String(schema.minimum);
      if (schema.exclusiveMinimum !== undefined) input.min = String(schema.exclusiveMinimum);
    } else if (schema.type === "array" || schema.type === "object") {
      input.placeholder = schema.type === "array" ? "JSON array, e.g. [1, 2]" : "JSON object";
    } else {
      input.placeholder = schemaType(schema);
    }
  }
  if (schema.default !== undefined) {
    input.value =
      typeof schema.default === "object" ? JSON.stringify(schema.default) : String(schema.default);
  }
  input.required = required;
  return input;
}

function collectSchemaParams(host) {
  const result = {};
  for (const label of host.querySelectorAll(".schema-field")) {
    const input = label.querySelector("input, select");
    const raw = input.value.trim();
    const required = label.dataset.required === "true";
    if (!raw && !required) continue;
    if (!raw && required) throw new Error(`${label.dataset.name} is required`);
    const schema = JSON.parse(label.dataset.schema);
    result[label.dataset.name] = parseSchemaValue(raw, schema, input.dataset.encodedEnum === "true");
  }
  return result;
}

function parseSchemaValue(raw, schema, encodedEnum) {
  if (encodedEnum) return JSON.parse(raw);
  if (schema.type === "integer") {
    const value = Number(raw);
    if (!Number.isInteger(value)) throw new Error(`Expected integer, got ${raw}`);
    return value;
  }
  if (schema.type === "number") {
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error(`Expected number, got ${raw}`);
    return value;
  }
  if (schema.type === "boolean") return raw === "true";
  if (schema.type === "array" || schema.type === "object") return JSON.parse(raw);
  if (schema.anyOf?.some((item) => item.type === "null") && raw === "null") return null;
  return raw;
}

function openConfigCreator() {
  elements["creator-error"].textContent = "";
  elements["creator-stages"].replaceChildren();
  state.stageCounter = 0;
  renderCreatorComponents();
  const noop = stageSpecs().find((spec) => spec.name === "core/noop") || stageSpecs()[0];
  if (noop) addStageRow(noop);
  elements["config-dialog"].showModal();
}

function closeConfigCreator() {
  elements["config-dialog"].close();
}

function collectCreatorPayload() {
  const path = elements["creator-path"].value.trim();
  if (state.files.some((entry) => entry.path === path)) {
    throw new Error(`${path} already exists; open it from the explorer instead`);
  }
  const seeds = elements["creator-seeds"].value
    .split(",")
    .map((value) => Number(value.trim()))
    .filter((value) => !Number.isNaN(value));
  if (!seeds.length || !seeds.every(Number.isInteger)) {
    throw new Error("Seeds must be comma-separated integers");
  }
  const components = [];
  for (const item of elements["creator-components"].querySelectorAll(".component-item")) {
    const type = item.querySelector(".component-type").value;
    if (!type) continue;
    components.push({
      kind: item.dataset.kind,
      type,
      params: collectSchemaParams(item.querySelector(".schema-fields")),
    });
  }
  const stages = [];
  for (const item of elements["creator-stages"].querySelectorAll(".stage-item")) {
    const name = item.querySelector(".stage-name").value.trim();
    if (!name) throw new Error("Every stage needs a name");
    stages.push({
      name,
      type: item.querySelector(".stage-type").value,
      needs: item
        .querySelector(".stage-needs")
        .value.split(",")
        .map((value) => value.trim())
        .filter(Boolean),
      params: collectSchemaParams(item.querySelector(".schema-fields")),
    });
  }
  if (!stages.length) throw new Error("Add at least one stage");
  const memory = elements["creator-memory"].value.trim();
  return {
    path,
    experiment_name: elements["creator-name"].value.trim(),
    description: elements["creator-description"].value.trim() || null,
    tags: elements["creator-tags"].value
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
    seeds,
    components,
    stages,
    accelerator: elements["creator-accelerator"].value,
    devices: Number(elements["creator-devices"].value),
    memory_gb: memory ? Number(memory) : null,
    artifact_root: elements["creator-artifacts"].value.trim() || "runs",
  };
}

async function submitCreator(event) {
  event.preventDefault();
  elements["creator-error"].textContent = "";
  try {
    const payload = collectCreatorPayload();
    const result = await api("/api/config/create", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    addBuffer(result.path, result.content, null, true);
    closeConfigCreator();
    setOutput(
      "Config ready",
      `${result.path}\n${result.plan.runs} run(s) · ${result.plan.trials} trial(s)\n\nSave with Ctrl+S.`,
      "success",
    );
  } catch (error) {
    elements["creator-error"].textContent = error.message || String(error);
  }
}

function savedYamlPaths() {
  return state.files
    .filter((entry) => entry.kind === "file" && /\.ya?ml$/i.test(entry.path))
    .map((entry) => entry.path)
    .sort((left, right) => left.localeCompare(right));
}

function fillLaunchSelectors() {
  const yamlPaths = savedYamlPaths();
  const previousConfig = elements["launch-config"].value;
  const activeSavedConfig =
    state.activePath &&
    isConfigPath(state.activePath) &&
    !state.buffers.get(state.activePath)?.isNew
      ? state.activePath
      : null;
  elements["launch-config"].replaceChildren();
  for (const path of yamlPaths) {
    const option = document.createElement("option");
    option.value = path;
    option.textContent = path;
    elements["launch-config"].append(option);
  }
  const preferredConfig = activeSavedConfig || previousConfig;
  if ([...elements["launch-config"].options].some((option) => option.value === preferredConfig)) {
    elements["launch-config"].value = preferredConfig;
  }

  const previousPolicy = elements["launch-policy"].value;
  elements["launch-policy"].replaceChildren();
  const automatic = document.createElement("option");
  automatic.value = "";
  automatic.textContent = "Built-in local subprocess policy";
  elements["launch-policy"].append(automatic);
  for (const path of yamlPaths) {
    const option = document.createElement("option");
    option.value = path;
    option.textContent = path;
    elements["launch-policy"].append(option);
  }
  if ([...elements["launch-policy"].options].some((option) => option.value === previousPolicy)) {
    elements["launch-policy"].value = previousPolicy;
  }
}

function activeConfigIsDirty(path) {
  const buffer = state.buffers.get(path);
  return Boolean(buffer && (buffer.isNew || bufferDirty(buffer)));
}

function launchPayload() {
  return {
    config_path: elements["launch-config"].value,
    launcher_path: elements["launch-policy"].value || null,
    artifact_root: elements["launch-artifacts"].value.trim() || null,
    resume: elements["launch-resume"].checked,
    overrides: overrideLines(elements["launch-overrides"].value),
    launcher_overrides: overrideLines(elements["launch-policy-overrides"].value),
  };
}

async function previewLaunchPlan() {
  const path = elements["launch-config"].value;
  elements["launch-error"].textContent = "";
  if (!path) {
    elements["launch-plan-preview"].textContent = "No saved YAML experiment is available.";
    elements["launch-submit"].disabled = true;
    return;
  }
  if (activeConfigIsDirty(path)) {
    elements["launch-plan-preview"].textContent =
      "This config has unsaved changes. Save it before launching.";
    elements["launch-submit"].disabled = true;
    return;
  }
  elements["launch-plan-preview"].textContent = `Compiling ${path}…`;
  elements["launch-submit"].disabled = true;
  try {
    const result = await api("/api/launches/preview", {
      method: "POST",
      body: JSON.stringify(launchPayload()),
    });
    const plan = result.plan;
    const launcher = result.launcher;
    const assignments = (plan.run_details || [])
      .slice(0, 3)
      .map((run) => `${run.run_id} ← ${JSON.stringify(run.assignments)}`);
    elements["launch-plan-preview"].textContent =
      `${plan.runs} run(s) · ${plan.trials} trial(s) · study ${plan.study_id}\n` +
      `launcher ${launcher.type} · max_parallel ${launcher.params.max_parallel ?? "auto"}\n` +
      `${assignments.join("\n")}${plan.runs > assignments.length ? "\n…" : ""}`;
    elements["launch-submit"].disabled = false;
  } catch (error) {
    elements["launch-plan-preview"].textContent = "The selected file is not launchable.";
    elements["launch-error"].textContent = error.message || String(error);
  }
}

function launchStateLabel(stateName) {
  return {
    queued: "queued",
    running: "running",
    completed: "completed",
    failed: "failed",
    orphaned: "scheduler lost",
  }[stateName] || stateName;
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function renderLaunchList() {
  const host = elements["launch-list"];
  host.replaceChildren();
  if (!state.launches.length) {
    const empty = document.createElement("div");
    empty.className = "launch-list-empty";
    empty.textContent = "No launches yet.";
    host.append(empty);
    return;
  }
  for (const launch of state.launches) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `launch-card ${launch.launch_id === state.selectedLaunchId ? "selected" : ""}`;
    const top = document.createElement("span");
    top.className = "launch-card-top";
    const name = document.createElement("strong");
    name.textContent = launch.config_path || launch.launch_id;
    name.title = launch.launch_id;
    const badge = document.createElement("span");
    badge.className = `state-badge ${launch.state}`;
    badge.textContent = launchStateLabel(launch.state);
    top.append(name, badge);
    const meta = document.createElement("span");
    meta.className = "launch-card-meta";
    const completed = launch.run_counts?.completed || 0;
    const total = launch.plan?.runs || 0;
    meta.textContent = `${completed}/${total} completed · ${formatTimestamp(launch.created_at)}`;
    item.append(top, meta);
    item.addEventListener("click", async () => {
      state.selectedLaunchId = launch.launch_id;
      state.selectedRunId = null;
      renderLaunchList();
      await refreshLaunchDetail();
    });
    host.append(item);
  }
}

function launchProgress(detail) {
  const total = detail.plan?.runs || 0;
  const completed = detail.run_counts?.completed || 0;
  const failed = detail.run_counts?.failed || 0;
  return {
    total,
    completed,
    failed,
    percent: total ? Math.round(((completed + failed) / total) * 100) : 0,
  };
}

function renderLaunchDetail(detail) {
  state.selectedRunId = detail.selected_run_id || null;
  const host = elements["launch-detail"];
  host.replaceChildren();
  const header = document.createElement("div");
  header.className = "launch-detail-header";
  const titleGroup = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = detail.launch_id;
  const title = document.createElement("h3");
  title.textContent = detail.config_path || "Experiment launch";
  titleGroup.append(eyebrow, title);
  const badge = document.createElement("span");
  badge.className = `state-badge ${detail.state}`;
  badge.textContent = launchStateLabel(detail.state);
  header.append(titleGroup, badge);

  const progress = launchProgress(detail);
  const progressBlock = document.createElement("div");
  progressBlock.className = "launch-progress";
  const progressMeta = document.createElement("div");
  progressMeta.className = "launch-progress-meta";
  progressMeta.textContent =
    `${progress.completed} completed · ${progress.failed} failed · ${progress.total} total`;
  const progressTrack = document.createElement("div");
  progressTrack.className = "progress-track";
  const progressValue = document.createElement("span");
  progressValue.style.width = `${progress.percent}%`;
  progressTrack.append(progressValue);
  progressBlock.append(progressMeta, progressTrack);

  const facts = document.createElement("div");
  facts.className = "launch-facts";
  const factValues = [
    ["Artifacts", detail.artifact_root || "runs"],
    ["Scheduler", detail.scheduler_alive ? `PID ${detail.scheduler_pid}` : "detached / finished"],
    ["Started", formatTimestamp(detail.started_at || detail.created_at)],
    ["Launcher", detail.launcher_path || "built-in"],
  ];
  for (const [label, value] of factValues) {
    const fact = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const content = document.createElement("strong");
    content.textContent = value;
    fact.append(name, content);
    facts.append(fact);
  }

  const runsHeading = document.createElement("div");
  runsHeading.className = "section-heading compact-heading";
  const runsTitle = document.createElement("h3");
  runsTitle.textContent = "Runs";
  const runsCount = document.createElement("span");
  runsCount.textContent = String(detail.runs?.length || 0);
  runsHeading.append(runsTitle, runsCount);
  const runs = document.createElement("div");
  runs.className = "run-status-list";
  for (const run of (detail.runs || []).slice(0, 500)) {
    const row = document.createElement("button");
    row.type = "button";
    row.className =
      `run-status-row ${run.run_id === state.selectedRunId ? "selected" : ""}`;
    const id = document.createElement("code");
    id.textContent = run.run_id;
    const device = document.createElement("span");
    device.textContent = run.gpu
      ? `GPU ${run.gpu.index}`
      : run.state === "pending"
        ? "pending"
        : "CPU";
    const runBadge = document.createElement("span");
    runBadge.className = `state-badge ${run.state}`;
    runBadge.textContent = run.state;
    row.append(id, device, runBadge);
    row.addEventListener("click", async () => {
      state.selectedRunId = run.run_id;
      await refreshLaunchDetail();
    });
    runs.append(row);
  }
  if ((detail.runs?.length || 0) > 500) {
    const note = document.createElement("div");
    note.className = "run-limit-note";
    note.textContent = `Showing 500/${detail.runs.length} runs.`;
    runs.append(note);
  }

  const workerLogHeading = document.createElement("div");
  workerLogHeading.className = "section-heading compact-heading";
  const workerLogTitle = document.createElement("h3");
  workerLogTitle.textContent = "Worker log";
  const workerLogState = document.createElement("span");
  workerLogState.textContent = detail.selected_run_id || "no run";
  workerLogHeading.append(workerLogTitle, workerLogState);
  const workerLog = document.createElement("pre");
  workerLog.className = "scheduler-log";
  workerLog.textContent = detail.worker_log || "Waiting for worker output…";

  const schedulerLogHeading = document.createElement("div");
  schedulerLogHeading.className = "section-heading compact-heading";
  const schedulerLogTitle = document.createElement("h3");
  schedulerLogTitle.textContent = "Scheduler log";
  const schedulerLogState = document.createElement("span");
  schedulerLogState.textContent = "last 64 KiB";
  schedulerLogHeading.append(schedulerLogTitle, schedulerLogState);
  const schedulerLog = document.createElement("pre");
  schedulerLog.className = "scheduler-log";
  schedulerLog.textContent = detail.scheduler_log || "Waiting for scheduler output…";

  host.append(
    header,
    progressBlock,
    facts,
    runsHeading,
    runs,
    workerLogHeading,
    workerLog,
    schedulerLogHeading,
    schedulerLog,
  );
}

async function refreshLaunchDetail() {
  if (!state.selectedLaunchId) return;
  try {
    const selectedRun = state.selectedRunId
      ? `?run_id=${encodeURIComponent(state.selectedRunId)}`
      : "";
    const detail = await api(
      `/api/launches/${encodeURIComponent(state.selectedLaunchId)}${selectedRun}`,
    );
    renderLaunchDetail(detail);
  } catch (error) {
    elements["launch-error"].textContent = error.message || String(error);
  }
}

async function refreshLaunches() {
  if (state.launchRefreshPending) return;
  state.launchRefreshPending = true;
  try {
    const result = await api("/api/launches");
    state.launches = result.launches;
    if (
      state.selectedLaunchId &&
      !state.launches.some((launch) => launch.launch_id === state.selectedLaunchId)
    ) {
      state.selectedLaunchId = null;
      state.selectedRunId = null;
    }
    if (!state.selectedLaunchId && state.launches.length) {
      state.selectedLaunchId = state.launches[0].launch_id;
    }
    renderLaunchList();
    if (state.selectedLaunchId) await refreshLaunchDetail();
  } catch (error) {
    elements["launch-error"].textContent = error.message || String(error);
  } finally {
    state.launchRefreshPending = false;
  }
}

async function submitLaunch(event) {
  event.preventDefault();
  const configPath = elements["launch-config"].value;
  elements["launch-error"].textContent = "";
  if (!configPath) return;
  if (activeConfigIsDirty(configPath)) {
    elements["launch-error"].textContent = "Save the selected config before launching.";
    return;
  }
  elements["launch-submit"].disabled = true;
  elements["launch-submit"].textContent = "Starting…";
  try {
    const detail = await api("/api/launches", {
      method: "POST",
      body: JSON.stringify(launchPayload()),
    });
    state.selectedLaunchId = detail.launch_id;
    state.selectedRunId = detail.selected_run_id || null;
    renderLaunchDetail(detail);
    await refreshLaunches();
    setOutput(
      "Experiment launched",
      `${detail.config_path}\nlaunch ${detail.launch_id}\n${detail.plan.runs} run(s) · detached scheduler`,
      "success",
    );
  } catch (error) {
    elements["launch-error"].textContent = error.message || String(error);
  } finally {
    elements["launch-submit"].textContent = "Start detached launch";
    await previewLaunchPlan();
  }
}

async function openExperiments() {
  elements["launch-error"].textContent = "";
  fillLaunchSelectors();
  const connection = state.bootstrap.connection || {};
  const note = elements["remote-session-note"].querySelector("span:last-child");
  note.textContent =
    connection.mode === "ssh"
      ? `SSH session on ${connection.hostname}. The tunnel may disconnect without stopping launches.`
      : "Localhost-only session. Launches persist if this browser disconnects.";
  elements["experiments-dialog"].showModal();
  await Promise.all([previewLaunchPlan(), refreshLaunches()]);
  window.clearInterval(state.launchPollTimer);
  state.launchPollTimer = window.setInterval(() => {
    if (elements["experiments-dialog"].open) refreshLaunches();
  }, 2000);
}

function closeExperiments() {
  elements["experiments-dialog"].close();
  window.clearInterval(state.launchPollTimer);
  state.launchPollTimer = null;
}

function fillInferenceSelectors() {
  const yamlPaths = savedYamlPaths();
  const previousConfig = elements["inference-config"].value;
  elements["inference-config"].replaceChildren();
  const automatic = document.createElement("option");
  automatic.value = "";
  automatic.textContent = "Restore managed checkpoint config";
  elements["inference-config"].append(automatic);
  for (const path of yamlPaths) {
    const option = document.createElement("option");
    option.value = path;
    option.textContent = path;
    elements["inference-config"].append(option);
  }
  if ([...elements["inference-config"].options].some((option) => option.value === previousConfig)) {
    elements["inference-config"].value = previousConfig;
  }

  const previousPolicy = elements["inference-policy"].value;
  elements["inference-policy"].replaceChildren();
  const builtIn = document.createElement("option");
  builtIn.value = "";
  builtIn.textContent = "Built-in local subprocess policy";
  elements["inference-policy"].append(builtIn);
  for (const path of yamlPaths) {
    const option = document.createElement("option");
    option.value = path;
    option.textContent = path;
    elements["inference-policy"].append(option);
  }
  if ([...elements["inference-policy"].options].some((option) => option.value === previousPolicy)) {
    elements["inference-policy"].value = previousPolicy;
  }
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
}

function selectedCheckpoint() {
  const path = elements["inference-checkpoint"].value.trim();
  return state.checkpoints.find((checkpoint) => checkpoint.path === path) || null;
}

function renderCheckpointDetail(checkpoint) {
  if (!checkpoint) {
    elements["checkpoint-detail"].textContent =
      "External checkpoint: choose an explicit config before previewing.";
    return;
  }
  const model = checkpoint.model?.type || "unknown model";
  elements["checkpoint-detail"].textContent =
    `${checkpoint.study_id} · ${checkpoint.run_id} · ${checkpoint.stage}/${checkpoint.name}\n` +
    `${model} · ${formatBytes(checkpoint.size)} · ${formatTimestamp(checkpoint.modified_at)}`;
}

function renderCheckpointList() {
  const host = elements["checkpoint-list"];
  host.replaceChildren();
  if (!state.checkpoints.length) {
    const empty = document.createElement("div");
    empty.className = "launch-list-empty";
    empty.textContent = "No managed checkpoints found.";
    host.append(empty);
    return;
  }
  for (const checkpoint of state.checkpoints) {
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      `checkpoint-card ${checkpoint.path === state.selectedCheckpointPath ? "selected" : ""}`;
    const top = document.createElement("span");
    top.className = "checkpoint-card-top";
    const name = document.createElement("strong");
    name.textContent = `${checkpoint.study_id} · ${checkpoint.name}`;
    const badge = document.createElement("span");
    badge.className = `checkpoint-kind ${checkpoint.name === "best" ? "best" : ""}`;
    badge.textContent = checkpoint.name;
    top.append(name, badge);
    const model = document.createElement("code");
    model.textContent = checkpoint.model?.type || "unknown model";
    const meta = document.createElement("span");
    meta.textContent = `${checkpoint.run_id} · ${checkpoint.stage} · ${formatBytes(checkpoint.size)}`;
    button.append(top, model, meta);
    button.addEventListener("click", async () => {
      state.selectedCheckpointPath = checkpoint.path;
      elements["inference-checkpoint"].value = checkpoint.path;
      elements["inference-config"].value = "";
      renderCheckpointList();
      renderCheckpointDetail(checkpoint);
      await previewInference();
    });
    host.append(button);
  }
}

async function refreshCheckpoints() {
  elements["checkpoint-error"].textContent = "";
  elements["checkpoint-summary"].textContent = "Scanning…";
  try {
    const result = await api("/api/checkpoints/catalog", {
      method: "POST",
      body: JSON.stringify({
        artifact_root: elements["checkpoint-root"].value.trim() || "runs",
      }),
    });
    state.checkpoints = result.checkpoints;
    elements["checkpoint-summary"].textContent = `${state.checkpoints.length} checkpoint(s)`;
    if (
      state.selectedCheckpointPath &&
      !state.checkpoints.some((checkpoint) => checkpoint.path === state.selectedCheckpointPath)
    ) {
      state.selectedCheckpointPath = null;
    }
    renderCheckpointList();
  } catch (error) {
    elements["checkpoint-summary"].textContent = "Catalog unavailable";
    elements["checkpoint-error"].textContent = error.message || String(error);
  }
}

function inferencePayload() {
  const splits = elements["inference-splits"].value
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (!splits.length) throw new Error("Enter at least one evaluation split");
  const checkpointPath = elements["inference-checkpoint"].value.trim();
  if (!checkpointPath) throw new Error("Select or enter a checkpoint path");
  return {
    checkpoint_path: checkpointPath,
    config_path: elements["inference-config"].value || null,
    splits,
    device: elements["inference-device"].value,
    predict: elements["inference-predict"].checked,
    overrides: overrideLines(elements["inference-overrides"].value),
    launcher_path: elements["inference-policy"].value || null,
    launcher_overrides: overrideLines(elements["inference-policy-overrides"].value),
    artifact_root: elements["inference-artifacts"].value.trim() || "runs",
  };
}

async function previewInference() {
  elements["checkpoint-error"].textContent = "";
  elements["start-inference"].disabled = true;
  try {
    const payload = inferencePayload();
    const result = await api("/api/checkpoints/inspect", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const plan = result.launch.plan;
    const checkpoint = result.checkpoint;
    renderCheckpointDetail(checkpoint.managed ? checkpoint : null);
    elements["inference-preview"].textContent =
      `${plan.runs} inference run · study ${plan.study_id}\n` +
      `${result.config.stages[0].type} · splits ${payload.splits.join(", ")} · ${payload.device}\n` +
      `model ${result.config.components.model.type}\ncheckpoint ${checkpoint.path}`;
    elements["start-inference"].disabled = false;
  } catch (error) {
    elements["inference-preview"].textContent = "Checkpoint/config compatibility is not validated.";
    elements["checkpoint-error"].textContent = error.message || String(error);
  }
}

async function submitInference(event) {
  event.preventDefault();
  elements["checkpoint-error"].textContent = "";
  elements["start-inference"].disabled = true;
  elements["start-inference"].textContent = "Starting…";
  try {
    const detail = await api("/api/checkpoints/infer", {
      method: "POST",
      body: JSON.stringify(inferencePayload()),
    });
    state.selectedLaunchId = detail.launch_id;
    state.selectedRunId = detail.selected_run_id || null;
    setOutput(
      "Inference launched",
      `${detail.config_path}\nlaunch ${detail.launch_id}\n${detail.plan.runs} run(s) · detached scheduler`,
      "success",
    );
    elements["checkpoints-dialog"].close();
    await openExperiments();
  } catch (error) {
    elements["checkpoint-error"].textContent = error.message || String(error);
  } finally {
    elements["start-inference"].textContent = "Start inference";
    elements["start-inference"].disabled = false;
  }
}

async function openCheckpoints() {
  elements["checkpoint-error"].textContent = "";
  fillInferenceSelectors();
  elements["checkpoints-dialog"].showModal();
  await refreshCheckpoints();
  if (elements["inference-checkpoint"].value.trim()) await previewInference();
}

function replaceOptions(select, values, { optional = false } = {}) {
  const previous = select.value;
  select.replaceChildren();
  if (optional) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "all";
    select.append(option);
  }
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

function replaceMultiOptions(select, values) {
  const selected = new Set([...select.selectedOptions].map((option) => option.value));
  select.replaceChildren();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = selected.has(String(value));
    select.append(option);
  }
}

function selectedValues(id) {
  return [...elements[id].selectedOptions].map((option) => option.value);
}

function commonMetricFilters() {
  return {
    study_ids: selectedValues("filter-studies"),
    trial_ids: selectedValues("filter-trials"),
    models: selectedValues("filter-models"),
    datasets: selectedValues("filter-datasets"),
    splits: selectedValues("filter-splits"),
    states: selectedValues("filter-states"),
  };
}

function updateActiveFilterCount() {
  const count = Object.values(commonMetricFilters()).reduce(
    (total, values) => total + values.length,
    0,
  );
  elements["active-filter-count"].textContent =
    count === 0 ? "all indexed data" : `${count} active value${count === 1 ? "" : "s"}`;
}

function clearAnalyticsFilters() {
  for (const id of [
    "filter-studies",
    "filter-trials",
    "filter-models",
    "filter-datasets",
    "filter-splits",
    "filter-states",
  ]) {
    for (const option of elements[id].options) option.selected = false;
  }
  updateActiveFilterCount();
}

function renderDataTable(host, rows, columns) {
  host.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "table-empty";
    empty.textContent = "No matching data.";
    host.append(empty);
    return;
  }
  const table = document.createElement("table");
  table.className = "data-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const column of columns) {
    const cell = document.createElement("th");
    cell.textContent = column.label;
    headRow.append(cell);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tableRow = document.createElement("tr");
    for (const column of columns) {
      const cell = document.createElement("td");
      const raw = row[column.key];
      cell.textContent = column.format
        ? column.format(raw, row)
        : raw === null || raw === undefined
          ? "—"
          : String(raw);
      tableRow.append(cell);
    }
    body.append(tableRow);
  }
  table.append(head, body);
  host.append(table);
}

function fixed(value, digits = 3) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

async function refreshRunOverview() {
  elements["analytics-error"].textContent = "";
  elements["run-catalog-summary"].textContent = "Scanning run artifacts…";
  try {
    const result = await api("/api/runs/catalog", {
      method: "POST",
      body: JSON.stringify({
        artifact_root: elements["analytics-root"].value.trim() || "runs",
        stage: elements["overview-stage"].value || null,
        metric: elements["overview-metric"].value || null,
        trial_ids: elements["overview-trials"].value
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        limit: Number(elements["overview-limit"].value) || 500,
      }),
    });
    const catalog = result.catalog;
    const counts = Object.entries(catalog.counts)
      .map(([name, count]) => `${name} ${count}`)
      .join(" · ");
    elements["run-catalog-summary"].textContent =
      `${catalog.total} run(s) in ${catalog.root}${counts ? ` · ${counts}` : ""}` +
      `${catalog.truncated ? ` · showing ${catalog.runs.length}` : ""}`;
    elements["overview-runs-count"].textContent = String(catalog.runs.length);
    renderDataTable(elements["overview-runs"], catalog.runs, [
      { key: "state", label: "State" },
      { key: "run_id", label: "Run" },
      { key: "trial_id", label: "Trial" },
      { key: "seed", label: "Seed" },
      {
        key: "gpu",
        label: "Device",
        format: (gpu) => (gpu && gpu.index !== undefined ? `GPU ${gpu.index}` : "CPU / unknown"),
      },
      { key: "updated_at", label: "Updated", format: formatTimestamp },
    ]);
    renderDataTable(elements["overview-summary"], result.summary, [
      { key: "trial_id", label: "Trial" },
      { key: "stage", label: "Stage" },
      { key: "metric", label: "Metric" },
      { key: "n", label: "n" },
      { key: "mean", label: "Mean", format: (value) => fixed(value) },
      { key: "std", label: "Std", format: (value) => fixed(value) },
    ]);
    renderDataTable(elements["overview-resources"], result.resources, [
      { key: "trial_id", label: "Trial" },
      { key: "n", label: "n" },
      { key: "wall_seconds_mean", label: "Wall s", format: (value) => fixed(value, 2) },
      { key: "gpu_hours_total", label: "GPU h", format: (value) => fixed(value, 3) },
      {
        key: "process_memory_peak_mb_max",
        label: "Peak MB",
        format: (value) => fixed(value, 1),
      },
      { key: "attempts_total", label: "Attempts" },
    ]);
  } catch (error) {
    elements["run-catalog-summary"].textContent = "Run catalog unavailable.";
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

async function refreshAnalytics(rebuild = false) {
  elements["analytics-error"].textContent = "";
  elements["analytics-summary"].textContent = "Indexing metric tails…";
  const previousSelectionMetric = elements["evaluation-selection-metric"].value;
  const previousTargetMetric = elements["evaluation-target-metric"].value;
  const previousSelectionSplit = elements["evaluation-selection-split"].value;
  const previousTargetSplit = elements["evaluation-target-split"].value;
  const result = await api("/api/analytics/catalog", {
    method: "POST",
    body: JSON.stringify({
      artifact_root: elements["analytics-root"].value.trim() || "runs",
      rebuild,
    }),
  });
  state.analyticsCatalog = result.catalog;
  replaceOptions(elements["chart-metric"], result.catalog.metrics);
  replaceOptions(elements["table-metric"], result.catalog.metrics);
  replaceOptions(elements["evaluation-selection-metric"], result.catalog.metrics);
  replaceOptions(elements["evaluation-target-metric"], result.catalog.metrics);
  replaceOptions(elements["chart-stage"], result.catalog.stages, { optional: true });
  replaceOptions(elements["table-stage"], result.catalog.stages, { optional: true });
  replaceOptions(elements["evaluation-stage"], result.catalog.stages, { optional: true });
  replaceOptions(elements["evaluation-selection-split"], result.catalog.splits, {
    optional: true,
  });
  replaceOptions(elements["evaluation-target-split"], result.catalog.splits, { optional: true });
  if (!previousSelectionMetric) {
    selectIfPresent(
      elements["evaluation-selection-metric"],
      result.catalog.metrics.find((metric) => /(^|[/_])val(idation)?([/_]|$)/i.test(metric)),
    );
  }
  if (!previousTargetMetric) {
    selectIfPresent(
      elements["evaluation-target-metric"],
      result.catalog.metrics.find((metric) => /(^|[/_])test([/_]|$)/i.test(metric)),
    );
  }
  if (!previousSelectionSplit) {
    selectIfPresent(
      elements["evaluation-selection-split"],
      result.catalog.splits.find((split) => /^val(idation)?$/i.test(split)),
    );
  }
  if (!previousTargetSplit) {
    selectIfPresent(
      elements["evaluation-target-split"],
      result.catalog.splits.find((split) => /^test$/i.test(split)),
    );
  }
  replaceOptions(elements["overview-metric"], result.catalog.metrics, { optional: true });
  replaceOptions(elements["overview-stage"], result.catalog.stages, { optional: true });
  replaceMultiOptions(elements["filter-studies"], result.catalog.studies);
  replaceMultiOptions(elements["filter-trials"], result.catalog.trials);
  replaceMultiOptions(elements["filter-models"], result.catalog.models);
  replaceMultiOptions(elements["filter-datasets"], result.catalog.datasets);
  replaceMultiOptions(elements["filter-splits"], result.catalog.splits);
  replaceMultiOptions(elements["filter-states"], result.catalog.states);
  updateActiveFilterCount();
  elements["analytics-summary"].textContent =
    `${result.catalog.run_count} runs · ${result.catalog.event_count} events · ` +
    `${result.refresh.events_indexed} new`;
}

async function openAnalytics() {
  replaceOptions(elements["report-spec-path"], savedYamlPaths());
  elements["analytics-dialog"].showModal();
  try {
    await refreshAnalytics(false);
    await refreshRunOverview();
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

function showAnalyticsPanel(kind) {
  const overview = kind === "overview";
  const evaluation = kind === "evaluation";
  const builders = kind === "builders";
  elements["analytics-overview-panel"].hidden = !overview;
  elements["analytics-evaluation-panel"].hidden = !evaluation;
  elements["analytics-builders-panel"].hidden = !builders;
  elements["analytics-overview-tab"].classList.toggle("active", overview);
  elements["analytics-evaluation-tab"].classList.toggle("active", evaluation);
  elements["analytics-builders-tab"].classList.toggle("active", builders);
}

function selectIfPresent(select, value) {
  if (value === null || value === undefined) return;
  if ([...select.options].some((option) => option.value === String(value))) {
    select.value = String(value);
  }
}

function applyCommonFilters(filters = {}) {
  const mapping = {
    "filter-studies": filters.study_ids || [],
    "filter-trials": filters.trial_ids || [],
    "filter-models": filters.models || [],
    "filter-datasets": filters.datasets || [],
    "filter-splits": filters.splits || [],
    "filter-states": filters.states || [],
  };
  for (const [id, values] of Object.entries(mapping)) {
    const selected = new Set(values.map(String));
    for (const option of elements[id].options) option.selected = selected.has(option.value);
  }
  updateActiveFilterCount();
}

function applyChartSpec(spec) {
  elements["analytics-root"].value = spec.artifact_root || "runs";
  elements["chart-name"].value = spec.name || "chart";
  selectIfPresent(elements["chart-metric"], spec.filters?.metrics?.[0]);
  selectIfPresent(elements["chart-stage"], spec.filters?.stages?.[0] || "");
  selectIfPresent(elements["chart-kind"], spec.filters?.kinds?.[0] || "progress");
  selectIfPresent(elements["chart-type"], spec.chart_type || "line");
  selectIfPresent(elements["chart-group"], spec.group_by);
  selectIfPresent(elements["chart-aggregate"], spec.aggregate);
  selectIfPresent(elements["chart-uncertainty"], spec.uncertainty);
  selectIfPresent(elements["chart-scale"], spec.y_scale);
  elements["chart-points"].value = String(spec.max_points ?? 1000);
  elements["chart-series"].value = String(spec.max_series ?? 50);
  elements["chart-title"].value = spec.title || "";
  applyCommonFilters(spec.filters);
}

function applyTableSpec(spec) {
  elements["analytics-root"].value = spec.artifact_root || "runs";
  elements["table-name"].value = spec.name || "table";
  selectIfPresent(elements["table-metric"], spec.filters?.metrics?.[0]);
  selectIfPresent(elements["table-stage"], spec.filters?.stages?.[0] || "");
  selectIfPresent(elements["table-row"], spec.row);
  selectIfPresent(elements["table-column"], spec.column);
  selectIfPresent(elements["table-aggregate"], spec.aggregate);
  selectIfPresent(elements["table-direction"], spec.direction);
  elements["table-precision"].value = String(spec.precision ?? 4);
  elements["table-rows"].value = String(spec.max_rows ?? 100);
  elements["table-columns"].value = String(spec.max_columns ?? 50);
  elements["table-label"].value = spec.label || "";
  elements["table-caption"].value = spec.caption || "";
  applyCommonFilters(spec.filters);
}

async function loadReportSpec() {
  elements["analytics-error"].textContent = "";
  const path = elements["report-spec-path"].value;
  const kind = elements["report-spec-kind"].value;
  if (!path) {
    elements["analytics-error"].textContent = "No saved YAML file is selected.";
    return;
  }
  try {
    const result = await api("/api/analytics/spec/load", {
      method: "POST",
      body: JSON.stringify({ path, kind }),
    });
    elements["analytics-root"].value = result.spec.artifact_root || "runs";
    await refreshAnalytics(false);
    if (kind === "chart") {
      state.loadedChartSpec = structuredClone(result.spec);
      applyChartSpec(result.spec);
    } else {
      state.loadedTableSpec = structuredClone(result.spec);
      applyTableSpec(result.spec);
    }
    setOutput("Report spec loaded", `${result.path}\n${kind}`, "success");
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

function chartSpec() {
  const metric = elements["chart-metric"].value;
  if (!metric) throw new Error("No indexed metric is selected");
  const stage = elements["chart-stage"].value;
  const base = structuredClone(state.loadedChartSpec || {});
  const keep = (values, selected) =>
    Array.isArray(values) && values[0] === selected ? values : selected ? [selected] : [];
  return {
    ...base,
    name: elements["chart-name"].value.trim() || "chart",
    artifact_root: elements["analytics-root"].value.trim() || "runs",
    filters: {
      ...(base.filters || {}),
      ...commonMetricFilters(),
      metrics: keep(base.filters?.metrics, metric),
      stages: keep(base.filters?.stages, stage),
      kinds: keep(base.filters?.kinds, elements["chart-kind"].value),
    },
    chart_type: elements["chart-type"].value,
    group_by: elements["chart-group"].value,
    aggregate: elements["chart-aggregate"].value,
    uncertainty: elements["chart-uncertainty"].value,
    max_points: Number(elements["chart-points"].value),
    max_series: Number(elements["chart-series"].value),
    y_scale: elements["chart-scale"].value,
    title: elements["chart-title"].value.trim() || null,
    x_label: base.x_label || "step",
    y_label: base.y_label || metric,
  };
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function renderBarChart(host, chart, logScale) {
  const observations = chart.series
    .filter((series) => series.points.length)
    .map((series) => ({ name: series.name, ...series.points.at(-1) }))
    .filter((point) => !logScale || point.y > 0);
  if (!observations.length) {
    host.textContent = logScale ? "Log scale requires positive values." : "No matching values.";
    return;
  }
  const width = 900;
  const height = 380;
  const padding = { left: 70, right: 24, top: 38, bottom: 92 };
  const transform = (value) =>
    logScale ? Math.log10(Math.max(Number(value), 1e-300)) : Number(value);
  const lowerValues = observations.map((point) => transform(point.lower));
  const upperValues = observations.map((point) => transform(point.upper));
  let yMin = logScale ? Math.min(...lowerValues) : Math.min(0, ...lowerValues);
  let yMax = Math.max(...upperValues);
  if (yMin === yMax) yMax = yMin + 1;
  const sy = (value) =>
    height -
    padding.bottom -
    ((transform(value) - yMin) / (yMax - yMin)) * (height - padding.top - padding.bottom);
  const plotWidth = width - padding.left - padding.right;
  const slot = plotWidth / observations.length;
  const barWidth = Math.max(4, Math.min(54, slot * 0.64));
  const baseline = sy(logScale ? 10 ** yMin : 0);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.append(
    svgElement("line", {
      x1: padding.left,
      y1: baseline,
      x2: width - padding.right,
      y2: baseline,
      class: "chart-axis",
    }),
  );
  svg.append(
    svgElement("line", {
      x1: padding.left,
      y1: padding.top,
      x2: padding.left,
      y2: height - padding.bottom,
      class: "chart-axis",
    }),
  );
  const colors = ["#7ce5b2", "#79a9ff", "#f3ca78", "#dd8cff", "#ff8c84", "#91d7e3"];
  observations.forEach((point, index) => {
    const center = padding.left + slot * (index + 0.5);
    const top = sy(point.y);
    const rectangle = svgElement("rect", {
      x: center - barWidth / 2,
      y: Math.min(top, baseline),
      width: barWidth,
      height: Math.max(1, Math.abs(baseline - top)),
      rx: 3,
      fill: colors[index % colors.length],
      opacity: 0.86,
    });
    const tooltip = svgElement("title");
    tooltip.textContent = `${point.name}: ${Number(point.y).toPrecision(5)} (n=${point.n})`;
    rectangle.append(tooltip);
    svg.append(rectangle);
    if (chart.spec.uncertainty !== "none") {
      const upper = sy(point.upper);
      const lower = sy(Math.max(point.lower, logScale ? 1e-300 : -Infinity));
      svg.append(
        svgElement("line", {
          x1: center,
          y1: upper,
          x2: center,
          y2: lower,
          class: "chart-error",
        }),
        svgElement("line", {
          x1: center - 5,
          y1: upper,
          x2: center + 5,
          y2: upper,
          class: "chart-error",
        }),
        svgElement("line", {
          x1: center - 5,
          y1: lower,
          x2: center + 5,
          y2: lower,
          class: "chart-error",
        }),
      );
    }
    const label = svgElement("text", {
      x: center,
      y: height - padding.bottom + 15,
      transform: `rotate(-32 ${center} ${height - padding.bottom + 15})`,
      "text-anchor": "end",
      class: "chart-category",
    });
    label.textContent = point.name;
    svg.append(label);
  });
  const title = svgElement("text", { x: padding.left, y: 21, class: "chart-title" });
  title.textContent = chart.spec.title || chart.spec.y_label || "metric";
  svg.append(title);
  host.append(svg);
}

function renderChart(chart) {
  const host = elements["chart-preview"];
  host.replaceChildren();
  if (chart.truncated) {
    const notice = document.createElement("span");
    notice.className = "chart-limit-note";
    notice.textContent = `Showing ${chart.series_count} of ${chart.series_total} series. Narrow filters or raise Max series.`;
    host.append(notice);
  }
  const all = chart.series.flatMap((series) =>
    series.points.map((point) => ({ ...point, series: series.name })),
  );
  if (!all.length) {
    host.textContent = "No matching metric events.";
    return;
  }
  const logScale = chart.spec.y_scale === "log";
  const valid = all.filter((point) => !logScale || point.y > 0);
  if (!valid.length) {
    host.textContent = "Log scale requires positive values.";
    return;
  }
  if (chart.spec.chart_type === "bar") {
    renderBarChart(host, chart, logScale);
    return;
  }
  const width = 900;
  const height = 360;
  const padding = { left: 68, right: 24, top: 30, bottom: 46 };
  const xs = valid.map((point) => Number(point.x));
  const transformed = (value) => (logScale ? Math.log10(Math.max(Number(value), 1e-300)) : Number(value));
  const ys = valid.flatMap((point) => [transformed(point.lower), transformed(point.upper)]);
  let xMin = Math.min(...xs);
  let xMax = Math.max(...xs);
  let yMin = Math.min(...ys);
  let yMax = Math.max(...ys);
  if (xMin === xMax) xMax = xMin + 1;
  if (yMin === yMax) yMax = yMin + 1;
  const sx = (value) => padding.left + ((Number(value) - xMin) / (xMax - xMin)) * (width - padding.left - padding.right);
  const sy = (value) => height - padding.bottom - ((transformed(value) - yMin) / (yMax - yMin)) * (height - padding.top - padding.bottom);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.append(svgElement("line", { x1: padding.left, y1: height - padding.bottom, x2: width - padding.right, y2: height - padding.bottom, class: "chart-axis" }));
  svg.append(svgElement("line", { x1: padding.left, y1: padding.top, x2: padding.left, y2: height - padding.bottom, class: "chart-axis" }));
  const colors = ["#7ce5b2", "#79a9ff", "#f3ca78", "#dd8cff", "#ff8c84", "#91d7e3"];
  chart.series.forEach((series, index) => {
    const points = series.points.filter((point) => !logScale || point.y > 0);
    if (!points.length) return;
    const color = colors[index % colors.length];
    if (chart.spec.uncertainty !== "none") {
      const upper = points.map((point) => `${sx(point.x)},${sy(Math.max(point.upper, logScale ? 1e-300 : -Infinity))}`);
      const lower = [...points].reverse().map((point) => `${sx(point.x)},${sy(Math.max(point.lower, logScale ? 1e-300 : -Infinity))}`);
      svg.append(svgElement("polygon", { points: [...upper, ...lower].join(" "), fill: color, opacity: 0.13 }));
    }
    const path = points.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${sx(point.x)} ${sy(point.y)}`).join(" ");
    svg.append(svgElement("path", { d: path, fill: "none", stroke: color, "stroke-width": 2 }));
    const label = svgElement("text", { x: width - padding.right - 8, y: padding.top + 16 * index, fill: color, "text-anchor": "end", class: "chart-label" });
    label.textContent = series.name;
    svg.append(label);
  });
  const title = svgElement("text", { x: padding.left, y: 19, class: "chart-title" });
  title.textContent = chart.spec.title || chart.spec.y_label || "metric";
  svg.append(title);
  host.append(svg);
}

async function previewChart() {
  elements["analytics-error"].textContent = "";
  try {
    const result = await api("/api/analytics/chart", {
      method: "POST",
      body: JSON.stringify(chartSpec()),
    });
    renderChart(result.chart);
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

function evaluationSpec() {
  const selectionMetric = elements["evaluation-selection-metric"].value;
  const targetMetric = elements["evaluation-target-metric"].value;
  if (!selectionMetric || !targetMetric) {
    throw new Error("Select both a validation/selection metric and a target metric");
  }
  const primary = elements["evaluation-group-primary"].value;
  const secondary = elements["evaluation-group-secondary"].value;
  const groupBy = [...new Set([primary, secondary].filter(Boolean))];
  const filters = commonMetricFilters();
  if (!filters.states.length) filters.states = ["completed"];
  return {
    name: elements["evaluation-name"].value.trim() || "evaluation",
    artifact_root: elements["analytics-root"].value.trim() || "runs",
    filters,
    selection_metric: selectionMetric,
    target_metric: targetMetric,
    stage: elements["evaluation-stage"].value || null,
    selection_split: elements["evaluation-selection-split"].value || null,
    target_split: elements["evaluation-target-split"].value || null,
    direction: elements["evaluation-direction"].value,
    alignment: elements["evaluation-alignment"].value,
    group_by: groupBy,
    precision: Number(elements["evaluation-precision"].value) || 4,
    table_direction: elements["evaluation-table-direction"].value,
    caption: elements["evaluation-caption"].value.trim() || null,
    label: elements["evaluation-label"].value.trim() || null,
    max_runs: Number(elements["evaluation-max-runs"].value) || 2000,
  };
}

async function runEvaluation() {
  elements["analytics-error"].textContent = "";
  elements["run-evaluation"].disabled = true;
  elements["run-evaluation"].textContent = "Evaluating…";
  try {
    const spec = evaluationSpec();
    const result = await api("/api/analytics/evaluate", {
      method: "POST",
      body: JSON.stringify(spec),
    });
    const evaluation = result.evaluation;
    state.currentEvaluationLatex = result.latex;
    elements["evaluation-latex"].textContent = result.latex;
    elements["evaluation-selected-count"].textContent = String(evaluation.selected_runs);
    elements["evaluation-eligible-count"].textContent = String(evaluation.eligible_runs);
    elements["evaluation-excluded-count"].textContent = String(evaluation.excluded_runs);
    elements["evaluation-group-count"].textContent = String(evaluation.groups.length);
    elements["evaluation-provenance"].textContent =
      `${spec.selection_metric} → ${spec.target_metric} · ` +
      `${spec.alignment === "same_step" ? "same step" : "latest target"}` +
      `${evaluation.truncated ? " · truncated" : ""}`;
    renderDataTable(elements["evaluation-groups"], evaluation.groups, [
      { key: "label", label: spec.group_by.join(" / ") },
      { key: "n", label: "Seeds" },
      { key: "mean", label: "Mean", format: (value) => fixed(value, 6) },
      { key: "std", label: "Std", format: (value) => fixed(value, 6) },
      { key: "minimum", label: "Min", format: (value) => fixed(value, 6) },
      { key: "maximum", label: "Max", format: (value) => fixed(value, 6) },
      { key: "seeds", label: "Seed IDs", format: (value) => value.join(", ") },
    ]);
    renderDataTable(elements["evaluation-runs"], evaluation.runs, [
      { key: "eligible", label: "Use", format: (value) => (value ? "yes" : "excluded") },
      { key: "trial_id", label: "Trial" },
      { key: "run_id", label: "Run" },
      { key: "seed", label: "Seed" },
      { key: "selected_step", label: "Best step" },
      { key: "selection_value", label: "Selection", format: (value) => fixed(value, 6) },
      { key: "target_value", label: "Target", format: (value) => fixed(value, 6) },
      { key: "reason", label: "Reason" },
    ]);
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  } finally {
    elements["run-evaluation"].disabled = false;
    elements["run-evaluation"].textContent = "Evaluate runs";
  }
}

async function copyEvaluationLatex() {
  if (!state.currentEvaluationLatex) {
    elements["analytics-error"].textContent = "Evaluate runs before copying LaTeX.";
    return;
  }
  try {
    await navigator.clipboard.writeText(state.currentEvaluationLatex);
    setOutput(
      "Evaluation LaTeX copied",
      `${state.currentEvaluationLatex.length} characters`,
      "success",
    );
  } catch (error) {
    elements["analytics-error"].textContent = `Could not copy LaTeX: ${error.message || error}`;
  }
}

async function exportEvaluation() {
  elements["analytics-error"].textContent = "";
  try {
    const result = await api("/api/analytics/evaluation/export", {
      method: "POST",
      body: JSON.stringify({
        spec: evaluationSpec(),
        output_path: elements["evaluation-output"].value.trim() || null,
      }),
    });
    await reloadWorkspaceFiles();
    setOutput("Evaluation bundle exported", result.path, "success");
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

function tableSpec() {
  const metric = elements["table-metric"].value;
  if (!metric) throw new Error("No indexed metric is selected");
  const stage = elements["table-stage"].value;
  const base = structuredClone(state.loadedTableSpec || {});
  const keep = (values, selected) =>
    Array.isArray(values) && values[0] === selected ? values : selected ? [selected] : [];
  return {
    ...base,
    name: elements["table-name"].value.trim() || "table",
    artifact_root: elements["analytics-root"].value.trim() || "runs",
    filters: {
      ...(base.filters || {}),
      ...commonMetricFilters(),
      metrics: keep(base.filters?.metrics, metric),
      stages: keep(base.filters?.stages, stage),
      kinds: base.filters?.kinds?.length ? base.filters.kinds : ["final"],
    },
    row: elements["table-row"].value,
    column: elements["table-column"].value,
    aggregate: elements["table-aggregate"].value,
    precision: Number(elements["table-precision"].value),
    direction: elements["table-direction"].value,
    bold_best: base.bold_best ?? true,
    underline_second: base.underline_second ?? false,
    caption: elements["table-caption"].value.trim() || null,
    label: elements["table-label"].value.trim() || null,
    missing: base.missing || "--",
    max_rows: Number(elements["table-rows"].value),
    max_columns: Number(elements["table-columns"].value),
  };
}

function tableCellText(cell, spec) {
  if (!cell) return spec.missing || "--";
  const precision = spec.precision || 4;
  const number = (value) => Number(value).toPrecision(precision);
  if (spec.aggregate === "mean_std") {
    return `${number(cell.mean)} ± ${number(cell.std)}`;
  }
  const value = {
    mean: cell.mean,
    min: cell.minimum,
    max: cell.maximum,
  }[spec.aggregate];
  return number(value);
}

function renderVisualTable(data) {
  const host = elements["table-visual-preview"];
  host.replaceChildren();
  if (!data.rows.length || !data.columns.length) {
    host.textContent = "No matching final metric events.";
    return;
  }
  const spec = data.spec;
  const cells = new Map(
    data.cells.map((cell) => [`${cell.row_name}\u0000${cell.column_name}`, cell]),
  );
  const table = document.createElement("table");
  table.className = "publication-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.textContent = spec.row.replaceAll("_", " ");
  headRow.append(corner);
  for (const column of data.columns) {
    const cell = document.createElement("th");
    cell.textContent = column;
    headRow.append(cell);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const rowName of data.rows) {
    const row = document.createElement("tr");
    const label = document.createElement("th");
    label.textContent = rowName;
    row.append(label);
    const rowCells = data.columns.map((column) =>
      cells.get(`${rowName}\u0000${column}`),
    );
    const values = rowCells
      .filter(Boolean)
      .map((cell) => Number(cell.mean))
      .sort((left, right) =>
        spec.direction === "maximize" ? right - left : left - right,
      );
    const distinct = [...new Set(values)];
    rowCells.forEach((cell, index) => {
      const node = document.createElement("td");
      node.textContent = tableCellText(cell, spec);
      if (cell && spec.direction !== "none") {
        const rank = distinct.indexOf(Number(cell.mean)) + 1;
        if (rank === 1 && spec.bold_best) node.classList.add("best-result");
        if (rank === 2 && spec.underline_second) node.classList.add("second-result");
      }
      if (cell) node.title = `n=${cell.n}; min=${cell.minimum}; max=${cell.maximum}`;
      row.append(node);
    });
    body.append(row);
  }
  table.append(head, body);
  host.append(table);
  if (data.truncated) {
    const note = document.createElement("div");
    note.className = "chart-limit-note";
    note.textContent =
      `Showing ${data.rows.length}/${data.row_total} rows and ` +
      `${data.columns.length}/${data.column_total} columns.`;
    host.prepend(note);
  }
}

async function previewTable() {
  elements["analytics-error"].textContent = "";
  try {
    const result = await api("/api/analytics/table", {
      method: "POST",
      body: JSON.stringify(tableSpec()),
    });
    state.currentTableLatex = result.latex;
    elements["table-preview"].textContent = result.latex;
    renderVisualTable(result.table);
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

async function copyTableLatex() {
  if (!state.currentTableLatex) {
    elements["analytics-error"].textContent = "Build the table before copying LaTeX.";
    return;
  }
  try {
    await navigator.clipboard.writeText(state.currentTableLatex);
    setOutput("LaTeX copied", `${state.currentTableLatex.length} characters`, "success");
  } catch (error) {
    elements["analytics-error"].textContent = `Could not copy LaTeX: ${error.message || error}`;
  }
}

async function reloadWorkspaceFiles() {
  state.bootstrap = await api("/api/bootstrap");
  state.files = state.bootstrap.files;
  renderFiles();
}

async function exportReport(kind) {
  elements["analytics-error"].textContent = "";
  try {
    const outputPath =
      elements[kind === "chart" ? "chart-output" : "table-output"].value.trim() || null;
    const formats =
      kind === "chart"
        ? elements["chart-formats"].value
            .split(",")
            .map((value) => value.trim().toLowerCase())
            .filter(Boolean)
        : [];
    if (kind === "chart" && !formats.length) throw new Error("Select at least one chart format");
    const payload =
      kind === "chart"
        ? {
            spec: chartSpec(),
            formats,
            output_path: outputPath,
          }
        : { spec: tableSpec(), output_path: outputPath };
    const result = await api(`/api/analytics/${kind}/export`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await reloadWorkspaceFiles();
    setOutput("Report exported", result.path, "success");
  } catch (error) {
    elements["analytics-error"].textContent = error.message || String(error);
  }
}

function openProjectDialog() {
  elements["project-error"].textContent = "";
  const diagnostics = state.bootstrap.diagnostics || {};
  const connection = state.bootstrap.connection || {};
  const facts = [
    ["ResearchAssistant", diagnostics.research_assistant || "unknown"],
    ["Python", diagnostics.python || "unknown"],
    ["Platform", diagnostics.platform || "unknown"],
    ["Executable", diagnostics.executable || "unknown"],
    ["Connection", `${connection.mode || "local"} · ${connection.hostname || "unknown"}`],
    ["Plugins", state.bootstrap.plugins?.join(", ") || "none"],
  ];
  const host = elements["project-diagnostics"];
  host.replaceChildren();
  for (const [label, value] of facts) {
    const item = document.createElement("div");
    const title = document.createElement("span");
    title.textContent = label;
    const content = document.createElement("code");
    content.textContent = value;
    item.append(title, content);
    host.append(item);
  }
  elements["project-dialog"].showModal();
}

async function initializeProject() {
  elements["project-error"].textContent = "";
  elements["initialize-project"].disabled = true;
  try {
    const result = await api("/api/project/init", {
      method: "POST",
      body: JSON.stringify({}),
    });
    elements["project-result"].textContent =
      `Created:\n${result.created.map((path) => `  ${path}`).join("\n")}\n\n` +
      `Restart the UI with --plugin ${result.plugin} to load the scaffolded plugin.`;
    await reloadWorkspaceFiles();
  } catch (error) {
    elements["project-error"].textContent = error.message || String(error);
  } finally {
    elements["initialize-project"].disabled = false;
  }
}

function installEvents() {
  elements["file-filter"].addEventListener("input", renderFiles);
  elements["component-filter"].addEventListener("input", renderRegistry);
  elements["save-button"].addEventListener("click", saveActive);
  elements["validate-button"].addEventListener("click", openConfigInspector);
  elements["new-file-button"].addEventListener("click", openNewFile);
  elements["new-config-button"].addEventListener("click", openConfigCreator);
  elements["experiments-button"].addEventListener("click", openExperiments);
  elements["checkpoints-button"].addEventListener("click", openCheckpoints);
  elements["analytics-button"].addEventListener("click", openAnalytics);
  elements["project-button"].addEventListener("click", openProjectDialog);
  elements["empty-create-button"].addEventListener("click", openConfigCreator);
  elements["clear-output"].addEventListener("click", () => setOutput("Ready", ""));
  elements["close-config-dialog"].addEventListener("click", closeConfigCreator);
  elements["cancel-config-button"].addEventListener("click", closeConfigCreator);
  elements["add-stage-button"].addEventListener("click", () => addStageRow());
  elements["config-form"].addEventListener("submit", submitCreator);
  elements["config-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["config-dialog"]) closeConfigCreator();
  });
  elements["close-inspect-dialog"].addEventListener("click", () => elements["inspect-dialog"].close());
  elements["inspect-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["inspect-dialog"]) elements["inspect-dialog"].close();
  });
  elements["run-inspection"].addEventListener("click", inspectActiveConfig);
  elements["close-experiments-dialog"].addEventListener("click", closeExperiments);
  elements["experiments-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["experiments-dialog"]) closeExperiments();
  });
  elements["launch-form"].addEventListener("submit", submitLaunch);
  elements["launch-config"].addEventListener("change", previewLaunchPlan);
  elements["launch-policy"].addEventListener("change", previewLaunchPlan);
  elements["launch-artifacts"].addEventListener("change", previewLaunchPlan);
  elements["launch-overrides"].addEventListener("change", previewLaunchPlan);
  elements["launch-policy-overrides"].addEventListener("change", previewLaunchPlan);
  elements["refresh-launches"].addEventListener("click", refreshLaunches);
  elements["close-checkpoints-dialog"].addEventListener("click", () =>
    elements["checkpoints-dialog"].close(),
  );
  elements["checkpoints-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["checkpoints-dialog"]) elements["checkpoints-dialog"].close();
  });
  elements["refresh-checkpoints"].addEventListener("click", refreshCheckpoints);
  elements["checkpoint-root"].addEventListener("change", refreshCheckpoints);
  elements["inference-form"].addEventListener("submit", submitInference);
  elements["preview-inference"].addEventListener("click", previewInference);
  for (const id of [
    "inference-checkpoint",
    "inference-config",
    "inference-splits",
    "inference-device",
    "inference-artifacts",
    "inference-predict",
    "inference-overrides",
    "inference-policy",
    "inference-policy-overrides",
  ]) {
    elements[id].addEventListener("change", previewInference);
  }
  elements["close-analytics-dialog"].addEventListener("click", () => elements["analytics-dialog"].close());
  elements["analytics-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["analytics-dialog"]) elements["analytics-dialog"].close();
  });
  elements["refresh-analytics"].addEventListener("click", async () => {
    try {
      await refreshAnalytics(false);
      await refreshRunOverview();
    } catch (error) {
      elements["analytics-error"].textContent = error.message || String(error);
    }
  });
  elements["rebuild-analytics"].addEventListener("click", async () => {
    try {
      await refreshAnalytics(true);
      await refreshRunOverview();
    } catch (error) {
      elements["analytics-error"].textContent = error.message || String(error);
    }
  });
  elements["refresh-overview"].addEventListener("click", refreshRunOverview);
  elements["analytics-overview-tab"].addEventListener("click", () => showAnalyticsPanel("overview"));
  elements["analytics-evaluation-tab"].addEventListener("click", () =>
    showAnalyticsPanel("evaluation"),
  );
  elements["analytics-builders-tab"].addEventListener("click", () => showAnalyticsPanel("builders"));
  elements["clear-analytics-filters"].addEventListener("click", clearAnalyticsFilters);
  for (const id of [
    "filter-studies",
    "filter-trials",
    "filter-models",
    "filter-datasets",
    "filter-splits",
    "filter-states",
  ]) {
    elements[id].addEventListener("change", updateActiveFilterCount);
  }
  elements["run-evaluation"].addEventListener("click", runEvaluation);
  elements["copy-evaluation-latex"].addEventListener("click", copyEvaluationLatex);
  elements["export-evaluation"].addEventListener("click", exportEvaluation);
  elements["load-report-spec"].addEventListener("click", loadReportSpec);
  elements["chart-kind"].addEventListener("change", () => {
    elements["chart-type"].value =
      elements["chart-kind"].value === "final" ? "bar" : "line";
  });
  elements["preview-chart"].addEventListener("click", previewChart);
  elements["export-chart"].addEventListener("click", () => exportReport("chart"));
  elements["preview-table"].addEventListener("click", previewTable);
  elements["copy-table-latex"].addEventListener("click", copyTableLatex);
  elements["export-table"].addEventListener("click", () => exportReport("table"));
  elements["close-project-dialog"].addEventListener("click", () => elements["project-dialog"].close());
  elements["project-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["project-dialog"]) elements["project-dialog"].close();
  });
  elements["initialize-project"].addEventListener("click", initializeProject);
  window.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveActive();
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if ([...state.buffers.values()].some(bufferDirty)) event.preventDefault();
  });
}

async function start() {
  monaco.editor.defineTheme("ra-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#101514",
      "editor.foreground": "#d9e4df",
      "editor.lineHighlightBackground": "#17201e",
      "editorCursor.foreground": "#7ce5b2",
      "editor.selectionBackground": "#245f4a99",
      "editorLineNumber.foreground": "#52645e",
      "editorLineNumber.activeForeground": "#a7bbb3",
    },
  });
  state.editor = monaco.editor.create(elements.editor, {
    model: null,
    theme: "ra-dark",
    automaticLayout: true,
    fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', monospace",
    fontSize: 14,
    lineHeight: 22,
    minimap: { enabled: true, scale: 1 },
    padding: { top: 14 },
    renderWhitespace: "selection",
    scrollBeyondLastLine: false,
    smoothScrolling: true,
    tabSize: 4,
  });
  state.editor.onDidChangeCursorPosition((event) => {
    elements["cursor-position"].textContent = `Ln ${event.position.lineNumber}, Col ${event.position.column}`;
  });
  state.editor.onDidChangeModel(() => updateEditorState());
  installEvents();

  try {
    state.bootstrap = await api("/api/bootstrap");
    state.files = state.bootstrap.files;
    elements["workspace-name"].textContent = state.bootstrap.workspace.name;
    elements["workspace-name"].title = state.bootstrap.workspace.path;
    const connection = state.bootstrap.connection || {};
    elements["connection-status"].replaceChildren();
    const dot = document.createElement("span");
    dot.className = "status-dot";
    const connectionText = document.createTextNode(
      connection.mode === "ssh" ? ` ssh · ${connection.hostname}` : " local",
    );
    elements["connection-status"].append(dot, connectionText);
    renderFiles();
    renderRegistry();
    if (state.bootstrap.files_truncated) {
      setOutput("Explorer limit", "Only the first 5000 workspace entries are shown.", "error");
    }
  } catch (error) {
    displayError(error, "Cannot initialize UI");
  }
}

start();
