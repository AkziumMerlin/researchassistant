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

async function validateActive() {
  const buffer = state.activePath ? state.buffers.get(state.activePath) : null;
  if (!buffer || !isConfigPath(buffer.path)) return;
  setOutput("Validating", `Compiling ${buffer.path}…`, "neutral");
  try {
    const result = await api("/api/config/validate", {
      method: "POST",
      body: JSON.stringify({ path: buffer.path, content: buffer.model.getValue() }),
    });
    const plan = result.plan;
    setOutput(
      "Valid experiment",
      [
        `experiment  ${result.experiment}`,
        `study       ${plan.study_id}`,
        `runs        ${plan.runs}`,
        `trials      ${plan.trials}`,
        "",
        ...plan.run_ids.map((id) => `run         ${id}`),
      ].join("\n"),
      "success",
    );
  } catch (error) {
    displayError(error, "Invalid experiment");
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

function installEvents() {
  elements["file-filter"].addEventListener("input", renderFiles);
  elements["component-filter"].addEventListener("input", renderRegistry);
  elements["save-button"].addEventListener("click", saveActive);
  elements["validate-button"].addEventListener("click", validateActive);
  elements["new-file-button"].addEventListener("click", openNewFile);
  elements["new-config-button"].addEventListener("click", openConfigCreator);
  elements["empty-create-button"].addEventListener("click", openConfigCreator);
  elements["clear-output"].addEventListener("click", () => setOutput("Ready", ""));
  elements["close-config-dialog"].addEventListener("click", closeConfigCreator);
  elements["cancel-config-button"].addEventListener("click", closeConfigCreator);
  elements["add-stage-button"].addEventListener("click", () => addStageRow());
  elements["config-form"].addEventListener("submit", submitCreator);
  elements["config-dialog"].addEventListener("click", (event) => {
    if (event.target === elements["config-dialog"]) closeConfigCreator();
  });
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
