const NOTEBOOK_MARK = "researchAssistantNotebookWorkbench";

if (!globalThis[NOTEBOOK_MARK]) {
  globalThis[NOTEBOOK_MARK] = true;
  installNotebookWorkbench();
}

async function installNotebookWorkbench() {
  const bridge = await waitForNotebookBridge();
  if (!bridge) return;
  installNotebookStyles();

  const state = {
    bridge,
    dialog: null,
    path: null,
    revision: null,
    notebook: null,
    dirty: false,
    editors: new Map(),
    cellViews: new Map(),
    kernel: null,
    socket: null,
    socketReady: null,
    kernels: [],
    sessions: [],
    pending: new Map(),
    runAll: false,
  };
  state.dialog = createNotebookDialog(state);
  document.body.append(state.dialog);

  const button = document.createElement("button");
  button.id = "notebooks-button";
  button.className = "button ghost";
  button.type = "button";
  button.textContent = "Notebooks";
  button.title = "Create or open a Jupyter notebook";
  const newFileButton = document.getElementById("new-file-button");
  newFileButton?.parentNode?.insertBefore(button, newFileButton.nextSibling);
  button.addEventListener("click", () => openNotebookLauncher(state));

  globalThis.__RA_NOTEBOOKS__ = {
    open: (path) => openNotebook(state, path),
    create: () => createNotebook(state),
    get activePath() {
      return state.path;
    },
  };
  addEventListener("ra-open-notebook", (event) => {
    const path = event.detail?.path;
    if (typeof path === "string") openNotebook(state, path).catch(showNotebookError);
  });
}

function waitForNotebookBridge() {
  if (globalThis.__RA_WORKBENCH__) return Promise.resolve(globalThis.__RA_WORKBENCH__);
  return new Promise((resolve) => {
    let attempts = 0;
    const check = () => {
      if (globalThis.__RA_WORKBENCH__) {
        resolve(globalThis.__RA_WORKBENCH__);
        return;
      }
      if (++attempts > 300) {
        resolve(null);
        return;
      }
      setTimeout(check, 50);
    };
    addEventListener("ra-workbench-ready", check, { once: true });
    check();
  });
}

async function notebookApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => ({ detail: response.statusText }))
    : await response.text();
  if (!response.ok) {
    throw new Error(payload?.detail || payload || `Request failed (${response.status})`);
  }
  return payload;
}

function createNotebookDialog(state) {
  const dialog = document.createElement("dialog");
  dialog.className = "raNotebookDialog";
  dialog.innerHTML = `
    <div class="raNotebookLayout">
      <header class="raNotebookHeader">
        <div class="raNotebookIdentity">
          <span class="eyebrow">JUPYTER PROTOCOL · WORKSPACE NATIVE</span>
          <h2 id="ra-notebook-title">Notebook</h2>
          <code id="ra-notebook-path">No notebook open</code>
        </div>
        <div class="raNotebookHeaderActions">
          <button type="button" class="button ghost" data-action="new">New</button>
          <button type="button" class="button ghost" data-action="reload">Reload</button>
          <button type="button" class="button primary" data-action="save">Save</button>
          <button type="button" class="icon-button" data-action="close" aria-label="Close">×</button>
        </div>
      </header>
      <div class="raNotebookToolbar">
        <label><span>Kernel</span><select data-role="kernel-select"></select></label>
        <button type="button" class="button compact primary" data-action="connect">Start / attach</button>
        <button type="button" class="button compact ghost" data-action="run-all">Run all</button>
        <button type="button" class="button compact ghost" data-action="interrupt">Interrupt</button>
        <button type="button" class="button compact ghost" data-action="restart">Restart</button>
        <span class="raNotebookKernelStatus" data-role="kernel-status">No kernel</span>
        <span class="raNotebookSaveStatus" data-role="save-status">Not loaded</span>
      </div>
      <div class="raNotebookInsertBar">
        <button type="button" data-action="add-code">+ Code</button>
        <button type="button" data-action="add-markdown">+ Markdown</button>
        <span>Shift+Enter runs a code cell and advances · Ctrl+Enter runs in place</span>
      </div>
      <main class="raNotebookCells" data-role="cells"></main>
      <footer class="raNotebookFooter">
        <span data-role="footer">Notebook kernels persist across browser and UI-server reconnects.</span>
        <button type="button" class="button compact danger" data-action="shutdown">Shut down kernel</button>
      </footer>
    </div>
  `;

  const action = (name) => dialog.querySelector(`[data-action="${name}"]`);
  action("close").addEventListener("click", () => closeNotebook(state));
  action("new").addEventListener("click", () => createNotebook(state));
  action("reload").addEventListener("click", () => reloadNotebook(state));
  action("save").addEventListener("click", () => saveNotebook(state));
  action("connect").addEventListener("click", () => ensureKernel(state, false));
  action("run-all").addEventListener("click", () => runAllCells(state));
  action("interrupt").addEventListener("click", () => interruptKernel(state));
  action("restart").addEventListener("click", () => restartKernel(state));
  action("shutdown").addEventListener("click", () => shutdownKernel(state));
  action("add-code").addEventListener("click", () => addNotebookCell(state, "code"));
  action("add-markdown").addEventListener("click", () => addNotebookCell(state, "markdown"));
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeNotebook(state);
  });
  return dialog;
}

