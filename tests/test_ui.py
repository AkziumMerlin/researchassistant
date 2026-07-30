import json
import re
import shutil
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from research_assistant.cli import app as cli_app
from research_assistant.config import dump_config, parse_config
from research_assistant.execution import execute_run
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry
from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.ui.server import create_app, run_ui  # noqa: E402


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
    assert "Launch and monitor experiments" in index.text
    assert "Inspect experiment" in index.text
    assert "Evaluate, compare and publish" in index.text
    assert "Selection protocol" in index.text
    assert "Design model architecture" in index.text
    assert "frame-ancestors 'none'" in index.headers["content-security-policy"]
    asset_path = re.search(r'src="(/assets/[^"]+\.js)"', index.text).group(1)
    frontend = client.get(asset_path)
    assert frontend.status_code == 200
    assert "/api/bootstrap" in frontend.text
    assert "/api/torch/graph/validate" in frontend.text
    assert "monaco-base-common-" not in frontend.text

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert payload["workspace"]["path"] == str(tmp_path)
    assert payload["diagnostics"]["research_assistant"]
    assert payload["diagnostics"]["python"]
    assert any(spec["name"] == "core/noop" for spec in payload["components"])
    assert any(
        spec["name"] == "torch/graph" and spec["editor"] == "torch-graph"
        for spec in payload["components"]
    )
    assert any(
        spec["name"] == "torch.nn/Conv2d" and spec["catalog"] == "graph-node"
        for spec in payload["components"]
    )

    graph = {
        "input_names": ["input"],
        "nodes": [
            {
                "id": "output",
                "type": "torch.nn/Linear",
                "inputs": ["input"],
                "params": {"in_features": 4, "out_features": 2},
                "position": {"x": 200, "y": 40},
            }
        ],
        "outputs": ["output"],
    }
    graph_validation = client.post("/api/torch/graph/validate", json={"params": graph})
    assert graph_validation.status_code == 200, graph_validation.text
    assert graph_validation.json()["nodes"] == 1

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
    inspected = client.post(
        "/api/config/inspect",
        json={
            "path": "configs/smoke.yaml",
            "content": config_content,
            "overrides": ["experiment.name=inspected", "matrix.seed=[0, 1]"],
            "include_manifests": True,
        },
    )
    assert inspected.status_code == 200, inspected.text
    inspected_payload = inspected.json()
    assert inspected_payload["experiment"] == "inspected"
    assert inspected_payload["plan"]["runs"] == 2
    assert len(inspected_payload["plan"]["run_details"]) == 2
    assert len(inspected_payload["manifests"]) == 2
    assert "name: inspected" in inspected_payload["rendered"]

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

    graph_generated = client.post(
        "/api/config/create",
        json={
            "path": "configs/graph.yaml",
            "experiment_name": "graph",
            "components": [{"kind": "model", "type": "torch/graph", "params": graph}],
            "stages": [{"name": "fit", "type": "core/noop", "params": {}}],
        },
    )
    assert graph_generated.status_code == 200, graph_generated.text
    assert "torch/graph" in graph_generated.json()["content"]


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


