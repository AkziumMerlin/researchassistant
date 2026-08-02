from __future__ import annotations

from io import StringIO
from pathlib import Path
import tomllib

import pytest

from research_assistant.remote_connect import (
    RemoteConnectionError,
    RemoteConnectSpec,
    RemoteProfileCatalog,
    _RemoteOutput,
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

    assert "CONDA_EXE=" in command
    assert "run --no-capture-output" in command
    assert "-n KNO python" in command
    assert "import research_assistant.cli_workbench" in command
    assert "create_app(root, plugins, ssh_mode=True)" in command
    assert "127.0.0.1" in command
    assert "34567" in command
    assert "ra_project.plugin" in command
    assert command.count("'/home/user/project with spaces'") == 1
    assert " . 34567" in command


def test_relative_workspace_is_resolved_only_once() -> None:
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="KNO-paper/",
        conda_env="KNO",
    )

    command = build_remote_ui_command(spec, 43892)

    assert command.count("KNO-paper/") == 1
    assert command.startswith("cd KNO-paper/")
    assert " . 43892" in command


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


def test_remote_output_hides_expected_startup_probe_refusals(capsys) -> None:
    output = _RemoteOutput(
        StringIO(
            "channel 2: open failed: connect failed: Connection refused\n"
            "actual remote diagnostic\n"
        )
    )

    output._pump()

    captured = capsys.readouterr()
    assert "Connection refused" not in captured.err
    assert "actual remote diagnostic" in captured.err
    assert output.tail() == "actual remote diagnostic"


def test_ui_extra_installs_uvicorn_websocket_transport() -> None:
    project_root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    ui_dependencies = configuration["project"]["optional-dependencies"]["ui"]

    assert any(dependency.startswith("uvicorn[standard]") for dependency in ui_dependencies)
