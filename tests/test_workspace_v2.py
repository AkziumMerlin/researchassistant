from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

import research_assistant.cli_workbench  # noqa: F401
from research_assistant.assistant_core import AssistantEngine, AssistantRequest
from research_assistant.capabilities import capability_matrix
from research_assistant.cli_workspace_v2 import workspace_v2_app
from research_assistant.durable_launches import DurableLaunchManager
from research_assistant.migrations import migrate_document
from research_assistant.notebook_context import NotebookContextStore
from research_assistant.plugin_sdk import contract_from_module
from research_assistant.run_workspace import RunWorkspace
from research_assistant.ui import server
from research_assistant.ui.workspace import Workspace

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _write_run(
    workspace: Path,
    *,
    study_id: str,
    trial_id: str,
    run_id: str,
    seed: int,
    error: float,
    state: str = "completed",
) -> Path:
    run_dir = workspace / "runs" / study_id / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "study_id": study_id,
        "trial_id": trial_id,
        "run_id": run_id,
        "assignments": {"seed": seed},
        "provenance": {},
        "config": {
            "version": 1,
            "experiment": {"name": study_id, "tags": ["test"]},
            "plugins": [],
            "seed": seed,
            "components": {
                "model": {"type": "example/model", "params": {}},
                "data": {"type": "example/data", "params": {}},
            },
            "matrix": {},
            "stages": [
                {"name": "test", "type": "core/noop", "needs": [], "params": {}}
            ],
            "resources": {"accelerator": "cpu", "devices": 1},
            "artifacts": {"root": "runs"},
            "logging": {
                "tensorboard": {
                    "enabled": False,
                    "directory": "tensorboard",
                    "flush_seconds": 30,
                }
            },
        },
    }
    status = {
        "run_id": run_id,
        "state": state,
        "updated_at": "2026-08-04T00:00:00+00:00",
        "stages": {
            "test": {
                "state": state,
                "metrics": {"relative_l2": error},
            }
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    return run_dir


def _write_launch(
    workspace: Path,
    *,
    launch_id: str,
    run_id: str,
    state: str,
    scheduler_pid: int,
) -> Path:
    launch_dir = workspace / ".ra" / "ui-launches" / launch_id
    launch_dir.mkdir(parents=True)
    request = {
        "schema_version": 1,
        "launch_id": launch_id,
        "created_at": "2026-08-04T00:00:00+00:00",
        "workspace_root": str(workspace),
        "config_path": "configs/test.yaml",
        "launcher_path": None,
        "artifact_root": str(workspace / "runs"),
        "artifact_root_relative": "runs",
        "resume": True,
        "overrides": [],
        "launcher_overrides": [],
        "plan": {
            "study_id": "study-a",
            "runs": 1,
            "trials": 1,
            "run_ids": [run_id],
            "trial_ids": ["trial-a"],
            "run_details": [],
        },
    }
    (launch_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (launch_dir / "state.json").write_text(
        json.dumps({"launch_id": launch_id, "state": state}),
        encoding="utf-8",
    )
    (launch_dir / "process.json").write_text(
        json.dumps({"scheduler_pid": scheduler_pid}),
        encoding="utf-8",
    )
    return launch_dir


def test_capability_matrix_declares_cli_api_ui_parity() -> None:
    matrix = capability_matrix()

    assert matrix["capabilities"]
    assert all(
        row[surface] in {"yes", "partial", "internal"}
        for row in matrix["capabilities"]
        for surface in ("cli", "api", "ui")
    )
    assert any(
        row["capability_id"] == "run.aggregate" for row in matrix["capabilities"]
    )


def test_legacy_config_migration_is_explicit_and_idempotent() -> None:
    migrated, report = migrate_document(
        {
            "experiment": {"name": "legacy"},
            "artifact_root": "legacy-runs",
            "seeds": [1, 2],
            "stages": [{"name": "fit", "type": "core/noop"}],
        }
    )

    assert report.changed is True
    assert migrated["version"] == 1
    assert migrated["artifacts"]["root"] == "legacy-runs"
    assert migrated["matrix"]["seed"] == [1, 2]
    repeated, repeated_report = migrate_document(migrated)
    assert repeated == migrated
    assert repeated_report.changed is False


def test_plugin_contract_reports_compatible_and_incompatible_plugins() -> None:
    compatible = ModuleType("compatible_plugin")
    compatible.RESEARCH_ASSISTANT_PLUGIN = {
        "name": "compatible",
        "version": "1.0.0",
        "minimum_research_assistant": "0.3.0",
        "config_schema_versions": [1],
    }
    incompatible = ModuleType("incompatible_plugin")
    incompatible.RESEARCH_ASSISTANT_PLUGIN = {
        "name": "future",
        "version": "1.0.0",
        "minimum_research_assistant": "99.0.0",
        "config_schema_versions": [1],
    }

    assert contract_from_module(compatible, "compatible").state == "compatible"
    diagnostic = contract_from_module(incompatible, "future")
    assert diagnostic.state == "incompatible"
    assert "requires ResearchAssistant" in diagnostic.message


def test_cross_study_run_aggregation_uses_explicit_run_selection(
    tmp_path: Path,
) -> None:
    _write_run(
        tmp_path,
        study_id="study-a",
        trial_id="trial-a",
        run_id="run-a",
        seed=0,
        error=0.1,
    )
    _write_run(
        tmp_path,
        study_id="study-b",
        trial_id="trial-b",
        run_id="run-b",
        seed=1,
        error=0.3,
    )

    workspace = RunWorkspace(tmp_path)
    catalog = workspace.catalog()
    aggregate = workspace.aggregate(
        ["run-a", "run-b"],
        metric="relative_l2",
        group_by=["model"],
    )

    assert catalog["total"] == 2
    assert {row["study_id"] for row in catalog["runs"]} == {
        "study-a",
        "study-b",
    }
    assert aggregate["selected_runs"] == ["run-a", "run-b"]
    assert aggregate["groups"][0]["n"] == 2
    assert aggregate["groups"][0]["mean"] == pytest.approx(0.2)
    assert aggregate["groups"][0]["run_ids"] == ["run-a", "run-b"]


def test_notebook_context_binds_selected_runs_and_creates_notebook(
    tmp_path: Path,
) -> None:
    pytest.importorskip("nbformat")
    _write_run(
        tmp_path,
        study_id="study-a",
        trial_id="trial-a",
        run_id="run-a",
        seed=0,
        error=0.1,
    )

    context = NotebookContextStore(tmp_path).create(
        run_ids=["run-a"],
        notebook_path="notebooks/run-a.ipynb",
        label="run-a-analysis",
    )

    assert context["run_ids"] == ["run-a"]
    assert context["runs"][0]["study_id"] == "study-a"
    notebook = json.loads(
        (tmp_path / "notebooks" / "run-a.ipynb").read_text(encoding="utf-8")
    )
    assert (
        notebook["metadata"]["research_assistant"]["context_path"]
        == context["context_path"]
    )
    assert "RA_CONTEXT" in notebook["cells"][1]["source"]


def test_typed_assistant_aggregates_but_blocks_unapproved_writes(
    tmp_path: Path,
) -> None:
    for run_id, seed, value in (("run-a", 0, 0.1), ("run-b", 1, 0.2)):
        _write_run(
            tmp_path,
            study_id="study-a",
            trial_id="trial-a",
            run_id=run_id,
            seed=seed,
            error=value,
        )
    request = AssistantRequest(
        goal="Aggregate the selected experiment runs and prepare analysis",
        run_ids=["run-a", "run-b"],
        allow_writes=False,
    )
    engine = AssistantEngine(str(tmp_path))
    plan = engine.plan(request)
    result = engine.apply(request, plan)

    assert any(action.kind == "aggregate_runs" for action in plan.actions)
    assert any(row["state"] == "completed" for row in result["results"])
    assert any(row["state"] == "blocked" for row in result["results"])


def test_durable_launch_reconciliation_and_adoption_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(
        tmp_path,
        study_id="study-a",
        trial_id="trial-a",
        run_id="run-a",
        seed=0,
        error=0.1,
    )
    completed = _write_launch(
        tmp_path,
        launch_id="launch-completed",
        run_id="run-a",
        state="running",
        scheduler_pid=999_999_999,
    )
    manager = DurableLaunchManager(Workspace(tmp_path))
    completed_state = json.loads(
        (completed / "state.json").read_text(encoding="utf-8")
    )
    assert completed_state["state"] == "completed"

    failed_run = tmp_path / "runs" / "study-a" / "run-a" / "status.json"
    failed_run.write_text(
        json.dumps({"run_id": "run-a", "state": "failed", "stages": {}}),
        encoding="utf-8",
    )
    adoptable = _write_launch(
        tmp_path,
        launch_id="launch-failed",
        run_id="run-a",
        state="failed",
        scheduler_pid=999_999_998,
    )
    (adoptable / "control.json").write_text(
        json.dumps({"action": "cancel"}),
        encoding="utf-8",
    )

    def fake_spawn(launch_dir: Path, _module: str) -> int:
        (launch_dir / "process.json").write_text(
            json.dumps({"scheduler_pid": os.getpid()}),
            encoding="utf-8",
        )
        return os.getpid()

    monkeypatch.setattr(manager, "_spawn_supervisor", fake_spawn)
    detail = manager.adopt("launch-failed")
    assert detail["state"] == "adopting"
    assert not (adoptable / "control.json").exists()
    request = json.loads(
        (adoptable / "request.json").read_text(encoding="utf-8")
    )
    assert request["resume"] is True
    assert request["adoption_generation"] == 1


def test_workspace_v2_api_and_assets_are_registered(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        study_id="study-a",
        trial_id="trial-a",
        run_id="run-a",
        seed=0,
        error=0.1,
    )
    client = TestClient(server.create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert "/api/extensions/layout-manager.js" in index.text
    assert "/api/extensions/research-workspace.js" in index.text
    assert "__RA_LAYOUT__" in client.get("/api/extensions/layout-manager.js").text
    workspace_script = client.get("/api/extensions/research-workspace.js").text
    assert "Cross-run aggregation" in workspace_script

    capabilities = client.get("/api/workspace-v2/capabilities")
    assert capabilities.status_code == 200
    assert any(
        row["capability_id"] == "notebook.context"
        for row in capabilities.json()["capabilities"]
    )
    runs = client.get("/api/workspace-v2/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["run_id"] == "run-a"
    aggregation = client.post(
        "/api/workspace-v2/runs/aggregate",
        json={"run_ids": ["run-a"], "metric": "relative_l2"},
    )
    assert aggregation.status_code == 200, aggregation.text
    assistant = client.post(
        "/api/workspace-v2/assistant/plan",
        json={"goal": "Inspect run results", "run_ids": ["run-a"]},
    )
    assert assistant.status_code == 200
    assert assistant.json()["actions"]


def test_workspace_v2_cli_is_available() -> None:
    result = CliRunner().invoke(workspace_v2_app, ["capabilities", "--json"])

    assert result.exit_code == 0, result.output
    assert "run.aggregate" in result.output


@pytest.mark.skipif(
    os.environ.get("RA_BROWSER_E2E") != "1",
    reason="browser E2E runs in the dedicated CI job",
)
def test_research_workspace_browser_flow(tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    _write_run(
        tmp_path,
        study_id="study-a",
        trial_id="trial-a",
        run_id="run-a",
        seed=0,
        error=0.1,
    )
    app = server.create_app(tmp_path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    instance = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not instance.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert instance.started

    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle")
            page.locator("#ra-research-workspace-button").click()
            page.locator("#ra-research-workspace[open]").wait_for()
            page.get_by_role("heading", name="Research workspace").wait_for()
            page.locator(
                "#ra-research-workspace .rwRunIdentity strong",
                has_text="study-a / run-a",
            ).first.wait_for()
            page.get_by_role("button", name="Layout", exact=True).wait_for()
            page.get_by_role("button", name="Artifacts", exact=True).click()
            page.get_by_role("button", name="Assistant", exact=True).click()
            page.get_by_role("heading", name="Typed research planner").wait_for()
            browser.close()
    finally:
        instance.should_exit = True
        thread.join(timeout=10)