async function openNotebookLauncher(state) {
  const active = state.bridge.getState?.().activePath;
  if (active?.toLowerCase().endsWith(".ipynb")) {
    await openNotebook(state, active);
    return;
  }
  const path = window.prompt("Notebook path to open, or leave empty to create one", "");
  if (path === null) return;
  if (!path.trim()) {
    await createNotebook(state);
  } else {
    await openNotebook(state, path.trim());
  }
}

async function createNotebook(state) {
  if (!(await confirmDiscardNotebook(state))) return;
  let path = window.prompt("New notebook path", "notebooks/analysis.ipynb");
  if (!path) return;
  path = path.trim();
  if (!path.toLowerCase().endsWith(".ipynb")) path += ".ipynb";
  await refreshKernelCatalog(state);
  const kernelName = selectedKernelName(state) || state.kernels[0]?.name || "python3";
  const result = await notebookApi("/api/notebooks/file", {
    method: "POST",
    body: JSON.stringify({ path, kernel_name: kernelName }),
  });
  await loadNotebookResult(state, result);
  state.dialog.showModal();
}

async function openNotebook(state, path) {
  if (state.path !== path && !(await confirmDiscardNotebook(state))) return;
  const result = await notebookApi(`/api/notebooks/file?path=${encodeURIComponent(path)}`);
  await loadNotebookResult(state, result);
  state.dialog.showModal();
}

async function loadNotebookResult(state, result) {
  disposeNotebookEditors(state);
  closeKernelSocket(state);
  state.path = result.path;
  state.revision = result.revision;
  state.notebook = result.notebook;
  state.dirty = false;
  state.kernel = null;
  state.pending.clear();
  await refreshKernelCatalog(state);
  const existing = state.sessions.find(
    (item) => item.notebook_path === state.path && item.state !== "dead",
  );
  if (existing) {
    state.kernel = existing;
    await connectKernelSocket(state);
  }
  syncNotebookHeader(state);
  renderNotebookCells(state);
}

async function reloadNotebook(state) {
  if (!state.path) return;
  if (state.dirty && !window.confirm("Discard unsaved notebook changes and reload from disk?")) return;
  await openNotebook(state, state.path);
}

async function saveNotebook(state) {
  if (!state.path || !state.notebook) return;
  setNotebookSaveStatus(state, "Saving…");
  try {
    const result = await notebookApi(
      `/api/notebooks/file?path=${encodeURIComponent(state.path)}`,
      {
        method: "PUT",
        body: JSON.stringify({ notebook: state.notebook, revision: state.revision }),
      },
    );
    state.revision = result.revision;
    state.notebook = result.notebook;
    state.dirty = false;
    setNotebookSaveStatus(state, "Saved");
  } catch (error) {
    setNotebookSaveStatus(state, `Save failed: ${error.message}`);
    throw error;
  }
}

function closeNotebook(state) {
  if (state.dirty && !window.confirm("Close with unsaved notebook changes?")) return;
  closeKernelSocket(state);
  state.dialog.close();
}

async function confirmDiscardNotebook(state) {
  return !state.dirty || window.confirm("Discard unsaved changes in the current notebook?");
}

