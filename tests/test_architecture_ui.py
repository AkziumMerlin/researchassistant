from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.explorer_ui import _PATCH_VERSION  # noqa: E402
from research_assistant.ui.server import create_app  # noqa: E402


def _graph() -> dict[str, object]:
    return {
        "variables": {"in_features": 4, "out_features": 2},
        "input_names": ["input"],
        "nodes": [
            {
                "id": "output",
                "type": "torch.nn/Linear",
                "inputs": ["input"],
                "params": {
                    "in_features": {"$var": "in_features"},
                    "out_features": {"$var": "out_features"},
                },
                "position": {"x": 280, "y": 70},
            }
        ],
        "outputs": ["output"],
    }


def test_architecture_extension_and_validation_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert "/api/extensions/architectures.js" in index.text
    assert index.headers["x-researchassistant-ui-build"] == str(_PATCH_VERSION)

    extension = client.get("/api/extensions/architectures.js")
    assert extension.status_code == 200
    assert extension.headers["cache-control"] == "no-store"
    assert "researchAssistantArchitectureWorkbenchV1" in extension.text
    assert "architectures-button" in extension.text
    assert "torch/parameterized-graph" in extension.text
    assert "components.model.params.variables" in extension.text

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
    assert parameterized[0]["metadata"] == {"architecture_variables": True}

    validation = client.post(
        "/api/torch/parameterized-graph/validate",
        json={"params": _graph()},
    )
    assert validation.status_code == 200
    assert validation.json() == {
        "valid": True,
        "nodes": 1,
        "inputs": ["input"],
        "outputs": ["output"],
        "variables": 2,
    }
