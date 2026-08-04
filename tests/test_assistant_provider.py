from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from research_assistant.assistant_core import AssistantEngine, AssistantRequest
from research_assistant.registry import Registry


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: str = "plugin"


class Provider:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def plan(self, request: AssistantRequest) -> dict[str, object]:
        return {
            "schema_version": 1,
            "goal": request.goal,
            "summary": f"{self.prefix}: typed provider",
            "actions": [
                {
                    "action_id": "inspect",
                    "kind": "inspect_runs",
                    "title": "Inspect",
                    "rationale": "Read persisted run state.",
                    "capability": "run.workspace",
                    "parameters": {"run_ids": []},
                    "mutates_workspace": False,
                }
            ],
            "warnings": [],
        }


def test_project_plugin_can_supply_a_typed_assistant_provider(tmp_path: Path) -> None:
    registry = Registry()
    registry.add(
        "assistant",
        "test/provider",
        factory=lambda params, _context: Provider(params.prefix),
        schema=ProviderConfig,
        provider=__name__,
    )
    request = AssistantRequest(
        goal="Inspect experiment state",
        provider="test/provider",
        provider_params={"prefix": "project"},
    )

    plan = AssistantEngine(str(tmp_path), registry=registry).plan(request)

    assert plan.summary == "project: typed provider"
    assert plan.actions[0].capability == "run.workspace"