async function refreshKernelCatalog(state) {
  const payload = await notebookApi("/api/notebooks/kernels");
  state.kernels = payload.available || [];
  state.sessions = payload.sessions || [];
  const select = state.dialog.querySelector('[data-role="kernel-select"]');
  const selected = select.value || notebookKernelName(state.notebook) || "python3";
  select.replaceChildren();
  for (const kernel of state.kernels) {
    const option = document.createElement("option");
    option.value = kernel.name;
    option.textContent = `${kernel.display_name}${kernel.language ? ` · ${kernel.language}` : ""}`;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function notebookKernelName(notebook) {
  return notebook?.metadata?.kernelspec?.name || null;
}

function selectedKernelName(state) {
  return state.dialog.querySelector('[data-role="kernel-select"]')?.value || null;
}

async function ensureKernel(state, reuse = true) {
  if (!state.path) throw new Error("Open a notebook first");
  if (state.kernel && state.kernel.state !== "dead") {
    await connectKernelSocket(state);
    return state.kernel;
  }
  setKernelStatus(state, "Starting kernel…");
  const kernelName = selectedKernelName(state) || notebookKernelName(state.notebook) || "python3";
  const kernel = await notebookApi("/api/notebooks/kernels", {
    method: "POST",
    body: JSON.stringify({
      notebook_path: state.path,
      kernel_name: kernelName,
      reuse,
    }),
  });
  state.kernel = kernel;
  state.notebook.metadata ||= {};
  state.notebook.metadata.kernelspec = {
    ...(state.notebook.metadata.kernelspec || {}),
    name: kernel.kernel_name,
    display_name: kernel.display_name,
    language: kernel.language,
  };
  markNotebookDirty(state);
  await connectKernelSocket(state);
  return kernel;
}

async function connectKernelSocket(state) {
  if (!state.kernel) return;
  if (state.socket?.readyState === WebSocket.OPEN) return;
  if (state.socketReady) return state.socketReady;
  closeKernelSocket(state);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/api/notebooks/kernels/${encodeURIComponent(
    state.kernel.kernel_id,
  )}/ws`;
  state.socketReady = new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    state.socket = socket;
    socket.addEventListener("open", () => resolve());
    socket.addEventListener("message", (event) => {
      try {
        handleKernelEvent(state, JSON.parse(event.data));
      } catch (error) {
        console.error(error);
      }
    });
    socket.addEventListener("close", () => {
      if (state.socket === socket) {
        state.socket = null;
        state.socketReady = null;
        setKernelStatus(state, "Disconnected · kernel remains alive");
      }
    });
    socket.addEventListener("error", () => reject(new Error("Cannot connect to notebook kernel")));
  });
  try {
    await state.socketReady;
  } finally {
    state.socketReady = null;
  }
}

function closeKernelSocket(state) {
  const socket = state.socket;
  state.socket = null;
  state.socketReady = null;
  if (socket) {
    try {
      socket.close();
    } catch {}
  }
}

async function runCell(state, cellId, { advance = false } = {}) {
  const cell = findNotebookCell(state, cellId);
  if (!cell || cell.cell_type !== "code") return;
  await ensureKernel(state, true);
  await connectKernelSocket(state);
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel WebSocket is not connected");
  }
  cell.outputs = [];
  cell.execution_count = null;
  updateCellOutputs(state, cellId);
  setCellState(state, cellId, "running");
  const completion = new Promise((resolve, reject) => {
    state.pending.set(cellId, { resolve, reject });
  });
  state.socket.send(
    JSON.stringify({
      type: "execute",
      cell_id: cellId,
      code: cell.source || "",
      store_history: true,
    }),
  );
  if (advance) focusNextNotebookCell(state, cellId);
  return completion;
}

async function runAllCells(state) {
  if (!state.notebook || state.runAll) return;
  state.runAll = true;
  const button = state.dialog.querySelector('[data-action="run-all"]');
  button.disabled = true;
  button.textContent = "Running…";
  try {
    for (const cell of state.notebook.cells) {
      if (cell.cell_type === "code") await runCell(state, cell.id);
    }
  } finally {
    state.runAll = false;
    button.disabled = false;
    button.textContent = "Run all";
  }
}

async function interruptKernel(state) {
  if (!state.kernel) return;
  await notebookApi(`/api/notebooks/kernels/${encodeURIComponent(state.kernel.kernel_id)}/interrupt`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  setKernelStatus(state, "Interrupt requested");
}

async function restartKernel(state) {
  if (!state.kernel) {
    await ensureKernel(state, false);
    return;
  }
  if (!window.confirm("Restart the kernel and lose all in-memory variables?")) return;
  closeKernelSocket(state);
  state.kernel = await notebookApi(
    `/api/notebooks/kernels/${encodeURIComponent(state.kernel.kernel_id)}/restart`,
    { method: "POST", body: JSON.stringify({}) },
  );
  await connectKernelSocket(state);
  setKernelStatus(state, "Kernel restarted");
}

async function shutdownKernel(state) {
  if (!state.kernel) return;
  if (!window.confirm("Shut down this notebook kernel?")) return;
  const kernelId = state.kernel.kernel_id;
  closeKernelSocket(state);
  await notebookApi(`/api/notebooks/kernels/${encodeURIComponent(kernelId)}`, {
    method: "DELETE",
  });
  state.kernel = null;
  setKernelStatus(state, "No kernel");
}

function handleKernelEvent(state, event) {
  if (event.type === "ready") {
    state.kernel = event.kernel;
    setKernelStatus(state, kernelStatusText(event.kernel));
    return;
  }
  if (event.type === "status") {
    if (state.kernel) state.kernel.state = event.state;
    setKernelStatus(state, event.state || "unknown");
    if (event.cell_id) setCellState(state, event.cell_id, event.state === "busy" ? "running" : event.state);
    return;
  }
  if (event.type === "execution_started") {
    setCellState(state, event.cell_id, "running");
    return;
  }
  if (event.type === "execution_complete") {
    setCellState(state, event.cell_id, "idle");
    const pending = state.pending.get(event.cell_id);
    state.pending.delete(event.cell_id);
    pending?.resolve();
    return;
  }
  if (event.type === "kernel_dead") {
    if (state.kernel) state.kernel.state = "dead";
    setKernelStatus(state, "Kernel stopped");
    for (const pending of state.pending.values()) pending.reject(new Error("Kernel stopped"));
    state.pending.clear();
    return;
  }
  if (event.type === "transport_error") {
    setKernelStatus(state, `Kernel transport error: ${event.detail}`);
    return;
  }
  const cell = event.cell_id ? findNotebookCell(state, event.cell_id) : null;
  if (!cell || cell.cell_type !== "code") return;
  const content = event.content || {};
  cell.outputs ||= [];
  if (event.type === "stream") {
    const previous = cell.outputs.at(-1);
    if (previous?.output_type === "stream" && previous.name === content.name) {
      previous.text = `${asText(previous.text)}${asText(content.text)}`;
    } else {
      cell.outputs.push({ output_type: "stream", name: content.name || "stdout", text: asText(content.text) });
    }
  } else if (event.type === "display_data") {
    cell.outputs.push({
      output_type: "display_data",
      data: content.data || {},
      metadata: content.metadata || {},
    });
  } else if (event.type === "execute_result") {
    cell.outputs.push({
      output_type: "execute_result",
      data: content.data || {},
      metadata: content.metadata || {},
      execution_count: content.execution_count ?? event.execution_count ?? null,
    });
  } else if (event.type === "error") {
    cell.outputs.push({
      output_type: "error",
      ename: content.ename || "Error",
      evalue: content.evalue || "",
      traceback: content.traceback || [],
    });
  } else if (event.type === "clear_output") {
    cell.outputs = [];
  } else if (event.type === "execute_input" || event.type === "execute_reply") {
    const count = content.execution_count ?? event.execution_count;
    if (Number.isInteger(count)) cell.execution_count = count;
  } else {
    return;
  }
  markNotebookDirty(state);
  updateCellOutputs(state, cell.id);
  updateCellExecutionCount(state, cell.id);
}

function renderNotebookCells(state) {
  disposeNotebookEditors(state);
  const host = state.dialog.querySelector('[data-role="cells"]');
  host.replaceChildren();
  state.cellViews.clear();
  for (const cell of state.notebook?.cells || []) {
    host.append(renderNotebookCell(state, cell));
  }
  if (!state.notebook?.cells?.length) {
    const empty = document.createElement("div");
    empty.className = "raNotebookEmpty";
    empty.textContent = "This notebook has no cells. Add a code or Markdown cell.";
    host.append(empty);
  }
}

function renderNotebookCell(state, cell) {
  cell.id ||= crypto.randomUUID().replaceAll("-", "").slice(0, 12);
  const article = document.createElement("article");
  article.className = `raNotebookCell ${cell.cell_type}`;
  article.dataset.cellId = cell.id;
  const header = document.createElement("header");
  header.className = "raNotebookCellHeader";
  const type = document.createElement("select");
  for (const value of ["code", "markdown", "raw"]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    type.append(option);
  }
  type.value = cell.cell_type;
  type.addEventListener("change", () => {
    cell.cell_type = type.value;
    if (cell.cell_type === "code") {
      cell.outputs ||= [];
      cell.execution_count ??= null;
    } else {
      delete cell.outputs;
      delete cell.execution_count;
    }
    markNotebookDirty(state);
    renderNotebookCells(state);
  });
  const count = document.createElement("span");
  count.className = "raNotebookExecutionCount";
  count.textContent = executionCountText(cell);
  const activity = document.createElement("span");
  activity.className = "raNotebookCellActivity";
  activity.textContent = "idle";
  const actions = document.createElement("div");
  actions.className = "raNotebookCellActions";
  if (cell.cell_type === "code") {
    actions.append(cellButton("Run", () => runCell(state, cell.id)));
  }
  if (cell.cell_type === "markdown") {
    actions.append(cellButton("Preview", () => toggleMarkdownPreview(state, cell.id)));
  }
  actions.append(
    cellButton("↑", () => moveNotebookCell(state, cell.id, -1), "Move up"),
    cellButton("↓", () => moveNotebookCell(state, cell.id, 1), "Move down"),
    cellButton("+", () => addNotebookCell(state, "code", cell.id), "Add cell below"),
    cellButton("×", () => deleteNotebookCell(state, cell.id), "Delete cell", "danger"),
  );
  header.append(type, count, activity, actions);

  const editorHost = document.createElement("div");
  editorHost.className = "raNotebookCellEditor";
  const preview = document.createElement("div");
  preview.className = "raNotebookMarkdownPreview";
  preview.hidden = true;
  const outputHost = document.createElement("div");
  outputHost.className = "raNotebookOutputs";
  article.append(header, editorHost, preview, outputHost);
  state.cellViews.set(cell.id, { article, count, activity, editorHost, preview, outputHost });
  createCellEditor(state, cell, editorHost);
  updateCellOutputs(state, cell.id);
  return article;
}

function createCellEditor(state, cell, host) {
  const monaco = state.bridge.monaco;
  if (!monaco) {
    const textarea = document.createElement("textarea");
    textarea.value = asText(cell.source);
    textarea.addEventListener("input", () => {
      cell.source = textarea.value;
      markNotebookDirty(state);
    });
    host.append(textarea);
    state.editors.set(cell.id, { dispose() {}, focus: () => textarea.focus() });
    return;
  }
  const language = cell.cell_type === "code" ? notebookLanguage(state.notebook) : "markdown";
  const model = monaco.editor.createModel(
    asText(cell.source),
    language,
    monaco.Uri.parse(`inmemory://ra-notebook/${encodeURIComponent(state.path)}/${cell.id}`),
  );
  const editor = monaco.editor.create(host, {
    model,
    theme: "ra-dark",
    automaticLayout: true,
    minimap: { enabled: false },
    lineNumbers: "on",
    folding: true,
    fontSize: 13,
    lineHeight: 20,
    padding: { top: 8, bottom: 8 },
    scrollBeyondLastLine: false,
    scrollbar: { alwaysConsumeMouseWheel: false },
  });
  const updateHeight = () => {
    const height = Math.max(70, Math.min(700, editor.getContentHeight() + 2));
    host.style.height = `${height}px`;
    editor.layout();
  };
  const change = model.onDidChangeContent(() => {
    cell.source = model.getValue();
    markNotebookDirty(state);
    updateHeight();
  });
  const size = editor.onDidContentSizeChange(updateHeight);
  if (cell.cell_type === "code") {
    editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () =>
      runCell(state, cell.id, { advance: true }),
    );
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => runCell(state, cell.id));
  }
  updateHeight();
  state.editors.set(cell.id, {
    editor,
    model,
    focus: () => editor.focus(),
    dispose() {
      change.dispose();
      size.dispose();
      editor.dispose();
      model.dispose();
    },
  });
}

