from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "desktop" / "application" / "package.json"
BROWSER = (
    ROOT
    / "desktop"
    / "research-assistant-extension"
    / "src"
    / "browser"
)


def test_media_preview_handles_pdf_and_common_image_formats() -> None:
    source = (BROWSER / "media-preview.ts").read_text(encoding="utf-8")

    for extension in [
        ".pdf",
        ".png",
        ".apng",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".avif",
        ".bmp",
        ".svg",
        ".ico",
    ]:
        assert f"'{extension}'" in source

    assert "extends NavigatableWidgetOpenHandler" in source
    assert "this.fileService.readFile" in source
    assert "URL.createObjectURL" in source
    assert "document.createElement('iframe')" in source
    assert "document.createElement('img')" in source
    assert "stat.isFile ? 900 : 0" in source
    assert "URL.revokeObjectURL" in source


def test_media_preview_is_registered_before_the_text_editor() -> None:
    frontend = (BROWSER / "research-assistant-frontend-module.ts").read_text(
        encoding="utf-8"
    )

    assert "ResearchAssistantMediaPreviewOpenHandler" in frontend
    assert "bind(OpenHandler).toService(ResearchAssistantMediaPreviewOpenHandler)" in frontend
    assert "ResearchAssistantMediaPreviewId" in frontend
    assert "NavigatableWidgetOptions.is(options)" in frontend
    assert "./style/media-preview.css" in frontend


def test_electron_pdf_plugin_is_enabled() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    electron = application["theia"]["frontend"]["config"]["electron"]

    assert electron["windowOptions"]["webPreferences"]["plugins"] is True
