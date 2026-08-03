from __future__ import annotations

from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parents[1] / "src" / "research_assistant" / "ui" / "static"


def _asset(name: str) -> str:
    return (STATIC_ROOT / name).read_text(encoding="utf-8")


def test_explorer_has_persistent_ide_style_resizer() -> None:
    source = _asset("explorer-plus.js")

    assert "installExplorerResizer();" in source
    assert 'resizer.setAttribute("role", "separator")' in source
    assert 'localStorage.setItem(EXPLORER_WIDTH_KEY, String(width))' in source
    assert "--ra-explorer-width" in source
    assert 'resizer.addEventListener("pointerdown"' in source
    assert 'resizer.addEventListener("dblclick"' in source


def test_models_palette_uses_visible_bounded_scroll_region() -> None:
    source = _asset("component-search.js")

    assert 'scroll.className = "raComponentSearchScroll"' in source
    assert "scroll.append(results, sourceList);" in source
    assert "overflow-y:scroll" in source
    assert "scrollbar-gutter:stable" in source
    assert "::-webkit-scrollbar-thumb" in source
