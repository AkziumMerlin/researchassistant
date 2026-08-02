const terminalFetch = window.fetch.bind(window);

async function terminalApi(path, options = {}) {
  const response = await terminalFetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.message || response.statusText);
  return payload;
}

function terminalElement(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
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

function terminalButton(text, handler, className = "") {
  return terminalElement("button", {
    class: `raTerminalButton ${className}`.trim(),
    text,
    onclick: handler,
  });
}

const terminalState = {
  dialog: null,
  host: null,
  tabs: null,
  status: null,
  cwd: null,
  shell: null,
  title: null,
  workspace: "",
  defaultShell: "",
  persistent: false,
  persistenceBackend: "process",
  persistenceMessage: "",
  sessions: [],
  activeId: null,
  client: null,
  runtime: null,
};

function installTerminalStyles() {
  if (document.querySelector("#ra-terminal-styles")) return;
  document.head.append(terminalElement("style", {
    id: "ra-terminal-styles",
    text: `
      .raTerminalDialog{width:min(1500px,98vw);height:min(980px,96vh);padding:0;border:1px solid #475569;border-radius:10px;background:#070b12;color:#e5e7eb;overflow:hidden}
      .raTerminalDialog::backdrop{background:#000b}
      .raTerminalLayout{height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto}
      .raTerminalHeader{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid #263244;background:#0b1220;min-width:0}
      .raTerminalTitle{font-weight:650;white-space:nowrap}
      .raTerminalControls{display:flex;align-items:center;gap:7px;min-width:0;flex:1}
      .raTerminalControls input{min-width:0;background:#030712;color:#f8fafc;border:1px solid #475569;border-radius:5px;padding:6px 8px;font:12px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace}
      .raTerminalControls .cwd{flex:1.4}.raTerminalControls .shell{flex:1}.raTerminalControls .title{width:140px}
      .raTerminalButton{background:#172033;color:#f8fafc;border:1px solid #475569;border-radius:5px;padding:6px 9px;cursor:pointer;white-space:nowrap}
      .raTerminalButton:hover{background:#24324a}.raTerminalButton.primary{background:#1d4ed8;border-color:#60a5fa}.raTerminalButton.danger{background:#7f1d1d;border-color:#b91c1c}.raTerminalButton:disabled{opacity:.5;cursor:not-allowed}
      .raTerminalTabs{display:flex;align-items:stretch;gap:3px;padding:5px 8px;background:#0a101b;border-bottom:1px solid #263244;overflow-x:auto;min-height:38px}
      .raTerminalTab{display:flex;align-items:center;gap:6px;max-width:260px;padding:5px 8px;border:1px solid #334155;border-radius:5px;background:#111827;color:#cbd5e1;cursor:pointer}
      .raTerminalTab.active{background:#1e293b;color:#fff;border-color:#64748b}.raTerminalTab.exited{opacity:.7}
      .raTerminalTabLabel{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.raTerminalTabClose{border:0;background:transparent;color:#94a3b8;cursor:pointer;font-size:15px;line-height:1;padding:0 1px}.raTerminalTabClose:hover{color:#fff}
      .raTerminalHost{position:relative;min-width:0;min-height:0;padding:6px;background:#05070b;overflow:hidden}
      .raTerminalHost .xterm{height:100%}.raTerminalHost .xterm-viewport{scrollbar-color:#475569 #0b1220}
      .raTerminalEmpty{height:100%;display:grid;place-items:center;color:#94a3b8;font:13px ui-monospace,SFMono-Regular,Consolas,monospace}
      .raTerminalFooter{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:5px 10px;border-top:1px solid #263244;background:#0b1220;color:#94a3b8;font:12px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace}
      .raTerminalFooterActions{display:flex;gap:5px}.raTerminalFooter .raTerminalButton{padding:3px 7px;font-size:11px}
      @media(max-width:900px){.raTerminalHeader{align-items:stretch;flex-direction:column}.raTerminalControls{width:100%;flex-wrap:wrap}.raTerminalControls input{flex:1 1 180px!important;width:auto!important}}
    `,
  }));
}

async function loadTerminalRuntime() {
  if (terminalState.runtime) return terminalState.runtime;
  terminalState.runtime = await import("/api/extensions/terminal-runtime.js");
  if (!document.querySelector("#ra-xterm-styles")) {
    document.head.append(terminalElement("style", {
      id: "ra-xterm-styles",
      text: terminalState.runtime.xtermCss,
    }));
  }
  return terminalState.runtime;
}

function setTerminalStatus(text) {
  if (terminalState.status) terminalState.status.textContent = text;
}

function activeSession() {
  return terminalState.sessions.find((session) => session.session_id === terminalState.activeId) || null;
}

function disposeTerminalClient() {
  const client = terminalState.client;
  terminalState.client = null;
  if (!client) return;
  client.disposed = true;
  clearTimeout(client.retryTimer);
  client.resizeObserver?.disconnect();
  client.dataDisposable?.dispose();
  client.keyDisposable?.dispose?.();
  try { client.socket?.close(); } catch {}
  client.terminal?.dispose();
}

function renderTerminalTabs() {
  const tabs = terminalState.tabs;
  if (!tabs) return;
  tabs.replaceChildren();
  for (const session of terminalState.sessions) {
    const label = terminalElement("span", {
      class: "raTerminalTabLabel",
      text: `${session.title}${session.state === "running" ? "" : ` · ${session.state}`}`,
    });
    const close = terminalElement("button", {
      class: "raTerminalTabClose",
      text: "×",
      title: "Close terminal process",
      onclick: async (event) => {
        event.stopPropagation();
        await closeTerminalSession(session.session_id);
      },
    });
    const tab = terminalElement("div", {
      class: `raTerminalTab ${session.session_id === terminalState.activeId ? "active" : ""} ${session.state === "running" ? "" : "exited"}`,
      onclick: () => activateTerminalSession(session.session_id),
      title: `${session.shell}\n${session.cwd}\n${session.persistent ? "Persistent tmux session" : "Backend-owned session"}`,
    }, [label, close]);
    tabs.append(tab);
  }
}

async function refreshTerminalSessions({ attach = false } = {}) {
  const payload = await terminalApi("/api/terminals");
  terminalState.workspace = payload.workspace || "";
  terminalState.defaultShell = payload.default_shell || "";
  terminalState.persistent = Boolean(payload.persistent);
  terminalState.persistenceBackend = payload.backend || "process";
  terminalState.persistenceMessage = payload.persistence_message || "";
  terminalState.sessions = payload.sessions || [];
  if (terminalState.cwd && !terminalState.cwd.value) terminalState.cwd.value = terminalState.workspace;
  if (terminalState.shell && !terminalState.shell.value) terminalState.shell.value = terminalState.defaultShell;
  if (!terminalState.sessions.some((session) => session.session_id === terminalState.activeId)) {
    terminalState.activeId = terminalState.sessions.at(-1)?.session_id || null;
  }
  renderTerminalTabs();
  if (attach && terminalState.activeId) await attachTerminalSession(terminalState.activeId);
  if (!terminalState.activeId && terminalState.persistenceMessage) {
    setTerminalStatus(terminalState.persistenceMessage);
  }
  return payload;
}

async function createTerminalSession() {
  setTerminalStatus("Starting terminal…");
  const session = await terminalApi("/api/terminals", {
    method: "POST",
    body: JSON.stringify({
      cwd: terminalState.cwd.value || null,
      shell: terminalState.shell.value || null,
      title: terminalState.title.value || null,
      cols: 100,
      rows: 30,
    }),
  });
  terminalState.title.value = "";
  terminalState.sessions.push(session);
  terminalState.activeId = session.session_id;
  renderTerminalTabs();
  await attachTerminalSession(session.session_id);
}

async function closeTerminalSession(sessionId) {
  if (terminalState.activeId === sessionId) disposeTerminalClient();
  setTerminalStatus("Closing terminal…");
  try {
    await terminalApi(`/api/terminals/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  } catch (error) {
    setTerminalStatus(error.message);
  }
  terminalState.sessions = terminalState.sessions.filter((session) => session.session_id !== sessionId);
  if (terminalState.activeId === sessionId) {
    terminalState.activeId = terminalState.sessions.at(-1)?.session_id || null;
  }
  renderTerminalTabs();
  if (terminalState.activeId) await attachTerminalSession(terminalState.activeId);
  else {
    terminalState.host.replaceChildren(terminalElement("div", { class: "raTerminalEmpty", text: "No terminal sessions" }));
    setTerminalStatus(terminalState.persistenceMessage || "No terminal sessions");
  }
}

async function activateTerminalSession(sessionId) {
  if (terminalState.activeId === sessionId && terminalState.client) {
    terminalState.client.terminal.focus();
    return;
  }
  terminalState.activeId = sessionId;
  renderTerminalTabs();
  await attachTerminalSession(sessionId);
}

async function attachTerminalSession(sessionId) {
  disposeTerminalClient();
  const session = terminalState.sessions.find((item) => item.session_id === sessionId);
  if (!session) return;
  const { Terminal, FitAddon } = await loadTerminalRuntime();
  const host = terminalState.host;
  host.replaceChildren();
  const terminal = new Terminal({
    allowProposedApi: false,
    convertEol: false,
    cursorBlink: true,
    cursorStyle: "block",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 13,
    lineHeight: 1.15,
    scrollback: 15000,
    theme: {
      background: "#05070b",
      foreground: "#e5e7eb",
      cursor: "#f8fafc",
      selectionBackground: "#334155aa",
      black: "#111827",
      brightBlack: "#64748b",
      red: "#ef4444",
      brightRed: "#f87171",
      green: "#22c55e",
      brightGreen: "#4ade80",
      yellow: "#eab308",
      brightYellow: "#facc15",
      blue: "#3b82f6",
      brightBlue: "#60a5fa",
      magenta: "#a855f7",
      brightMagenta: "#c084fc",
      cyan: "#06b6d4",
      brightCyan: "#22d3ee",
      white: "#d1d5db",
      brightWhite: "#f9fafb",
    },
  });
  const fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(host);

  const client = {
    sessionId,
    session,
    terminal,
    fitAddon,
    socket: null,
    disposed: false,
    retryTimer: null,
    reconnectAttempt: 0,
    resizeObserver: null,
    dataDisposable: null,
    keyDisposable: null,
  };
  terminalState.client = client;

  const send = (payload) => {
    if (client.socket?.readyState === WebSocket.OPEN) {
      client.socket.send(JSON.stringify(payload));
    }
  };

  const fit = () => {
    if (client.disposed || !host.isConnected) return;
    try {
      fitAddon.fit();
      send({ type: "resize", cols: terminal.cols, rows: terminal.rows });
    } catch {}
  };

  client.dataDisposable = terminal.onData((data) => send({ type: "input", data }));
  terminal.attachCustomKeyEventHandler((event) => {
    if (event.type !== "keydown") return true;
    if (event.ctrlKey && event.shiftKey && event.code === "KeyC" && terminal.hasSelection()) {
      navigator.clipboard?.writeText(terminal.getSelection()).catch(() => {});
      return false;
    }
    if (event.ctrlKey && event.shiftKey && event.code === "KeyV") {
      navigator.clipboard?.readText().then((text) => send({ type: "input", data: text })).catch(() => {});
      return false;
    }
    return true;
  });
  client.resizeObserver = new ResizeObserver(() => requestAnimationFrame(fit));
  client.resizeObserver.observe(host);

  const connect = (manual = false) => {
    if (client.disposed || terminalState.activeId !== sessionId) return;
    clearTimeout(client.retryTimer);
    if (client.socket) {
      try { client.socket.close(); } catch {}
    }
    if (client.reconnectAttempt > 0 || manual) terminal.reset();
    setTerminalStatus(`Connecting · ${session.cwd}`);
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/terminals/${encodeURIComponent(sessionId)}/ws`);
    socket.binaryType = "arraybuffer";
    client.socket = socket;
    socket.addEventListener("open", () => {
      if (client.disposed || client.socket !== socket) return;
      client.reconnectAttempt = 0;
      const persistence = session.persistent || terminalState.persistent ? ` · ${terminalState.persistenceBackend}` : " · non-persistent";
      setTerminalStatus(`${session.title} · PID ${session.pid ?? "—"} · ${session.cwd}${persistence}`);
      requestAnimationFrame(() => { fit(); terminal.focus(); });
    });
    socket.addEventListener("message", async (event) => {
      if (client.disposed || client.socket !== socket) return;
      if (typeof event.data === "string") {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === "ready" && message.session) {
          Object.assign(session, message.session);
          renderTerminalTabs();
        } else if (message.type === "exit" && message.session) {
          Object.assign(session, message.session);
          renderTerminalTabs();
          terminal.write(`\r\n\x1b[90m[process exited${session.exit_code === null ? "" : ` with code ${session.exit_code}`} ]\x1b[0m\r\n`);
          setTerminalStatus(`${session.title} · ${session.state}`);
        }
        return;
      }
      const bytes = event.data instanceof Blob ? new Uint8Array(await event.data.arrayBuffer()) : new Uint8Array(event.data);
      terminal.write(bytes);
    });
    socket.addEventListener("close", () => {
      if (client.disposed || client.socket !== socket) return;
      client.socket = null;
      if (session.state !== "running") {
        setTerminalStatus(`${session.title} · ${session.state}`);
        return;
      }
      const delay = Math.min(10000, 500 * (2 ** Math.min(client.reconnectAttempt, 5)));
      client.reconnectAttempt += 1;
      setTerminalStatus(`Disconnected · reconnecting in ${(delay / 1000).toFixed(1)}s`);
      client.retryTimer = setTimeout(() => connect(), delay);
    });
    socket.addEventListener("error", () => {
      if (!client.disposed) setTerminalStatus("Terminal connection error");
    });
  };

  client.connect = connect;
  connect();
}

