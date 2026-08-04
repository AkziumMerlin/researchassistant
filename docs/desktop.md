# ResearchAssistant Desktop

ResearchAssistant uses an Eclipse Theia application as its primary user interface. The desktop
shell supplies the workspace explorer, Monaco editor, terminal, command palette, keybindings,
dockable views and persisted IDE layout. ResearchAssistant remains a Python application: the
Electron/Theia backend starts a loopback-only Python sidecar and communicates with it through a
private Theia JSON-RPC service.

## Architecture

```text
ResearchAssistant Desktop (Theia + Electron)
├── Theia frontend
│   ├── Explorer, Monaco, terminal, search and tasks
│   └── dockable ResearchAssistant workspace
├── Theia Node backend
│   └── authenticated bounded proxy; the token never reaches renderer code
└── Python sidecar
    ├── ResearchAssistant domain API and plugin registry
    ├── runs, launch recovery, checkpoints and inference
    ├── artifacts, notebooks and reports
    └── loopback-only random port with a per-session bearer token
```

The sidecar emits one JSON handshake line, binds only to a loopback interface, and requires the
random session token on every HTTP request. The renderer cannot choose an arbitrary origin: the
Node proxy accepts only paths under `/api/`. The sidecar is headless and does not serve `/` or
`/assets`.

For SSH workspaces, `ra connect` keeps Electron and Node local, starts only this Python sidecar on
the server, and forwards it through an authenticated loopback tunnel. A native `ra-remote` Theia
filesystem provider drives Explorer and Monaco; the generated terminal profile starts an
independent remote SSH/tmux terminal. See [remote.md](remote.md).

## Development build

The desktop build requires Node.js 24 and Python 3.11 or newer.

```bash
pip install -e '.[dev,desktop]'
npm install --prefix desktop
npm run build --prefix desktop
ra ui . --plugin my_project.plugin --dev
```

`ra desktop` is an alias of `ra ui`. During development the launcher runs `npm --prefix desktop
run start`; packaged builds can be selected with `--executable` or `RA_DESKTOP_EXECUTABLE`.

## Workbench mapping

Theia replaces the previous browser-specific infrastructure:

- Theia Navigator replaces the custom Explorer.
- Monaco and Theia editor widgets replace the custom editor wrapper.
- Theia terminal and process services replace the browser terminal dialog.
- ResearchAssistant workflows live in an ordinary dockable view rather than modal dialogs.
- Runs can be selected explicitly across different studies, aggregated with full contributing run
  and seed provenance, and inspected through indexed metric/resource summaries.
- Project restores project initialization, schema-driven configuration creation, matrix axes,
  stage-local component overrides and compiled-plan inspection.
- Jobs restores persistent job creation, recovery/adoption, logs, raw metric streams, saved live
  multi-run dashboards and per-run artifacts.
- Artifacts exposes discovery, explicit registration, lineage, bounded slicing/comparison, pinning,
  archival, trash/restore and garbage collection.
- Models provides a native visual parameterized-PyTorch editor with architecture files, registered
  components, subgraphs, control nodes, a draggable canvas, visual edges, JSON inspectors,
  optimistic saves and server-side validation.
- Reports provides chart, advanced scatter/histogram/heatmap/composite plots, tables,
  validation-selected evaluations, saved YAML specs and reproducible export bundles.
- Notebooks creates immutable run/artifact contexts and includes a native cell editor with
  create/open/save, cell ordering, persistent kernels, execution events and stored Jupyter outputs.
- Execution previews and creates durable launches, reconciles scheduler state, adopts or retries
  orphaned work, cancels processes, catalogs checkpoints and launches inference-only runs.
- Pipeline exposes persistent-job recovery, stage-cache pruning, asset promotion/release/pinning,
  diagnostics and reproducible publication bundles.
- Workbench restores workspace/environment catalogs, detached analysis sessions, project tasks,
  search and trusted Git diagnostics/write operations.
- The assistant produces typed, capability-bounded plans and applies them through the existing
  Python provider API.

All lists and editors that can grow independently use bounded internal scroll areas. In particular,
the Models component palette, architecture-file list, graph canvas and inspector do not expand the
outer Theia workbench.

## Updating the local desktop

```bash
conda activate researchassistant
ra update local --repo /path/to/researchassistant
```

The command accepts only a clean Git checkout, fast-forwards the current branch from `origin`,
reinstalls the current Python environment, runs `npm ci` when a lockfile exists (otherwise `npm install`), rebuilds Theia and repackages Electron.
`--no-package` keeps only the development build; `--dry-run` prints the exact commands. Server
checkouts use the intentionally narrower `ra update server` command documented in
[remote.md](remote.md).

## Packaging

```bash
npm run package --prefix desktop
```

The Python environment containing `research-assistant[desktop]` must be available to the packaged
application. `RA_PYTHON` is set automatically by `ra ui`; distributable installers will bundle a
managed Python runtime in a later packaging pass.

## Removed browser entry point

`ra ui` no longer starts a web server or opens a browser. The FastAPI application is an internal
headless API for the desktop sidecar and future remote agents. The old Vite source tree was removed
from the repository and is not part of desktop build or release validation.
