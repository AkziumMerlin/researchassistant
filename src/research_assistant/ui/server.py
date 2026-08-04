from __future__ import annotations

import getpass
import json
import os
import platform
import shlex
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_assistant import __version__
from research_assistant.analytics import (
    ChartSpec,
    EvaluationSpec,
    MetricIndex,
    TableSpec,
    bounded_artifact_root,
)
from research_assistant.checkpoints import (
    build_inference_config,
    catalog_checkpoints,
    inspect_checkpoint,
)
from research_assistant.config import dump_config, load_config_text
from research_assistant.config_creator import assemble_config
from research_assistant.durable_launches import DurableLaunchManager
from research_assistant.errors import ResearchAssistantError
from research_assistant.integrations.torch_graph import TorchGraphParams, validate_graph
from research_assistant.planning import Plan, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.registry import Registry
from research_assistant.reporting import (
    collect_resource_summary,
    collect_summary,
    render_evaluation_latex,
    render_latex_table,
    write_chart_bundle,
    write_evaluation_bundle,
    write_table_bundle,
)
from research_assistant.scaffold import initialize_project
from research_assistant.ui.launches import LaunchCreateRequest
from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

MAX_RUN_ROWS = 2000
MAX_REPORT_ROWS = 2000


class UiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileWriteRequest(UiModel):
    content: str
    revision: str | None = None


class ConfigValidateRequest(UiModel):
    path: str
    content: str
    overrides: list[str] = Field(default_factory=list)
    include_manifests: bool = False


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


class GraphValidateRequest(UiModel):
    params: TorchGraphParams


class AnalyticsRootRequest(UiModel):
    artifact_root: str = "runs"
    rebuild: bool = False


class RunCatalogRequest(UiModel):
    artifact_root: str = "runs"
    stage: str | None = None
    metric: str | None = None
    trial_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=MAX_RUN_ROWS)


class ReportSpecLoadRequest(UiModel):
    path: str
    kind: Literal["chart", "table"]


class ChartExportRequest(UiModel):
    spec: ChartSpec
    formats: list[Literal["svg", "pdf", "png"]] = Field(
        default_factory=lambda: ["svg", "pdf"],
        min_length=1,
    )
    output_path: str | None = None


class TableExportRequest(UiModel):
    spec: TableSpec
    output_path: str | None = None


class EvaluationExportRequest(UiModel):
    spec: EvaluationSpec
    output_path: str | None = None


class CheckpointCatalogRequest(UiModel):
    artifact_root: str = "runs"


class InferenceRequest(UiModel):
    checkpoint_path: str = Field(min_length=1)
    config_path: str | None = None
    splits: list[str] = Field(default_factory=lambda: ["test"], min_length=1)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    predict: bool = False
    overrides: list[str] = Field(default_factory=list)
    launcher_path: str | None = None
    launcher_overrides: list[str] = Field(default_factory=list)
    artifact_root: str = "runs"


def _plan_summary(plan: Plan) -> dict[str, Any]:
    trials = sorted({run.trial_id for run in plan.runs})
    return {
        "study_id": plan.study_id,
        "runs": len(plan.runs),
        "trials": len(trials),
        "trial_ids": trials,
        "run_ids": [run.run_id for run in plan.runs],
        "run_details": [
            {
                "run_id": run.run_id,
                "trial_id": run.trial_id,
                "assignments": run.assignments,
            }
            for run in plan.runs
        ],
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
                "catalog": spec.catalog,
                "editor": spec.editor,
                "metadata": dict(spec.metadata or {}),
                "schema": schema,
            }
        )
    return catalog


def _registry_for_config(config_plugins: list[str], server_plugins: list[str]) -> Registry:
    modules = list(dict.fromkeys([*server_plugins, *config_plugins]))
    return load_registry(modules)


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_gpu(
    launcher: dict[str, Any],
    resources: dict[str, Any],
) -> dict[str, Any] | None:
    gpu = launcher.get("gpu")
    if isinstance(gpu, dict):
        return gpu
    attempts = resources.get("attempts")
    if not isinstance(attempts, list):
        return None
    attempt_id = launcher.get("attempt_id")
    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        if attempt_id is not None and attempt.get("attempt_id") != attempt_id:
            continue
        gpu = attempt.get("gpu")
        return gpu if isinstance(gpu, dict) else None
    return None


