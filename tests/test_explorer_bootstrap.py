import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.explorer_ui import _patch_main_bundle  # noqa: E402
from research_assistant.ui.server import create_app  # noqa: E402


def test_main_bundle_patch_registers_connection_status() -> None:
    source = 'const ids=["workspace-name","file-count","file-filter"];'

    patched, applied = _patch_main_bundle(source)
    repeated, repeated_applied = _patch_main_bundle(patched)

    assert applied is True
    assert '["workspace-name","connection-status","file-count"' in patched
    assert repeated_applied is False
    assert repeated == patched


def test_explorer_bundle_is_patched_and_lists_files(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("visible\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    compatibility = 'src="/api/extensions/explorer-bootstrap.js"'
    main_match = re.search(
        r'type="module" crossorigin src="(?P<src>/assets/index-[^\"]+\.js\?explorer=4)"',
        index.text,
    )
    assert compatibility in index.text
    assert main_match is not None
    assert index.text.index(compatibility) < main_match.start()
    assert index.headers["cache-control"] == "no-store"

    script = client.get("/api/extensions/explorer-bootstrap.js")
    assert script.status_code == 200
    assert 'result["connection-status"]' in script.text
    assert "Object.fromEntries = originalFromEntries" in script.text
    assert script.headers["cache-control"] == "no-store"

    main_bundle = client.get(main_match.group("src"))
    assert main_bundle.status_code == 200
    assert main_bundle.headers["x-researchassistant-explorer-patch"] == "applied"
    assert main_bundle.headers["cache-control"] == "no-store"
    assert "/api/bootstrap" in main_bundle.text
    assert re.search(
        r'''["']workspace-name["'],["']connection-status["'],["']file-count["']''',
        main_bundle.text,
    )

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert any(entry["path"] == "local.txt" for entry in bootstrap.json()["files"])
