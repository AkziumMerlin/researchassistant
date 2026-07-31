const MARK = "researchAssistantArchitectureWorkbenchV2Loader";
if (!globalThis[MARK]) {
  globalThis[MARK] = true;
  const parts = Array.from({ length: 7 }, (_, index) =>
    `/api/extensions/architecture-v2/part-${String(index).padStart(2, "0")}.txt`,
  );
  Promise.all(parts.map(async (path) => {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`Cannot load architecture UI part ${path}`);
    return response.text();
  }))
    .then((sources) => {
      const url = URL.createObjectURL(new Blob(sources, { type: "text/javascript" }));
      return import(url).finally(() => URL.revokeObjectURL(url));
    })
    .catch((error) => {
      console.error(error);
      const panel = document.getElementById("output-content");
      if (panel) panel.textContent = `Cannot initialize Models UI: ${error.message}`;
    });
}
