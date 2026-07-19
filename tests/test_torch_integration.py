import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from research_assistant.builtin import register as register_builtin
from research_assistant.config import parse_config
from research_assistant.execution import StageContext, execute_run
from research_assistant.integrations.torch import TorchDataLoaders, TorchRecipe, TorchStep
from research_assistant.planning import compile_plan
from research_assistant.registry import Registry

torch = pytest.importorskip("torch")


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def build_model(_params: EmptyParams, _context: Any) -> Any:
    return torch.nn.Linear(1, 1)


def build_data(_params: EmptyParams, _context: Any) -> TorchDataLoaders:
    x = torch.tensor([[-1.0], [0.0], [1.0], [2.0]])
    y = 2.0 * x + 1.0
    loader = torch.utils.data.DataLoader(torch.utils.data.TensorDataset(x, y), batch_size=4)
    return TorchDataLoaders(train=loader, evaluation={"val": loader, "test": loader})


def make_recipe(context: StageContext, *, interrupt_once: bool) -> TorchRecipe:
    def step(model: Any, batch: Any, device: Any, _split: str | None = None) -> TorchStep:
        x, y = (value.to(device) for value in batch)
        prediction = model(x)
        loss = torch.nn.functional.mse_loss(prediction, y)
        return TorchStep(loss=loss, metrics={"mae": (prediction - y).abs().mean()}, weight=len(x))

    def train_step(model: Any, batch: Any, device: Any) -> TorchStep:
        if interrupt_once:
            calls_path = context.run_dir / "train-calls.txt"
            calls = int(calls_path.read_text(encoding="utf-8")) if calls_path.exists() else 0
            calls_path.write_text(str(calls + 1), encoding="utf-8")
            if calls + 1 == 2:
                raise KeyboardInterrupt
        return step(model, batch, device)

    return TorchRecipe(
        optimizer=lambda model: torch.optim.SGD(model.parameters(), lr=0.1),
        train_step=train_step,
        eval_step=lambda model, batch, device, split: step(model, batch, device, split),
    )


def build_recipe(_params: EmptyParams, context: StageContext) -> TorchRecipe:
    return make_recipe(context, interrupt_once=False)


def build_interrupting_recipe(_params: EmptyParams, context: StageContext) -> TorchRecipe:
    return make_recipe(context, interrupt_once=True)


def torch_registry() -> Registry:
    registry = Registry()
    register_builtin(registry)
    registry.add("model", "test/linear", factory=build_model, schema=EmptyParams)
    registry.add("data", "test/regression", factory=build_data, schema=EmptyParams)
    registry.add("recipe", "test/mse", factory=build_recipe, schema=EmptyParams)
    registry.add(
        "recipe", "test/interrupting-mse", factory=build_interrupting_recipe, schema=EmptyParams
    )
    return registry


def experiment(recipe: str, *, epochs: int = 4) -> Any:
    return parse_config(
        {
            "version": 1,
            "experiment": {"name": "torch-test"},
            "seed": 7,
            "components": {
                "model": {"type": "test/linear"},
                "data": {"type": "test/regression"},
                "recipe": {"type": recipe},
            },
            "stages": [
                {
                    "name": "fit",
                    "type": "torch/fit",
                    "params": {"epochs": epochs, "monitor": "val/loss"},
                },
                {
                    "name": "test",
                    "type": "torch/evaluate",
                    "needs": ["fit"],
                    "params": {"splits": ["test"]},
                },
            ],
            "resources": {"accelerator": "cpu"},
        }
    )


def test_fit_and_evaluate_publish_checkpoint(tmp_path: Path) -> None:
    registry = torch_registry()
    manifest = compile_plan(experiment("test/mse"), registry).runs[0]

    status = execute_run(manifest, registry, artifact_root=tmp_path)

    assert status["state"] == "completed"
    assert set(status["stages"]["fit"]["artifacts"]) == {"best", "last"}
    assert status["stages"]["test"]["metrics"]["test/loss"] >= 0.0
    run_dir = tmp_path / "torch-test" / manifest.run_id
    assert (run_dir / status["stages"]["fit"]["artifacts"]["best"]).exists()
    events = [
        json.loads(line)
        for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["kind"] for event in events].count("progress") == 4


def test_fit_resumes_from_last_completed_epoch(tmp_path: Path) -> None:
    registry = torch_registry()
    manifest = compile_plan(experiment("test/interrupting-mse", epochs=2), registry).runs[0]

    with pytest.raises(KeyboardInterrupt):
        execute_run(manifest, registry, artifact_root=tmp_path)

    status = execute_run(manifest, registry, artifact_root=tmp_path)

    run_dir = tmp_path / "torch-test" / manifest.run_id
    assert status["state"] == "completed"
    assert (run_dir / "train-calls.txt").read_text(encoding="utf-8") == "3"
