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
    assert dependencies["@research-assistant/theia-extension"] == "0.4.2"


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
    assert "All categories" in source
    assert "All providers" in source
    assert "componentScore" in source
    assert "Ctrl+K" in source


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
    workspace = (EXTENSION / "remote-workspace-service.ts").read_text(encoding="utf-8")
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
    assert "extends WorkspaceService" in workspace
    assert "computeRemoteRoots" in workspace
    assert "new URI(folder.path)" in workspace
    assert "rebind(WorkspaceService).toService(ResearchAssistantWorkspaceService)" in frontend
    assert "RA_REMOTE_ENDPOINT" in backend
    assert "RA_REMOTE_TOKEN" in backend
    assert "reconnecting" in backend


def test_theia_restores_browser_workflow_parity_as_native_tabs() -> None:
    widget = (EXTENSION / "research-assistant-widget.ts").read_text(encoding="utf-8")
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((EXTENSION / "tabs").glob("*.ts"))
    )

    for label in ["Project", "Jobs", "Pipeline", "Workbench"]:
        assert f"'{label}'" in widget
    project = (EXTENSION / "tabs" / "project-tab.ts").read_text(encoding="utf-8")
    assert "defaultsFromSchema" in project
    assert "componentsForKind" in project
    assert "Stage-local component overrides" in project

    for endpoint in [
        "/api/project/init",
        "/api/config/create",
        "/api/config/inspect",
        "/api/jobs/${",
        "/api/jobs/",
        "/api/notebooks/file",
        "/api/workbench/artifacts/discover",
        "/api/workbench/artifacts/register",
        "/api/workbench/artifacts/slice",
        "/api/workbench/lifecycle/",
        "/api/pipeline/cache",
        "/api/pipeline/assets",
        "/api/pipeline/diagnostics",
        "/api/pipeline/publication/",
        "/api/workbench/workspaces",
        "/api/workbench/environments",
        "/api/workbench/analysis/",
        "/api/workbench/dev/",
        "/api/analytics/advanced",
        "/api/analytics/spec/load",
        "/api/runs/catalog",
        "/api/analytics/chart/export",
        "/api/analytics/table/export",
        "/api/jobs/${encodeURIComponent(selectedJob)}/live-metrics",
    ]:
        assert endpoint in sources


def test_native_notebook_editor_persists_cells_and_execution_outputs() -> None:
    source = (EXTENSION / "tabs" / "notebooks-tab.ts").read_text(encoding="utf-8")
    backend = (ROOT / "src" / "research_assistant" / "notebook_ui.py").read_text(encoding="utf-8")

    assert "Create or load a notebook" in source
    assert "/api/notebooks/file" in source
    assert "execution_complete" in source
    assert "output_type" in source
    assert "parent_id=" in source
    assert "Discard unsaved notebook changes" in source
    assert "Add markdown" in source
    assert "/api/notebooks/kernels/{kernel_id}/events" in backend
    assert "parent_id: str | None" in backend


def test_reports_and_live_jobs_render_visual_results() -> None:
    reports = (EXTENSION / "tabs" / "reports-tab.ts").read_text(encoding="utf-8")
    jobs = (EXTENSION / "tabs" / "jobs-tab.ts").read_text(encoding="utf-8")
    visuals = (EXTENSION / "tabs" / "visualization.ts").read_text(encoding="utf-8")
    css = (EXTENSION / "style" / "research-assistant.css").read_text(encoding="utf-8")

    assert "renderChart(view, chartVisual" in reports
    assert "renderTable(view, tableVisual" in reports
    assert "renderEvaluation(view, evaluationVisual" in reports
    assert "navigator.clipboard.writeText" in reports
    assert "renderLiveDashboard(view, liveVisual" in jobs
    assert "Refresh dashboard every 3s" in jobs
    assert "function renderLineChart" in visuals
    assert "function renderBarChart" in visuals
    assert "ra-data-table" in visuals
    assert ".ra-chart-grid" in css
    assert ".ra-summary-cards" in css
