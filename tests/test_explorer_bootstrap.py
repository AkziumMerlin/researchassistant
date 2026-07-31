import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.explorer_ui import (  # noqa: E402
    _EXPLORER_REGISTRY_PATCH_MARKER,
    _EXPLORER_REGISTRY_PRELUDE,
    _patch_explorer_bundle,
    _virtualize_main_script,
)
from research_assistant.ui.server import create_app  # noqa: E402


def test_main_bundle_url_is_virtualized_without_query_parameters() -> None:
    source = '<script type="module" src="/assets/index-example.js"></script>'

    patched = _virtualize_main_script(source)

    assert 'src="/assets/index-example-explorer6.js"' in patched
    assert "?" not in patched


def test_registry_patch_is_prepended_once() -> None:
    source = "const bundledApplication=true;"

    patched, applied = _patch_explorer_bundle(source)

    assert applied
    assert patched.startswith(_EXPLORER_REGISTRY_PRELUDE)
    assert patched.endswith(source)
    assert 'result["connection-status"]=' in patched
    assert "Object.fromEntries=originalFromEntries" in patched

    unchanged, reapplied = _patch_explorer_bundle(patched)
    assert unchanged == patched
    assert not reapplied


def test_explorer_bundle_is_patched_and_lists_files(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("visible\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    main_match = re.search(
        r'type="module" crossorigin src="(?P<src>/assets/index-[^\"]+-explorer6\.js)"',
        index.text,
    )
    assert main_match is not None
    assert "/api/extensions/explorer-bootstrap.js" not in index.text
    assert index.headers["cache-control"] == "no-store"

    main_bundle = client.get(main_match.group("src"))
    assert main_bundle.status_code == 200
    assert main_bundle.headers["x-researchassistant-explorer-patch"] == "applied"
    assert main_bundle.headers["cache-control"] == "no-store"
    assert main_bundle.text.startswith(_EXPLORER_REGISTRY_PRELUDE)
    assert _EXPLORER_REGISTRY_PATCH_MARKER in main_bundle.text
    assert "/api/bootstrap" in main_bundle.text
    assert "/api/torch/graph/validate" in main_bundle.text

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert any(entry["path"] == "local.txt" for entry in bootstrap.json()["files"])
