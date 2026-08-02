const EXPLORER_MARK = "researchAssistantLazyExplorer";

if (!globalThis[EXPLORER_MARK]) {
  globalThis[EXPLORER_MARK] = true;
  installExplorerWhenReady();
}

async function installExplorerWhenReady() {
  const bridge = await waitForWorkbench();
  const tree = document.getElementById("file-tree");
  const originalFilter = document.getElementById("file-filter");
  const count = document.getElementById("file-count");
  if (!bridge || !tree || !originalFilter || !count) return;

  installExplorerStyles();

  const filter = originalFilter.cloneNode(true);
  originalFilter.replaceWith(filter);
  const searchBox = filter.closest(".search-box");
  const toolbar = document.createElement("div");
  toolbar.className = "raExplorerToolbar";
  toolbar.innerHTML = `
    <button type="button" data-action="refresh" title="Refresh the visible tree">Refresh</button>
    <button type="button" data-action="collapse" title="Collapse all folders">Collapse</button>
    <span class="raExplorerScope">lazy tree</span>
  `;
  searchBox?.after(toolbar);

  const workspacePath = bridge.getState?.().bootstrap?.workspace?.path || location.pathname;
  const storageKey = `ra.explorer.expanded:${workspacePath}`;
  const state = {
    bridge,
    tree,
    filter,
    count,
    toolbar,
    directories: new Map(),
    expanded: new Set(readExpanded(storageKey)),
    storageKey,
    mode: "tree",
    searchQuery: "",
    searchEntries: [],
    searchNextOffset: null,
    searchLoading: false,
    searchError: null,
    searchTimer: null,
  };

  toolbar.querySelector('[data-action="refresh"]').addEventListener("click", async () => {
    if (state.mode === "search") {
      await runSearch(state, true);
    } else {
      state.directories.clear();
      await ensureDirectory(state, "", true);
      await restoreExpandedDirectories(state);
    }
    renderExplorer(state);
  });
  toolbar.querySelector('[data-action="collapse"]').addEventListener("click", () => {
    state.mode = "tree";
    state.expanded.clear();
    persistExpanded(state);
    renderExplorer(state);
  });

  filter.placeholder = "Search the entire workspace…";
  filter.setAttribute("aria-label", "Search all workspace paths");
  filter.addEventListener("input", () => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(async () => {
      const query = filter.value.trim();
      if (!query) {
        state.mode = "tree";
        state.searchQuery = "";
        renderExplorer(state);
        return;
      }
      state.mode = "search";
      state.searchQuery = query;
      await runSearch(state, true);
      renderExplorer(state);
    }, 180);
  });

  tree.addEventListener("click", (event) => handleExplorerClick(state, event));
  const observer = new MutationObserver(() => {
    const root = tree.firstElementChild;
    if (!root || root.dataset.raExplorerRoot !== "true") {
      queueMicrotask(() => renderExplorer(state));
    }
  });
  observer.observe(tree, { childList: true });

  await ensureDirectory(state, "", true);
  await restoreExpandedDirectories(state);
  renderExplorer(state);
}

function waitForWorkbench() {
  if (globalThis.__RA_WORKBENCH__) return Promise.resolve(globalThis.__RA_WORKBENCH__);
  return new Promise((resolve) => {
    let attempts = 0;
    const check = () => {
      if (globalThis.__RA_WORKBENCH__) {
        resolve(globalThis.__RA_WORKBENCH__);
        return;
      }
      attempts += 1;
      if (attempts > 300) {
        resolve(null);
        return;
      }
      setTimeout(check, 50);
    };
    addEventListener("ra-workbench-ready", check, { once: true });
    check();
  });
}

function readExpanded(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.filter((item) => typeof item === "string").slice(0, 200) : [];
  } catch {
    return [];
  }
}

function persistExpanded(state) {
  try {
    localStorage.setItem(state.storageKey, JSON.stringify([...state.expanded].slice(0, 200)));
  } catch {}
}

