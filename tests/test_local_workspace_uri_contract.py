from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "desktop"
    / "research-assistant-extension"
    / "src"
    / "browser"
    / "remote-workspace-service.ts"
)


def test_local_file_uris_are_not_resolved_as_relative_paths() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "const resource = new URI(path);" in source
    assert "if (resource.scheme)" in source
    assert "return resource.normalizePath().toString();" in source
    assert "URI.fromFilePath(path).normalizePath().toString()" in source
    assert "isAbsoluteFileSystemPath" in source
    assert "resource.scheme === 'file'" in source
