const LAYOUT_MARK = "researchAssistantLayoutManagerV1";
const LAYOUT_KEY = "ra.ui.layout.v1";

if (!globalThis[LAYOUT_MARK]) {
  globalThis[LAYOUT_MARK] = true;
  installLayoutManager();
  void import("/assets/research-workspace-ready.js").catch((error) => console.error(error));
}

function readLayoutState() {
  try {
    const value = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function writeLayoutState(state) {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(state));
  } catch {}
}

function installLayoutManager() {
  const state = readLayoutState();
  const registrations = new Map();
  let saveTimer = null;

  const save = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => writeLayoutState(state), 80);
  };

  const manager = {
    version: 1,
    state,
    registerPanel(id, element, options = {}) {
      if (!id || !element || registrations.has(id)) return;
      const minimum = Number(options.minimum || 180);
      const maximum = Number(options.maximum || 900);
      const axis = options.axis === "y" ? "y" : "x";
      const initial = Number(
        state[id]?.size ||
          options.initial ||
          element.getBoundingClientRect()[axis === "x" ? "width" : "height"] ||
          minimum,
      );
      const variable = options.variable || `--ra-panel-${id}-size`;
      const apply = (raw, persist = false) => {
        const size = Math.round(
          Math.min(maximum, Math.max(minimum, Number(raw) || minimum)),
        );
        document.documentElement.style.setProperty(variable, `${size}px`);
        element.dataset.raPanelSize = String(size);
        if (persist) {
          state[id] = { ...(state[id] || {}), size };
          save();
        }
        return size;
      };
      apply(initial);
      registrations.set(id, {
        id,
        element,
        axis,
        minimum,
        maximum,
        variable,
        apply,
      });
      return {
        setSize: apply,
        reset: () => apply(options.initial || minimum, true),
      };
    },
    registerDialog(id, dialog, options = {}) {
      if (!id || !dialog || dialog.dataset.raLayoutDialog === "true") return;
      dialog.dataset.raLayoutDialog = "true";
      dialog.classList.add("raManagedDialog");
      const saved = state[`dialog:${id}`] || {};
      if (saved.width) dialog.style.width = `${saved.width}px`;
      if (saved.height) dialog.style.height = `${saved.height}px`;
      const observer = new ResizeObserver(() => {
        if (!dialog.open) return;
        const box = dialog.getBoundingClientRect();
        state[`dialog:${id}`] = {
          width: Math.round(box.width),
          height: Math.round(box.height),
        };
        save();
      });
      observer.observe(dialog);
      dialog.addEventListener("dblclick", (event) => {
        if (!event.target.closest(".raDialogResizeReset")) return;
        dialog.style.width = options.width || "";
        dialog.style.height = options.height || "";
        delete state[`dialog:${id}`];
        save();
      });
    },
    snapshot() {
      return structuredClone(state);
    },
    restore(value) {
      if (!value || typeof value !== "object") {
        throw new Error("Layout snapshot must be an object");
      }
      for (const key of Object.keys(state)) delete state[key];
      Object.assign(state, structuredClone(value));
      writeLayoutState(state);
      location.reload();
    },
    reset() {
      for (const key of Object.keys(state)) delete state[key];
      try {
        localStorage.removeItem(LAYOUT_KEY);
      } catch {}
      try {
        localStorage.removeItem("ra.ui.explorerWidth");
      } catch {}
      location.reload();
    },
  };
  globalThis.__RA_LAYOUT__ = manager;
  globalThis.dispatchEvent(new CustomEvent("ra-layout-ready", { detail: manager }));

  installLayoutStyles();
  installLayoutControls(manager);
  observeDialogs(manager);
}

function observeDialogs(manager) {
  const register = (root = document) => {
    root
      .querySelectorAll?.("dialog[id],dialog.ra-models-v2,dialog.wbDialog")
      .forEach((dialog) => {
        const id = dialog.id || [...dialog.classList].join("-") || "dialog";
        manager.registerDialog(id, dialog);
      });
  };
  register();
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node instanceof Element) register(node);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
}

function installLayoutStyles() {
  if (document.getElementById("ra-layout-manager-styles")) return;
  const style = document.createElement("style");
  style.id = "ra-layout-manager-styles";
  style.textContent = `
    .raManagedDialog{resize:both;min-width:620px;min-height:420px;max-width:99vw;max-height:98vh;overflow:hidden}
    .raLayoutDialog{width:min(720px,94vw);max-height:85vh;background:#0b1411;color:#d8e6df;border:1px solid #40574d;border-radius:8px;padding:0}
    .raLayoutDialog::backdrop{background:#000b}
    .raLayoutHeader{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #30443b}
    .raLayoutBody{padding:14px;display:grid;gap:10px}
    .raLayoutActions{display:flex;gap:8px;flex-wrap:wrap}
    .raLayoutActions button{border:1px solid #486558;background:#14231d;color:inherit;border-radius:5px;padding:7px 10px;cursor:pointer}
    .raLayoutSnapshot{width:100%;min-height:180px;resize:vertical;background:#07100c;color:#d8e6df;border:1px solid #30443b;padding:8px;font:12px/1.4 ui-monospace,monospace}
  `;
  document.head.append(style);
}

function installLayoutControls(manager) {
  const actions = document.querySelector(".topbar-actions");
  if (!actions || document.getElementById("ra-layout-button")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "ra-layout-dialog";
  dialog.className = "raLayoutDialog";
  dialog.innerHTML = `
    <div class="raLayoutHeader"><div><strong>Workspace layout</strong><div>Persistent IDE-style panel and dialog geometry</div></div><button type="button" data-close>×</button></div>
    <div class="raLayoutBody">
      <textarea class="raLayoutSnapshot" aria-label="Layout snapshot"></textarea>
      <div class="raLayoutActions">
        <button type="button" data-export>Export current layout</button>
        <button type="button" data-import>Import snapshot</button>
        <button type="button" data-reset>Reset layout</button>
      </div>
    </div>`;
  document.body.append(dialog);
  const area = dialog.querySelector(".raLayoutSnapshot");
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.querySelector("[data-export]").addEventListener("click", () => {
    area.value = JSON.stringify(manager.snapshot(), null, 2);
  });
  dialog.querySelector("[data-import]").addEventListener("click", () => {
    manager.restore(JSON.parse(area.value));
  });
  dialog.querySelector("[data-reset]").addEventListener("click", () => manager.reset());
  const button = document.createElement("button");
  button.id = "ra-layout-button";
  button.type = "button";
  button.className = "button ghost";
  button.textContent = "Layout";
  button.addEventListener("click", () => {
    area.value = JSON.stringify(manager.snapshot(), null, 2);
    dialog.showModal();
  });
  actions.prepend(button);
}