async function explorerApi(path) {
  const response = await fetch(path, { cache: "no-store" });
  const payload = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

async function ensureDirectory(state, path, reset = false) {
  const current = state.directories.get(path);
  if (current?.loading) return current.promise;
  if (current && !reset) return current;
  const record = {
    entries: reset ? [] : current?.entries || [],
    nextOffset: reset ? 0 : current?.nextOffset ?? 0,
    total: reset ? null : current?.total ?? null,
    loading: true,
    error: null,
    promise: null,
  };
  state.directories.set(path, record);
  const offset = reset ? 0 : record.nextOffset || 0;
  record.promise = explorerApi(
    `/api/workspace/entries?path=${encodeURIComponent(path)}&offset=${offset}&limit=250`,
  )
    .then((payload) => {
      record.entries = reset ? payload.entries || [] : [...record.entries, ...(payload.entries || [])];
      record.nextOffset = payload.next_offset;
      record.total = payload.total;
      record.loading = false;
      return record;
    })
    .catch((error) => {
      record.loading = false;
      record.error = error.message || String(error);
      return record;
    });
  return record.promise;
}

async function restoreExpandedDirectories(state) {
  const paths = [...state.expanded].sort((left, right) => left.split("/").length - right.split("/").length);
  for (const path of paths.slice(0, 100)) {
    await ensureDirectory(state, path);
  }
}

async function runSearch(state, reset) {
  if (!state.searchQuery || state.searchLoading) return;
  state.searchLoading = true;
  state.searchError = null;
  if (reset) {
    state.searchEntries = [];
    state.searchNextOffset = 0;
  }
  const offset = state.searchNextOffset || 0;
  try {
    const payload = await explorerApi(
      `/api/workspace/search?query=${encodeURIComponent(state.searchQuery)}&offset=${offset}&limit=300`,
    );
    state.searchEntries = reset
      ? payload.entries || []
      : [...state.searchEntries, ...(payload.entries || [])];
    state.searchNextOffset = payload.next_offset;
  } catch (error) {
    state.searchError = error.message || String(error);
  } finally {
    state.searchLoading = false;
  }
}

async function handleExplorerClick(state, event) {
  const action = event.target.closest("[data-ra-action]");
  if (!action) return;
  const kind = action.dataset.raAction;
  const path = action.dataset.path || "";
  if (kind === "toggle") {
    if (state.expanded.has(path)) {
      state.expanded.delete(path);
    } else {
      state.expanded.add(path);
      await ensureDirectory(state, path);
    }
    persistExpanded(state);
    renderExplorer(state);
    return;
  }
  if (kind === "more-directory") {
    await ensureDirectory(state, path, false);
    renderExplorer(state);
    return;
  }
  if (kind === "more-search") {
    await runSearch(state, false);
    renderExplorer(state);
    return;
  }
  if (kind === "open") {
    await openWorkspaceEntry(state, path, action.dataset.notebook === "true");
  }
}

async function openWorkspaceEntry(state, path, notebook) {
  if (notebook || path.toLowerCase().endsWith(".ipynb")) {
    if (globalThis.__RA_NOTEBOOKS__?.open) {
      await globalThis.__RA_NOTEBOOKS__.open(path);
    } else {
      dispatchEvent(new CustomEvent("ra-open-notebook", { detail: { path } }));
    }
    return;
  }
  await state.bridge.openFile(path);
}

function renderExplorer(state) {
  const root = document.createElement("div");
  root.dataset.raExplorerRoot = "true";
  root.className = "raExplorerRoot";
  if (state.mode === "search") {
    renderSearch(state, root);
  } else {
    const record = state.directories.get("");
    if (!record || record.loading) {
      root.append(explorerMessage("Loading workspace…"));
    } else if (record.error) {
      root.append(explorerMessage(record.error, "error"));
    } else {
      renderEntries(state, root, record.entries, 0);
      appendDirectoryMore(state, root, "", record, 0);
      if (!record.entries.length) root.append(explorerMessage("Workspace is empty."));
    }
    const loaded = [...state.directories.values()].reduce(
      (total, item) => total + item.entries.length,
      0,
    );
    state.count.textContent = String(loaded);
    state.count.title = `${loaded} loaded lazily; folders are fetched when expanded`;
    state.toolbar.querySelector(".raExplorerScope").textContent = `${state.expanded.size} open`;
  }
  state.tree.replaceChildren(root);
}

function renderEntries(state, host, entries, depth) {
  for (const entry of entries) {
    if (entry.kind === "directory") {
      renderDirectory(state, host, entry, depth);
    } else {
      host.append(renderFile(entry, depth));
    }
  }
}

function renderDirectory(state, host, entry, depth) {
  const expanded = state.expanded.has(entry.path);
  const row = document.createElement("button");
  row.type = "button";
  row.className = "raExplorerRow directory";
  row.style.setProperty("--depth", String(depth));
  row.dataset.raAction = "toggle";
  row.dataset.path = entry.path;
  row.setAttribute("aria-expanded", String(expanded));
  row.title = entry.path;
  row.innerHTML = `
    <span class="raExplorerChevron">${entry.has_children === false ? "·" : expanded ? "▾" : "▸"}</span>
    <span class="raExplorerIcon">${expanded ? "▾" : "▸"}</span>
    <span class="raExplorerName"></span>
  `;
  row.querySelector(".raExplorerName").textContent = entry.name;
  host.append(row);
  if (!expanded) return;

  const record = state.directories.get(entry.path);
  if (!record || record.loading) {
    host.append(explorerMessage("Loading…", "neutral", depth + 1));
    return;
  }
  if (record.error) {
    host.append(explorerMessage(record.error, "error", depth + 1));
    return;
  }
  renderEntries(state, host, record.entries, depth + 1);
  appendDirectoryMore(state, host, entry.path, record, depth + 1);
  if (!record.entries.length) host.append(explorerMessage("Empty folder", "neutral", depth + 1));
}

function renderFile(entry, depth, showPath = false) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = `raExplorerRow file${entry.editable === false && !entry.notebook ? " disabled" : ""}`;
  row.style.setProperty("--depth", String(depth));
  row.dataset.raAction = "open";
  row.dataset.path = entry.path;
  row.dataset.notebook = String(Boolean(entry.notebook || entry.path.toLowerCase().endsWith(".ipynb")));
  row.title = `${entry.path}${entry.size !== undefined ? ` · ${formatBytes(entry.size)}` : ""}`;
  const icon = document.createElement("span");
  icon.className = "raExplorerIcon";
  icon.textContent = fileIcon(entry);
  const label = document.createElement("span");
  label.className = "raExplorerName";
  label.textContent = showPath ? entry.path : entry.name;
  row.append(icon, label);
  if (showPath) {
    const kind = document.createElement("span");
    kind.className = "raExplorerMatchKind";
    kind.textContent = entry.kind === "directory" ? "folder" : entry.notebook ? "notebook" : "file";
    row.append(kind);
  }
  return row;
}

