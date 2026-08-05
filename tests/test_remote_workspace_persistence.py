from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_assistant.remote_connect import RemoteConnectSpec
from research_assistant.remote_workspace_persistence import prepare_remote_desktop


def test_reconnect_preserves_local_roots_and_restores_remote_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/srv/project",
        conda_env="KNO",
        local_port=41000,
    )

    first = prepare_remote_desktop(spec)
    document = json.loads(first.workspace_file.read_text(encoding="utf-8"))
    document["folders"] = [
        {
            "name": "gpu-server:/srv/project",
            "path": f"file:///tmp/ra-remote:/{first.workspace_id}",
        },
        {"name": "Local notes", "path": "file:///home/user/notes"},
    ]
    document["settings"]["editor.fontSize"] = 15
    document["settings"]["terminal.integrated.profiles.linux"]["Local shell"] = {
        "path": "/bin/bash",
        "args": [],
    }
    first.workspace_file.write_text(json.dumps(document), encoding="utf-8")

    second = prepare_remote_desktop(spec)
    restored = json.loads(second.workspace_file.read_text(encoding="utf-8"))

    assert restored["folders"] == [
        {
            "name": "gpu-server:/srv/project",
            "uri": f"ra-remote://{second.workspace_id}/",
        },
        {"name": "Local notes", "path": "file:///home/user/notes"},
    ]
    assert restored["settings"]["editor.fontSize"] == 15
    profiles = restored["settings"]["terminal.integrated.profiles.linux"]
    assert profiles["Local shell"]["path"] == "/bin/bash"
    assert profiles["ResearchAssistant SSH"]["path"] == str(second.terminal_wrapper)
    assert restored["settings"]["terminal.integrated.defaultProfile.linux"] == (
        "ResearchAssistant SSH"
    )


def test_connect_cli_uses_persistent_remote_workspace_launcher() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "research_assistant" / "cli_remote.py").read_text(
        encoding="utf-8"
    )

    assert "from research_assistant.remote_workspace_persistence import connect_remote" in source