function disposeNotebookEditors(state) {
  for (const editor of state.editors.values()) editor.dispose();
  state.editors.clear();
}

function updateCellOutputs(state, cellId) {
  const cell = findNotebookCell(state, cellId);
  const view = state.cellViews.get(cellId);
  if (!cell || !view) return;
  view.outputHost.replaceChildren();
  for (const output of cell.outputs || []) {
    view.outputHost.append(renderNotebookOutput(output));
  }
}

function renderNotebookOutput(output) {
  const host = document.createElement("div");
  host.className = `raNotebookOutput ${output.output_type || "unknown"}`;
  if (output.output_type === "stream") {
    const pre = document.createElement("pre");
    pre.textContent = asText(output.text);
    host.append(pre);
  } else if (output.output_type === "error") {
    const pre = document.createElement("pre");
    pre.textContent = (output.traceback || []).join("\n") || `${output.ename}: ${output.evalue}`;
    host.append(pre);
  } else if (output.output_type === "display_data" || output.output_type === "execute_result") {
    host.append(renderMimeBundle(output.data || {}));
  } else {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(output, null, 2);
    host.append(pre);
  }
  return host;
}

function renderMimeBundle(data) {
  if (typeof data["image/png"] === "string") {
    const image = document.createElement("img");
    image.src = `data:image/png;base64,${data["image/png"]}`;
    image.alt = "Notebook output";
    return image;
  }
  if (typeof data["image/jpeg"] === "string") {
    const image = document.createElement("img");
    image.src = `data:image/jpeg;base64,${data["image/jpeg"]}`;
    image.alt = "Notebook output";
    return image;
  }
  const pre = document.createElement("pre");
  if (data["text/plain"] !== undefined) pre.textContent = asText(data["text/plain"]);
  else if (data["application/json"] !== undefined) {
    pre.textContent = JSON.stringify(data["application/json"], null, 2);
  } else if (data["text/html"] !== undefined) {
    pre.textContent = stripHtml(asText(data["text/html"]));
  } else pre.textContent = JSON.stringify(data, null, 2);
  return pre;
}

