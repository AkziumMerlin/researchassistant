const COMPONENT_SEARCH_MARK = "researchAssistantComponentSearch";

if (!globalThis[COMPONENT_SEARCH_MARK]) {
  globalThis[COMPONENT_SEARCH_MARK] = true;
  installComponentSearch();
}

function installComponentSearch() {
  installComponentSearchStyles();
  const enhanced = new WeakSet();
  const observer = new MutationObserver(() => {
    const dialog = document.querySelector("dialog.ra-models-v2");
    if (dialog && !enhanced.has(dialog)) {
      enhanced.add(dialog);
      enhanceModelsDialog(dialog).catch((error) => console.error(error));
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  const existing = document.querySelector("dialog.ra-models-v2");
  if (existing) {
    enhanced.add(existing);
    enhanceModelsDialog(existing).catch((error) => console.error(error));
  }
}

async function enhanceModelsDialog(dialog) {
  const input = dialog.querySelector("#ra-palette-filter");
  const sourceList = dialog.querySelector("#ra-palette-list");
  const palette = input?.closest(".ra-palette");
  if (!input || !sourceList || !palette) return;

  const bootstrap = await componentApi("/api/bootstrap");
  const specs = (bootstrap.components || []).filter((item) => item.catalog === "graph-node");
  const categories = [...new Set(specs.map((item) => item.metadata?.category || "Modules"))].sort();
  const providers = [...new Set(specs.map((item) => item.provider || "unknown"))].sort();

  const controls = document.createElement("div");
  controls.className = "raComponentSearchControls";
  const category = selectControl("All categories", categories);
  const provider = selectControl("All providers", providers);
  const shortcut = document.createElement("button");
  shortcut.type = "button";
  shortcut.className = "raComponentSearchShortcut";
  shortcut.textContent = "Ctrl+K";
  shortcut.title = "Focus component search";
  const status = document.createElement("span");
  status.className = "raComponentSearchStatus";
  controls.append(category, provider, shortcut, status);
  input.after(controls);

  const results = document.createElement("div");
  results.className = "raComponentSearchResults";
  results.hidden = true;
  controls.after(results);

  input.placeholder = "Search name, provider, category, description…";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Search model components");

  const state = {
    dialog,
    input,
    sourceList,
    results,
    status,
    category,
    provider,
    specs,
    bypass: false,
    rebuilding: false,
    selected: 0,
  };

  const captureInput = (event) => {
    if (event.target !== input || state.bypass) return;
    event.stopImmediatePropagation();
    rebuildCompletePalette(state);
  };
  document.addEventListener("input", captureInput, true);

  category.addEventListener("change", () => refreshComponentResults(state));
  provider.addEventListener("change", () => refreshComponentResults(state));
  shortcut.addEventListener("click", () => focusComponentSearch(state));
  input.addEventListener("keydown", (event) => handleSearchKeys(state, event), true);

  document.addEventListener("keydown", (event) => {
    if (!dialog.open) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      focusComponentSearch(state);
    } else if (event.key === "/" && !isTextInput(event.target)) {
      event.preventDefault();
      focusComponentSearch(state);
    }
  });

  const listObserver = new MutationObserver(() => {
    if (state.rebuilding) return;
    if (input.value.trim() || category.value || provider.value) {
      rebuildCompletePalette(state);
    }
  });
  listObserver.observe(sourceList, { childList: true, subtree: true });

  const modelsButton = document.getElementById("architectures-button");
  modelsButton?.addEventListener("click", () => {
    setTimeout(() => rebuildCompletePalette(state), 0);
  });

  rebuildCompletePalette(state);
}

function selectControl(allLabel, values) {
  const select = document.createElement("select");
  select.className = "raComponentSearchSelect";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = allLabel;
  select.append(all);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  return select;
}

async function componentApi(path) {
  const response = await fetch(path, { cache: "no-store" });
  const payload = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function rebuildCompletePalette(state) {
  if (state.rebuilding) return;
  const query = state.input.value;
  state.rebuilding = true;
  state.bypass = true;
  state.input.value = "";
  state.input.dispatchEvent(new Event("input", { bubbles: true }));
  state.input.value = query;
  state.bypass = false;
  requestAnimationFrame(() => {
    state.rebuilding = false;
    refreshComponentResults(state);
  });
}

function refreshComponentResults(state) {
  const query = state.input.value.trim();
  const category = state.category.value;
  const provider = state.provider.value;
  const searching = Boolean(query || category || provider);
  state.sourceList.hidden = searching;
  state.results.hidden = !searching;
  state.results.replaceChildren();
  state.selected = 0;

  if (!searching) {
    state.status.textContent = `${state.specs.length} modules`;
    return;
  }

  const sourceButtons = mapSourceButtons(state.sourceList);
  const ranked = [];
  for (const spec of state.specs) {
    const specCategory = spec.metadata?.category || "Modules";
    const specProvider = spec.provider || "unknown";
    if (category && specCategory !== category) continue;
    if (provider && specProvider !== provider) continue;
    const score = fuzzyComponentScore(query, spec);
    if (query && score < 0) continue;
    const source = findSourceButton(sourceButtons, spec, specCategory);
    if (!source) continue;
    ranked.push({ spec, score, source, category: specCategory, provider: specProvider });
  }

  ranked.sort((left, right) => {
    if (right.score !== left.score) return right.score - left.score;
    return left.spec.name.localeCompare(right.spec.name);
  });

  for (const [index, item] of ranked.slice(0, 200).entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `raComponentSearchResult${index === state.selected ? " selected" : ""}`;
    button.dataset.resultIndex = String(index);
    const name = document.createElement("strong");
    name.textContent = item.spec.name;
    const meta = document.createElement("span");
    meta.className = "raComponentSearchMeta";
    meta.textContent = `${item.category} · ${item.provider}`;
    const description = document.createElement("small");
    description.textContent = item.spec.description || "No description";
    button.append(name, meta, description);
    button.addEventListener("click", () => {
      item.source.click();
      state.input.focus();
    });
    state.results.append(button);
  }

  if (!ranked.length) {
    const empty = document.createElement("div");
    empty.className = "raComponentSearchEmpty";
    empty.textContent = "No components match this search.";
    state.results.append(empty);
  }
  state.status.textContent = ranked.length > 200 ? `200 of ${ranked.length}` : `${ranked.length} result(s)`;
}

function mapSourceButtons(sourceList) {
  const result = [];
  let group = "";
  for (const child of sourceList.children) {
    if (child.classList.contains("ra-palette-group")) {
      group = child.textContent.trim();
      continue;
    }
    if (!child.classList.contains("ra-palette-button")) continue;
    result.push({
      button: child,
      group,
      name: child.querySelector("strong")?.textContent?.trim() || "",
      description: child.querySelector("small")?.textContent?.trim() || "",
    });
  }
  return result;
}

function findSourceButton(buttons, spec, category) {
  const shortName = spec.name.split("/").at(-1);
  return (
    buttons.find(
      (item) =>
        item.group === category &&
        item.name === shortName &&
        item.description === (spec.description || ""),
    ) ||
    buttons.find((item) => item.name === shortName && item.description === (spec.description || ""))
  )?.button;
}

function fuzzyComponentScore(query, spec) {
  if (!query) return 0;
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  const name = spec.name.toLowerCase();
  const shortName = name.split("/").at(-1);
  const category = String(spec.metadata?.category || "").toLowerCase();
  const provider = String(spec.provider || "").toLowerCase();
  const description = String(spec.description || "").toLowerCase();
  const metadata = JSON.stringify(spec.metadata || {}).toLowerCase();
  const searchable = `${name} ${shortName} ${category} ${provider} ${description} ${metadata}`;
  let total = 0;
  for (const token of tokens) {
    let score = -1;
    if (shortName === token || name === token) score = 1200;
    else if (shortName.startsWith(token)) score = 900 - shortName.length;
    else if (name.startsWith(token)) score = 800 - name.length * 0.1;
    else if (shortName.includes(token)) score = 650 - shortName.indexOf(token);
    else if (name.includes(token)) score = 560 - name.indexOf(token) * 0.1;
    else if (category.includes(token)) score = 430;
    else if (provider.includes(token)) score = 400;
    else if (description.includes(token)) score = 320 - description.indexOf(token) * 0.02;
    else {
      const subsequence = subsequenceScore(token, searchable);
      if (subsequence >= 0) score = 120 + subsequence;
    }
    if (score < 0) return -1;
    total += score;
  }
  return total;
}

function subsequenceScore(needle, haystack) {
  let position = -1;
  let gap = 0;
  for (const character of needle) {
    const next = haystack.indexOf(character, position + 1);
    if (next < 0) return -1;
    if (position >= 0) gap += next - position - 1;
    position = next;
  }
  return Math.max(0, 80 - gap);
}

function handleSearchKeys(state, event) {
  if (state.results.hidden) return;
  const buttons = [...state.results.querySelectorAll(".raComponentSearchResult")];
  if (!buttons.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    state.selected = Math.min(buttons.length - 1, state.selected + 1);
    updateSelectedResult(state, buttons);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    state.selected = Math.max(0, state.selected - 1);
    updateSelectedResult(state, buttons);
  } else if (event.key === "Enter") {
    event.preventDefault();
    buttons[state.selected]?.click();
  } else if (event.key === "Escape") {
    state.input.value = "";
    state.category.value = "";
    state.provider.value = "";
    rebuildCompletePalette(state);
  }
}

function updateSelectedResult(state, buttons) {
  for (const [index, button] of buttons.entries()) {
    button.classList.toggle("selected", index === state.selected);
  }
  buttons[state.selected]?.scrollIntoView({ block: "nearest" });
}

function focusComponentSearch(state) {
  state.input.focus();
  state.input.select();
}

function isTextInput(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable;
}

function installComponentSearchStyles() {
  if (document.getElementById("ra-component-search-styles")) return;
  const style = document.createElement("style");
  style.id = "ra-component-search-styles";
  style.textContent = `
    .raComponentSearchControls{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;gap:5px;align-items:center;margin:6px 0 8px}
    .raComponentSearchSelect{min-width:0;background:#0d141c;color:#d7e2ec;border:1px solid #39475a;border-radius:5px;padding:5px;font-size:11px}
    .raComponentSearchShortcut{border:1px solid #43536a;border-radius:5px;background:#182331;color:#d7e2ec;padding:5px 7px;font-size:10px;cursor:pointer}
    .raComponentSearchStatus{grid-column:1/-1;color:#8292a5;font-size:10px;text-align:right}
    .raComponentSearchResults{display:grid;gap:4px;padding-bottom:10px}
    .raComponentSearchResult{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 8px;width:100%;text-align:left;border:1px solid #303e51;border-radius:6px;background:#121b26;color:#e1e8f0;padding:7px;cursor:pointer}
    .raComponentSearchResult:hover,.raComponentSearchResult.selected{border-color:#70a7ff;background:#1b2a3c}
    .raComponentSearchResult strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}
    .raComponentSearchMeta{color:#8195aa;font-size:9px;white-space:nowrap}
    .raComponentSearchResult small{grid-column:1/-1;color:#9caabd;font-size:10px;line-height:1.25}
    .raComponentSearchEmpty{padding:12px 4px;color:#8998aa;font-size:11px}
  `;
  document.head.append(style);
}
