import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.cli_explorer  # noqa: E402,F401
from research_assistant.explorer_ui import (  # noqa: E402
    _EXPLORER_REGISTRY_PATCH_MARKER,
    _EXPLORER_REGISTRY_PRELUDE,
    _PATCH_VERSION,
    _patch_explorer_bundle,
    _virtualize_main_script,
)
from research_assistant.ui.server import create_app  # noqa: E402


def test_main_bundle_url_is_virtualized_without_query_parameters() -> None:
    source = '<script type="module" src="/assets/index-example.js"></script>'

    patched = _virtualize_main_script(source)

    assert f'src="/assets/index-example-explorer{_PATCH_VERSION}.js"' in patched
    assert "?" not in patched


def test_registry_patch_is_generic_and_prepended_once() -> None:
    source = "const bundledApplication=true;"

    patched, applied = _patch_explorer_bundle(source)

    assert applied
    assert patched.startswith(_EXPLORER_REGISTRY_PRELUDE)
    assert patched.endswith(source)
    assert "return new Proxy(result" in patched
    assert "document.getElementById(property)" in patched
    assert "UI element #${property}" in patched
    assert "Object.fromEntries=originalFromEntries" in patched

    unchanged, reapplied = _patch_explorer_bundle(patched)
    assert unchanged == patched
    assert not reapplied


def test_explorer_bundle_is_patched_and_lists_files(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("visible\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    main_pattern = (
        r'type="module" crossorigin src="'
        rf'(?P<src>/assets/index-[^\"]+-explorer{_PATCH_VERSION}\.js)"'
    )
    main_match = re.search(main_pattern, index.text)
    assert main_match is not None
    assert index.headers["cache-control"] == "no-store"
    assert index.headers["x-researchassistant-ui-build"] == str(_PATCH_VERSION)

    main_bundle = client.get(main_match.group("src"))
    assert main_bundle.status_code == 200
    assert main_bundle.headers["x-researchassistant-explorer-patch"] == "applied"
    assert main_bundle.headers["x-researchassistant-ui-build"] == str(_PATCH_VERSION)
    assert main_bundle.headers["cache-control"] == "no-store"
    assert main_bundle.text.startswith(_EXPLORER_REGISTRY_PRELUDE)
    assert _EXPLORER_REGISTRY_PATCH_MARKER in main_bundle.text
    assert "return new Proxy(result" in main_bundle.text
    assert "/api/bootstrap" in main_bundle.text

    build = client.get("/api/ui-build")
    assert build.status_code == 200
    assert build.headers["cache-control"] == "no-store"
    payload = build.json()
    assert payload["patch_version"] == _PATCH_VERSION
    assert payload["patch_marker"] == _EXPLORER_REGISTRY_PATCH_MARKER
    assert payload["served_asset"] == main_match.group("src")
    assert payload["source_asset"].endswith(".js")
    assert payload["explorer_module"].endswith("explorer_ui.py")
    assert payload["server_module"].endswith("server.py")

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert any(entry["path"] == "local.txt" for entry in bootstrap.json()["files"])
