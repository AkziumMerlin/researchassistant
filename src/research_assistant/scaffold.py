from __future__ import annotations

from pathlib import Path

from research_assistant.errors import ResearchAssistantError

SMOKE_CONFIG = """version: 1
experiment:
  name: smoke
plugins: [ra_project.plugin]
seed: 0
components:
  value:
    type: example/constant
    params:
      value: 1.0
matrix:
  seed: [0, 1, 2]
stages:
  - name: fit
    type: example/measure
  - name: test
    type: core/noop
    needs: [fit]
    params:
      metrics:
        test/example: 1.0
"""


PLUGIN_TEMPLATE = """from typing import Any

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
        description="Example project component.",
        provider=__name__,
    )
    registry.add(
        "stage",
        "example/measure",
        factory=measure,
        schema=MeasureConfig,
        description="Example stage using a configured component.",
        provider=__name__,
    )
"""


def initialize_project(path: str | Path) -> list[Path]:
    """Create the minimal project scaffold without replacing existing files."""
    root = Path(path).expanduser().resolve()
    files = {
        root / "configs" / "smoke.yaml": SMOKE_CONFIG,
        root / "ra_project" / "__init__.py": "",
        root / "ra_project" / "plugin.py": PLUGIN_TEMPLATE,
    }
    unsafe_parents = sorted(
        {
            str(file.parent)
            for file in files
            if file.parent.is_symlink()
            or not file.resolve(strict=False).is_relative_to(root)
        }
    )
    if unsafe_parents:
        raise ResearchAssistantError(
            f"refusing to initialize through unsafe directory: {', '.join(unsafe_parents)}"
        )
    conflicts = [str(file) for file in files if file.exists() or file.is_symlink()]
    if conflicts:
        raise ResearchAssistantError(f"refusing to overwrite: {', '.join(conflicts)}")
    for file, content in files.items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    return list(files)
