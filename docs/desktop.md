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

The sidecar emits one JSON handshake line, binds only to `127.0.0.1`, and requires the random
session token on every HTTP request. The renderer cannot choose an arbitrary origin: the Node
proxy accepts only paths under `/api/`. The sidecar is headless and does not serve `/` or `/assets`.

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
- Runs can be selected explicitly across different studies and aggregated with full contributing
  run and seed provenance.
- Artifacts expose discovery, lineage and bounded comparison.
- Models provides a native visual parameterized-PyTorch editor with architecture files, registered
  components, subgraphs, control nodes, a draggable canvas, visual edges, JSON inspectors,
  optimistic saves and server-side validation.
- Reports provides chart, table and validation-selected evaluation specifications plus reproducible
  export bundles.
- Notebooks creates immutable run/artifact contexts, opens `.ipynb` files in the workspace, and
  controls persistent kernels and cell execution.
- Execution previews and creates durable launches, reconciles scheduler state, adopts or retries
  orphaned work, cancels processes, catalogs checkpoints and launches inference-only runs.
- The assistant produces typed, capability-bounded plans and applies them through the existing
  Python provider API.

All lists and editors that can grow independently use bounded internal scroll areas. In particular,
the Models component palette, architecture-file list, graph canvas and inspector do not expand the
outer Theia workbench.

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
