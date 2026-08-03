# Versioning and releases

ResearchAssistant follows Semantic Versioning. The Python project version in
`pyproject.toml` is the single source of truth for the product version. The CLI, Python API,
packaged wheel, and browser diagnostics read that installed distribution metadata rather than
maintaining separate version constants.

While the project is below `1.0.0`:

- patch releases contain compatible fixes, documentation changes, and internal maintenance;
- minor releases mark a meaningful set of new product capabilities and may include explicitly
  documented compatibility changes;
- major version `1.0.0` will mark a stable public configuration, plugin, CLI, and artifact contract.

Release tags use `vMAJOR.MINOR.PATCH`, for example `v0.3.0`. A release change should update
`pyproject.toml` and `CHANGELOG.md` in the same pull request.

## Release checklist

1. Choose the next version from the user-visible change set, not the number of commits.
2. Update `[project].version` in `pyproject.toml`.
3. Add the dated release notes to `CHANGELOG.md`.
4. Run Ruff, the full test suite, the frontend build, and the wheel build.
5. Verify that `ra version`, `research_assistant.__version__`, wheel metadata, and UI diagnostics
   report the same version.
6. Merge the release pull request and create the matching annotated Git tag.

The private npm package under `ui/frontend` is build tooling rather than an independently released
product. Its package metadata must not be used as the ResearchAssistant version; the browser obtains
the product version from the backend bootstrap diagnostics.
