from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.asset_registry import AssetRegistry
from research_assistant.diagnostics import diagnostic_catalog, load_diagnostic_policy
from research_assistant.errors import ResearchAssistantError
from research_assistant.publication import (
    PublicationSpec,
    build_publication_bundle,
    preview_publication,
)
from research_assistant.stage_cache import StageCache



class PipelineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RootRequest(PipelineModel):
    artifact_root: str = "runs"


class CachePruneRequest(PipelineModel):
    keep_entries: int = Field(default=10000, ge=0, le=1000000)


class AssetActionRequest(PipelineModel):
    asset_id: str = Field(min_length=1)
    action: Literal[
        "select", "release", "archive", "candidate", "pin", "unpin", "delete"
    ]
    delete_source: bool = False


class PublicationRequest(PipelineModel):
    spec: PublicationSpec
    output_path: str | None = None


def register_pipeline_routes(app) -> None:
    try:
        from fastapi import Query
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace
    @app.post("/api/jobs/{job_id}/adopt")
    def adopt_job(job_id: str) -> dict[str, Any]:
        return app.state.job_service.adopt(job_id)

    @app.get("/api/pipeline/cache")
    def cache_stats() -> dict[str, Any]:
        return StageCache(workspace.root, app.state.registry).stats()

    @app.post("/api/pipeline/cache/prune")
    def cache_prune(payload: CachePruneRequest) -> dict[str, Any]:
        return StageCache(workspace.root, app.state.registry).prune(
            keep_entries=payload.keep_entries
        )

    @app.post("/api/pipeline/assets/refresh")
    def assets_refresh(payload: RootRequest) -> dict[str, Any]:
        registry = AssetRegistry(workspace.root)
        try:
            return registry.refresh(payload.artifact_root)
        finally:
            registry.close()

    @app.get("/api/pipeline/assets")
    def assets_list(
        kind: Literal["artifact", "checkpoint"] | None = Query(default=None),
        status: Literal["candidate", "selected", "released", "archived"] | None = Query(
            default=None
        ),
        run_id: str | None = Query(default=None),
        search: str | None = Query(default=None),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> dict[str, Any]:
        registry = AssetRegistry(workspace.root)
        try:
            rows = registry.list(
                kind=kind,
                status=status,
                run_id=run_id,
                search=search,
                limit=limit,
            )
            return {"assets": rows, "stats": registry.stats()}
        finally:
            registry.close()

    @app.post("/api/pipeline/assets/action")
    def asset_action(payload: AssetActionRequest) -> dict[str, Any]:
        registry = AssetRegistry(workspace.root)
        try:
            if payload.action == "pin":
                return registry.pin(payload.asset_id, True)
            if payload.action == "unpin":
                return registry.pin(payload.asset_id, False)
            if payload.action == "delete":
                registry.delete(payload.asset_id, delete_source=payload.delete_source)
                return {"deleted": payload.asset_id}
            status = {
                "select": "selected",
                "release": "released",
                "archive": "archived",
                "candidate": "candidate",
            }[payload.action]
            return registry.promote(payload.asset_id, status)  # type: ignore[arg-type]
        finally:
            registry.close()

    @app.get("/api/pipeline/diagnostics")
    def diagnostics(
        artifact_root: str = Query(default="runs"),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> dict[str, Any]:
        root = workspace.resolve(artifact_root)
        result = diagnostic_catalog(root, limit=limit)
        result["policy"] = load_diagnostic_policy(workspace.root).model_dump(mode="json")
        return result

    @app.post("/api/pipeline/publication/preview")
    def publication_preview(payload: PublicationRequest) -> dict[str, Any]:
        return preview_publication(workspace.root, payload.spec)

    @app.post("/api/pipeline/publication/build")
    def publication_build(payload: PublicationRequest) -> dict[str, Any]:
        destination = payload.output_path or f"publications/{payload.spec.name}"
        path = build_publication_bundle(workspace.root, payload.spec, destination)
        return {"path": path.relative_to(workspace.root).as_posix()}