function appendDirectoryMore(state, host, path, record, depth) {
  if (record.nextOffset === null || record.nextOffset === undefined) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "raExplorerMore";
  button.style.setProperty("--depth", String(depth));
  button.dataset.raAction = "more-directory";
  button.dataset.path = path;
  button.textContent = `Load more… (${record.entries.length}/${record.total ?? "?"})`;
  host.append(button);
}

function renderSearch(state, root) {
  state.toolbar.querySelector(".raExplorerScope").textContent = "workspace search";
  if (state.searchError) root.append(explorerMessage(state.searchError, "error"));
  for (const entry of state.searchEntries) {
    if (entry.kind === "directory") {
      const row = renderFile(entry, 0, true);
      row.dataset.raAction = "toggle";
      root.append(row);
    } else {
      root.append(renderFile(entry, 0, true));
    }
  }
  if (state.searchLoading) root.append(explorerMessage("Searching…"));
  if (!state.searchLoading && !state.searchEntries.length && !state.searchError) {
    root.append(explorerMessage(`No paths match “${state.searchQuery}”.`));
  }
  if (state.searchNextOffset !== null && state.searchNextOffset !== undefined) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "raExplorerMore";
    more.dataset.raAction = "more-search";
    more.textContent = "Load more search results…";
    root.append(more);
  }
  state.count.textContent = String(state.searchEntries.length);
  state.count.title = "Loaded search results";
}