def test_ui_project_init_is_safe_and_reports_scaffold(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    initialized = client.post("/api/project/init", json={})

    assert initialized.status_code == 201, initialized.text
    assert initialized.json()["restart_required"] is True
    assert initialized.json()["plugin"] == "ra_project.plugin"
    assert (tmp_path / "configs" / "smoke.yaml").is_file()
    assert (tmp_path / "ra_project" / "plugin.py").is_file()
    repeated = client.post("/api/project/init", json={})
    assert repeated.status_code == 400
    assert "refusing to overwrite" in repeated.json()["detail"]


def test_ui_project_init_rejects_symlinked_scaffold_directory(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "configs").symlink_to(outside, target_is_directory=True)
    client = TestClient(create_app(tmp_path))

    response = client.post("/api/project/init", json={})

    assert response.status_code == 400
    assert "unsafe directory" in response.json()["detail"]
    assert not (outside / "smoke.yaml").exists()


def test_ui_ssh_mode_prints_tunnel_and_does_not_open_browser(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import uvicorn

    captured: dict[str, object] = {}

    def fake_run(app, **kwargs) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr("webbrowser.open", lambda _url: pytest.fail("browser should not open"))

    run_ui(tmp_path, port=9123, ssh_mode=True, ssh_target="user@gpu-server")

    output = capsys.readouterr().out
    assert "ssh -N -L 9123:127.0.0.1:9123 user@gpu-server" in output
    assert "http://127.0.0.1:9123" in output
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9123
    bootstrap = TestClient(captured["app"]).get("/api/bootstrap")
    assert bootstrap.json()["connection"]["mode"] == "ssh"


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
        resources_path = tmp_path / "runs" / manifest.study_id / manifest.run_id / "resources.json"
        resources_path.write_text(
            json.dumps(
                {
                    "total": {
                        "wall_seconds": 3.5,
                        "gpu_wall_seconds": 1.0,
                        "process_memory_peak_mb": 128.0,
                        "attempts": 1,
                    }
                }
            ),
            encoding="utf-8",
        )
    client = TestClient(create_app(tmp_path))

    catalog = client.post("/api/analytics/catalog", json={"artifact_root": "runs"})
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["catalog"]["event_count"] == 2
    run_catalog = client.post(
        "/api/runs/catalog",
        json={"artifact_root": "runs", "metric": "test/error", "limit": 1},
    )
    assert run_catalog.status_code == 200, run_catalog.text
    run_payload = run_catalog.json()
    assert run_payload["catalog"]["total"] == 2
    assert run_payload["catalog"]["truncated"] is True
    assert run_payload["catalog"]["counts"] == {"completed": 2}
    assert run_payload["summary"][0]["mean"] == pytest.approx(0.1)
    assert run_payload["resources"][0]["n"] == 2

    chart_spec = {
        "name": "curves",
        "artifact_root": "runs",
        "filters": {"metrics": ["test/error"], "kinds": ["final"]},
        "group_by": "trial_id",
    }
    chart = client.post("/api/analytics/chart", json=chart_spec)
    assert chart.status_code == 200, chart.text
    assert chart.json()["chart"]["series"][0]["points"][0]["n"] == 2
    evaluation = client.post(
        "/api/analytics/evaluate",
        json={
            "artifact_root": "runs",
            "selection_metric": "test/error",
            "target_metric": "test/error",
            "selection_kind": "final",
            "target_kind": "final",
            "group_by": ["trial_id"],
        },
    )
    assert evaluation.status_code == 200, evaluation.text
    assert evaluation.json()["evaluation"]["eligible_runs"] == 2
    assert evaluation.json()["evaluation"]["groups"][0]["mean"] == pytest.approx(0.1)
    assert "\\begin{tabular}" in evaluation.json()["latex"]
    evaluation_export = client.post(
        "/api/analytics/evaluation/export",
        json={
            "spec": {
                "name": "selected",
                "artifact_root": "runs",
                "selection_metric": "test/error",
                "target_metric": "test/error",
                "selection_kind": "final",
                "target_kind": "final",
                "group_by": ["trial_id"],
            },
            "output_path": "custom/selected",
        },
    )
    assert evaluation_export.status_code == 200, evaluation_export.text
    assert (tmp_path / "custom" / "selected" / "table.tex").is_file()
    assert (tmp_path / "custom" / "selected" / "provenance.json").is_file()

    table_spec = {
        "name": "benchmark",
        "artifact_root": "runs",
        "filters": {"metrics": ["test/error"], "kinds": ["final"]},
        "row": "study_id",
        "column": "trial_id",
    }
    spec_path = tmp_path / "table-spec.yaml"
    spec_path.write_text(
        """name: from-spec
artifact_root: runs
filters:
  metrics: [test/error]
  kinds: [final]
row: study_id
column: trial_id
""",
        encoding="utf-8",
    )
    loaded_spec = client.post(
        "/api/analytics/spec/load",
        json={"path": "table-spec.yaml", "kind": "table"},
    )
    assert loaded_spec.status_code == 200, loaded_spec.text
    assert loaded_spec.json()["spec"]["name"] == "from-spec"
    table = client.post("/api/analytics/table", json=table_spec)
    assert table.status_code == 200, table.text
    assert "\\begin{tabular}" in table.json()["latex"]
    exported = client.post(
        "/api/analytics/table/export",
        json={"spec": table_spec, "output_path": "custom/report"},
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["path"] == "custom/report"
    assert (tmp_path / "custom" / "report" / "table.tex").is_file()


def test_ui_launches_saved_config_in_detached_scheduler(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "smoke.yaml").write_text(
        """version: 1
experiment:
  name: ui-launch
matrix:
  seed: [0, 1]
stages:
  - name: fit
    type: core/noop
resources:
  accelerator: cpu
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    preview = client.post(
        "/api/launches/preview",
        json={
            "config_path": "configs/smoke.yaml",
            "artifact_root": "runs",
            "overrides": ["matrix.seed=[3, 4, 5]"],
            "launcher_overrides": ["params.max_parallel=2"],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["plan"]["runs"] == 3
    assert preview.json()["launcher"]["params"]["max_parallel"] == 2

    launched = client.post(
        "/api/launches",
        json={
            "config_path": "configs/smoke.yaml",
            "artifact_root": "runs",
            "resume": True,
            "overrides": ["matrix.seed=[3, 4, 5]"],
            "launcher_overrides": ["params.max_parallel=2"],
        },
    )

    assert launched.status_code == 202, launched.text
    launch_id = launched.json()["launch_id"]
    deadline = time.monotonic() + 15
    detail = launched.json()
    while detail["state"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        response = client.get(f"/api/launches/{launch_id}")
        assert response.status_code == 200, response.text
        detail = response.json()

    assert detail["state"] == "completed", detail
    assert detail["scheduler_alive"] is False
    assert detail["plan"]["runs"] == 3
    assert detail["run_counts"] == {"completed": 3}
    assert detail["overrides"] == ["matrix.seed=[3, 4, 5]"]
    assert detail["launcher_overrides"] == ["params.max_parallel=2"]
    assert all(run["state"] == "completed" for run in detail["runs"])
    assert f"launch {launch_id}: completed" in detail["scheduler_log"]
    assert (tmp_path / ".ra" / "ui-launches" / launch_id / "request.json").is_file()
    selected_run = detail["runs"][0]["run_id"]
    selected = client.get(f"/api/launches/{launch_id}", params={"run_id": selected_run})
    assert selected.status_code == 200
    assert selected.json()["selected_run_id"] == selected_run
    assert "worker_log" in selected.json()
    foreign_run = client.get(f"/api/launches/{launch_id}", params={"run_id": "../foreign"})
    assert foreign_run.status_code == 400

    reconnected = TestClient(create_app(tmp_path))
    history = reconnected.get("/api/launches")
    assert history.status_code == 200
    assert history.json()["launches"][0]["launch_id"] == launch_id
    assert history.json()["launches"][0]["state"] == "completed"


def test_ui_launch_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "smoke.yaml").write_text(
        """version: 1
experiment:
  name: ui-launch-bounds
stages:
  - name: fit
    type: core/noop
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    escaped_output = client.post(
        "/api/launches",
        json={"config_path": "configs/smoke.yaml", "artifact_root": "../runs"},
    )
    escaped_config = client.post(
        "/api/launches",
        json={"config_path": "../smoke.yaml", "artifact_root": "runs"},
    )

    assert escaped_output.status_code == 400
    assert "workspace-relative" in escaped_output.json()["detail"]
    assert escaped_config.status_code == 400
    assert "escapes workspace" in escaped_config.json()["detail"]


def test_ui_checkpoint_catalog_preview_and_detached_inference(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    source = Path(__file__).parents[1] / "examples" / "torch" / "ra_torch_example"
    shutil.copytree(source, tmp_path / "ra_torch_example")
    (tmp_path / "configs").mkdir()
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "ui-checkpoint"},
            "plugins": ["ra_torch_example.plugin"],
            "seed": 0,
            "components": {
                "model": {"type": "torch_example/mlp", "params": {"width": 4}},
                "data": {"type": "torch_example/regression", "params": {"batch_size": 64}},
                "recipe": {"type": "torch_example/mse", "params": {"learning_rate": 0.01}},
            },
            "stages": [
                {
                    "name": "fit",
                    "type": "torch/fit",
                    "params": {"epochs": 1, "monitor": "val/loss", "device": "cpu"},
                }
            ],
            "resources": {"accelerator": "cpu"},
            "artifacts": {"root": "runs"},
        }
    )
    config_path = tmp_path / "configs" / "train.yaml"
    config_path.write_text(dump_config(config), encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        registry = load_registry(config.plugins)
        training_manifest = compile_plan(config, registry).runs[0]
        status = execute_run(training_manifest, registry, artifact_root=tmp_path / "runs")
    finally:
        sys.path.remove(str(tmp_path))
    checkpoint = status["stages"]["fit"]["artifacts"]["best"]
    checkpoint_path = (
        Path("runs") / training_manifest.study_id / training_manifest.run_id / checkpoint
    ).as_posix()
    client = TestClient(create_app(tmp_path, plugins=["ra_torch_example.plugin"]))

    catalog = client.post("/api/checkpoints/catalog", json={"artifact_root": "runs"})
    assert catalog.status_code == 200, catalog.text
    assert {item["name"] for item in catalog.json()["checkpoints"]} == {"best", "last"}

    request = {
        "checkpoint_path": checkpoint_path,
        "config_path": None,
        "splits": ["test"],
        "device": "cpu",
        "artifact_root": "runs",
    }
    preview = client.post("/api/checkpoints/inspect", json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["checkpoint"]["run_id"] == training_manifest.run_id
    assert [stage["type"] for stage in preview.json()["config"]["stages"]] == ["torch/evaluate"]

    launched = client.post("/api/checkpoints/infer", json=request)
    assert launched.status_code == 202, launched.text
    launch_id = launched.json()["launch_id"]
    deadline = time.monotonic() + 20
    detail = launched.json()
    while detail["state"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        detail = client.get(f"/api/launches/{launch_id}").json()
    assert detail["state"] == "completed", detail
    inference_run = detail["runs"][0]["run_id"]
    manifest_path = (
        tmp_path / "runs" / "ui-checkpoint-inference" / inference_run / "manifest.json"
    )
    inference_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert inference_manifest["provenance"]["source_run_id"] == training_manifest.run_id
