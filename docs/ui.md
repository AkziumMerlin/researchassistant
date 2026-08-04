# Retired browser UI

The standalone Vite/browser workbench was removed in ResearchAssistant 0.4.0. `ra ui` now launches
the Eclipse Theia/Electron desktop application; it no longer starts a browser-facing web server.

See [`desktop.md`](desktop.md) for installation, development, architecture and launch instructions.
The Python FastAPI process is an authenticated, loopback-only headless sidecar used by the Theia
backend. It does not serve `/` or `/assets`.

Existing experiment configs, run directories, artifacts, notebook contexts and plugin contracts are
unchanged by the UI migration.
