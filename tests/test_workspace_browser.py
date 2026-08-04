from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import research_assistant.cli_workbench  # noqa: F401
from research_assistant.ui import server
from research_assistant.ui.workspace import Workspace


def test_workspace_directory_is_lazy_and_paginated(tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "nested.py").write_text("print('nested')\n", encoding="utf-8")
    for index in range(12):
        (tmp_path / f"file_{index:02d}.txt").write_text(str(index), encoding="utf-8")

    workspace = Workspace(tmp_path)
    first = workspace.directory("", limit=5)
    second = workspace.directory("", offset=first["next_offset"], limit=5)

    assert first["entries"][0]["kind"] == "directory"
    assert first["entries"][0]["path"] == "alpha"
    assert first["entries"][0]["has_children"] is True
    assert len(first["entries"]) == 5
    assert first["total"] == 13
    assert first["next_offset"] == 5
    assert second["offset"] == 5
    assert not set(item["path"] for item in first["entries"]) & set(
        item["path"] for item in second["entries"]
    )


def test_workspace_search_traverses_unloaded_directories(tmp_path: Path) -> None:
    deep = tmp_path / "large" / "nested" / "tree"
    deep.mkdir(parents=True)
    (deep / "representative_notebook.ipynb").write_text("{}", encoding="utf-8")
    for index in range(40):
        (tmp_path / f"unrelated_{index:02d}.txt").write_text("x", encoding="utf-8")

    result = Workspace(tmp_path).search("representative notebook", limit=10)

    assert [item["path"] for item in result["entries"]] == [
        "large/nested/tree/representative_notebook.ipynb"
    ]
    assert result["entries"][0]["notebook"] is True


def test_workspace_browser_routes_and_extensions(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "model.py").write_text("class Model: pass\n", encoding="utf-8")
    app = server.create_app(tmp_path)

    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "/api/extensions/" not in index.text
        main_source = (
            Path(__file__).parents[1] / "ui/frontend/src/main.js"
        ).read_text(encoding="utf-8")
        assert "globalThis.__RA_WORKBENCH__" in main_source
        assert "globalThis.monaco = monaco" in main_source

        explorer_source = (
            Path(__file__).parents[1]
            / "ui/frontend/src/extensions/explorer-plus.js"
        ).read_text(encoding="utf-8")
        assert (
            ".raExplorerRow.directory{grid-template-columns:18px 18px minmax(0,1fr)"
            in explorer_source
        )
        assert ".raExplorerName{min-width:0;" in explorer_source

        component_search_source = (
            Path(__file__).parents[1]
            / "ui/frontend/src/extensions/component-search.js"
        ).read_text(encoding="utf-8")
        assert 'palette.classList.add("raComponentSearchPalette")' in component_search_source
        assert ".ra-models-main{min-height:0}" in component_search_source
        assert ".ra-models-work{min-height:0;overflow:hidden}" in component_search_source
        assert "overflow-y:scroll;overflow-x:hidden;scrollbar-gutter:stable" in (
            component_search_source
        )
        assert "::-webkit-scrollbar-thumb" in component_search_source

        root = client.get("/api/workspace/entries", params={"path": "", "limit": 10})
        assert root.status_code == 200
        assert root.json()["entries"][0]["path"] == "src"

        nested = client.get(
            "/api/workspace/entries",
            params={"path": "src", "limit": 10},
        )
        assert nested.status_code == 200
        assert nested.json()["entries"][0]["path"] == "src/model.py"

        search = client.get("/api/workspace/search", params={"query": "model"})
        assert search.status_code == 200
        assert search.json()["entries"][0]["path"] == "src/model.py"

        created = client.post(
            "/api/notebooks/file",
            json={"path": "notebooks/reports/analysis.ipynb", "kernel_name": "python3"},
        )
        assert created.status_code == 201
        assert (tmp_path / "notebooks" / "reports" / "analysis.ipynb").is_file()
