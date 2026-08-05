from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_assistant.desktop import normalize_theia_workspace_file
from research_assistant.remote_connect import RemoteConnectSpec, prepare_remote_desktop


def test_remote_workspace_root_uses_theia_path_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    normalize_theia_workspace_file(prepared.workspace_file)
    document = json.loads(prepared.workspace_file.read_text(encoding="utf-8"))
    folder = document["folders"][0]

    assert folder["path"] == f"ra-remote://{prepared.workspace_id}/"
    assert "uri" not in folder
    assert folder["name"] == "gpu-server:/srv/project"


def test_workspace_normalization_does_not_rewrite_unrelated_uri(tmp_path: Path) -> None:
    workspace = tmp_path / "custom.theia-workspace"
    workspace.write_text(
        json.dumps({"folders": [{"uri": "custom://authority/root"}]}),
        encoding="utf-8",
    )

    normalize_theia_workspace_file(workspace)

    document = json.loads(workspace.read_text(encoding="utf-8"))
    assert document["folders"] == [{"uri": "custom://authority/root"}]
