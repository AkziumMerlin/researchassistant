import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  base: "/",
  plugins: [
    {
      name: "explorer-bootstrap-compatibility",
      transformIndexHtml: {
        order: "pre",
        handler() {
          return [
            {
              tag: "script",
              attrs: { src: "/assets/explorer-bootstrap.js" },
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