function buildTerminalDialog() {
  const dialog = terminalElement("dialog", { class: "raTerminalDialog", id: "ra-terminal-dialog" });
  const cwd = terminalElement("input", { class: "cwd", placeholder: "Working directory" });
  const shell = terminalElement("input", { class: "shell", placeholder: "Shell command" });
  const title = terminalElement("input", { class: "title", placeholder: "Title" });
  const tabs = terminalElement("div", { class: "raTerminalTabs" });
  const host = terminalElement("div", { class: "raTerminalHost" }, [
    terminalElement("div", { class: "raTerminalEmpty", text: "Open or create a terminal" }),
  ]);
  const status = terminalElement("span", { text: "Loading…" });
  const clearButton = terminalButton("Clear", () => terminalState.client?.terminal.clear());
  const reconnectButton = terminalButton("Reconnect", () => terminalState.client?.connect(true));
  const closeDialogButton = terminalButton("Close", () => dialog.close());
  const newButton = terminalButton("+ New", () => createTerminalSession().catch((error) => setTerminalStatus(error.message)), "primary");

  dialog.append(terminalElement("div", { class: "raTerminalLayout" }, [
    terminalElement("div", { class: "raTerminalHeader" }, [
      terminalElement("div", { class: "raTerminalTitle", text: "Terminal" }),
      terminalElement("div", { class: "raTerminalControls" }, [cwd, shell, title, newButton]),
      closeDialogButton,
    ]),
    tabs,
    host,
    terminalElement("div", { class: "raTerminalFooter" }, [
      status,
      terminalElement("div", { class: "raTerminalFooterActions" }, [clearButton, reconnectButton]),
    ]),
  ]));
  dialog.addEventListener("close", () => disposeTerminalClient());
  document.body.append(dialog);
  Object.assign(terminalState, { dialog, host, tabs, status, cwd, shell, title });
  return dialog;
}

async function openTerminalDialog() {
  const dialog = terminalState.dialog || buildTerminalDialog();
  if (!dialog.open) dialog.showModal();
  try {
    await refreshTerminalSessions();
    if (!terminalState.sessions.length) await createTerminalSession();
    else await attachTerminalSession(terminalState.activeId || terminalState.sessions.at(-1).session_id);
  } catch (error) {
    setTerminalStatus(error.message);
  }
}

async function installTerminal() {
  if (document.querySelector("#ra-terminal-dialog")) return;
  installTerminalStyles();
  buildTerminalDialog();
  const actions = document.querySelector(".topbar-actions");
  const button = terminalElement("button", {
    class: "button ghost",
    text: "Terminal",
    onclick: openTerminalDialog,
  });
  if (actions) actions.prepend(button);
  else document.body.prepend(button);
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.shiftKey && event.code === "Backquote") {
      event.preventDefault();
      openTerminalDialog();
    }
  });
  try { await refreshTerminalSessions(); }
  catch (error) { setTerminalStatus(error.message); }
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", installTerminal)
  : installTerminal();
