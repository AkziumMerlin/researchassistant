from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.advanced_analytics import (
    AdvancedChartSpec,
    advanced_chart,
    write_advanced_chart_bundle,
)
from research_assistant.analytics import MetricIndex, bounded_artifact_root
from research_assistant.config import dump_config, parse_config
from research_assistant.errors import ResearchAssistantError
from research_assistant.jobs import JobError, JobService, JobStartRequest
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry


class AdvancedExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: AdvancedChartSpec
    output_path: str = Field(min_length=1)
    formats: list[Literal["svg", "pdf", "png"]] = Field(default_factory=list)

_INSTALLED = False


def _plan_summary(plan) -> dict[str, Any]:
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


def _create_config_from_extended_payload(app, payload: dict[str, Any]) -> dict[str, Any]:
    workspace = app.state.workspace
    path = str(payload.get("path") or "")
    workspace.resolve(path)
    seeds = payload.get("seeds") or [0]
    if (
        not isinstance(seeds, list)
        or not seeds
        or not all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds)
    ):
        raise JobError("seeds must be a non-empty list of integers")
    if len(seeds) != len(set(seeds)):
        raise JobError("seeds must be unique")

    components: dict[str, Any] = {}
    for raw in payload.get("components") or []:
        if not isinstance(raw, dict):
            raise JobError("components must contain mappings")
        kind = str(raw.get("kind") or "")
        if not kind or kind in components:
            raise JobError(f"invalid or duplicate component kind: {kind!r}")
        components[kind] = {
            "type": raw.get("type"),
            "params": raw.get("params") or {},
        }

    stages: list[dict[str, Any]] = []
    for raw in payload.get("stages") or []:
        if not isinstance(raw, dict):
            raise JobError("stages must contain mappings")
        stage = {
            "name": raw.get("name"),
            "type": raw.get("type"),
            "needs": raw.get("needs") or [],
            "params": raw.get("params") or {},
        }
        stage_components = raw.get("components") or {}
        if stage_components:
            if not isinstance(stage_components, dict):
                raise JobError("stage-local components must be a mapping")
            stage["components"] = stage_components
        stages.append(stage)
    if not stages:
        raise JobError("an experiment must contain at least one stage")

    experiment = {
        "name": payload.get("experiment_name"),
        "tags": payload.get("tags") or [],
    }
    if payload.get("description"):
        experiment["description"] = payload["description"]

    matrix = payload.get("matrix") or {}
    if not isinstance(matrix, dict):
        raise JobError("matrix must be a mapping from dotted paths to value lists")
    matrix = dict(matrix)
    for axis, values in matrix.items():
        if not isinstance(axis, str) or not axis:
            raise JobError("matrix axis names must be non-empty strings")
        if not isinstance(values, list) or not values:
            raise JobError(f"matrix axis {axis!r} must contain at least one value")
    if len(seeds) > 1:
        matrix.setdefault("seed", seeds)

    document: dict[str, Any] = {
        "version": 1,
        "experiment": experiment,
        "plugins": list(app.state.plugins),
        "seed": seeds[0],
        "components": components,
        "stages": stages,
        "resources": {
            "accelerator": payload.get("accelerator", "auto"),
            "devices": payload.get("devices", 1),
            "memory_gb": payload.get("memory_gb"),
        },
        "artifacts": {"root": payload.get("artifact_root", "runs")},
    }
    if matrix:
        document["matrix"] = matrix
    config = parse_config(document)
    registry = load_registry(list(dict.fromkeys([*app.state.plugins, *config.plugins])))
    plan = compile_plan(config, registry)
    return {
        "path": path,
        "content": dump_config(config, compact=True),
        "plan": _plan_summary(plan),
    }


