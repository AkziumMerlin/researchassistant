from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.assistant_core import (
    AssistantEngine,
    AssistantPlan,
    AssistantRequest,
)
from research_assistant.capabilities import capability_matrix
from research_assistant.durable_launches import DurableLaunchManager
from research_assistant.errors import ResearchAssistantError
from research_assistant.migrations import migrate_document, migration_catalog
from research_assistant.notebook_context import NotebookContextStore
from research_assistant.run_workspace import RunWorkspace
from research_assistant.scientific_artifacts import ScientificArtifactCatalog


class WorkspaceV2Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunAggregateRequest(WorkspaceV2Model):
    artifact_root: str = "runs"
    run_ids: list[str] = Field(min_length=1)
    metric: str | None = None
    stage: str | None = None
    group_by: list[str] = Field(default_factory=lambda: ["study_id", "trial_id"])


class NotebookContextRequest(WorkspaceV2Model):
    artifact_root: str = "runs"
    run_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    label: str | None = None
    notebook_path: str | None = None
    kernel_name: str = "python3"


class MigrationPreviewRequest(WorkspaceV2Model):
    kind: str = "experiment"
    document: dict[str, Any]


class AssistantApplyRequest(WorkspaceV2Model):
    request: AssistantRequest
    plan: AssistantPlan


class CancelLaunchRequest(WorkspaceV2Model):
    force: bool = False