function toggleMarkdownPreview(state, cellId) {
  const cell = findNotebookCell(state, cellId);
  const view = state.cellViews.get(cellId);
  if (!cell || !view) return;
  view.preview.hidden = !view.preview.hidden;
  view.editorHost.hidden = !view.preview.hidden;
  if (!view.preview.hidden) {
    view.preview.replaceChildren(renderMarkdownSafe(asText(cell.source)));
  }
}

function renderMarkdownSafe(source) {
  const host = document.createElement("div");
  host.className = "raNotebookMarkdownBody";
  const lines = source.split(/\r?\n/);
  let code = false;
  let codeLines = [];
  const flushCode = () => {
    if (!codeLines.length) return;
    const pre = document.createElement("pre");
    const codeNode = document.createElement("code");
    codeNode.textContent = codeLines.join("\n");
    pre.append(codeNode);
    host.append(pre);
    codeLines = [];
  };
  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (code) flushCode();
      code = !code;
      continue;
    }
    if (code) {
      codeLines.push(line);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const node = document.createElement(`h${heading[1].length}`);
      node.textContent = heading[2];
      host.append(node);
    } else if (/^\s*[-*]\s+/.test(line)) {
      const item = document.createElement("div");
      item.className = "raNotebookMarkdownListItem";
      item.textContent = `• ${line.replace(/^\s*[-*]\s+/, "")}`;
      host.append(item);
    } else if (line.trim()) {
      const paragraph = document.createElement("p");
      paragraph.textContent = line;
      host.append(paragraph);
    } else {
      host.append(document.createElement("br"));
    }
  }
  if (code) flushCode();
  return host;
}

