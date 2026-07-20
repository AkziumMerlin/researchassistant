# Local browser UI

ResearchAssistant includes a self-contained browser workbench for authoring project files and
experiment configurations. It is launched by the Python CLI and uses the same registry, Pydantic
schemas, config model, and planner as terminal commands.

## Install and launch

Install the optional server dependencies:

```bash
pip install -e '.[ui]'
```

Launch a project and load its development plugin:

```bash
ra ui . --plugin my_project.plugin
```

The default URL is `http://127.0.0.1:8765`. `--no-open` suppresses automatic browser launch, and
`--port` selects another local port.

On a remote Linux server, keep the service bound to localhost and use SSH port forwarding. The
base UI deliberately rejects `0.0.0.0` and other remote bindings.

## Workbench features

- project tree with filtering and generated-directory exclusions;
- Monaco Editor, the MIT-licensed editor core from VS Code;
- multiple file models, tab-local undo history, syntax highlighting, find, folding, and `Ctrl+S`;
- new UTF-8 text files without implicit directory creation;
- live catalog of registered component types and their schema fields;
- a visual config creator generated from component Pydantic schemas;
- enum, boolean, number, required-field, array, and object inputs;
- multiple seeds, resources, stages, and stage dependencies;
- validation of unsaved YAML, including relative `extends` inside the workspace;
- run/trial preview before execution.
- an incremental run/metric catalog for large artifact roots;
- configurable learning curves with seed aggregation, uncertainty, log scale, and downsampling;
- configurable LaTeX tables with row/column grouping, ranking, precision, captions, and labels;
- reproducible report-bundle export under `reports/`.

The creator returns an unsaved editor buffer. Saving remains a separate explicit action.

## File consistency and security boundary

The server receives a single project root. Browser paths cannot be absolute, contain `..`, enter
excluded generated directories, or resolve through a symlink outside that root. Files must be
UTF-8 text and are limited to 2 MiB.

Each read returns a SHA-256 revision. A save succeeds only if that revision still matches the file
on disk, or if a new path still does not exist. The write is flushed and atomically replaces the
target. This prevents a browser tab from silently overwriting edits made by Git, another editor,
or another UI session.

The server sets a same-origin content security policy, does not enable CORS, accepts local Host
headers only, and ships Monaco assets inside the wheel. No editor code is loaded from a CDN.

There is intentionally no browser terminal, command runner, file deletion, or experiment launch
endpoint in the base milestone.

The analytics endpoints accept only artifact roots inside the workspace. They never return raw
unbounded event streams: aggregation and optional step bucketing run in SQLite, and the browser
receives a bounded series payload. The SQLite file is a disposable index; run-local JSONL events
remain the source of truth.

## Frontend development

Frontend source and its lockfile live under `ui/frontend`. Rebuild packaged assets after changing
the workbench:

```bash
cd ui/frontend
npm ci
npm run build
```

Vite writes the production build to `src/research_assistant/ui/static`. Those generated files and
the Monaco license are included in the Python wheel; `node_modules` is not.
