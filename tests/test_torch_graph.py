from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_assistant.errors import RegistryError
from research_assistant.plugins import load_registry


def _mlp_graph() -> dict[str, object]:
    return {
        "input_names": ["input"],
        "nodes": [
            {
                "id": "hidden",
                "type": "torch.nn/Linear",
                "inputs": ["input"],
                "params": {"in_features": 4, "out_features": 8},
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
                "params": {"in_features": 8, "out_features": 2},
                "position": {"x": 710, "y": 50},
            },
        ],
        "outputs": ["output"],
    }


def test_builtin_registry_exposes_torch_graph_and_standard_modules() -> None:
    registry = load_registry()

    graph = registry.get("model", "torch/graph")
    modules = registry.list("torch_module")

    assert graph.editor == "torch-graph"
    assert len(modules) >= 40
    assert all(spec.catalog == "graph-node" for spec in modules)
    assert {spec.name for spec in modules} >= {
        "torch.nn/Linear",
        "torch.nn/Conv2d",
        "torch.nn/LayerNorm",
        "torch.nn/GELU",
        "torch.graph/Add",
        "torch.graph/Concat",
    }
    registry.validate("model", {"type": "torch/graph", "params": _mlp_graph()})


def test_torch_graph_validation_rejects_nested_params_arity_and_cycles() -> None:
    registry = load_registry()
    graph = _mlp_graph()
    graph["nodes"][0]["params"]["in_features"] = 0
    with pytest.raises(RegistryError, match="in_features"):
        registry.validate("model", {"type": "torch/graph", "params": graph})

    graph = _mlp_graph()
    graph["nodes"][1]["inputs"] = ["input", "hidden"]
    with pytest.raises(RegistryError, match=r"requires 1 input"):
        registry.validate("model", {"type": "torch/graph", "params": graph})

    graph = _mlp_graph()
    graph["nodes"][0]["inputs"] = ["output"]
    with pytest.raises(RegistryError, match="cycle"):
        registry.validate("model", {"type": "torch/graph", "params": graph})


def test_torch_graph_builds_executable_module() -> None:
    torch = pytest.importorskip("torch")
    registry = load_registry()
    model = registry.invoke(
        "model",
        {"type": "torch/graph", "params": _mlp_graph()},
        SimpleNamespace(registry=registry),
    )

    output = model(torch.randn(3, 4))

    assert output.shape == (3, 2)
    assert set(model.state_dict()) == {
        "graph_modules.hidden.weight",
        "graph_modules.hidden.bias",
        "graph_modules.output.weight",
        "graph_modules.output.bias",
    }
