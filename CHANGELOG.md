# Changelog

All notable user-visible changes to ResearchAssistant are documented here. Versions follow
Semantic Versioning; the project remains pre-1.0 while its public configuration and plugin contracts
continue to mature.

## [0.4.1] - 2026-08-04

### Added

- Native SSH workspaces for the Theia desktop application: Electron and Node remain local while an
  authenticated Python sidecar runs in the selected remote Conda environment or interpreter.
- A writable `ra-remote` Theia filesystem provider for Navigator, Monaco, file operations, and
  bounded remote change polling.
- Remote terminal profiles backed by OpenSSH and optional dedicated tmux sessions.

### Changed

- `ra connect` now launches local Theia/Electron instead of the retired browser frontend.
- Remote profiles and reconnect behavior now apply to the desktop sidecar tunnel. Notebooks,
  monitoring, execution, reports, and Research views all use the remote backend.

### Security

- Remote sidecars bind only to loopback, require a random per-session token, and expose the token
  only to the local Theia Node backend. Node.js and Electron are not installed or run remotely.

## [0.4.0] - 2026-08-04

### Added

- A branded Eclipse Theia/Electron desktop application with native IDE docking, Explorer, Monaco,
  integrated terminals, search, commands, keybindings and persisted layouts.
- Dockable runs, cross-study aggregation, artifacts, models, reports, notebook-context, durable
  execution and typed-assistant views.
- A Node-side Python-sidecar supervisor with handshake validation, lifecycle management and a
  bounded authenticated API proxy.
- A machine-readable CLI/API/UI capability matrix, plugin compatibility contracts and sequential
  persisted-schema migrations.

### Changed

- `ra ui` now launches the desktop IDE; `ra desktop` is an explicit alias.
- The Python backend remains the source of truth and runs as a loopback-only per-session sidecar.
- Workspace navigation, editing, terminals and layout management now use Theia platform services
  instead of custom browser runtime extensions and modal dialogs.

### Removed

- The browser tab as the supported ResearchAssistant application entry point.

## [0.3.0] - 2026-08-03

### Added

- A scalable browser workspace with lazy directory loading, path search, Monaco editing, and
  integrated persistent Jupyter notebooks.
- Persistent local and SSH experiment workflows, including reconnectable tmux-backed terminals.
- Integrated CPU, GPU, and process monitoring.
- Visual PyTorch architecture composition with searchable registered components.
- Checkpoint discovery, inspection, inference, and evaluation from both CLI and UI.
- Structured result aggregation, configurable plots, evaluation tables, and LaTeX export.

### Changed

- Established `pyproject.toml` as the single source of the ResearchAssistant product version.
- Made the CLI, Python API, wheel metadata, and browser diagnostics report the installed package
  version consistently.
- Documented the pre-1.0 Semantic Versioning policy and release checklist.

## [0.2.0]

- Expanded the initial experiment orchestrator into a browser-accessible research workbench with
  persistent jobs, remote execution, checkpoint workflows, and reporting.

## [0.1.0]

- Initial local-first experiment orchestration, configuration, registry, execution, and reporting
  foundation.
