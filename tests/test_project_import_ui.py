from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from research_assistant.ui.server import create_app

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TAB = (
    ROOT
    / "desktop"
    / "research-assistant-extension"
    / "src"
    / "browser"
    / "tabs"
    / "legacy-tab.ts"
)


def _project(root: Path) -> None:
    (root / "models").mkdir()
    (root / "examples").mkdir()
    (root / "configs").mkdir()
    (root / "models/model.py").write_text(
        "class Model:\n"
        "    def __init__(self, width: int = 8):\n"
        "        self.width = width\n",
        encoding="utf-8",
    )
    (root / "examples/train_from_yaml.py").write_text("print('runner')\n")
    (root / "configs/old.yaml").write_text(
        yaml.safe_dump(
            {
                "experiment": {"name": "old"},
                "models": {"model": {}},
                "train": {"epochs": 1},
            }
        ),
        encoding="utf-8",
    )


def test_project_import_routes_scan_and_apply_checked_candidates(tmp_path: Path) -> None:
    _project(tmp_path)

    with TestClient(create_app(tmp_path)) as client:
        scanned = client.post(
            "/api/project/import/scan",
            json={"include_python": True, "include_configs": True},
        )
        assert scanned.status_code == 200, scanned.text
        plan = scanned.json()
        selected = [
            candidate["id"]
            for candidate in plan["candidates"]
            if candidate["selected"]
        ]
        assert len(selected) == 2

        applied = client.post(
            "/api/project/import/apply",
            json={
                "candidate_ids": selected,
                "import_all": False,
                "replace": False,
                "include_python": True,
                "include_configs": True,
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["summary"] == {"imported": 2, "skipped": 0, "failed": 0}
        assert result["restart_required"] is False

        catalog = client.get("/api/legacy/registrations")
        assert catalog.status_code == 200
        assert catalog.json()["python"][0]["name"] == "local/model"
        assert catalog.json()["legacy_configs"][0]["path"] == "configs/old.yaml"


def test_register_tab_exposes_project_scan_and_checkbox_import() -> None:
    source = LEGACY_TAB.read_text(encoding="utf-8")

    assert "Import an existing project" in source
    assert "/api/project/import/scan" in source
    assert "/api/project/import/apply" in source
    assert "data-candidate-id" in source
    assert "Select recommended" in source
    assert "Import checked" in source
