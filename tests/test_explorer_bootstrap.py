from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.ui.server import create_app  # noqa: E402


def test_explorer_bootstrap_precedes_main_bundle_and_lists_files(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("visible\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    compatibility = 'src="/assets/explorer-bootstrap.js"'
    main_bundle = 'type="module" crossorigin src="/assets/index-'
    assert compatibility in index.text
    assert main_bundle in index.text
    assert index.text.index(compatibility) < index.text.index(main_bundle)

    script = client.get("/assets/explorer-bootstrap.js")
    assert script.status_code == 200
    assert 'result["connection-status"]' in script.text
    assert "Object.fromEntries = originalFromEntries" in script.text

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert any(entry["path"] == "local.txt" for entry in bootstrap.json()["files"])
