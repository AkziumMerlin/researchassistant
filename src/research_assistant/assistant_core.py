from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_assistant.capabilities import CAPABILITIES
from research_assistant.errors import ResearchAssistantError
from research_assistant.notebook_context import NotebookContextStore
from research_assistant.run_workspace import RunWorkspace
from research_assistant.scientific_artifacts import ScientificArtifactCatalog

ActionKind = Literal[
    "inspect_runs",
    "aggregate_runs",
    "compare_artifacts",
    "create_notebook_context",
    "draft_config",
]


class AssistantModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssistantRequest(AssistantModel):
    goal: str = Field(min_length=3, max_length=8000)
    artifact_root: str = "runs"
    run_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    allow_writes: bool = False


class AssistantAction(AssistantModel):
    action_id: str
    kind: ActionKind
    title: str
    rationale: str
    capability: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    mutates_workspace: bool = False


class AssistantPlan(AssistantModel):
    schema_version: Literal[1] = 1
    goal: str
    summary: str
    actions: list[AssistantAction]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_actions(self) -> AssistantPlan:
        known = {item.capability_id for item in CAPABILITIES}
        identifiers: set[str] = set()
        for action in self.actions:
            if action.action_id in identifiers:
                raise ValueError("assistant action identifiers must be unique")
            identifiers.add(action.action_id)
            if action.capability not in known:
                raise ValueError(f"unknown assistant capability {action.capability!r}")
        return self


class AssistantProvider(Protocol):
    def plan(self, request: AssistantRequest) -> AssistantPlan: ...


class DeterministicAssistant:
    """Conservative fallback planner used when no project AI provider is registered."""

    def plan(self, request: AssistantRequest) -> AssistantPlan:
        goal = request.goal.strip()
        lower = goal.lower()
        actions: list[AssistantAction] = []
        warnings: list[str] = []

        if request.run_ids or any(token in lower for token in ("run", "эксперимент", "результат")):
            actions.append(
                AssistantAction(
                    action_id="inspect-runs",
                    kind="inspect_runs",
                    title="Inspect selected runs",
                    rationale="Resolve run states, configurations, metrics and resource provenance first.",
                    capability="run.workspace",
                    parameters={"run_ids": request.run_ids, "artifact_root": request.artifact_root},
                )
            )

        if request.run_ids and len(request.run_ids) > 1:
            actions.append(
                AssistantAction(
                    action_id="aggregate-runs",
                    kind="aggregate_runs",
                    title="Aggregate selected runs",
                    rationale="The selected runs may belong to different studies or trials; aggregate only explicit run identifiers.",
                    capability="run.aggregate",
                    parameters={
                        "run_ids": request.run_ids,
                        "artifact_root": request.artifact_root,
                        "group_by": ["study_id", "trial_id"],
                    },
                )
            )

        if len(request.artifact_ids) >= 2 or any(
            token in lower for token in ("compare", "сравн", "ошиб", "artifact", "артефакт")
        ):
            if len(request.artifact_ids) >= 2:
                actions.append(
                    AssistantAction(
                        action_id="compare-artifacts",
                        kind="compare_artifacts",
                        title="Compare scientific artifacts",
                        rationale="Use typed artifact metadata and bounded numerical comparison rather than loading arbitrary files.",
                        capability="artifact.preview",
                        parameters={
                            "left_id": request.artifact_ids[0],
                            "right_id": request.artifact_ids[1],
                        },
                    )
                )
            else:
                warnings.append("Artifact comparison needs at least two explicit artifact identifiers.")

        if request.run_ids or request.artifact_ids:
            actions.append(
                AssistantAction(
                    action_id="analysis-context",
                    kind="create_notebook_context",
                    title="Create a reproducible notebook context",
                    rationale="Bind analysis to an immutable explicit selection instead of relying on notebook-global filesystem discovery.",
                    capability="notebook.context",
                    parameters={
                        "run_ids": request.run_ids,
                        "artifact_ids": request.artifact_ids,
                        "artifact_root": request.artifact_root,
                        "label": goal[:80],
                    },
                    mutates_workspace=True,
                )
            )

        if any(token in lower for token in ("config", "конфиг", "train", "обуч", "launch", "запуск")):
            actions.append(
                AssistantAction(
                    action_id="draft-config",
                    kind="draft_config",
                    title="Draft a validated experiment configuration",
                    rationale="Produce a schema-valid draft only; execution remains a separate previewed action.",
                    capability="assistant.plan",
                    parameters={"experiment_name": "assistant-draft"},
                    mutates_workspace=False,
                )
            )

        if not actions:
            actions.append(
                AssistantAction(
                    action_id="inspect-runs",
                    kind="inspect_runs",
                    title="Inspect the current run workspace",
                    rationale="Start from persisted manifests and statuses before proposing research actions.",
                    capability="run.workspace",
                    parameters={"run_ids": [], "artifact_root": request.artifact_root},
                )
            )

        if any(action.mutates_workspace for action in actions) and not request.allow_writes:
            warnings.append(
                "Workspace-mutating actions are present but disabled; enable writes only after reviewing the typed plan."
            )

        return AssistantPlan(
            goal=goal,
            summary=(
                "A conservative typed plan derived from the current selection. It cannot execute "
                "experiments or arbitrary shell commands."
            ),
            actions=actions,
            warnings=warnings,
        )


