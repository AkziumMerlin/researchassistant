from __future__ import annotations

from pathlib import Path

import pytest

from research_assistant.remote_connect import (
    RemoteConnectionError,
    RemoteConnectSpec,
    RemoteProfileCatalog,
    build_remote_ui_command,
    build_ssh_argv,
)


def test_remote_profile_catalog_round_trip(tmp_path: Path) -> None:
    catalog = RemoteProfileCatalog(tmp_path / "remotes.json")
    saved = catalog.add(
        "gpu",
        target="gpu-server",
        workspace="/home/user/project",
        conda_env="KNO",
        plugins=["ra_project.plugin", "ra_project.plugin"],
    )

    assert saved["target"] == "gpu-server"
    assert saved["plugins"] == ["ra_project.plugin"]
    assert catalog.get("gpu") == saved
    assert catalog.list() == [saved]

    catalog.remove("gpu")
    assert catalog.list() == []


def test_remote_spec_rejects_two_environment_selectors() -> None:
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/srv/project",
        conda_env="KNO",
        remote_python="/opt/venv/bin/python",
    )

    with pytest.raises(RemoteConnectionError, match="mutually exclusive"):
        spec.validate()


def test_remote_command_uses_conda_and_headless_asgi_server() -> None:
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/home/user/project with spaces",
        conda_env="KNO",
        plugins=("ra_project.plugin",),
    )

    command = build_remote_ui_command(spec, 34567)

    assert "conda run --no-capture-output" in command
    assert "-n KNO python" in command
    assert "create_app(root, plugins, ssh_mode=True)" in command
    assert "host='127.0.0.1'" in command
    assert "34567" in command
    assert "ra_project.plugin" in command
    assert "'/home/user/project with spaces'" in command


def test_ssh_command_forwards_only_loopback() -> None:
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/srv/project",
        remote_python="~/miniconda3/envs/KNO/bin/python",
        ssh_options=("ProxyJump=bastion",),
    )

    argv = build_ssh_argv(
        spec,
        local_port=40123,
        remote_port=41234,
        ssh_executable="/usr/bin/ssh",
    )

    assert argv[0] == "/usr/bin/ssh"
    assert "127.0.0.1:40123:127.0.0.1:41234" in argv
    assert "ProxyJump=bastion" in argv
    assert argv[-4:] == ["gpu-server", "sh", "-lc", argv[-1]]
    assert '"$HOME"/miniconda3/envs/KNO/bin/python' in argv[-1]
