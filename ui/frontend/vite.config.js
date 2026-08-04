import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { defineConfig } from "vite";

const staticRoot = resolve(import.meta.dirname, "../../src/research_assistant/ui/static");
const architecturePartRoot = resolve(import.meta.dirname, "src/extensions/architecture-v2");
const architectureModuleId = "virtual:architecture-workbench";
const resolvedArchitectureModuleId = `\0${architectureModuleId}`;

function architectureWorkbenchModule() {
  return {
    name: "researchassistant-architecture-workbench",
    resolveId(id) {
      return id === architectureModuleId ? resolvedArchitectureModuleId : null;
    },
    load(id) {
      if (id !== resolvedArchitectureModuleId) return null;
      return Array.from({ length: 8 }, (_, index) =>
        readFileSync(
          resolve(architecturePartRoot, `part-${String(index).padStart(2, "0")}.txt`),
          "utf8",
        ),
      ).join("");
    },
  };
}

export default defineConfig({
  base: "/",
  plugins: [architectureWorkbenchModule()],
  build: {
    outDir: staticRoot,
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    // Monaco's internal ESM graph is cyclic. Keep its core in the entry chunk;
    // manually splitting modules by path can change their initialization order.
    chunkSizeWarningLimit: 4000,
  },
});