class AssistantEngine:
    def __init__(
        self,
        workspace: str,
        *,
        provider: AssistantProvider | None = None,
    ) -> None:
        self.workspace = workspace
        self.provider = provider or DeterministicAssistant()

    def plan(self, request: AssistantRequest) -> AssistantPlan:
        return self.provider.plan(request)

    def apply(self, request: AssistantRequest, plan: AssistantPlan) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        handlers: dict[ActionKind, Callable[[AssistantAction], Any]] = {
            "inspect_runs": lambda action: self._inspect_runs(action, request),
            "aggregate_runs": lambda action: self._aggregate_runs(action, request),
            "compare_artifacts": self._compare_artifacts,
            "create_notebook_context": lambda action: self._create_context(action, request),
            "draft_config": self._draft_config,
        }
        for action in plan.actions:
            if action.mutates_workspace and not request.allow_writes:
                results.append(
                    {
                        "action_id": action.action_id,
                        "state": "blocked",
                        "reason": "workspace writes were not explicitly enabled",
                    }
                )
                continue
            try:
                value = handlers[action.kind](action)
            except Exception as exc:
                results.append(
                    {"action_id": action.action_id, "state": "failed", "error": str(exc)}
                )
            else:
                results.append(
                    {"action_id": action.action_id, "state": "completed", "result": value}
                )
        return {"schema_version": 1, "goal": plan.goal, "results": results}

    def _inspect_runs(self, action: AssistantAction, request: AssistantRequest) -> Any:
        workspace = RunWorkspace(self.workspace, action.parameters.get("artifact_root", request.artifact_root))
        run_ids = list(action.parameters.get("run_ids") or [])
        if run_ids:
            return {"runs": workspace.require_runs(run_ids)}
        return workspace.catalog(limit=200)

    def _aggregate_runs(self, action: AssistantAction, request: AssistantRequest) -> Any:
        workspace = RunWorkspace(self.workspace, action.parameters.get("artifact_root", request.artifact_root))
        return workspace.aggregate(
            list(action.parameters.get("run_ids") or []),
            metric=action.parameters.get("metric"),
            stage=action.parameters.get("stage"),
            group_by=list(action.parameters.get("group_by") or ["study_id", "trial_id"]),
        )

    def _compare_artifacts(self, action: AssistantAction) -> Any:
        return ScientificArtifactCatalog(self.workspace).compare(
            str(action.parameters["left_id"]),
            str(action.parameters["right_id"]),
            key=action.parameters.get("key"),
        )

    def _create_context(self, action: AssistantAction, request: AssistantRequest) -> Any:
        return NotebookContextStore(self.workspace).create(
            run_ids=list(action.parameters.get("run_ids") or []),
            artifact_ids=list(action.parameters.get("artifact_ids") or []),
            artifact_root=str(action.parameters.get("artifact_root", request.artifact_root)),
            label=action.parameters.get("label"),
            notebook_path=action.parameters.get("notebook_path"),
        )

    def _draft_config(self, action: AssistantAction) -> Any:
        name = str(action.parameters.get("experiment_name") or "assistant-draft")
        document = {
            "version": 1,
            "experiment": {
                "name": name,
                "description": "Typed ResearchAssistant draft; review components and stages before launch.",
                "tags": ["assistant-draft"],
            },
            "stages": [{"name": "prepare", "type": "core/noop", "params": {}}],
            "resources": {"accelerator": "auto", "devices": 1},
            "artifacts": {"root": "runs"},
        }
        return {"document": document, "yaml": yaml.safe_dump(document, sort_keys=False)}


def validate_plan_payload(value: dict[str, Any]) -> AssistantPlan:
    try:
        return AssistantPlan.model_validate(value)
    except Exception as exc:
        raise ResearchAssistantError(f"invalid typed assistant plan: {exc}") from exc
