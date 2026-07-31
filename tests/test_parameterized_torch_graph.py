from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_assistant.errors import RegistryError
from research_assistant.models import ExperimentConfig
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry


def _legacy_mlp() -> dict[str, object]:
    return {
        "variables": {"in_features": 4, "width": 8, "out_features": 2},
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


def _advanced_switch() -> dict[str, object]:
    return {
        "variables": {
            "variant": "small",
            "in_features": 4,
            "width": 3,
            "use_bias": False,
        },
        "variable_specs": {
            "variant": {
                "type": "enum",
                "choices": ["small", "large"],
                "description": "Architecture branch.",
            },
            "in_features": {"type": "int", "min": 1},
            "width": {"type": "int", "min": 1},
            "use_bias": {
                "type": "bool",
                "enabled_if": "variant == 'small'",
            },
        },
        "input_names": ["input"],
        "subgraphs": {
            "small": {
                "input_names": ["input"],
                "nodes": [
                    {
                        "id": "linear",
                        "kind": "module",
                        "type": "torch.nn/Linear",
                        "inputs": {"input": "input"},
                        "call_style": "positional",
                        "params": {
                            "in_features": {"$var": "in_features"},
                            "out_features": {"$expr": "width * 2"},
                            "bias": {"$var": "use_bias"},
                        },
                        "output_ports": ["output"],
                    }
                ],
                "outputs": {"output": "linear"},
            },
            "large": {
                "input_names": ["input"],
                "nodes": [
                    {
                        "id": "linear",
                        "kind": "module",
                        "type": "torch.nn/Linear",
                        "inputs": ["input"],
                        "params": {
                            "in_features": {"$var": "in_features"},
                            "out_features": {"$expr": "width * 4"},
                            "bias": True,
                        },
                        "output_ports": ["output"],
                    }
                ],
                "outputs": {"output": "linear"},
            },
        },
        "nodes": [
            {
                "id": "choice",
                "kind": "switch",
                "inputs": {"input": "input"},
                "selector": {"$var": "variant"},
                "branches": {"small": "small", "large": "large"},
                "output_ports": ["output"],
            }
        ],
        "outputs": {"output": "choice"},
    }


def _repeated_block(weights: str = "independent") -> dict[str, object]:
    return {
        "variables": {"depth": 3, "width": 4},
        "variable_specs": {
            "depth": {"type": "int", "min": 1},
            "width": {"type": "int", "min": 1},
        },
        "input_names": ["input"],
        "subgraphs": {
            "block": {
                "input_names": ["state"],
                "nodes": [
                    {
                        "id": "linear",
                        "kind": "module",
                        "type": "torch.nn/Linear",
                        "inputs": {"input": "state"},
                        "call_style": "positional",
                        "params": {
                            "in_features": {"$var": "width"},
                            "out_features": {"$var": "width"},
                        },
                        "output_ports": ["state"],
                    }
                ],
                "outputs": {"state": "linear.state"},
            }
        },
        "nodes": [
            {
                "id": "layers",
                "kind": "repeat",
                "template": "block",
                "inputs": {"state": "input"},
                "output_ports": ["state"],
                "count": {"$var": "depth"},
                "weights": weights,
                "index_name": "layer_index",
                "carry": {"state": "state"},
            }
        ],
        "outputs": {"output": "layers.state"},
    }


def test_registry_exposes_advanced_parameterized_graph() -> None:
    registry = load_registry()
    spec = registry.get("model", "torch/parameterized-graph")

    assert spec.editor == "torch-graph"
    assert spec.metadata["typed_variables"] is True
    assert spec.metadata["expressions"] is True
    assert spec.metadata["named_ports"] is True
    assert spec.metadata["control_flow"] == ["repeat", "switch", "composite", "python"]
    registry.validate(
        "model",
        {"type": "torch/parameterized-graph", "params": _advanced_switch()},
    )


def test_parameterized_graph_rejects_bad_types_and_unsafe_expressions() -> None:
    registry = load_registry()
    graph = _advanced_switch()
    graph["variables"]["variant"] = "missing"
    with pytest.raises(RegistryError, match="declared type"):
        registry.validate(
            "model",
            {"type": "torch/parameterized-graph", "params": graph},
        )

    graph = _advanced_switch()
    graph["subgraphs"]["small"]["nodes"][0]["params"]["out_features"] = {
        "$expr": "__import__('os').system('true')"
    }
    with pytest.raises(RegistryError, match="unsupported"):
        registry.validate(
            "model",
            {"type": "torch/parameterized-graph", "params": graph},
        )


def test_parameterized_graph_rejects_unknown_variables_and_bad_interfaces() -> None:
    registry = load_registry()
    graph = _advanced_switch()
    graph["subgraphs"]["small"]["nodes"][0]["params"]["out_features"] = {
        "$var": "missing"
    }
    with pytest.raises(RegistryError, match="unknown architecture variables"):
        registry.validate(
            "model",
            {"type": "torch/parameterized-graph", "params": graph},
        )

    graph = _advanced_switch()
    graph["nodes"][0]["output_ports"] = ["wrong"]
    with pytest.raises(RegistryError, match="output ports must match"):
        registry.validate(
            "model",
            {"type": "torch/parameterized-graph", "params": graph},
        )


def test_matrix_can_override_typed_architecture_variables() -> None:
    registry = load_registry()
    config = ExperimentConfig.model_validate(
        {
            "version": 1,
            "experiment": {"name": "architecture_matrix"},
            "components": {
                "model": {
                    "type": "torch/parameterized-graph",
                    "params": _advanced_switch(),
                }
            },
            "matrix": {
                "components.model.params.variables.variant": ["small", "large"],
                "components.model.params.variables.width": [2, 3],
            },
            "stages": [{"name": "noop", "type": "core/noop"}],
        }
    )

    plan = compile_plan(config, registry)

    assert len(plan.runs) == 4
    assert {run.config.components["model"].params["variables"]["variant"] for run in plan.runs} == {
        "small",
        "large",
    }
    assert {run.config.components["model"].params["variables"]["width"] for run in plan.runs} == {
        2,
        3,
    }


def test_legacy_parameterized_graph_remains_executable() -> None:
    torch = pytest.importorskip("torch")
    registry = load_registry()
    model = registry.invoke(
        "model",
        {"type": "torch/parameterized-graph", "params": _legacy_mlp()},
        SimpleNamespace(registry=registry),
    )

    output = model(torch.randn(3, 4))

    assert output.shape == (3, 2)
    assert model.graph_modules.hidden.out_features == 8


def test_switch_selects_enum_branch_and_resolves_expression() -> None:
    torch = pytest.importorskip("torch")
    registry = load_registry()
    model = registry.invoke(
        "model",
        {"type": "torch/parameterized-graph", "params": _advanced_switch()},
        SimpleNamespace(registry=registry),
    )

    output = model(torch.randn(5, 4))

    assert output.shape == (5, 6)
    choice = model.graph_modules["choice"]
    assert choice.graph_modules["linear"].bias is None


def test_repeat_supports_independent_and_shared_weights() -> None:
    torch = pytest.importorskip("torch")
    registry = load_registry()

    independent = registry.invoke(
        "model",
        {"type": "torch/parameterized-graph", "params": _repeated_block("independent")},
        SimpleNamespace(registry=registry),
    )
    shared = registry.invoke(
        "model",
        {"type": "torch/parameterized-graph", "params": _repeated_block("shared")},
        SimpleNamespace(registry=registry),
    )

    value = torch.randn(2, 4)
    assert independent(value).shape == (2, 4)
    assert shared(value).shape == (2, 4)
    assert len(independent.graph_modules["layers"]) == 3
    assert hasattr(shared.graph_modules["layers"], "run_mapping")


def test_python_module_nodes_support_workspace_import_targets() -> None:
    torch = pytest.importorskip("torch")
    registry = load_registry()
    graph = {
        "variables": {},
        "input_names": ["input"],
        "nodes": [
            {
                "id": "identity",
                "kind": "python",
                "target": "torch.nn:Identity",
                "inputs": {"input": "input"},
                "call_style": "positional",
                "params": {},
                "output_ports": ["output"],
            }
        ],
        "outputs": {"output": "identity"},
    }
    model = registry.invoke(
        "model",
        {"type": "torch/parameterized-graph", "params": graph},
        SimpleNamespace(registry=registry),
    )
    value = torch.randn(2, 3)

    assert model(value) is value
