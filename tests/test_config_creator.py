from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from typer.testing import CliRunner

from research_assistant.builtin import register as register_builtin
from research_assistant.cli import app
from research_assistant.config import load_config
from research_assistant.config_creator import ConfigCreator, parse_selection
from research_assistant.planning import compile_plan
from research_assistant.registry import Registry


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0, description="Hidden width.")
    activation: str = "gelu"


class FitParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epochs: int = Field(default=3, ge=1)


class ScriptedPrompt:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def ask(self, label: str, *, default: str | None = None) -> str:
        if label == "Seeds [YAML list]":
            return "[1, 2]"
        if "width" in label:
            return "64"
        if default is None:
            raise AssertionError(f"missing scripted answer for {label}")
        return default

    def choose(self, label: str, options, *, default: int = 0) -> int:
        if label == "Accelerator":
            return list(options).index("cpu")
        return default

    def confirm(self, label: str, *, default: bool = False) -> bool:
        if label in {"Add a registered component?", "Add a stage?"}:
            return False
        return default

    def write(self, message: str) -> None:
        self.messages.append(message)


def creator_registry() -> Registry:
    registry = Registry()
    register_builtin(registry)
    registry.add("model", "test/model", factory=lambda params, context: None, schema=ModelParams)
    registry.add("stage", "test/fit", factory=lambda params, context: None, schema=FitParams)
    return registry


def test_schema_driven_creator_builds_valid_matrix_config() -> None:
    registry = creator_registry()
    creator = ConfigCreator(registry=registry, prompt=ScriptedPrompt(), plugins=["test.plugin"])

    config = creator.build(
        default_name="generated",
        selected_components=[("model", "test/model")],
        selected_stages=[("fit", "test/fit")],
    )
    plan = compile_plan(config, registry)

    assert config.experiment.name == "generated"
    assert config.plugins == ["test.plugin"]
    assert config.components["model"].params == {"width": 64}
    assert config.stages[0].params == {}
    assert config.resources.accelerator == "cpu"
    assert config.matrix == {"seed": [1, 2]}
    assert len(plan.runs) == 2


def test_parse_selection_preserves_order() -> None:
    assert parse_selection(
        ["model=project/mlp", "data=project/data"], option="--component"
    ) == [("model", "project/mlp"), ("data", "project/data")]


def test_cli_creator_writes_and_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "created.yaml"
    runner = CliRunner()
    answers = "\n\n\n\nn\n\n\nn\n2\n\n\n\n"

    result = runner.invoke(
        app,
        ["config", "create", str(output), "--stage", "fit=core/noop", "--name", "created"],
        input=answers,
    )

    assert result.exit_code == 0, result.output
    config = load_config(output)
    assert config.experiment.name == "created"
    assert config.stages[0].type == "core/noop"
    assert config.resources.accelerator == "cpu"
    generated = output.read_text(encoding="utf-8")
    assert generated.startswith("version: 1\n")
    assert "components: {}" not in generated
    assert "params: {}" not in generated

    repeated = runner.invoke(
        app,
        ["config", "create", str(output), "--stage", "fit=core/noop"],
    )
    assert repeated.exit_code == 2
    assert "refusing to overwrite" in repeated.output
