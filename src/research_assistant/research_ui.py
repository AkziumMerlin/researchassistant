from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.dataset_registry import DatasetRegistry, DatasetSpec
from research_assistant.errors import ResearchAssistantError
from research_assistant.hpo import HpoController, HpoSpec
from research_assistant.publication_plus import (
    EnhancedPublicationSpec,
    build_enhanced_publication_bundle,
    preview_enhanced_publication,
)
from research_assistant.research_log import (
    DecisionInput,
    EvidenceInput,
    HypothesisInput,
    ResearchLog,
)
from research_assistant.selection import (
    SelectionSpec,
    evaluate_selection,
    list_selection_locks,
    lock_selection,
    preview_selection,
)
from research_assistant.statistics_suite import (
    StatisticalSpec,
    analyze_statistics,
    write_statistical_report,
)


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HpoRequest(ResearchModel):
    spec: HpoSpec
    count: int = Field(default=1, ge=1, le=1000)
    launch: bool = False


class DatasetRegisterRequest(ResearchModel):
    spec: DatasetSpec


class DatasetActionRequest(ResearchModel):
    dataset_id: str
    destination: str | None = None
    overwrite: bool = False


class SelectionRequest(ResearchModel):
    spec: SelectionSpec
    overwrite: bool = False


class SelectionEvaluationRequest(ResearchModel):
    name_or_path: str
    output_path: str | None = None


class StatisticsRequest(ResearchModel):
    spec: StatisticalSpec
    output_path: str | None = None


class PublicationFullRequest(ResearchModel):
    spec: EnhancedPublicationSpec
    output_path: str | None = None


class HypothesisUpdateRequest(ResearchModel):
    hypothesis_id: str
    status: str | None = None
    conclusion: str | None = None
    title: str | None = None
    statement: str | None = None


def register_research_routes(app) -> None:
    try:
        from fastapi import Query
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace
    @app.post("/api/research/hpo/status")
    def hpo_status(payload: HpoRequest) -> dict[str, Any]:
        controller = HpoController(workspace.root, payload.spec)
        return controller.refresh(prune=False)

    @app.post("/api/research/hpo/propose")
    def hpo_propose(payload: HpoRequest) -> dict[str, Any]:
        controller = HpoController(workspace.root, payload.spec)
        proposals = controller.propose(payload.count)
        launched = (
            controller.launch([str(row["trial_id"]) for row in proposals])
            if payload.launch
            else []
        )
        return {"proposals": proposals, "launched": launched}

    @app.post("/api/research/hpo/step")
    def hpo_step(payload: HpoRequest) -> dict[str, Any]:
        return HpoController(workspace.root, payload.spec).step()

    @app.get("/api/research/datasets")
    def datasets_list(
        name: str | None = Query(default=None),
        search: str | None = Query(default=None),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> dict[str, Any]:
        registry = DatasetRegistry(workspace.root)
        try:
            return {"datasets": registry.list(name=name, search=search, limit=limit)}
        finally:
            registry.close()

    @app.post("/api/research/datasets/register")
    def datasets_register(payload: DatasetRegisterRequest) -> dict[str, Any]:
        registry = DatasetRegistry(workspace.root)
        try:
            return registry.register(payload.spec)
        finally:
            registry.close()

    @app.post("/api/research/datasets/validate")
    def datasets_validate(payload: DatasetActionRequest) -> dict[str, Any]:
        registry = DatasetRegistry(workspace.root)
        try:
            return registry.validate(payload.dataset_id)
        finally:
            registry.close()

    @app.post("/api/research/datasets/materialize")
    def datasets_materialize(payload: DatasetActionRequest) -> dict[str, Any]:
        if not payload.destination:
            raise ResearchAssistantError("dataset materialization requires destination")
        registry = DatasetRegistry(workspace.root)
        try:
            path = registry.materialize(
                payload.dataset_id,
                payload.destination,
                overwrite=payload.overwrite,
            )
            return {"path": path.relative_to(workspace.root).as_posix()}
        finally:
            registry.close()

    @app.post("/api/research/selection/preview")
    def selection_preview(payload: SelectionRequest) -> dict[str, Any]:
        return preview_selection(workspace.root, payload.spec)

    @app.post("/api/research/selection/lock")
    def selection_lock(payload: SelectionRequest) -> dict[str, Any]:
        return lock_selection(
            workspace.root,
            payload.spec,
            overwrite=payload.overwrite,
        )

    @app.post("/api/research/selection/evaluate")
    def selection_evaluate(payload: SelectionEvaluationRequest) -> dict[str, Any]:
        return evaluate_selection(
            workspace.root,
            payload.name_or_path,
            output=payload.output_path,
        )

    @app.get("/api/research/selections")
    def selections_list() -> dict[str, Any]:
        return {"selections": list_selection_locks(workspace.root)}

    @app.post("/api/research/statistics/run")
    def statistics_run(payload: StatisticsRequest) -> dict[str, Any]:
        if payload.output_path:
            path = write_statistical_report(
                workspace.root, payload.spec, payload.output_path
            )
            return {
                "path": path.relative_to(workspace.root).as_posix(),
                "analysis": analyze_statistics(workspace.root, payload.spec),
            }
        return analyze_statistics(workspace.root, payload.spec)

    @app.get("/api/research/hypotheses")
    def hypotheses_list(
        status: str | None = Query(default=None),
        search: str | None = Query(default=None),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return {
                "hypotheses": log.list_hypotheses(
                    status=status,  # type: ignore[arg-type]
                    search=search,
                    limit=limit,
                )
            }
        finally:
            log.close()

    @app.post("/api/research/hypotheses")
    def hypotheses_create(payload: HypothesisInput) -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return log.create_hypothesis(payload)
        finally:
            log.close()

    @app.post("/api/research/hypotheses/update")
    def hypotheses_update(payload: HypothesisUpdateRequest) -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return log.update_hypothesis(
                payload.hypothesis_id,
                status=payload.status,  # type: ignore[arg-type]
                conclusion=payload.conclusion,
                title=payload.title,
                statement=payload.statement,
            )
        finally:
            log.close()

    @app.post("/api/research/evidence")
    def evidence_create(payload: EvidenceInput) -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return log.add_evidence(payload)
        finally:
            log.close()

    @app.get("/api/research/decisions")
    def decisions_list(
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return {"decisions": log.list_decisions(limit=limit)}
        finally:
            log.close()

    @app.post("/api/research/decisions")
    def decisions_create(payload: DecisionInput) -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return log.record_decision(payload)
        finally:
            log.close()

    @app.get("/api/research/export")
    def research_export() -> dict[str, Any]:
        log = ResearchLog(workspace.root)
        try:
            return log.export()
        finally:
            log.close()

    @app.post("/api/research/publication/preview")
    def publication_preview(payload: PublicationFullRequest) -> dict[str, Any]:
        return preview_enhanced_publication(workspace.root, payload.spec)

    @app.post("/api/research/publication/build")
    def publication_build(payload: PublicationFullRequest) -> dict[str, Any]:
        destination = payload.output_path or f"publications/{payload.spec.name}"
        path = build_enhanced_publication_bundle(
            workspace.root, payload.spec, destination
        )
        return {"path": path.relative_to(workspace.root).as_posix()}