def register_research_workspace(app) -> None:
    try:
        from fastapi import Query, Request
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace.root
    static_root = Path(__file__).with_name("ui") / "static"
    layout_script = static_root / "layout-manager.js"
    workspace_script = static_root / "research-workspace.js"
    context_store = NotebookContextStore(workspace)
    assistant = AssistantEngine(str(workspace), registry=app.state.registry)

    if not isinstance(app.state.launch_manager, DurableLaunchManager):
        app.state.launch_manager = DurableLaunchManager(
            app.state.workspace,
            getattr(app.state, "plugins", []),
        )

    @app.middleware("http")
    async def research_workspace_extension(request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET" or request.url.path != "/":
            return response
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        html = body.decode("utf-8")
        sources = (
            "/api/extensions/layout-manager.js",
            "/api/extensions/research-workspace.js",
        )
        tags = "".join(
            f'  <script type="module" src="{source}"></script>\n'
            for source in sources
            if source not in html
        )
        if tags:
            html = html.replace("</head>", f"{tags}  </head>")
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() != "content-length"
        }
        result = HTMLResponse(html, status_code=response.status_code, headers=headers)
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.get("/api/extensions/layout-manager.js")
    def layout_javascript():
        if not layout_script.is_file():
            raise ResearchAssistantError("the layout manager asset is missing")
        response = Response(
            layout_script.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/extensions/research-workspace.js")
    def research_workspace_javascript():
        if not workspace_script.is_file():
            raise ResearchAssistantError("the research workspace asset is missing")
        source = workspace_script.read_text(encoding="utf-8")
        bootstrap = (
            "const startResearchWorkspace = () => {\n"
            f"{source}\n"
            "};\n"
            "if (document.readyState === 'complete') {\n"
            "  startResearchWorkspace();\n"
            "} else {\n"
            "  window.addEventListener('load', startResearchWorkspace, { once: true });\n"
            "}\n"
        )
        response = Response(bootstrap, media_type="application/javascript")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/workspace-v2/capabilities")
    def capabilities() -> dict[str, Any]:
        matrix = capability_matrix()
        matrix["plugins"] = list(
            getattr(app.state.registry, "plugin_diagnostics", [])
        )
        matrix["assistant_providers"] = [
            spec.name for spec in app.state.registry.list("assistant")
        ]
        matrix["migrations"] = migration_catalog()
        return matrix

    @app.get("/api/workspace-v2/runs")
    def runs(
        artifact_root: str = Query(default="runs"),
        study: list[str] | None = Query(default=None),
        state: list[str] | None = Query(default=None),
        search: str | None = Query(default=None),
        limit: int = Query(default=5000, ge=1, le=20000),
    ) -> dict[str, Any]:
        return RunWorkspace(workspace, artifact_root).catalog(
            study_ids=set(study or []) or None,
            states=set(state or []) or None,
            search=search,
            limit=limit,
        )

    @app.post("/api/workspace-v2/runs/aggregate")
    def aggregate_runs(payload: RunAggregateRequest) -> dict[str, Any]:
        return RunWorkspace(workspace, payload.artifact_root).aggregate(
            payload.run_ids,
            metric=payload.metric,
            stage=payload.stage,
            group_by=payload.group_by,
        )

    @app.get("/api/workspace-v2/runs/{run_id}")
    def run_lineage(
        run_id: str,
        artifact_root: str = Query(default="runs"),
    ) -> dict[str, Any]:
        return RunWorkspace(workspace, artifact_root).lineage_for_run(run_id)

    @app.get("/api/workspace-v2/artifacts/{artifact_id}/lineage")
    def artifact_lineage(
        artifact_id: str,
        artifact_root: str = Query(default="runs"),
    ) -> dict[str, Any]:
        catalog = ScientificArtifactCatalog(workspace)
        artifact = catalog.require(artifact_id)
        run_id = artifact.get("run_id")
        if not run_id:
            parts = Path(str(artifact.get("path", ""))).parts
            root_parts = Path(artifact_root).parts
            if len(parts) >= len(root_parts) + 2 and parts[: len(root_parts)] == root_parts:
                run_id = parts[len(root_parts) + 1]
        lineage = (
            RunWorkspace(workspace, artifact_root).lineage_for_run(str(run_id))
            if run_id
            else None
        )
        related = catalog.list(run_id=str(run_id), limit=200) if run_id else []
        return {
            "artifact": artifact,
            "run_lineage": lineage,
            "related_artifacts": related,
        }

    @app.get("/api/workspace-v2/notebook-contexts")
    def notebook_contexts(
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        return {"contexts": context_store.list(limit=limit)}

    @app.post("/api/workspace-v2/notebook-contexts", status_code=201)
    def create_notebook_context(payload: NotebookContextRequest) -> dict[str, Any]:
        return context_store.create(
            run_ids=payload.run_ids,
            artifact_ids=payload.artifact_ids,
            artifact_root=payload.artifact_root,
            label=payload.label,
            notebook_path=payload.notebook_path,
            kernel_name=payload.kernel_name,
        )

    @app.get("/api/workspace-v2/notebook-contexts/{context_id}")
    def notebook_context(context_id: str) -> dict[str, Any]:
        return context_store.require(context_id)

    @app.get("/api/workspace-v2/plugins")
    def plugins() -> dict[str, Any]:
        return {
            "diagnostics": list(
                getattr(app.state.registry, "plugin_diagnostics", [])
            ),
            "assistant_providers": [
                spec.name for spec in app.state.registry.list("assistant")
            ],
            "migrations": migration_catalog(),
        }

    @app.post("/api/workspace-v2/migrations/preview")
    def migration_preview(payload: MigrationPreviewRequest) -> dict[str, Any]:
        document, report = migrate_document(payload.document, kind=payload.kind)
        return {"document": document, "report": report.as_dict()}

    @app.post("/api/workspace-v2/assistant/plan")
    def assistant_plan(payload: AssistantRequest) -> dict[str, Any]:
        return assistant.plan(payload).model_dump(mode="json")

    @app.post("/api/workspace-v2/assistant/apply")
    def assistant_apply(payload: AssistantApplyRequest) -> dict[str, Any]:
        return assistant.apply(payload.request, payload.plan)

    @app.post("/api/workspace-v2/launches/reconcile")
    def reconcile_launches() -> dict[str, Any]:
        return app.state.launch_manager.reconcile()

    @app.post("/api/workspace-v2/launches/{launch_id}/adopt")
    def adopt_launch(launch_id: str) -> dict[str, Any]:
        return app.state.launch_manager.adopt(launch_id)

    @app.post("/api/workspace-v2/launches/{launch_id}/retry")
    def retry_launch(launch_id: str) -> dict[str, Any]:
        return app.state.launch_manager.retry(launch_id)

    @app.post("/api/workspace-v2/launches/{launch_id}/cancel")
    def cancel_launch(
        launch_id: str,
        payload: CancelLaunchRequest,
    ) -> dict[str, Any]:
        return app.state.launch_manager.cancel(launch_id, force=payload.force)
