from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.execution import StageContext, StageResult
from research_assistant.registry import Registry


class NoopParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)


def run_noop(params: NoopParams, context: StageContext) -> StageResult:
    if params.message:
        print(f"[{context.manifest.run_id}:{context.stage.name}] {params.message}")
    return StageResult(metrics=params.metrics)


class ValueParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


def build_value(params: ValueParams, _context: Any) -> Any:
    return params.value


def register(registry: Registry) -> None:
    registry.add(
        "stage",
        "core/noop",
        factory=run_noop,
        schema=NoopParams,
        description="Complete a stage without external work; useful for smoke tests.",
        provider="research-assistant",
    )
    registry.add(
        "value",
        "core/value",
        factory=build_value,
        schema=ValueParams,
        description="Return a configured value; useful in examples and plugin tests.",
        provider="research-assistant",
    )
