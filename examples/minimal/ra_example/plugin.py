from typing import Any

from pydantic import BaseModel, ConfigDict

from research_assistant.execution import StageContext, StageResult
from research_assistant.registry import Registry


class ConstantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float


def build_constant(config: ConstantConfig, _context: Any) -> float:
    return config.value


class MeasureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def measure(_config: MeasureConfig, context: StageContext) -> StageResult:
    value = context.component("value")
    return StageResult(metrics={"train/example": value + float(context.seed or 0)})


def register(registry: Registry) -> None:
    registry.add(
        "value",
        "example/constant",
        factory=build_constant,
        schema=ConstantConfig,
        description="A configured scalar.",
        provider=__name__,
    )
    registry.add(
        "stage",
        "example/measure",
        factory=measure,
        schema=MeasureConfig,
        description="Record a deterministic seed-dependent metric.",
        provider=__name__,
    )
