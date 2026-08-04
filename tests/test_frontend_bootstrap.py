import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.ui.server import create_app  # noqa: E402


def test_frontend_source_registers_elements_and_workbench_natively() -> None:
    source = (
        Path(__file__).parents[1] / "ui/frontend/src/main.js"
    ).read_text(encoding="utf-8")

    assert "const elements = new Proxy(" in source
    assert "document.getElementById(property)" in source
    assert '"connection-status"' in source
    assert "globalThis.monaco = monaco" in source
    assert "globalThis.__RA_WORKBENCH__" in source
    assert "await installExtensions()" in source


def test_frontend_bundle_is_served_without_runtime_patch(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("visible\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert "/api/extensions/" not in index.text
    main_match = re.search(
        r'type="module" crossorigin src="(?P<src>/assets/index-[^\"]+\.js)"',
        index.text,
    )
    assert main_match is not None
    assert "-explorer" not in main_match.group("src")

    main_bundle = client.get(main_match.group("src"))
    assert main_bundle.status_code == 200
    assert "x-researchassistant-explorer-patch" not in main_bundle.headers

    build = client.get("/api/ui-build")
    assert build.status_code == 200
    assert build.json() == {
        "frontend": "vite",
        "extensions": "bundled",
        "architecture_language_version": 2,
    }

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert any(entry["path"] == "local.txt" for entry in bootstrap.json()["files"])
