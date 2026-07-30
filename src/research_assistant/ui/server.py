from __future__ import annotations

import getpass
import os
import shlex
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.analytics import (
    ChartSpec,
    MetricIndex,
    TableSpec,
    bounded_artifact_root,
)
from research_assistant.config import dump_config, load_config_text
from research_assistant.config_creator import assemble_config
from research_assistant.errors import ResearchAssistantError
from research_assistant.planning import Plan, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.registry import Registry
from research_assistant.reporting import render_latex_table, write_chart_bundle, write_table_bundle
from research_assistant.ui.launches import LaunchCreateRequest, LaunchManager
from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError


class UiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileWriteRequest(UiModel):
    content: str
    revision: str | None = None


class ConfigValidateRequest(UiModel):
    path: str
    content: str


class ComponentInput(UiModel):
    kind: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class StageInput(UiModel):
    name: str
    type: str
    needs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ConfigCreateRequest(UiModel):
    path: str
    experiment_name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    seeds: list[int] = Field(default_factory=lambda: [0])
    components: list[ComponentInput] = Field(default_factory=list)
    stages: list[StageInput]
    accelerator: Literal["auto", "cpu", "cuda"] = "auto"
    devices: int = Field(default=1, ge=1)
    memory_gb: float | None = Field(default=None, gt=0)
    artifact_root: str = "runs"


class AnalyticsRootRequest(UiModel):
    artifact_root: str = "runs"
    rebuild: bool = False


class ChartExportRequest(UiModel):
    spec: ChartSpec
    formats: list[Literal["svg", "pdf", "png"]] = Field(default_factory=lambda: ["svg", "pdf"])


class TableExportRequest(UiModel):
    spec: TableSpec


def _plan_summary(plan: Plan) -> dict[str, Any]:
    trials = sorted({run.trial_id for run in plan.runs})
    return {
        "study_id": plan.study_id,
        "runs": len(plan.runs),
        "trials": len(trials),
        "trial_ids": trials,
        "run_ids": [run.run_id for run in plan.runs],
    }


def _component_catalog(registry: Registry) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for spec in registry.list():
        schema = registry.schema(spec.kind, spec.name)
        catalog.append(
            {
                "kind": spec.kind,
                "name": spec.name,
                "description": spec.description,
                "provider": spec.provider,
                "schema": schema,
            }
        )
    return catalog


def _registry_for_config(config_plugins: list[str], server_plugins: list[str]) -> Registry:
    modules = list(dict.fromkeys([*server_plugins, *config_plugins]))
    return load_registry(modules)