def _register_routes(app, server_module) -> None:
    try:
        from fastapi import Query, Request
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace
    service = JobService(workspace.root, app.state.plugins)
    app.state.job_service = service
    extension_script = Path(__file__).with_name("static") / "jobs-extension.js"
    original_index = Path(server_module.__file__).with_name("static") / "index.html"

    @app.middleware("http")
    async def extended_ui_middleware(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/":
            html = original_index.read_text(encoding="utf-8")
            marker = '<script type="module" src="/api/extensions/jobs.js"></script>'
            html = html.replace("</head>", f"  {marker}\n  </head>")
            response = HTMLResponse(html)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "worker-src 'self' blob:; img-src 'self' data: blob:; connect-src 'self'; "
                "font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response
        if request.method == "POST" and request.url.path == "/api/config/create":
            try:
                raw = await request.json()
                if not isinstance(raw, dict):
                    raise JobError("config creator payload must be a mapping")
                result = _create_config_from_extended_payload(app, raw)
                return JSONResponse(result)
            except ResearchAssistantError as exc:
                return JSONResponse(status_code=400, content={"detail": str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return JSONResponse(status_code=400, content={"detail": str(exc)})
        return await call_next(request)

    @app.get("/api/extensions/jobs.js")
    def extension_javascript():
        return Response(
            extension_script.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": service.list()}

    @app.post("/api/jobs/preview")
    def preview_job(payload: JobStartRequest) -> dict[str, Any]:
        return service.preview(payload)

    @app.post("/api/jobs", status_code=202)
    def start_job(payload: JobStartRequest) -> dict[str, Any]:
        return service.start(payload)

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str, run_id: str | None = Query(default=None)) -> dict[str, Any]:
        return service.detail(job_id, run_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        return service.cancel(job_id)

    @app.post("/api/jobs/{job_id}/recover")
    def recover_job(job_id: str) -> dict[str, Any]:
        return service.recover(job_id)

    @app.get("/api/jobs/{job_id}/logs")
    def job_logs(
        job_id: str,
        source: Literal["scheduler", "worker"] = Query(default="scheduler"),
        run_id: str | None = Query(default=None),
        cursor: int | None = Query(default=None, ge=0),
        limit: int = Query(default=65536, ge=1, le=262144),
        tail: bool = Query(default=False),
    ) -> dict[str, Any]:
        return service.log_page(
            job_id,
            source=source,
            run_id=run_id,
            cursor=cursor,
            limit=limit,
            tail=tail,
        )

    @app.get("/api/jobs/{job_id}/metrics")
    def job_metrics(
        job_id: str,
        run_id: str = Query(min_length=1),
        since_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        return service.metrics(
            job_id,
            run_id,
            since_sequence=since_sequence,
            limit=limit,
        )

    @app.get("/api/jobs/{job_id}/artifacts")
    def job_artifacts(
        job_id: str,
        run_id: str = Query(min_length=1),
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> dict[str, Any]:
        return service.artifacts(job_id, run_id, limit=limit)

    @app.get("/api/jobs/{job_id}/artifacts/preview")
    def artifact_preview(
        job_id: str,
        run_id: str = Query(min_length=1),
        path: str = Query(min_length=1),
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=65536, ge=1, le=262144),
    ) -> dict[str, Any]:
        return service.artifact_preview(job_id, run_id, path, cursor=cursor, limit=limit)

    @app.get("/api/jobs/{job_id}/artifacts/file")
    def artifact_file(
        job_id: str,
        run_id: str = Query(min_length=1),
        path: str = Query(min_length=1),
    ):
        return FileResponse(service.artifact_path(job_id, run_id, path))

    def metric_index(spec: AdvancedChartSpec) -> MetricIndex:
        root = bounded_artifact_root(workspace.root, spec.artifact_root)
        key = str(root)
        index: MetricIndex | None = app.state.metric_indices.get(key)
        if index is None:
            index = MetricIndex(root)
            app.state.metric_indices[key] = index
        return index

    @app.post("/api/analytics/advanced")
    def analytics_advanced(spec: AdvancedChartSpec) -> dict[str, Any]:
        index = metric_index(spec)
        refresh = index.refresh()
        return {"refresh": refresh, "chart": advanced_chart(index, spec)}

    @app.post("/api/analytics/advanced/export")
    def analytics_advanced_export(payload: AdvancedExportRequest) -> dict[str, Any]:
        index = metric_index(payload.spec)
        refresh = index.refresh()
        destination = workspace.resolve(payload.output_path)
        write_advanced_chart_bundle(
            index,
            payload.spec,
            destination,
            formats=tuple(payload.formats),
        )
        return {
            "refresh": refresh,
            "path": destination.relative_to(workspace.root).as_posix(),
        }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from research_assistant.ui import server

    original_create_app = server.create_app

    def create_app(root, plugins=None, *, ssh_mode=None):
        app = original_create_app(root, plugins, ssh_mode=ssh_mode)
        _register_routes(app, server)
        return app

    server.create_app = create_app
    _INSTALLED = True