def _catalog_runs(workspace: Workspace, root: Path, limit: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = 0
    counts: dict[str, int] = {}
    for status_path in sorted(root.glob("*/*/status.json")):
        total += 1
        status = _read_json_mapping(status_path)
        state = str(status.get("state", "unknown"))
        counts[state] = counts.get(state, 0) + 1
        if len(rows) >= limit:
            continue
        run_dir = status_path.parent
        manifest = _read_json_mapping(run_dir / "manifest.json")
        launcher = _read_json_mapping(run_dir / "launcher.json")
        resources = _read_json_mapping(run_dir / "resources.json")
        manifest_config = manifest.get("config")
        stages = status.get("stages")
        total_resources = resources.get("total")
        rows.append(
            {
                "study_id": str(manifest.get("study_id", run_dir.parent.name)),
                "trial_id": str(manifest.get("trial_id", "unknown")),
                "run_id": str(status.get("run_id", run_dir.name)),
                "seed": manifest_config.get("seed") if isinstance(manifest_config, dict) else None,
                "state": state,
                "attempt": status.get("attempt"),
                "updated_at": status.get("updated_at"),
                "path": run_dir.relative_to(workspace.root).as_posix(),
                "stages": {
                    str(name): str(value.get("state", "unknown"))
                    for name, value in stages.items()
                    if isinstance(value, dict)
                }
                if isinstance(stages, dict)
                else {},
                "worker_pid": launcher.get("worker_pid"),
                "gpu": _latest_gpu(launcher, resources),
                "resources": total_resources if isinstance(total_resources, dict) else {},
            }
        )
    return {
        "root": root.relative_to(workspace.root).as_posix(),
        "total": total,
        "counts": counts,
        "runs": rows,
        "truncated": total > len(rows),
    }


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
    app.state.launch_manager = DurableLaunchManager(workspace, server_plugins)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; img-src 'self' data:; connect-src 'self' ws: wss:; "
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
            "diagnostics": {
                "research_assistant": __version__,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "executable": sys.executable,
            },
            "plugins": server_plugins,
            "files": tree["entries"],
            "files_truncated": tree["truncated"],
            "components": _component_catalog(registry),
        }

    @app.post("/api/project/init", status_code=201)
    def initialize_workspace_project() -> dict[str, Any]:
        created = initialize_project(workspace.root)
        return {
            "created": [path.relative_to(workspace.root).as_posix() for path in created],
            "restart_required": True,
            "plugin": "ra_project.plugin",
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
    @app.post("/api/config/inspect")
    def inspect_config(payload: ConfigValidateRequest) -> dict[str, Any]:
        source = workspace.resolve(payload.path)
        config = load_config_text(
            payload.content,
            source,
            payload.overrides,
            allowed_root=workspace.root,
        )
        configured_registry = _registry_for_config(config.plugins, server_plugins)
        plan = compile_plan(config, configured_registry)
        return {
            "valid": True,
            "experiment": config.experiment.name,
            "rendered": dump_config(config),
            "plan": _plan_summary(plan),
            "manifests": (
                [manifest.model_dump(mode="json") for manifest in plan.runs]
                if payload.include_manifests
                else []
            ),
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

    @app.post("/api/torch/graph/validate")
    def validate_torch_graph(payload: GraphValidateRequest) -> dict[str, Any]:
        validate_graph(payload.params, registry)
        return {
            "valid": True,
            "nodes": len(payload.params.nodes),
            "inputs": payload.params.input_names,
            "outputs": payload.params.outputs,
        }

    @app.get("/api/launches")
    def list_launches() -> dict[str, Any]:
        return {"launches": app.state.launch_manager.list()}

    @app.post("/api/launches/preview")
    def preview_launch(payload: LaunchCreateRequest) -> dict[str, Any]:
        return app.state.launch_manager.preview(payload)

    @app.post("/api/launches", status_code=202)
    def create_launch(payload: LaunchCreateRequest) -> dict[str, Any]:
        return app.state.launch_manager.create(payload)

    @app.get("/api/launches/{launch_id}")
    def launch_detail(
        launch_id: str,
        run_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return app.state.launch_manager.detail(launch_id, run_id)

    def prepare_inference(payload: InferenceRequest):
        checkpoint_path = bounded_artifact_root(workspace.root, payload.checkpoint_path)
        descriptor = inspect_checkpoint(checkpoint_path)
        if payload.config_path is not None:
            source_file = workspace.read(payload.config_path)
            source_config = load_config_text(
                source_file.content,
                workspace.resolve(source_file.path),
                payload.overrides,
                allowed_root=workspace.root,
            )
            config_label = source_file.path
        elif descriptor.manifest is not None:
            document = descriptor.manifest.config.model_dump(mode="python")
            source_config = load_config_text(
                yaml.safe_dump(document, sort_keys=False),
                workspace.root / "managed-checkpoint.yaml",
                payload.overrides,
                allowed_root=workspace.root,
            )
            config_label = f"checkpoint:{payload.checkpoint_path}"
        else:
            raise WorkspaceError("an external checkpoint requires an explicit config")
        configured_registry = _registry_for_config(source_config.plugins, server_plugins)
        config, provenance = build_inference_config(
            checkpoint_path,
            configured_registry,
            base_config=source_config,
            splits=payload.splits,
            device=payload.device,
            predict=payload.predict,
        )
        config = config.model_copy(
            update={"plugins": list(dict.fromkeys([*server_plugins, *config.plugins]))}
        )
        return descriptor, config, provenance, config_label

    @app.post("/api/checkpoints/catalog")
    def checkpoint_catalog(payload: CheckpointCatalogRequest) -> dict[str, Any]:
        root_path = bounded_artifact_root(workspace.root, payload.artifact_root)
        rows = [
            descriptor.as_dict(relative_to=workspace.root)
            for descriptor in catalog_checkpoints(root_path)
        ]
        return {"artifact_root": payload.artifact_root, "checkpoints": rows}

    @app.post("/api/checkpoints/inspect")
    def checkpoint_inspect(payload: InferenceRequest) -> dict[str, Any]:
        descriptor, config, provenance, config_label = prepare_inference(payload)
        preview = app.state.launch_manager.preview_resolved(
            config,
            config_path=config_label,
            launcher_path=payload.launcher_path,
            artifact_root=payload.artifact_root,
            launcher_overrides=payload.launcher_overrides,
            provenance=provenance,
        )
        return {
            "checkpoint": descriptor.as_dict(relative_to=workspace.root),
            "config": config.model_dump(mode="json"),
            "rendered": dump_config(config),
            "launch": preview,
        }

    @app.post("/api/checkpoints/infer", status_code=202)
    def checkpoint_infer(payload: InferenceRequest) -> dict[str, Any]:
        _descriptor, config, provenance, config_label = prepare_inference(payload)
        return app.state.launch_manager.create_resolved(
            config,
            config_path=config_label,
            launcher_path=payload.launcher_path,
            artifact_root=payload.artifact_root,
            launcher_overrides=payload.launcher_overrides,
            provenance=provenance,
        )

    def analytics_index(artifact_root: str) -> MetricIndex:
        root_path = bounded_artifact_root(workspace.root, artifact_root)
        key = str(root_path)
        index = app.state.metric_indices.get(key)
        if index is None:
            index = MetricIndex(root_path)
            app.state.metric_indices[key] = index
        return index

    def report_destination(name: str, output_path: str | None = None) -> Path:
        if output_path is not None:
            destination = workspace.resolve(output_path)
            if destination.exists() and not destination.is_dir():
                raise WorkspaceError(f"report destination is not a directory: {output_path}")
            return destination
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

    @app.post("/api/runs/catalog")
    def run_catalog(payload: RunCatalogRequest) -> dict[str, Any]:
        root_path = bounded_artifact_root(workspace.root, payload.artifact_root)
        catalog = _catalog_runs(workspace, root_path, payload.limit)
        summaries = collect_summary(root_path, stage=payload.stage, metric=payload.metric)
        resources = collect_resource_summary(
            root_path,
            trial_ids=set(payload.trial_ids) or None,
        )
        return {
            "catalog": catalog,
            "summary": summaries[:MAX_REPORT_ROWS],
            "summary_total": len(summaries),
            "summary_truncated": len(summaries) > MAX_REPORT_ROWS,
            "resources": resources[:MAX_REPORT_ROWS],
            "resources_total": len(resources),
            "resources_truncated": len(resources) > MAX_REPORT_ROWS,
        }

    @app.post("/api/analytics/spec/load")
    def load_report_spec(payload: ReportSpecLoadRequest) -> dict[str, Any]:
        source = workspace.read(payload.path)
        try:
            document = yaml.safe_load(source.content)
            model = ChartSpec if payload.kind == "chart" else TableSpec
            spec = model.model_validate(document)
        except (yaml.YAMLError, ValidationError) as exc:
            raise WorkspaceError(f"invalid {payload.kind} spec {payload.path}: {exc}") from exc
        bounded_artifact_root(workspace.root, spec.artifact_root)
        return {
            "path": source.path,
            "kind": payload.kind,
            "spec": spec.model_dump(mode="json"),
        }

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

    @app.post("/api/analytics/evaluate")
    def analytics_evaluate(spec: EvaluationSpec) -> dict[str, Any]:
        index = analytics_index(spec.artifact_root)
        refresh = index.refresh()
        evaluation = index.evaluate(spec)
        return {
            "refresh": refresh,
            "evaluation": evaluation,
            "latex": render_evaluation_latex(evaluation, spec),
        }

    @app.post("/api/analytics/evaluation/export")
    def export_evaluation(payload: EvaluationExportRequest) -> dict[str, Any]:
        index = analytics_index(payload.spec.artifact_root)
        index.refresh()
        destination = report_destination(payload.spec.name, payload.output_path)
        write_evaluation_bundle(index, payload.spec, destination)
        return {"path": destination.relative_to(workspace.root).as_posix()}

    @app.post("/api/analytics/chart/export")
    def analytics_chart_export(payload: ChartExportRequest) -> dict[str, Any]:
        index = analytics_index(payload.spec.artifact_root)
        index.refresh()
        destination = report_destination(payload.spec.name, payload.output_path)
        write_chart_bundle(index, payload.spec, destination, formats=tuple(payload.formats))
        return {"path": destination.relative_to(workspace.root).as_posix()}

    @app.post("/api/analytics/table/export")
    def analytics_table_export(payload: TableExportRequest) -> dict[str, Any]:
        index = analytics_index(payload.spec.artifact_root)
        index.refresh()
        destination = report_destination(payload.spec.name, payload.output_path)
        write_table_bundle(index, payload.spec, destination)
        return {"path": destination.relative_to(workspace.root).as_posix()}

    # Register feature APIs explicitly. Frontend modules are compiled into the Vite bundle;
    # these functions expose only typed server routes and never rewrite HTML or JavaScript.
    from research_assistant.explorer_ui import register_architecture_routes
    from research_assistant.notebook_ui import register_notebook_routes
    from research_assistant.pipeline_ui import register_pipeline_routes
    from research_assistant.research_ui import register_research_routes
    from research_assistant.research_workspace_ui import register_research_workspace
    from research_assistant.system_monitor_ui import register_system_monitor_routes
    from research_assistant.terminal_ui import register_terminal_routes
    from research_assistant.ui.extensions import register_job_routes
    from research_assistant.workbench_ui import register_workbench_routes
    from research_assistant.workspace_browser_ui import register_workspace_browser_routes

    register_job_routes(app)
    register_pipeline_routes(app)
    register_research_routes(app)
    register_workbench_routes(app)
    register_terminal_routes(app)
    register_system_monitor_routes(app)
    register_workspace_browser_routes(app)
    register_notebook_routes(app)
    register_architecture_routes(app)
    register_research_workspace(app)

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