def create_app(
    root: str | Path,
    plugins: list[str] | None = None,
    *,
    ssh_mode: bool | None = None,
):
    """Create the optional FastAPI application without importing web dependencies at CLI import."""
    try:
        from fastapi import FastAPI, Query, Request
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.middleware.trustedhost import TrustedHostMiddleware
    except ImportError as exc:  # pragma: no cover - exercised without the optional extra
        raise ResearchAssistantError(
            "the UI dependencies are not installed; run pip install 'research-assistant[ui]'"
        ) from exc

    workspace = Workspace(root)
    server_plugins = list(dict.fromkeys(plugins or []))
    if str(workspace.root) not in sys.path:
        sys.path.insert(0, str(workspace.root))
    registry = load_registry(server_plugins)
    static_root = Path(__file__).with_name("static")
    index_path = static_root / "index.html"
    if not index_path.is_file():
        raise ResearchAssistantError("the bundled UI assets are missing from this installation")

    @asynccontextmanager
    async def lifespan(application):
        yield
        for index in application.state.metric_indices.values():
            index.close()

    app = FastAPI(
        title="ResearchAssistant UI",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.workspace = workspace
    app.state.registry = registry
    app.state.plugins = server_plugins
    app.state.metric_indices = {}
    app.state.launch_manager = LaunchManager(workspace, server_plugins)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; img-src 'self' data:; connect-src 'self'; "
            "font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(WorkspaceConflict)
    async def workspace_conflict(_request: Request, exc: WorkspaceConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ResearchAssistantError)
    async def research_assistant_error(_request: Request, exc: ResearchAssistantError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        tree = workspace.entries()
        ssh_session = (
            bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"))
            if ssh_mode is None
            else ssh_mode
        )
        return {
            "workspace": {"name": workspace.root.name, "path": str(workspace.root)},
            "connection": {
                "mode": "ssh" if ssh_session else "local",
                "hostname": socket.gethostname(),
                "localhost_only": True,
                "persistent_launches": True,
            },
            "plugins": server_plugins,
            "files": tree["entries"],
            "files_truncated": tree["truncated"],
            "components": _component_catalog(registry),
        }

    @app.get("/api/files")
    def read_file(path: str = Query(min_length=1)) -> dict[str, Any]:
        result = workspace.read(path)
        return {
            "path": result.path,
            "content": result.content,
            "revision": result.revision,
            "size": result.size,
        }

    @app.put("/api/files")
    def write_file(payload: FileWriteRequest, path: str = Query(min_length=1)) -> dict[str, Any]:
        result = workspace.write(path, payload.content, payload.revision)
        return {
            "path": result.path,
            "revision": result.revision,
            "size": result.size,
        }

    @app.post("/api/config/validate")
    def validate_config(payload: ConfigValidateRequest) -> dict[str, Any]:
        source = workspace.resolve(payload.path)
        config = load_config_text(
            payload.content,
            source,
            allowed_root=workspace.root,
        )
        configured_registry = _registry_for_config(config.plugins, server_plugins)
        plan = compile_plan(config, configured_registry)
        return {
            "valid": True,
            "experiment": config.experiment.name,
            "plan": _plan_summary(plan),
        }

    @app.post("/api/config/create")
    def create_config(payload: ConfigCreateRequest) -> dict[str, Any]:
        workspace.resolve(payload.path)
        components: dict[str, dict[str, Any]] = {}
        for component in payload.components:
            if component.kind in components:
                raise WorkspaceError(f"component kind is selected twice: {component.kind}")
            reference = {"type": component.type, "params": component.params}
            components[component.kind] = reference

        stages: list[dict[str, Any]] = []
        for stage in payload.stages:
            stages.append(
                {
                    "name": stage.name,
                    "type": stage.type,
                    "needs": stage.needs,
                    "params": stage.params,
                }
            )

        config = assemble_config(
            experiment_name=payload.experiment_name,
            description=payload.description,
            tags=payload.tags,
            plugins=server_plugins,
            seeds=payload.seeds,
            components=components,
            stages=stages,
            accelerator=payload.accelerator,
            devices=payload.devices,
            memory_gb=payload.memory_gb,
            artifact_root=payload.artifact_root,
        )
        plan = compile_plan(config, registry)
        return {
            "path": payload.path,
            "content": dump_config(config, compact=True),
            "plan": _plan_summary(plan),
        }

    @app.get("/api/launches")
    def list_launches() -> dict[str, Any]:
        return {"launches": app.state.launch_manager.list()}

    @app.post("/api/launches", status_code=202)
    def create_launch(payload: LaunchCreateRequest) -> dict[str, Any]:
        return app.state.launch_manager.create(payload)

    @app.get("/api/launches/{launch_id}")
    def launch_detail(
        launch_id: str,
        run_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return app.state.launch_manager.detail(launch_id, run_id)

    def analytics_index(artifact_root: str) -> MetricIndex:
        root_path = bounded_artifact_root(workspace.root, artifact_root)
        key = str(root_path)
        index = app.state.metric_indices.get(key)
        if index is None:
            index = MetricIndex(root_path)
            app.state.metric_indices[key] = index
        return index

    def report_destination(name: str) -> Path:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        if name in {"", ".", ".."} or any(character not in allowed for character in name):
            raise WorkspaceError(
                "report names may contain only letters, digits, dot, dash, underscore"
            )
        destination = (workspace.root / "reports" / name).resolve()
        if not destination.is_relative_to(workspace.root):
            raise WorkspaceError("report destination escapes workspace")
        return destination

    @app.post("/api/analytics/catalog")
    def analytics_catalog(payload: AnalyticsRootRequest) -> dict[str, Any]:
        index = analytics_index(payload.artifact_root)
        refresh = index.rebuild() if payload.rebuild else index.refresh()
        return {"refresh": refresh, "catalog": index.catalog()}

    @app.post("/api/analytics/chart")
    def analytics_chart(spec: ChartSpec) -> dict[str, Any]:
        index = analytics_index(spec.artifact_root)
        refresh = index.refresh()
        return {"refresh": refresh, "chart": index.chart(spec)}

    @app.post("/api/analytics/table")
    def analytics_table(spec: TableSpec) -> dict[str, Any]:
        index = analytics_index(spec.artifact_root)
        refresh = index.refresh()
        table = index.table(spec)
        return {"refresh": refresh, "table": table, "latex": render_latex_table(table, spec)}

    @app.post("/api/analytics/chart/export")
    def analytics_chart_export(payload: ChartExportRequest) -> dict[str, Any]:
        index = analytics_index(payload.spec.artifact_root)
        index.refresh()
        destination = report_destination(payload.spec.name)
        write_chart_bundle(index, payload.spec, destination, formats=tuple(payload.formats))
        return {"path": destination.relative_to(workspace.root).as_posix()}

    @app.post("/api/analytics/table/export")
    def analytics_table_export(payload: TableExportRequest) -> dict[str, Any]:
        index = analytics_index(payload.spec.artifact_root)
        index.refresh()
        destination = report_destination(payload.spec.name)
        write_table_bundle(index, payload.spec, destination)
        return {"path": destination.relative_to(workspace.root).as_posix()}

    @app.get("/")
    def index():
        return FileResponse(index_path)

    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")
    return app


def run_ui(
    root: str | Path,
    *,
    plugins: list[str] | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    ssh_mode: bool = False,
    ssh_target: str | None = None,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ResearchAssistantError(
            "the base UI only binds to localhost; use SSH port forwarding for a remote server"
        )
    try:
        import uvicorn
    except ImportError as exc:
        raise ResearchAssistantError(
            "the UI dependencies are not installed; run pip install 'research-assistant[ui]'"
        ) from exc

    app = create_app(root, plugins, ssh_mode=ssh_mode)
    url_host = "[::1]" if host == "::1" else host
    url = f"http://{url_host}:{port}"
    if ssh_mode:
        open_browser = False
        target = ssh_target or f"{getpass.getuser()}@{socket.getfqdn()}"
        quoted_target = shlex.quote(target)
        forward_host = "[::1]" if host == "::1" else "127.0.0.1"
        print("SSH mode: ResearchAssistant remains bound to the server loopback interface.")
        print("Run this on your local machine:")
        print(f"  ssh -N -L {port}:{forward_host}:{port} {quoted_target}")
        print(f"Then open http://127.0.0.1:{port}")
    if open_browser:
        timer = threading.Timer(0.75, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host=host, port=port, log_level="info")
