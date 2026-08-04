# Managed SSH workspaces

`ra connect` opens a remote project in the local Eclipse Theia/Electron application. Electron and
Node.js remain on the local machine. The server needs only Python, OpenSSH access, and the
ResearchAssistant package with its `desktop` dependencies.

```text
local machine                              SSH server
──────────────────────────────────────     ─────────────────────────────────
Theia/Electron
├── Navigator + Monaco   ─ file API ───┐   Python desktop sidecar
├── Research views      ─ domain API ──┼─► ├── workspace files
├── notebooks           ─ kernel API ──┤   ├── runs/checkpoints/reports
├── monitor             ─ monitor API ─┤   ├── Jupyter kernels
└── terminal ─ independent SSH/tmux ───┘   └── CPU/GPU/process monitor

Python `ra connect` owns the loopback tunnel and reconnect loop.
```

The remote sidecar binds to `127.0.0.1` on the server and requires a random per-session bearer
token. The token is passed only to the local Theia Node backend; renderer code never receives it.
The custom `ra-remote` filesystem provider exposes the remote project to the normal Theia
Navigator and Monaco editor. No browser server, Electron runtime, or Node installation is started
on the server.

## Install

Install and build the desktop application locally:

```bash
conda activate researchassistant
cd /path/to/researchassistant
python -m pip install -e '.[desktop,reports]'
npm install --prefix desktop
npm run build --prefix desktop
```

Install the matching Python version in the server environment. Node.js is not required remotely:

```bash
ssh gpu-server
conda activate KNO
cd /path/to/researchassistant
python -m pip install -e '.[desktop,reports]'
ra version
```

The local and remote `ra version` values should match. `ra connect` prints a warning when they do
not.

## Updating

Update the remote checkout without installing Node.js or rebuilding the UI:

```bash
ssh gpu-server
conda activate KNO
ra update server --repo /path/to/researchassistant
```

`ra update server` only performs a clean, fast-forward-only Git update. It never invokes `pip`,
`npm`, Theia, Electron or package generation. When a release changes Python dependencies, update
the server environment explicitly after reviewing the release notes.

Update the local machine separately:

```bash
conda activate researchassistant
ra update local --repo /path/to/researchassistant
```

The local command also reinstalls the Python package and rebuilds/packages the Theia UI. Use
`--dry-run` with either command to inspect its plan.

## One-off connection

```bash
ra connect gpu-server \
  --workspace /home/akzium/Kuramoto-Neural-Operator \
  --conda-env KNO \
  --plugin ra_project.plugin \
  --dev
```

`gpu-server` may be an alias from `~/.ssh/config`. `--dev` runs the locally built Theia source
application. A packaged executable can be selected with `--executable`.

The command:

1. creates a local `.theia-workspace` containing an `ra-remote://` workspace root;
2. chooses unused local and remote loopback ports;
3. starts `research_assistant.desktop_server` in the selected remote environment;
4. creates an authenticated SSH tunnel to that sidecar;
5. launches local Electron/Theia;
6. reconnects the tunnel with bounded backoff after transient SSH failures;
7. terminates only the temporary sidecar and tunnel when the desktop window closes.

Detached schedulers, workers, notebook kernel records, run artifacts, and tmux sessions remain on
the server.

Use an explicit remote interpreter instead of Conda when needed:

```bash
ra connect gpu-server \
  --workspace /srv/project \
  --remote-python /srv/venvs/project/bin/python \
  --dev
```

Workspace paths may be absolute or relative. Relative paths are resolved once from the SSH login
directory.

## Remote terminal

The generated Theia workspace selects a local terminal profile that starts `ssh -tt` into the
remote workspace. When `tmux` exists on the server, every terminal tab uses a dedicated tmux
session and reconnects to that session after a transient SSH interruption. Without tmux, the
terminal remains remote but is not persistent.

```bash
conda install -n KNO -c conda-forge tmux
```

The terminal shell is started inside the selected Conda environment. ResearchAssistant uses a
dedicated tmux server name derived from the remote workspace and does not modify the user's normal
tmux server.

## Profiles

Save a profile while connecting:

```bash
ra connect gpu-server \
  --workspace /home/akzium/Kuramoto-Neural-Operator \
  --conda-env KNO \
  --plugin ra_project.plugin \
  --save kno \
  --dev
```

Reconnect with:

```bash
ra connect kno --dev
```

Profiles can also be managed explicitly:

```bash
ra remote add kno \
  --target gpu-server \
  --workspace /home/akzium/Kuramoto-Neural-Operator \
  --conda-env KNO \
  --plugin ra_project.plugin

ra remote list
ra remote remove kno
```

Profiles are stored under
`${XDG_CONFIG_HOME:-~/.config}/research-assistant/remotes.json`. They contain only SSH aliases,
paths, environment selectors, and plugin names. Passwords, private keys, bearer tokens, and
`ssh-agent` state are never stored.

## Connection options

Use fixed ports when required by local policy:

```bash
ra connect kno --local-port 41000 --remote-port 41001 --dev
```

Disable automatic reconnect:

```bash
ra connect kno --no-reconnect --dev
```

Pass additional OpenSSH options without bypassing `~/.ssh/config`:

```bash
ra connect kno --ssh-option ProxyJump=bastion --dev
```