function addNotebookCell(state, type, afterId = null) {
  if (!state.notebook) return;
  const cell = {
    id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
    cell_type: type,
    metadata: {},
    source: "",
    ...(type === "code" ? { execution_count: null, outputs: [] } : {}),
  };
  const index = afterId
    ? state.notebook.cells.findIndex((item) => item.id === afterId) + 1
    : state.notebook.cells.length;
  state.notebook.cells.splice(Math.max(0, index), 0, cell);
  markNotebookDirty(state);
  renderNotebookCells(state);
  requestAnimationFrame(() => state.editors.get(cell.id)?.focus());
}

function deleteNotebookCell(state, cellId) {
  const index = state.notebook?.cells.findIndex((item) => item.id === cellId) ?? -1;
  if (index < 0) return;
  state.notebook.cells.splice(index, 1);
  markNotebookDirty(state);
  renderNotebookCells(state);
}

function moveNotebookCell(state, cellId, direction) {
  const cells = state.notebook?.cells || [];
  const index = cells.findIndex((item) => item.id === cellId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= cells.length) return;
  [cells[index], cells[target]] = [cells[target], cells[index]];
  markNotebookDirty(state);
  renderNotebookCells(state);
  requestAnimationFrame(() => state.editors.get(cellId)?.focus());
}

