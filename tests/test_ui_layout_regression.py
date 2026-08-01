from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_editor_and_registry_layout_are_explicit() -> None:
    html = (ROOT / "ui/frontend/index.html").read_text(encoding="utf-8")
    css = (ROOT / "ui/frontend/src/styles.css").read_text(encoding="utf-8")
    assert 'id="editor" class="editor" aria-label="File editor" hidden' in html
    assert 'id="registry-panel" class="sidebar registry-panel" hidden' in html
    assert ".empty-state,\n.editor {\n  grid-row: 2;" in css
    assert ".workbench.ra-registry-open" in css
    assert ".registry-panel {\n  display: none;" in css


def test_toolbar_observer_does_not_rewrite_itself_forever() -> None:
    source = (ROOT / "src/research_assistant/ui/static/architecture-v2/part-07.txt").read_text(
        encoding="utf-8"
    )
    assert "observer.disconnect();" in source
    assert "mutation.target === actions" in source
    assert 'registryToggle.id = "ra-registry-toggle"' in source
    assert 'const moreLabels = ["Registry",' in source


def test_vite_preserves_architecture_runtime_files() -> None:
    source = (ROOT / "ui/frontend/vite.config.js").read_text(encoding="utf-8")
    assert '"architecture-extension.js"' in source
    assert "`architecture-v2/part-" in source
    assert "mkdir(dirname(destination)" in source
