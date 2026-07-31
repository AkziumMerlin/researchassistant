from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_assistant.errors import RegistryError
from research_assistant.models import ExperimentConfig
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry


def _parameterized_mlp() -> dict[str, object]:
    return {
        "variables": {
            "in_features": 4,
            "width": 8,
            "out_features": 2,
        },
        "input_names": ["input"],
        "nodes": [
            {
                "id": "hidden",
                "type": "torch.nn/Linear",
                "inputs": ["input"],
                "params": {
                    "in_features": {"$var": "in_features"},
                    "out_features": {"$var": "width"},
                },
                "position": {"x": 250, "y": 50},
            },
            {
                "id": "activation",
                "type": "torch.nn/ReLU",
                "inputs": ["hidden"],
                "params": {},
                "position": {"x": 480, "y": 50},
            },
            {
                "id": "output",
                "type": "torch.nn/Linear",
                "inputs": ["activation"],
                "params": {
                    "in_features": {"$var": "width"},
                    "out_features": {"$var": "out_features"},
                },
                "position": {"x": 710, "y": 50},
            },
        ],
        "outputs": ["output"],
    }


def test_registry_exposes_parameterized_torch_graph() -> None:
    registry = load_registry()
    spec = registry.get("model", "torch/parameterized-graph")

    assert spec.editor == "torch-graph"
    assert spec.metadata == {"architecture_variables": True}
    registry.validate(
        "model",
        {"type": "torch/parameterized-graph", "params": _parameterized_mlp()},
    )


def test_parameterized_graph_rejects_unknown_or_invalid_variables() -> None:
    registry = load_registry()
    graph = _parameterized_mlp()
    graph["nodes"][0]["params"]["out_features"] = {"$var": "missing"}
    with pytest.raises(RegistryError, match="unknown architecture variables"):
        registry.validate(
            "model",
            {"type": "torch/parameterized-graph", "params": graph},
        )

    graph = _parameterized_mlp()
    graph["variables"]["bad-name"] = 16
    with pytest.raises(RegistryError, match="invalid architecture variable names"):
        registry.validate(
            "model",
            {"type": "torch/parameterized-graph", "params": graph},
        )


def test_matrix_can_override_architecture_variable() -> None:
    registry = load_registry()
    config = ExperimentConfig.model_validate(
        {
            "version": 1,
            "experiment": {"name": "architecture_matrix"},
            "components": {
                "model": {
                    "type": "torch/parameterized-graph",
                    "params": _parameterized_mlp(),
                }
            },
            "matrix": {
                "components.model.params.variables.width": [8, 16],
            },
            "stages": [{"name": "noop", "type": "core/noop"}],
        }
    )

    plan = compile_plan(config, registry)

    assert len(plan.runs) == 2
    assert [run.assignments["components.model.params.variables.width"] for run in plan.runs] == [
        8,
        16,
    ]
    assert [run.config.components["model"].params["variables"]["width"] for run in plan.runs] == [
        8,
        16,
    ]


def test_parameterized_graph_builds_executable_module() -> None:
    torch = pytest.importorskip("torch")
    registry = load_registry()
    model = registry.invoke(
        "model",
        {"type": "torch/parameterized-graph", "params": _parameterized_mlp()},
        SimpleNamespace(registry=registry),
    )

    output = model(torch.randn(3, 4))

    assert output.shape == (3, 2)
    assert model.graph_modules.hidden.out_features == 8
