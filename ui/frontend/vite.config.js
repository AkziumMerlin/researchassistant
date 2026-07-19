import { defineConfig } from "vite";
import { resolve } from "node:path";

function bucket(name) {
  const first = name.toLowerCase()[0] || "x";
  if (first < "g") return "a-f";
  if (first < "m") return "g-l";
  if (first < "s") return "m-r";
  return "s-z";
}

function monacoChunkName(moduleId) {
  const marker = "/monaco-editor/esm/vs/";
  const offset = moduleId.indexOf(marker);
  if (offset < 0) return null;
  const parts = moduleId.slice(offset + marker.length).split("/");
  if (parts[0] === "basic-languages") return "monaco-languages";
  if (parts[0] === "editor" && parts[1] === "contrib") {
    return `monaco-contrib-${parts[2] || "core"}`;
  }
  if (parts[0] === "editor" && ["browser", "common"].includes(parts[1])) {
    const section = parts[2]?.includes(".") ? `root-${bucket(parts[2])}` : parts[2] || "root";
    return `monaco-editor-${parts[1]}-${section}`;
  }
  if (parts[0] === "base" && ["browser", "common"].includes(parts[1])) {
    const section = parts[2]?.includes(".") ? `root-${bucket(parts[2])}` : parts[2] || "root";
    return `monaco-base-${parts[1]}-${section}`;
  }
  if (parts[0] === "platform") return `monaco-platform-${bucket(parts[1] || "x")}`;
  if (parts[0] === "editor" && parts[1] === "standalone") return "monaco-standalone";
  return `monaco-core-${bucket(parts[0] || "x")}`;
}

export default defineConfig({
  base: "/",
  build: {
    outDir: resolve(import.meta.dirname, "../../src/research_assistant/ui/static"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: monacoChunkName,
              test: /node_modules[\\/]monaco-editor/,
              includeDependenciesRecursively: false,
            },
          ],
        },
      },
    },
  },
});
