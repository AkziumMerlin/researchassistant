# Changelog

All notable user-visible changes to ResearchAssistant are documented here. Versions follow
Semantic Versioning; the project remains pre-1.0 while its public configuration and plugin contracts
continue to mature.

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
