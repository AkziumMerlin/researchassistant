# Local browser UI

ResearchAssistant includes a self-contained browser workbench for authoring project files,
launching experiment configurations, monitoring runs, and building reports. It is launched by the
Python CLI and uses the same registry, Pydantic schemas, config model, planner, and local
subprocess launcher as terminal commands.

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

On a remote Linux server, use:

```bash
ra ui . --plugin my_project.plugin --ssh --ssh-target user@server --port 8765
```

SSH mode suppresses the server-side browser and prints the exact local forwarding command:

```bash
ssh -N -L 8765:127.0.0.1:8765 user@server
```

Open `http://127.0.0.1:8765` locally. The service remains bound to the server loopback interface;
the UI deliberately rejects `0.0.0.0` and other remote bindings.

## Workbench features

- project tree with filtering and generated-directory exclusions;
- Monaco Editor, the MIT-licensed editor core from VS Code;
- multiple file models, tab-local undo history, syntax highlighting, find, folding, and `Ctrl+S`;
- new UTF-8 text files without implicit directory creation;
- live catalog of registered component types and their schema fields;
- a PyTorch model-graph editor with a searchable standard-module palette, draggable nodes,
  visual edges, multi-input operations, and server-side DAG validation;
- a visual config creator generated from component Pydantic schemas;
- enum, boolean, number, required-field, array, and object inputs;
- multiple seeds, resources, stages, and stage dependencies;
- inspection of unsaved YAML, including relative `extends`, CLI-style dotted overrides, the
  rendered composed config, run identities, trial identities, assignments, and optional manifests;
- run/trial and resolved-launcher preview before execution;
- detached launch of saved experiment configs with config overrides, an optional launcher-policy
  YAML, and launcher-policy overrides;
- persistent launch history, per-run state and GPU assignment, progress, and bounded scheduler
  and worker logs;
- a managed `best`/`last` checkpoint catalog with source run, stage, registered model, size, and
  modification time;
- inference preview with exact model-component compatibility checks, split/device/config
  overrides, external workspace-relative checkpoints, and optional batch-wise prediction export;
- an arbitrary workspace artifact-root catalog with run states, final-metric summaries, and
  resource summaries;
- an incremental run/metric catalog for large artifact roots with explicit rebuild;
- shared multi-value study/trial/model/dataset/split/state filters across analytical views;
- validation-selected evaluation that chooses a best step per run, reads a target metric at the
  same step, exposes excluded seeds, and aggregates by up to three dimensions;
- configurable line and bar figures with seed aggregation, uncertainty, log scale, and
  downsampling;
- visual publication-table previews plus generated LaTeX with row/column grouping, ranking,
  precision, captions, labels, and one-click copying;
- reproducible validation-selected evaluation bundles containing LaTeX, CSV, JSON, and separate
  eligible/excluded run provenance;
- loading of saved chart/table YAML specs and reproducible report-bundle export to a bounded
  workspace destination;
- runtime diagnostics plus safe project scaffold initialization without overwriting files.

The creator returns an unsaved editor buffer. Saving remains a separate explicit action.

The Checkpoints panel scans a selected artifact root without loading model tensors into the UI
server. Selecting a managed checkpoint restores its resolved source config and plugin list.
Standalone `.pt`, `.pth`, and `.ckpt` files require an explicit saved config. Accepted inference
requests use the same detached scheduler as ordinary launches, so browser or SSH-tunnel loss does
not interrupt evaluation.

## Browser launches and SSH resilience

The browser never submits a shell command. A launch request contains a saved workspace-relative
experiment config, an optional saved launcher policy, a workspace-relative artifact root, and the
resume choice. Both the config and launcher policy may carry the same dotted-path overrides as
their CLI commands. The backend composes and validates inheritance, loads the component registry,
compiles the complete plan, checks the launcher contract, and rejects paths outside the workspace
before starting anything.

Each accepted request is resolved into an immutable snapshot under:

```text
.ra/ui-launches/<launch-id>/
├── request.json
├── process.json
├── state.json
└── scheduler.log
```

The scheduler is a new session rather than a background task owned by FastAPI. Browser closure,
temporary tunnel loss, or stopping and later restarting `ra ui` therefore does not stop the
scheduler. The Launch panel reloads these records and the authoritative run-local `status.json`
files after reconnection.

This guarantee covers loss of the browser and UI server. It does not yet provide scheduler-worker
adoption if the detached scheduler itself is killed or the machine restarts.

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

There is intentionally no browser terminal, general command runner, file deletion, remote bind, or
arbitrary process endpoint. Experiment launch is the only process operation and is restricted to
the validated orchestration contract above. The UI currently does not expose force-kill or file
deletion operations.

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
