import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { defineConfig } from "vite";

const staticRoot = resolve(import.meta.dirname, "../../src/research_assistant/ui/static");
const runtimeExtensions = [
  "jobs-extension.js",
  "pipeline-extension.js",
  "research-extension.js",
  "workbench-extension.js",
];
const workspaceElementNeedle = '    "workspace-name",\n    "file-count",';
const workspaceElementReplacement =
  '    "workspace-name",\n    "connection-status",\n    "file-count",';

function preserveRuntimeExtensions() {
  const contents = new Map();
  return {
    name: "preserve-runtime-extensions",
    enforce: "pre",
    async configResolved() {
      for (const name of runtimeExtensions) {
        contents.set(name, await readFile(resolve(staticRoot, name)));
      }
    },
    async closeBundle() {
      for (const [name, content] of contents) {
        await writeFile(resolve(staticRoot, name), content);
      }
    },
  };
}

export default defineConfig({
  base: "/",
  plugins: [
    preserveRuntimeExtensions(),
    {
      name: "explorer-connection-status-registry",
      enforce: "pre",
      transform(code, id) {
        if (!id.endsWith("/src/main.js")) return null;
        if (code.includes('    "connection-status",\n')) return null;
        if (!code.includes(workspaceElementNeedle)) {
          throw new Error("Could not locate the frontend workspace element registry");
        }
        return {
          code: code.replace(workspaceElementNeedle, workspaceElementReplacement),
          map: null,
        };
      },
    },
  ],
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