function focusNextNotebookCell(state, cellId) {
  const cells = state.notebook?.cells || [];
  const index = cells.findIndex((item) => item.id === cellId);
  const next = cells[index + 1];
  if (next) {
    requestAnimationFrame(() => state.editors.get(next.id)?.focus());
  } else {
    addNotebookCell(state, "code", cellId);
  }
}

function findNotebookCell(state, cellId) {
  return state.notebook?.cells.find((item) => item.id === cellId) || null;
}

function markNotebookDirty(state) {
  state.dirty = true;
  setNotebookSaveStatus(state, "Modified");
}

function setCellState(state, cellId, value) {
  const view = state.cellViews.get(cellId);
  if (!view) return;
  view.activity.textContent = value || "idle";
  view.article.classList.toggle("running", value === "running" || value === "busy");
}

function updateCellExecutionCount(state, cellId) {
  const cell = findNotebookCell(state, cellId);
  const view = state.cellViews.get(cellId);
  if (cell && view) view.count.textContent = executionCountText(cell);
}

function executionCountText(cell) {
  return cell.cell_type === "code" ? `In [${cell.execution_count ?? " "}]` : cell.cell_type;
}

function syncNotebookHeader(state) {
  state.dialog.querySelector("#ra-notebook-title").textContent =
    state.path?.split("/").at(-1) || "Notebook";
  state.dialog.querySelector("#ra-notebook-path").textContent = state.path || "No notebook open";
  setNotebookSaveStatus(state, state.dirty ? "Modified" : "Saved");
  setKernelStatus(state, state.kernel ? kernelStatusText(state.kernel) : "No kernel");
}

function setNotebookSaveStatus(state, text) {
  state.dialog.querySelector('[data-role="save-status"]').textContent = text;
}

function setKernelStatus(state, text) {
  state.dialog.querySelector('[data-role="kernel-status"]').textContent = text;
}

function kernelStatusText(kernel) {
  return `${kernel.display_name || kernel.kernel_name} · ${kernel.state || "unknown"} · pid ${kernel.pid}`;
}

function notebookLanguage(notebook) {
  const language = notebook?.metadata?.language_info?.name || notebook?.metadata?.kernelspec?.language;
  if (String(language).toLowerCase().includes("python")) return "python";
  if (String(language).toLowerCase().includes("javascript")) return "javascript";
  if (String(language).toLowerCase().includes("typescript")) return "typescript";
  return "plaintext";
}

function cellButton(text, handler, title = text, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `raNotebookCellButton ${className}`.trim();
  button.textContent = text;
  button.title = title;
  button.addEventListener("click", handler);
  return button;
}

function asText(value) {
  if (Array.isArray(value)) return value.join("");
  if (value === null || value === undefined) return "";
  return String(value);
}

function stripHtml(value) {
  const template = document.createElement("template");
  template.innerHTML = value;
  return template.content.textContent || "";
}

function showNotebookError(error) {
  console.error(error);
  window.alert(error.message || String(error));
}

