const READY_MARK = "researchAssistantWorkspaceReadyV1";

if (!globalThis[READY_MARK]) {
  globalThis[READY_MARK] = true;
  waitForResearchWorkspace();
}

function ensureButton(actions, id, label, handler) {
  let button = document.getElementById(id);
  if (!button) {
    button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.className = "button ghost";
    button.textContent = label;
    button.addEventListener("click", handler);
  }
  if (!button.isConnected) actions.prepend(button);
}

function waitForResearchWorkspace() {
  const bridge = globalThis.__RA_WORKBENCH__;
  const actions = document.querySelector(".topbar-actions");
  const researchDialog = document.getElementById("ra-research-workspace");
  const layoutDialog = document.getElementById("ra-layout-dialog");
  if (!bridge || !actions || !researchDialog || !layoutDialog) {
    window.setTimeout(waitForResearchWorkspace, 50);
    return;
  }

  ensureButton(actions, "ra-layout-button", "Layout", () => {
    const area = layoutDialog.querySelector(".raLayoutSnapshot");
    if (area && globalThis.__RA_LAYOUT__) {
      area.value = JSON.stringify(globalThis.__RA_LAYOUT__.snapshot(), null, 2);
    }
    layoutDialog.showModal();
  });
  ensureButton(actions, "ra-research-workspace-button", "Research", () => {
    researchDialog.showModal();
    const active = researchDialog.querySelector("[data-rw-tab].active");
    const fallback = researchDialog.querySelector('[data-rw-tab="runs"]');
    (active || fallback)?.click();
  });
}
