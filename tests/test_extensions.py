from pathlib import Path

import pytest
from typer.testing import CliRunner

from research_assistant.cli_ext import app

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.ui.server import create_app  # noqa: E402


def test_extended_cli_registers_job_commands(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["job", "list", "--workspace", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "no jobs found" in result.output


def test_extended_ui_matrix_stage_overrides_and_job_routes(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert "/api/extensions/" not in index.text
    assert client.get("/api/jobs").json() == {"jobs": []}

    generated = client.post(
        "/api/config/create",
        json={
            "path": "configs/generated.yaml",
            "experiment_name": "generated",
            "seeds": [0, 1],
            "components": [
                {"kind": "value", "type": "core/value", "params": {"value": "global"}}
            ],
            "matrix": {"components.value.params.value": ["small", "large"]},
            "stages": [
                {
                    "name": "test",
                    "type": "core/noop",
                    "params": {},
                    "components": {
                        "value": {"type": "core/value", "params": {"value": "stage"}}
                    },
                }
            ],
            "accelerator": "cpu",
        },
    )

    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["plan"]["runs"] == 4
    assert "components.value.params.value" in payload["content"]
    assert "value: stage" in payload["content"]
