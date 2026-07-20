import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from research_assistant.cli import app as cli_app
from research_assistant.config import parse_config
from research_assistant.execution import execute_run
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry
from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.ui.server import create_app  # noqa: E402


def test_workspace_bounds_atomic_writes_and_conflicts(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    path = tmp_path / "configs" / "experiment.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "outside-link").symlink_to(outside)
    workspace = Workspace(tmp_path)

    entries = workspace.entries()["entries"]
    paths = {entry["path"] for entry in entries}
    assert "configs/experiment.yaml" in paths
    assert "node_modules/ignored.js" not in paths
    assert "outside-link" not in paths

    opened = workspace.read("configs/experiment.yaml")
    path.write_text("changed outside\n", encoding="utf-8")
    with pytest.raises(WorkspaceConflict, match="changed outside"):
        workspace.write("configs/experiment.yaml", "from editor\n", opened.revision)

    current = workspace.read("configs/experiment.yaml")
    saved = workspace.write("configs/experiment.yaml", "from editor\n", current.revision)
    assert path.read_text(encoding="utf-8") == "from editor\n"
    assert saved.revision != current.revision

    created = workspace.write("configs/new.yaml", "new\n", None)
    assert created.content == "new\n"
    with pytest.raises(WorkspaceConflict, match="already exists"):
        workspace.write("configs/new.yaml", "overwrite\n", None)
    with pytest.raises(WorkspaceError, match="escapes workspace"):
        workspace.read("../outside.txt")


def test_ui_api_edits_validates_and_creates_configs(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    config_path = tmp_path / "configs" / "smoke.yaml"
    config_content = """version: 1
experiment:
  name: smoke
stages:
  - name: fit
    type: core/noop
"""
    config_path.write_text(config_content, encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert "ResearchAssistant" in index.text
    assert "frame-ancestors 'none'" in index.headers["content-security-policy"]
    asset_path = re.search(r'src="(/assets/[^"]+\.js)"', index.text).group(1)
    assert client.get(asset_path).status_code == 200

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert payload["workspace"]["path"] == str(tmp_path)
    assert any(spec["name"] == "core/noop" for spec in payload["components"])

    opened = client.get("/api/files", params={"path": "configs/smoke.yaml"}).json()
    saved = client.put(
        "/api/files",
        params={"path": "configs/smoke.yaml"},
        json={"content": config_content + "# edited\n", "revision": opened["revision"]},
    )
    assert saved.status_code == 200
    conflict = client.put(
        "/api/files",
        params={"path": "configs/smoke.yaml"},
        json={"content": "stale", "revision": opened["revision"]},
    )
    assert conflict.status_code == 409

    validated = client.post(
        "/api/config/validate",
        json={"path": "configs/smoke.yaml", "content": config_content},
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["plan"]["runs"] == 1

    generated = client.post(
        "/api/config/create",
        json={
            "path": "configs/generated.yaml",
            "experiment_name": "generated",
            "seeds": [1, 2],
            "components": [],
            "stages": [{"name": "fit", "type": "core/noop", "params": {}}],
            "accelerator": "cpu",
        },
    )
    assert generated.status_code == 200, generated.text
    generated_payload = generated.json()
    assert generated_payload["plan"]["runs"] == 2
    assert "seed:" in generated_payload["content"]
    assert "components: {}" not in generated_payload["content"]


def test_ui_validation_cannot_follow_extends_outside_workspace(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/config/validate",
        json={"path": "configs/escape.yaml", "content": "extends: ../../outside.yaml\n"},
    )

    assert response.status_code == 400
    assert "escapes allowed root" in response.json()["detail"]


def test_ui_catalog_and_creator_use_project_plugin() -> None:
    project = Path(__file__).parents[1] / "examples" / "minimal"
    client = TestClient(create_app(project, plugins=["ra_example.plugin"]))

    catalog = client.get("/api/bootstrap").json()["components"]
    assert any(spec["name"] == "example/constant" for spec in catalog)
    generated = client.post(
        "/api/config/create",
        json={
            "path": "configs/from-ui.yaml",
            "experiment_name": "from-ui",
            "components": [
                {"kind": "value", "type": "example/constant", "params": {"value": 3.5}}
            ],
            "stages": [{"name": "fit", "type": "example/measure", "params": {}}],
        },
    )

    assert generated.status_code == 200, generated.text
    assert "example/constant" in generated.json()["content"]


def test_ui_cli_refuses_remote_binding(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_app,
        ["ui", str(tmp_path), "--host", "0.0.0.0", "--no-open"],
    )

    assert result.exit_code == 2
    assert "only binds to localhost" in result.output


def test_ui_analytics_catalog_chart_table_and_export(tmp_path: Path) -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "ui-report"},
            "seed": 0,
            "matrix": {"seed": [0, 1]},
            "stages": [
                {
                    "name": "test",
                    "type": "core/noop",
                    "params": {"metrics": {"test/error": 0.1}},
                }
            ],
        }
    )
    registry = load_registry()
    for manifest in compile_plan(config, registry).runs:
        execute_run(manifest, registry, artifact_root=tmp_path / "runs")
    client = TestClient(create_app(tmp_path))

    catalog = client.post("/api/analytics/catalog", json={"artifact_root": "runs"})
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["catalog"]["event_count"] == 2

    chart_spec = {
        "name": "curves",
        "artifact_root": "runs",
        "filters": {"metrics": ["test/error"], "kinds": ["final"]},
        "group_by": "trial_id",
    }
    chart = client.post("/api/analytics/chart", json=chart_spec)
    assert chart.status_code == 200, chart.text
    assert chart.json()["chart"]["series"][0]["points"][0]["n"] == 2

    table_spec = {
        "name": "benchmark",
        "artifact_root": "runs",
        "filters": {"metrics": ["test/error"], "kinds": ["final"]},
        "row": "study_id",
        "column": "trial_id",
    }
    table = client.post("/api/analytics/table", json=table_spec)
    assert table.status_code == 200, table.text
    assert "\\begin{tabular}" in table.json()["latex"]
    exported = client.post("/api/analytics/table/export", json={"spec": table_spec})
    assert exported.status_code == 200, exported.text
    assert (tmp_path / exported.json()["path"] / "table.tex").is_file()
