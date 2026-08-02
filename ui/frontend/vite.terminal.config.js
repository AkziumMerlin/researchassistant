import { resolve } from "node:path";

import { defineConfig } from "vite";

const staticRoot = resolve(import.meta.dirname, "../../src/research_assistant/ui/static");

export default defineConfig({
  build: {
    outDir: staticRoot,
    emptyOutDir: false,
    sourcemap: false,
    target: "es2022",
    lib: {
      entry: resolve(import.meta.dirname, "src/terminal-runtime.js"),
      formats: ["es"],
      fileName: () => "terminal-runtime.js",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
});
