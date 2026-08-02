# Local browser UI

ResearchAssistant includes a self-contained browser workbench for authoring project files,
launching experiment configurations, monitoring runs, working in an interactive terminal, and
building reports. It is launched by the Python CLI and uses the same registry, Pydantic schemas,
config model, planner, and local subprocess launcher as terminal commands.

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

For normal remote work, run the client locally:

```bash
ra connect gpu-server \
  --workspace /home/user/project \
  --conda-env project-env \
  --plugin my_project.plugin
```

`ra connect` starts the UI backend on the server loopback interface, creates the SSH forwarding,
waits for readiness, and opens the browser locally. The legacy `ra ui --ssh` mode remains available
when a manually managed tunnel is required.

## Workbench features

- project tree with filtering and generated-directory exclusions;
- Monaco Editor, the MIT-licensed editor core from VS Code;
- multiple file models, tab-local undo history, syntax highlighting, find, folding, and `Ctrl+S`;
- a full PTY-backed terminal using xterm.js, including multiple tabs, ANSI colors, interactive TUI
  programs, stdin, `Ctrl+C`, resize, scrollback, and tmux-backed restoration after UI/SSH reconnects;
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

## Browser terminal

Open **Terminal** in the top bar or press `Ctrl+Shift+Backquote`. Each tab owns a real POSIX PTY, so
ordinary shells, Conda activation, Python/IPython, `vim`, `htop`, and other interactive programs
behave as they do in a native terminal. A new tab can choose its working directory, shell command,
and title; otherwise it starts in the workspace using `$SHELL`.

When `tmux` is installed on the backend machine, each tab is hosted by a session in a dedicated,
workspace-scoped tmux server. Closing the dialog or browser only disconnects the renderer. Loss of
the SSH tunnel or restart of the ResearchAssistant Uvicorn process also leaves the shell, current
directory, environment, foreground program, screen state, and tmux scrollback running. A new UI
backend for the same resolved workspace discovers those sessions and restores the tabs
automatically. Closing an individual terminal tab explicitly kills its tmux session.

ResearchAssistant does not reuse or modify the user's ordinary tmux server. The dedicated server is
selected from a stable hash of the resolved workspace path. Sessions survive UI and `ra connect`
restarts, but not a server reboot unless tmux itself is restored by the host.

If `tmux` is absent, the UI falls back to a PTY owned by the current backend and reports that the
session is non-persistent. Install tmux through the system package manager or, for a Conda-backed
remote environment, with:

```bash
conda install -n project-env -c conda-forge tmux
```

With `ra connect`, both the PTY and the dedicated tmux server run remotely. The browser remains
local, while every terminal command executes directly on the selected server in the remote
workspace and environment.

## Browser launches and SSH resilience

A structured launch request contains a saved workspace-relative experiment config, an optional
saved launcher policy, a workspace-relative artifact root, and the resume choice. Both the config
and launcher policy may carry the same dotted-path overrides as their CLI commands. The backend
composes and validates inheritance, loads the component registry, compiles the complete plan,
checks the launcher contract, and rejects paths outside the workspace before starting anything.

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

## File consistency and server boundary

The server receives a single project root. Browser file-editor paths cannot be absolute, contain
`..`, enter excluded generated directories, or resolve through a symlink outside that root. Files
must be UTF-8 text and are limited to 2 MiB.

Each read returns a SHA-256 revision. A save succeeds only if that revision still matches the file
on disk, or if a new path still does not exist. The write is flushed and atomically replaces the
target. This prevents a browser tab from silently overwriting edits made by Git, another editor,
or another UI session.

The server sets a same-origin content security policy, does not enable CORS, accepts local Host
headers only, and ships Monaco and xterm assets inside the wheel. No editor or terminal code is
loaded from a CDN. There is no separate general-purpose command-over-HTTP endpoint: interactive
commands flow through a PTY WebSocket, while experiment launches continue to use their typed
orchestration API.

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

The build first produces the standalone xterm runtime and then the main Monaco workbench. Vite
writes both to `src/research_assistant/ui/static`. Generated files and their licenses are included
in the Python wheel; `node_modules` is not.
