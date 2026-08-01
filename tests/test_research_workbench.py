from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from research_assistant.analysis_sessions import AnalysisSessionManager
from research_assistant.developer_tools import DeveloperToolError, DeveloperTools
from research_assistant.lifecycle import LifecycleError, LifecycleManager
from research_assistant.scientific_artifacts import ScientificArtifactCatalog
from research_assistant.workspaces import WorkspaceCatalog, inspect_interpreter


def test_scientific_artifact_slice_and_compare(tmp_path: Path) -> None:
    left_path = tmp_path / "runs" / "prediction.json"
    right_path = tmp_path / "runs" / "target.json"
    left_path.parent.mkdir(parents=True)
    left_path.write_text(json.dumps({"data": [[1.0, 2.0], [3.0, 4.0]]}), encoding="utf-8")
    right_path.write_text(json.dumps({"data": [[1.0, 1.0], [5.0, 4.0]]}), encoding="utf-8")

    catalog = ScientificArtifactCatalog(tmp_path)
    left = catalog.register(left_path, kind="prediction", dimensions=["y", "x"])
    right = catalog.register(right_path, kind="target", dimensions=["y", "x"])

    sliced = catalog.slice(left["artifact_id"], selection=["1", ":"])
    assert sliced["shape"] == [2]
    assert sliced["data"] == [3.0, 4.0]
    assert sliced["mean"] == 3.5

    comparison = catalog.compare(left["artifact_id"], right["artifact_id"])
    assert comparison["compatible"] is True
    assert comparison["mae"] == pytest.approx(0.75)
    assert comparison["maximum_absolute_error"] == pytest.approx(2.0)


def test_lifecycle_protect_trash_restore_and_gc(tmp_path: Path) -> None:
    result = tmp_path / "runs" / "study" / "run"
    result.mkdir(parents=True)
    (result / "metrics.jsonl").write_text("{}\n", encoding="utf-8")
    manager = LifecycleManager(tmp_path)

    manager.pin(result, reason="paper result")
    with pytest.raises(LifecycleError, match="protected"):
        manager.trash(result)
    manager.unpin(result)

    trashed = manager.trash(result, reason="cleanup")
    assert not result.exists()
    restored = manager.restore(trashed["trash_id"])
    assert restored["restored_path"] == "runs/study/run"
    assert result.is_dir()

    trashed = manager.trash(result)
    preview = manager.gc(older_than_days=0, dry_run=True)
    assert [item["trash_id"] for item in preview["items"]] == [trashed["trash_id"]]
    applied = manager.gc(older_than_days=0, dry_run=False)
    assert applied["bytes"] > 0
    assert manager.state()["trash"] == {}


def test_workspace_catalog_and_interpreter_inspection(tmp_path: Path) -> None:
    catalog = WorkspaceCatalog(tmp_path / "catalog.json")
    entry = catalog.add("project", tmp_path, python=sys.executable, conda_env="KNO")
    assert entry["name"] == "project"
    assert catalog.list()[0]["python_exists"] is True

    inspected = inspect_interpreter(sys.executable)
    assert inspected["executable"] == str(Path(sys.executable).resolve())
    assert inspected["version"]

    catalog.remove("project")
    assert catalog.list() == []


def test_detached_analysis_session(tmp_path: Path) -> None:
    script = tmp_path / "analysis.py"
    script.write_text("print('analysis-ok')\n", encoding="utf-8")
    manager = AnalysisSessionManager(tmp_path)
    session = manager.start_script(script, python=sys.executable)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = manager.status(session["session_id"])
        if state["state"] != "running":
            break
        time.sleep(0.05)
    else:
        pytest.fail("analysis session did not finish")

    assert state["state"] == "finished"
    assert "analysis-ok" in manager.logs(session["session_id"])


def test_developer_tools_are_read_only_without_trust(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("VALUE = 'needle'\n", encoding="utf-8")
    tools = DeveloperTools(tmp_path, trusted=False)
    result = tools.search("needle", pattern="*.py")
    assert result["matches"][0]["path"] == "module.py"
    with pytest.raises(DeveloperToolError, match="trusted developer mode"):
        tools.mkdir("new-directory")
