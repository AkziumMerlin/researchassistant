from __future__ import annotations

import time
from pathlib import Path

import pytest

from research_assistant.notebooks import NotebookKernelManager, NotebookStore
from research_assistant.ui.workspace import Workspace, WorkspaceConflict


def test_notebook_store_round_trip_and_conflict(tmp_path: Path) -> None:
    (tmp_path / "notebooks").mkdir()
    store = NotebookStore(Workspace(tmp_path))

    created = store.create("notebooks/analysis.ipynb", kernel_name="python3")
    assert created["notebook"]["nbformat"] == 4
    assert created["notebook"]["cells"][0]["cell_type"] == "code"
    assert created["notebook"]["cells"][0]["id"]

    notebook = created["notebook"]
    notebook["cells"][0]["source"] = "answer = 42"
    saved = store.write(
        "notebooks/analysis.ipynb",
        notebook,
        expected_revision=created["revision"],
    )
    loaded = store.read("notebooks/analysis.ipynb")
    assert loaded["revision"] == saved["revision"]
    assert loaded["notebook"]["cells"][0]["source"] == "answer = 42"

    with pytest.raises(WorkspaceConflict, match="changed outside"):
        store.write(
            "notebooks/analysis.ipynb",
            notebook,
            expected_revision=created["revision"],
        )


def _wait_for_stream(
    manager: NotebookKernelManager,
    kernel_id: str,
    needle: str,
    timeout: float = 20.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = manager.require(kernel_id)
        for event in list(session.recent_events):
            if event.get("type") != "stream":
                continue
            text = str((event.get("content") or {}).get("text") or "")
            if needle in text:
                return
        time.sleep(0.05)
    raise AssertionError(f"kernel output did not contain {needle!r}")


def test_notebook_kernel_survives_manager_replacement(tmp_path: Path) -> None:
    (tmp_path / "notebooks").mkdir()
    store = NotebookStore(Workspace(tmp_path))
    store.create("notebooks/persistent.ipynb")

    first = NotebookKernelManager(Workspace(tmp_path))
    if not any(item["name"] == "python3" for item in first.available_kernels()):
        pytest.skip("native python3 Jupyter kernel is unavailable")

    kernel = first.start("notebooks/persistent.ipynb", kernel_name="python3")
    kernel_id = kernel["kernel_id"]
    try:
        first.execute(
            kernel_id,
            cell_id="cell-one",
            code="persistent_value = 41\nprint('first-ready')",
        )
        _wait_for_stream(first, kernel_id, "first-ready")
        first.detach()

        second = NotebookKernelManager(Workspace(tmp_path))
        try:
            restored = {item["kernel_id"]: item for item in second.list()}
            assert kernel_id in restored
            assert restored[kernel_id]["persistent"] is True
            second.execute(
                kernel_id,
                cell_id="cell-two",
                code="print(f'restored-value={persistent_value + 1}')",
            )
            _wait_for_stream(second, kernel_id, "restored-value=42")
        finally:
            second.shutdown(kernel_id)
    finally:
        # The second manager normally removes the record. This covers startup failures.
        try:
            first.shutdown(kernel_id)
        except Exception:
            pass