function installNotebookStyles() {
  if (document.getElementById("ra-notebook-styles")) return;
  const style = document.createElement("style");
  style.id = "ra-notebook-styles";
  style.textContent = `
    .raNotebookDialog{width:min(1660px,99vw);height:min(1040px,98vh);padding:0;border:1px solid #3a4b45;border-radius:9px;background:#0c1211;color:#dce7e2;overflow:hidden}
    .raNotebookDialog::backdrop{background:#020806d9}
    .raNotebookLayout{height:100%;display:grid;grid-template-rows:auto auto auto minmax(0,1fr) auto}
    .raNotebookHeader{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;border-bottom:1px solid #2a3a35;background:#101917}
    .raNotebookIdentity{min-width:0}.raNotebookIdentity h2{margin:2px 0}.raNotebookIdentity code{display:block;max-width:850px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8fa69c}
    .raNotebookHeaderActions{display:flex;align-items:center;gap:6px}
    .raNotebookToolbar{display:grid;grid-template-columns:minmax(210px,360px) auto auto auto auto minmax(180px,1fr) auto;gap:7px;align-items:end;padding:8px 14px;border-bottom:1px solid #283833;background:#0e1614}
    .raNotebookToolbar label{display:grid;gap:3px;font-size:10px;color:#8ca198}.raNotebookToolbar select{background:#101a17;color:#e0ebe6;border:1px solid #3a5048;border-radius:5px;padding:6px}
    .raNotebookKernelStatus,.raNotebookSaveStatus{align-self:center;font:11px ui-monospace,SFMono-Regular,Consolas,monospace;color:#91aa9f;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .raNotebookInsertBar{display:flex;align-items:center;gap:6px;padding:6px 14px;border-bottom:1px solid #263630;background:#0b1311;color:#82998f;font-size:11px}
    .raNotebookInsertBar button{border:1px solid #3c554b;border-radius:4px;background:#15221e;color:#cfe0d8;padding:4px 8px;cursor:pointer}.raNotebookInsertBar span{margin-left:auto}
    .raNotebookCells{overflow:auto;padding:18px max(12px,calc((100% - 1120px)/2));background:#0a0f0e}
    .raNotebookCell{margin:0 0 14px;border:1px solid #2f413a;border-radius:7px;background:#101715;box-shadow:0 7px 18px #0004;overflow:hidden}
    .raNotebookCell.running{border-color:#6fc89d;box-shadow:0 0 0 1px #6fc89d55}
    .raNotebookCellHeader{display:grid;grid-template-columns:100px 75px minmax(65px,1fr) auto;gap:7px;align-items:center;padding:5px 7px;border-bottom:1px solid #2b3b35;background:#121d1a}
    .raNotebookCellHeader select{background:#0f1816;color:#dce7e2;border:1px solid #3a5048;border-radius:4px;padding:4px}
    .raNotebookExecutionCount,.raNotebookCellActivity{font:10px ui-monospace,SFMono-Regular,Consolas,monospace;color:#8ba096}.raNotebookCellActivity{text-align:right}
    .raNotebookCellActions{display:flex;gap:4px}.raNotebookCellButton{border:1px solid #3a5048;border-radius:4px;background:#16231f;color:#d8e5df;padding:3px 7px;cursor:pointer}.raNotebookCellButton:hover{background:#21332d}.raNotebookCellButton.danger{color:#f2a8a8}
    .raNotebookCellEditor{min-height:70px}.raNotebookCellEditor textarea{box-sizing:border-box;width:100%;min-height:100px;border:0;background:#0e1413;color:#e3ece8;padding:10px;font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;resize:vertical}
    .raNotebookMarkdownPreview{padding:14px 18px;background:#111917}.raNotebookMarkdownBody{max-width:900px;line-height:1.55}.raNotebookMarkdownBody h1,.raNotebookMarkdownBody h2,.raNotebookMarkdownBody h3{margin:.7em 0 .3em}.raNotebookMarkdownBody p{margin:.45em 0}.raNotebookMarkdownBody pre{padding:10px;background:#080d0c;border-radius:5px;overflow:auto}.raNotebookMarkdownListItem{padding-left:12px}
    .raNotebookOutputs{border-top:1px solid #263630;background:#090e0d}.raNotebookOutputs:empty{display:none}.raNotebookOutput{padding:8px 12px;border-top:1px solid #1d2a26;overflow:auto}.raNotebookOutput:first-child{border-top:0}.raNotebookOutput pre{margin:0;white-space:pre-wrap;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}.raNotebookOutput.error{color:#ff9d9d;background:#241313}.raNotebookOutput img{display:block;max-width:100%;height:auto;background:white}
    .raNotebookFooter{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 12px;border-top:1px solid #2a3a35;background:#0f1715;color:#82978e;font-size:11px}
    .raNotebookEmpty{padding:50px;text-align:center;color:#83968e}.raNotebookDialog .button.danger{background:#572525;border-color:#8d3f3f;color:#ffd8d8}
    @media(max-width:1000px){.raNotebookToolbar{grid-template-columns:1fr 1fr 1fr}.raNotebookInsertBar span{display:none}.raNotebookCellHeader{grid-template-columns:85px 65px 1fr}.raNotebookCellActions{grid-column:1/-1}}
  `;
  document.head.append(style);
}
