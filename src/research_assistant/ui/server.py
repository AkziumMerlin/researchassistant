from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.config import dump_config, load_config_text
from research_assistant.config_creator import assemble_config
from research_assistant.errors import ResearchAssistantError
from research_assistant.planning import Plan, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.registry import Registry
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


def create_app(root: str | Path, plugins: list[str] | None = None):
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

    app = FastAPI(
        title="ResearchAssistant UI",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.workspace = workspace
    app.state.registry = registry
    app.state.plugins = server_plugins
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
        return {
            "workspace": {"name": workspace.root.name, "path": str(workspace.root)},
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

    app = create_app(root, plugins)
    url_host = "[::1]" if host == "::1" else host
    url = f"http://{url_host}:{port}"
    if open_browser:
        timer = threading.Timer(0.75, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host=host, port=port, log_level="info")
