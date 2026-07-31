import { defineConfig } from "vite";
import { resolve } from "node:path";

const workspaceElementNeedle = '    "workspace-name",\n    "file-count",';
const workspaceElementReplacement =
  '    "workspace-name",\n    "connection-status",\n    "file-count",';

export default defineConfig({
  base: "/",
  plugins: [
    {
      name: "explorer-connection-status-registry",
      enforce: "pre",
      transform(code, id) {
        if (!id.endsWith("/src/main.js")) return null;
        if (!code.includes(workspaceElementNeedle)) {
          throw new Error("Could not locate the frontend workspace element registry");
        }
        return {
          code: code.replace(workspaceElementNeedle, workspaceElementReplacement),
          map: null,
        };
      },
      transformIndexHtml: {
        order: "pre",
        handler() {
          return [
            {
              tag: "script",
              attrs: { src: "/api/extensions/explorer-bootstrap.js" },
              injectTo: "head-prepend",
            },
          ];
        },
      },
    },
  ],
  build: {
    outDir: resolve(import.meta.dirname, "../../src/research_assistant/ui/static"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    // Monaco's internal ESM graph is cyclic. Keep its core in the entry chunk;
    // manually splitting modules by path can change their initialization order.
    chunkSizeWarningLimit: 4000,
  },
});
