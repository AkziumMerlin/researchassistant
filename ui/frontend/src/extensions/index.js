const extensionLoaders = [
  () => import("./jobs-extension.js"),
  () => import("./pipeline-extension.js"),
  () => import("./research-extension.js"),
  () => import("./workbench-extension.js"),
  () => import("./terminal-extension.js"),
  () => import("./system-monitor-extension.js"),
  () => import("virtual:architecture-workbench"),
  () => import("./explorer-plus.js"),
  () => import("./component-search.js"),
  () => import("./notebook-extension.js"),
  () => import("./layout-manager.js"),
  () => import("./research-workspace.js"),
];

export async function installExtensions() {
  for (const load of extensionLoaders) {
    await load();
  }
}
