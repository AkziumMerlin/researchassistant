import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.explorer_ui import (  # noqa: E402
    _DIRECT_CONNECTION_STATUS_REPLACE,
    _patch_explorer_bundle,
    _virtualize_main_script,
)
from research_assistant.ui.server import create_app  # noqa: E402


def test_main_bundle_url_is_virtualized_without_query_parameters() -> None:
    source = '<script type="module" src="/assets/index-example.js"></script>'

    patched = _virtualize_main_script(source)

    assert 'src="/assets/index-example-explorer5.js"' in patched
    assert "?" not in patched


def test_connection_status_update_is_patched_directly() -> None:
    source = 'const elements={};elements["connection-status"].replaceChildren();'

    patched, applied = _patch_explorer_bundle(source)

    assert applied
    assert _DIRECT_CONNECTION_STATUS_REPLACE in patched
    assert 'elements["connection-status"].replaceChildren()' not in patched

    unchanged, reapplied = _patch_explorer_bundle(patched)
    assert unchanged == patched
    assert not reapplied


def test_connection_status_patch_rejects_ambiguous_bundles() -> None:
    source = (
        'a["connection-status"].replaceChildren();'
        'b["connection-status"].replaceChildren();'
    )

    with pytest.raises(Exception, match="found 2 matches"):
        _patch_explorer_bundle(source)


def test_explorer_bundle_is_patched_and_lists_files(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("visible\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    compatibility = 'src="/api/extensions/explorer-bootstrap.js"'
    main_match = re.search(
        r'type="module" crossorigin src="(?P<src>/assets/index-[^\"]+-explorer5\.js)"',
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
    assert "/api/torch/graph/validate" in main_bundle.text
    assert _DIRECT_CONNECTION_STATUS_REPLACE in main_bundle.text
    assert "researchAssistantFromEntries" not in main_bundle.text

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert any(entry["path"] == "local.txt" for entry in bootstrap.json()["files"])
