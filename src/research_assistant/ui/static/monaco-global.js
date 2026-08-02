(() => {
  const marker = "researchAssistantMonacoBridge";
  if (globalThis[marker]) return;
  globalThis[marker] = true;

  let monacoEnvironment = globalThis.MonacoEnvironment || {};
  monacoEnvironment.globalAPI = true;
  Object.defineProperty(globalThis, "MonacoEnvironment", {
    configurable: true,
    enumerable: true,
    get() {
      return monacoEnvironment;
    },
    set(value) {
      monacoEnvironment = { ...(value || {}), globalAPI: true };
    },
  });

  const state = {
    bootstrap: null,
    dialog: null,
    editor: null,
    tabs: null,
    title: null,
    status: null,
    buffers: new Map(),
    activePath: null,
  };

  function api(path, options = {}) {
    return fetch(path, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    }).then(async (response) => {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
      return payload;
    });
  }

  function languageFor(path) {
    const lower = path.toLowerCase();
    if (lower.endsWith(".py")) return "python";
    if (lower.endsWith(".js") || lower.endsWith(".mjs") || lower.endsWith(".cjs")) {
      return "javascript";
    }
    if (lower.endsWith(".ts") || lower.endsWith(".tsx")) return "typescript";
    if (lower.endsWith(".json")) return "json";
    if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
    if (lower.endsWith(".md")) return "markdown";
    if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
    if (lower.endsWith(".css")) return "css";
    if (lower.endsWith(".ini") || lower.endsWith(".toml")) return "ini";
    if (lower.endsWith(".sh") || lower.endsWith(".bash")) return "shell";
    return "plaintext";
  }

  function installStyles() {
    if (document.getElementById("ra-lazy-editor-styles")) return;
    const style = document.createElement("style");
    style.id = "ra-lazy-editor-styles";
    style.textContent = `
      .raLazyEditorDialog{width:min(1550px,98vw);height:min(960px,96vh);padding:0;border:1px solid #40534b;border-radius:9px;background:#0b1110;color:#dce7e2;overflow:hidden}
      .raLazyEditorDialog::backdrop{background:#020806d9}
      .raLazyEditorLayout{height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto}
      .raLazyEditorHeader{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 11px;border-bottom:1px solid #2a3a35;background:#101917}
      .raLazyEditorHeader strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}
      .raLazyEditorActions{display:flex;gap:6px}.raLazyEditorActions button,.raLazyEditorTab button{border:1px solid #3a5048;border-radius:4px;background:#16231f;color:#d8e5df;padding:5px 8px;cursor:pointer}
      .raLazyEditorActions button:hover,.raLazyEditorTab button:hover{background:#21332d}.raLazyEditorActions .primary{border-color:#5aa982;background:#245f48}.raLazyEditorActions .close{font-size:17px;padding:2px 8px}
      .raLazyEditorTabs{display:flex;gap:3px;padding:5px 7px;border-bottom:1px solid #293a34;background:#0d1513;overflow-x:auto}
      .raLazyEditorTab{display:flex;align-items:center;gap:6px;max-width:300px;border:1px solid #30433c;border-radius:5px;background:#111b18;color:#bfcfc8;padding:4px 6px;cursor:pointer}
      .raLazyEditorTab.active{border-color:#66b990;background:#1a2b25;color:#fff}.raLazyEditorTab span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.raLazyEditorTab button{border:0;background:transparent;padding:0 2px;color:#91a49b}
      .raLazyEditorHost{min-width:0;min-height:0}.raLazyEditorFooter{display:flex;justify-content:space-between;gap:8px;padding:5px 9px;border-top:1px solid #293a34;background:#0e1614;color:#82968d;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}
    `;
    document.head.append(style);
  }

  function ensureDialog(monaco) {
    if (state.dialog) return;
    installStyles();
    const dialog = document.createElement("dialog");
    dialog.className = "raLazyEditorDialog";
    dialog.innerHTML = `
      <div class="raLazyEditorLayout">
        <header class="raLazyEditorHeader">
          <strong data-role="title">Workspace editor</strong>
          <div class="raLazyEditorActions">
            <button type="button" data-action="reload">Reload</button>
            <button type="button" class="primary" data-action="save">Save</button>
            <button type="button" class="close" data-action="close" aria-label="Close">×</button>
          </div>
        </header>
        <div class="raLazyEditorTabs" data-role="tabs"></div>
        <div class="raLazyEditorHost" data-role="host"></div>
        <footer class="raLazyEditorFooter"><span data-role="status">Ready</span><span>Ctrl+S saves</span></footer>
      </div>
    `;
    document.body.append(dialog);
    state.dialog = dialog;
    state.tabs = dialog.querySelector('[data-role="tabs"]');
    state.title = dialog.querySelector('[data-role="title"]');
    state.status = dialog.querySelector('[data-role="status"]');
    state.editor = monaco.editor.create(dialog.querySelector('[data-role="host"]'), {
      theme: "ra-dark",
      automaticLayout: true,
      minimap: { enabled: true },
      fontSize: 13,
      lineHeight: 20,
      folding: true,
      scrollBeyondLastLine: false,
    });
    state.editor.onDidChangeModelContent(() => {
      const buffer = state.buffers.get(state.activePath);
      if (!buffer || buffer.suppressChanges) return;
      buffer.dirty = true;
      renderTabs();
      setStatus("Modified");
    });
    state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      saveActive().catch(showError);
    });
    dialog.querySelector('[data-action="save"]').addEventListener("click", () => {
      saveActive().catch(showError);
    });
    dialog.querySelector('[data-action="reload"]').addEventListener("click", () => {
      reloadActive().catch(showError);
    });
    dialog.querySelector('[data-action="close"]').addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  }

  function setStatus(text) {
    if (state.status) state.status.textContent = text;
  }

  function showError(error) {
    console.error(error);
    setStatus(error.message || String(error));
  }

  function renderTabs() {
    if (!state.tabs) return;
    state.tabs.replaceChildren();
    for (const buffer of state.buffers.values()) {
      const tab = document.createElement("div");
      tab.className = `raLazyEditorTab${buffer.path === state.activePath ? " active" : ""}`;
      tab.title = buffer.path;
      const label = document.createElement("span");
      label.textContent = `${buffer.dirty ? "● " : ""}${buffer.path.split("/").at(-1)}`;
      const close = document.createElement("button");
      close.type = "button";
      close.textContent = "×";
      close.title = "Close file";
      close.addEventListener("click", (event) => {
        event.stopPropagation();
        closeBuffer(buffer.path);
      });
      tab.addEventListener("click", () => activate(buffer.path));
      tab.append(label, close);
      state.tabs.append(tab);
    }
  }

  function activate(path) {
    const buffer = state.buffers.get(path);
    if (!buffer) return;
    state.activePath = path;
    state.editor.setModel(buffer.model);
    state.title.textContent = path;
    setStatus(buffer.dirty ? "Modified" : `Revision ${buffer.revision.slice(0, 10)}`);
    renderTabs();
    state.editor.focus();
  }

  function closeBuffer(path) {
    const buffer = state.buffers.get(path);
    if (!buffer) return;
    if (buffer.dirty && !window.confirm(`Close ${path} with unsaved changes?`)) return;
    const paths = [...state.buffers.keys()];
    const index = paths.indexOf(path);
    buffer.model.dispose();
    state.buffers.delete(path);
    if (state.activePath === path) {
      const next = paths[index + 1] || paths[index - 1] || null;
      state.activePath = null;
      if (next && state.buffers.has(next)) activate(next);
      else {
        state.editor.setModel(null);
        state.title.textContent = "Workspace editor";
        setStatus("No open files");
      }
    }
    renderTabs();
  }

  async function openFile(path) {
    const monaco = globalThis.monaco;
    if (!monaco) throw new Error("Monaco is still loading");
    ensureDialog(monaco);
    let buffer = state.buffers.get(path);
    if (!buffer) {
      setStatus(`Loading ${path}…`);
      const file = await api(`/api/files?path=${encodeURIComponent(path)}`);
      const uri = monaco.Uri.parse(`inmemory://ra-workspace/${encodeURIComponent(path)}`);
      const model = monaco.editor.createModel(file.content, languageFor(path), uri);
      buffer = {
        path,
        revision: file.revision,
        model,
        dirty: false,
        suppressChanges: false,
      };
      state.buffers.set(path, buffer);
    }
    activate(path);
    if (!state.dialog.open) state.dialog.showModal();
    return buffer;
  }

  async function saveActive() {
    const buffer = state.buffers.get(state.activePath);
    if (!buffer) return;
    setStatus("Saving…");
    const saved = await api(`/api/files?path=${encodeURIComponent(buffer.path)}`, {
      method: "PUT",
      body: JSON.stringify({ content: buffer.model.getValue(), revision: buffer.revision }),
    });
    buffer.revision = saved.revision;
    buffer.dirty = false;
    renderTabs();
    setStatus("Saved");
  }

  async function reloadActive() {
    const buffer = state.buffers.get(state.activePath);
    if (!buffer) return;
    if (buffer.dirty && !window.confirm(`Discard unsaved changes in ${buffer.path}?`)) return;
    const file = await api(`/api/files?path=${encodeURIComponent(buffer.path)}`);
    buffer.suppressChanges = true;
    buffer.model.setValue(file.content);
    buffer.suppressChanges = false;
    buffer.revision = file.revision;
    buffer.dirty = false;
    renderTabs();
    setStatus("Reloaded");
  }

  async function installBridge() {
    for (let attempt = 0; attempt < 400; attempt += 1) {
      if (globalThis.__RA_WORKBENCH__) return;
      if (globalThis.monaco) {
        try {
          state.bootstrap = await api("/api/bootstrap");
        } catch (error) {
          console.error(error);
          state.bootstrap = { workspace: { path: location.pathname } };
        }
        if (globalThis.__RA_WORKBENCH__) return;
        globalThis.__RA_WORKBENCH__ = Object.freeze({
          api,
          monaco: globalThis.monaco,
          openFile,
          getState: () => ({ bootstrap: state.bootstrap, activePath: state.activePath }),
        });
        globalThis.dispatchEvent(new CustomEvent("ra-workbench-ready"));
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    console.error("ResearchAssistant: Monaco global API did not become available");
  }

  installBridge();
})();
