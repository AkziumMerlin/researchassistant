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
│   ├── Explorer, Monaco, terminal, search, tasks
│   └── ResearchAssistant dockable workspace
├── Theia Node backend
│   └── authenticated proxy; the token never reaches renderer code
└── Python sidecar
    ├── existing ResearchAssistant API and plugin registry
    ├── runs, launch recovery, checkpoints and inference
    ├── artifacts, notebooks and reports
    └── loopback-only random port with per-session bearer token
```

The sidecar emits one JSON handshake line, binds only to `127.0.0.1`, and requires the random
session token on every HTTP request. The renderer cannot choose an arbitrary origin: the Node
proxy accepts only paths under `/api/`.

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
- Theia terminal and process services replace the terminal dialog.
- ResearchAssistant views are ordinary dockable widgets rather than modal dialogs.
- Runs can be explicitly selected across different studies and aggregated.
- Artifacts expose lineage and bounded comparisons.
- Models expose registered PyTorch components and architecture documents.
- Notebook contexts open their `.ipynb` documents in the workspace.
- Execution lists durable launches managed by the Python scheduler.
- The assistant produces typed, capability-bounded plans through the existing Python provider API.

## Packaging

```bash
npm run package --prefix desktop
```

The Python environment containing `research-assistant[desktop]` must be available to the packaged
application. `RA_PYTHON` is set automatically by `ra ui`; distributable installers will bundle a
managed Python runtime in a later packaging pass.

## Removed browser entry point

`ra ui` no longer starts a web server or opens a browser. The FastAPI application remains an
internal headless API for the desktop sidecar and remote agents. The old Vite application is not
part of the desktop build or release validation.
