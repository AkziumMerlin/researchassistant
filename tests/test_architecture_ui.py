from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.desktop_server import create_desktop_app  # noqa: E402


def _advanced_graph() -> dict[str, object]:
    return {
        "variables": {
            "backend": "kuramoto",
            "use_omega": True,
            "depth": 2,
        },
        "variable_specs": {
            "backend": {
                "type": "enum",
                "choices": ["kuramoto", "cnn"],
            },
            "use_omega": {
                "type": "bool",
                "enabled_if": "backend == 'kuramoto'",
            },
            "depth": {"type": "int", "min": 1},
        },
        "input_names": ["input"],
        "subgraphs": {
            "identity": {
                "input_names": ["state"],
                "nodes": [
                    {
                        "id": "identity",
                        "kind": "python",
                        "target": "torch.nn:Identity",
                        "inputs": {"input": "state"},
                        "call_style": "positional",
                        "output_ports": ["state"],
                    }
                ],
                "outputs": {"state": "identity.state"},
            }
        },
        "nodes": [
            {
                "id": "layers",
                "kind": "repeat",
                "template": "identity",
                "inputs": {"state": "input"},
                "output_ports": ["state"],
                "count": {"$var": "depth"},
                "weights": "shared",
                "carry": {"state": "state"},
            }
        ],
        "outputs": {"output": "layers.state"},
    }


def test_native_models_editor_and_advanced_validation_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_desktop_app(tmp_path, token="secret"))
    headers = {"Authorization": "Bearer secret"}

    source = (
        Path(__file__).parents[1]
        / "desktop/research-assistant-extension/src/browser/models-editor.ts"
    ).read_text(encoding="utf-8")
    assert "class ModelsEditor" in source
    assert "Architecture files" in source
    assert "Components" in source
    assert "Python" in source
    assert "Repeat" in source
    assert "Switch" in source
    assert "Composite" in source
    assert "variable_specs" in source
    assert "subgraphs" in source
    assert "/api/torch/parameterized-graph/validate" in source

    catalog = client.get("/api/architectures", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json() == {"architectures": [], "truncated": False}

    bootstrap = client.get("/api/bootstrap", headers=headers).json()
    parameterized = [
        spec
        for spec in bootstrap["components"]
        if spec["kind"] == "model" and spec["name"] == "torch/parameterized-graph"
    ]
    assert len(parameterized) == 1
    metadata = parameterized[0]["metadata"]
    assert metadata["typed_variables"] is True
    assert metadata["expressions"] is True
    assert metadata["named_ports"] is True
    assert metadata["subgraphs"] is True

    validation = client.post(
        "/api/torch/parameterized-graph/validate",
        headers=headers,
        json={"params": _advanced_graph()},
    )
    assert validation.status_code == 200
    assert validation.json() == {
        "valid": True,
        "nodes": 2,
        "root_nodes": 1,
        "subgraph_nodes": 1,
        "subgraphs": 1,
        "inputs": ["input"],
        "outputs": {"output": "layers.state"},
        "variables": 3,
        "typed_variables": 3,
        "language_version": 2,
    }
