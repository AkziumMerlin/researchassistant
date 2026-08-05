from __future__ import annotations

import json
from pathlib import Path

from research_assistant.remote_connect import RemoteConnectSpec, prepare_remote_desktop

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
BROWSER = DESKTOP / "research-assistant-extension" / "src" / "browser"


def test_remote_workspace_declares_ssh_terminal_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    prepared = prepare_remote_desktop(
        RemoteConnectSpec(
            target="gpu-server",
            workspace="/srv/project",
            conda_env="KNO",
            local_port=41000,
        )
    )
    document = json.loads(prepared.workspace_file.read_text(encoding="utf-8"))
    settings = document["settings"]
    profile = settings["terminal.integrated.profiles.linux"]["ResearchAssistant SSH"]

    assert profile["path"] == str(prepared.terminal_wrapper)
    assert profile["args"] == []
    assert settings["terminal.integrated.defaultProfile.linux"] == "ResearchAssistant SSH"
    assert prepared.terminal_wrapper.stat().st_mode & 0o100


def test_remote_terminal_profile_does_not_block_frontend_startup() -> None:
    source = (BROWSER / "remote-terminal-contribution.ts").read_text(encoding="utf-8")
    frontend = (BROWSER / "research-assistant-frontend-module.ts").read_text(encoding="utf-8")
    application = json.loads(
        (DESKTOP / "application" / "package.json").read_text(encoding="utf-8")
    )

    assert "onStart(): void" in source
    assert "void this.registerAfterFrontendReady()" in source
    assert "reachedState('ready')" in source
    assert "async onStart" not in source
    assert "await this.preferences.ready" not in source
    assert "FileService" not in source
    assert "UserTerminalProfileStore" in source
    assert "new ShellTerminalProfile" in source
    assert "setDefaultProfile(REMOTE_PROFILE)" in source
    assert "ResearchAssistantRemoteTerminalContribution" in frontend
    binding = (
        "FrontendApplicationContribution)"
        ".toService(ResearchAssistantRemoteTerminalContribution)"
    )
    assert binding in frontend
    preferences = application["theia"]["frontend"]["config"]["preferences"]
    assert "terminal.integrated.defaultProfile.linux" not in preferences


def test_path_completion_supports_prefix_popup_and_tab_completion() -> None:
    source = (BROWSER / "path-completion.ts").read_text(encoding="utf-8")
    frontend = (BROWSER / "research-assistant-frontend-module.ts").read_text(encoding="utf-8")
    css = (BROWSER / "style" / "path-completion.css").read_text(encoding="utf-8")

    assert "closest('.ra-theia-workspace')" in source
    assert "candidate.resource.scheme === REMOTE_SCHEME" in source
    assert "this.fileService.resolve(directory)" in source
    assert "toLocaleLowerCase().startsWith" in source
    assert "event.key === 'Tab'" in source
    assert "longestCommonPrefix" in source
    assert "event.key === 'ArrowDown'" in source
    assert "role', 'listbox'" in source
    assert "ResearchAssistantPathCompletionContribution" in frontend
    assert "./style/path-completion.css" in frontend
    assert ".ra-path-completion-item.selected" in css
