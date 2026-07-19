from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

COMPONENT_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*/[a-zA-Z0-9][a-zA-Z0-9_.-]*$"
LOCAL_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentMeta(StrictModel):
    name: str = Field(pattern=LOCAL_NAME_PATTERN)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class ComponentRef(StrictModel):
    type: str = Field(pattern=COMPONENT_NAME_PATTERN)
    params: dict[str, Any] = Field(default_factory=dict)


class StageConfig(StrictModel):
    name: str = Field(pattern=LOCAL_NAME_PATTERN)
    type: str = Field(pattern=COMPONENT_NAME_PATTERN)
    needs: list[str] = Field(default_factory=list)
    components: dict[str, ComponentRef] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


class ResourceConfig(StrictModel):
    accelerator: Literal["auto", "cpu", "cuda"] = "auto"
    devices: int = Field(default=1, ge=1)
    memory_gb: float | None = Field(default=None, gt=0)


class ArtifactConfig(StrictModel):
    root: str = "runs"


class ExperimentConfig(StrictModel):
    version: Literal[1] = 1
    experiment: ExperimentMeta
    plugins: list[str] = Field(default_factory=list)
    seed: int | None = None
    components: dict[str, ComponentRef] = Field(default_factory=dict)
    matrix: dict[str, list[Any]] = Field(default_factory=dict)
    stages: list[StageConfig]
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    artifacts: ArtifactConfig = Field(default_factory=ArtifactConfig)

    @model_validator(mode="after")
    def validate_graph_names(self) -> ExperimentConfig:
        names = [stage.name for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("stage names must be unique")

        known = set(names)
        for stage in self.stages:
            missing = sorted(set(stage.needs) - known)
            if missing:
                raise ValueError(
                    f"stage {stage.name!r} depends on unknown stages: {', '.join(missing)}"
                )
            if stage.name in stage.needs:
                raise ValueError(f"stage {stage.name!r} cannot depend on itself")
        return self
