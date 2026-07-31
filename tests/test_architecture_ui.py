from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.explorer_ui import _PATCH_VERSION  # noqa: E402
from research_assistant.ui.server import create_app  # noqa: E402


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


def test_architecture_extension_and_advanced_validation_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert "/api/extensions/architectures.js" in index.text
    assert index.headers["x-researchassistant-ui-build"] == str(_PATCH_VERSION)

    extension = client.get("/api/extensions/architectures.js")
    assert extension.status_code == 200
    assert extension.headers["cache-control"] == "no-store"
    assert "researchAssistantArchitectureWorkbenchV2Loader" in extension.text
    assert "architecture-v2/part-" in extension.text
    assert "blob:" in index.headers["content-security-policy"]
    source = "".join(
        client.get(f"/api/extensions/architecture-v2/part-{index:02d}.txt").text
        for index in range(7)
    )
    assert "researchAssistantArchitectureWorkbenchV2" in source
    assert "architectures-button" in source
    assert "typed pytorch architecture language" in source.lower()
    assert "Architecture controls" in source
    assert "Python module" in source
    assert "Repeat" in source
    assert "Switch" in source
    assert "Composite" in source
    assert "variable_specs" in source
    assert "$expr" in source
    assert "components.model.params.variables" in source

    catalog = client.get("/api/architectures")
    assert catalog.status_code == 200
    assert catalog.json() == {"architectures": [], "truncated": False}

    bootstrap = client.get("/api/bootstrap").json()
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

    build = client.get("/api/ui-build")
    assert build.status_code == 200
    assert build.json()["architecture_language_version"] == 2