function explorerMessage(text, kind = "neutral", depth = 0) {
  const message = document.createElement("div");
  message.className = `raExplorerMessage ${kind}`;
  message.style.setProperty("--depth", String(depth));
  message.textContent = text;
  return message;
}

function fileIcon(entry) {
  const path = entry.path.toLowerCase();
  if (entry.notebook || path.endsWith(".ipynb")) return "◫";
  if (/\.py$/.test(path)) return "Py";
  if (/\.ya?ml$/.test(path)) return "Y";
  if (/\.json$/.test(path)) return "{}";
  if (/\.md$/.test(path)) return "M";
  if (/\.(png|jpe?g|gif|webp|svg|pdf)$/.test(path)) return "▧";
  return "·";
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 ** 2).toFixed(1)} MiB`;
}

function installExplorerStyles() {
  if (document.getElementById("ra-explorer-plus-styles")) return;
  const style = document.createElement("style");
  style.id = "ra-explorer-plus-styles";
  style.textContent = `
    .raExplorerToolbar{display:flex;align-items:center;gap:5px;padding:0 10px 8px;color:#8fa49b;font-size:11px}
    .raExplorerToolbar button{border:1px solid #33443e;border-radius:4px;background:#131b19;color:#c8d6d0;padding:3px 7px;cursor:pointer}
    .raExplorerToolbar button:hover{border-color:#5f8877;background:#1a2521}
    .raExplorerScope{margin-left:auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .raExplorerRoot{min-width:max-content;padding-bottom:12px}
    .raExplorerRow{width:100%;min-width:210px;display:grid;grid-template-columns:18px minmax(0,1fr) auto;align-items:center;gap:4px;border:0;background:transparent;color:inherit;text-align:left;padding:4px 8px 4px calc(8px + var(--depth,0) * 14px);font:12px/1.25 ui-monospace,SFMono-Regular,Consolas,monospace;cursor:pointer}
    .raExplorerRow:hover{background:#1c2824}.raExplorerRow:focus-visible{outline:1px solid #6bb893;outline-offset:-1px}
    .raExplorerRow.directory{font-weight:600}.raExplorerRow.file.disabled{opacity:.55}
    .raExplorerChevron{width:14px;text-align:center;color:#8ca79b}.raExplorerRow.file .raExplorerChevron{display:none}
    .raExplorerIcon{width:18px;text-align:center;color:#76c9a2;font-size:10px}.raExplorerName{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .raExplorerMatchKind{margin-left:10px;color:#71857c;font-size:10px}
    .raExplorerMore{display:block;width:calc(100% - 8px);border:0;background:transparent;color:#7fc9a7;text-align:left;padding:5px 8px 5px calc(26px + var(--depth,0) * 14px);font-size:11px;cursor:pointer}
    .raExplorerMore:hover{background:#1c2824}
    .raExplorerMessage{padding:6px 8px 6px calc(26px + var(--depth,0) * 14px);color:#82968d;font-size:11px;white-space:normal;max-width:250px}.raExplorerMessage.error{color:#f39a9a}
    #file-tree{overflow:auto}
  `;
  document.head.append(style);
}
