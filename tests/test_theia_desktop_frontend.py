from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
EXTENSION = DESKTOP / "research-assistant-extension" / "src" / "browser"


def test_theia_replaces_retired_vite_workbench() -> None:
    assert not (ROOT / "ui").exists()

    application = json.loads((DESKTOP / "application" / "package.json").read_text(encoding="utf-8"))
    dependencies = application["dependencies"]
    assert application["theia"]["target"] == "electron"
    assert dependencies["@theia/navigator"] == "1.73.1"
    assert dependencies["@theia/monaco"] == "1.73.1"
    assert dependencies["@theia/terminal"] == "1.73.1"
    assert dependencies["@research-assistant/theia-extension"] == "0.4.1"


def test_models_editor_uses_parameterized_graph_contract() -> None:
    source = (EXTENSION / "models-editor.ts").read_text(encoding="utf-8")

    assert "class ModelsEditor" in source
    assert "/api/torch/parameterized-graph/validate" in source
    assert "view.put<FilePayload>" in source
    assert "ra-model-palette-list" in source
    assert "setPointerCapture" in source
    assert "subgraphs" in source
    assert "Composite" in source
    assert "Repeat" in source
    assert "Switch" in source


def test_models_editor_has_bounded_independent_scroll_regions() -> None:
    css = (EXTENSION / "style" / "research-assistant.css").read_text(encoding="utf-8")

    assert ".ra-content:has(> .ra-model-editor)" in css
    assert ".ra-model-palette-list" in css
    assert "overflow-y: scroll" in css
    assert ".ra-model-files" in css
    assert ".ra-model-inspector" in css
    assert ".ra-model-canvas" in css
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in css
    assert "scrollbar-gutter: stable" in css


def test_frontend_is_registered_as_normal_theia_extension() -> None:
    source = (EXTENSION / "research-assistant-frontend-module.ts").read_text(encoding="utf-8")

    assert "bindViewContribution" in source
    assert "WebSocketConnectionProvider.createProxy" in source
    assert "./style/research-assistant.css" in source
    assert "./style/execution.css" in source
    assert "/api/extensions/" not in source


def test_remote_workspace_uses_native_theia_filesystem_provider() -> None:
    provider = (EXTENSION / "remote-file-system-provider.ts").read_text(encoding="utf-8")
    frontend = (EXTENSION / "research-assistant-frontend-module.ts").read_text(encoding="utf-8")
    backend = (
        DESKTOP
        / "research-assistant-extension"
        / "src"
        / "node"
        / "research-assistant-backend-service.ts"
    ).read_text(encoding="utf-8")

    assert "implements FileSystemProvider" in provider
    assert "service.registerProvider(REMOTE_SCHEME" in provider
    assert "/api/desktop/files/read" in provider
    assert "/api/desktop/files/write" in provider
    assert "FileServiceContribution" in frontend
    assert "RA_REMOTE_ENDPOINT" in backend
    assert "RA_REMOTE_TOKEN" in backend
    assert "reconnecting" in backend
