const READY_MARK = "researchAssistantWorkspaceReadyV1";

if (!globalThis[READY_MARK]) {
  globalThis[READY_MARK] = true;
  waitForResearchWorkspace();
}

function waitForResearchWorkspace() {
  const bridge = globalThis.__RA_WORKBENCH__;
  const actions = document.querySelector(".topbar-actions");
  const dialog = document.getElementById("ra-research-workspace");
  if (!bridge || !actions || !dialog) {
    window.setTimeout(waitForResearchWorkspace, 50);
    return;
  }

  let button = document.getElementById("ra-research-workspace-button");
  if (!button) {
    button = document.createElement("button");
    button.id = "ra-research-workspace-button";
    button.type = "button";
    button.className = "button ghost";
    button.textContent = "Research";
    button.addEventListener("click", () => {
      dialog.showModal();
      const active = dialog.querySelector("[data-rw-tab].active");
      const fallback = dialog.querySelector('[data-rw-tab="runs"]');
      (active || fallback)?.click();
    });
  }
  if (!button.isConnected) actions.prepend(button);
}
