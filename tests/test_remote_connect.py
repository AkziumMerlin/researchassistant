from __future__ import annotations

import json
import tomllib
from io import StringIO
from pathlib import Path

import pytest

from research_assistant.remote_connect import (
    RemoteConnectionError,
    RemoteConnectSpec,
    RemoteProfileCatalog,
    _RemoteOutput,
    build_remote_ui_command,
    build_ssh_argv,
    prepare_remote_desktop,
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


def test_remote_command_uses_conda_and_desktop_sidecar() -> None:
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/home/user/project with spaces",
        conda_env="KNO",
        plugins=("ra_project.plugin",),
    )

    command = build_remote_ui_command(spec, 34567, token="session-token")

    assert "CONDA_EXE=" in command
    assert "run --no-capture-output" in command
    assert "-n KNO python" in command
    assert "-m research_assistant.desktop_server" in command
    assert "--connection-mode ssh" in command
    assert "RA_DESKTOP_TOKEN" in command
    assert "session-token" not in command
    assert "--port 34567" in command
    assert "--plugin ra_project.plugin" in command
    assert command.count("'/home/user/project with spaces'") == 1


def test_relative_workspace_is_resolved_only_once() -> None:
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="KNO-paper/",
        conda_env="KNO",
    )

    command = build_remote_ui_command(spec, 43892)

    assert command.count("KNO-paper/") == 1
    assert "cd KNO-paper/ || exit $?" in command
    assert "--root ." in command
    assert "--port 43892" in command


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
        token="secret",
        ssh_executable="/usr/bin/ssh",
    )

    assert argv[0] == "/usr/bin/ssh"
    assert "127.0.0.1:40123:127.0.0.1:41234" in argv
    assert "ProxyJump=bastion" in argv
    assert argv[-4:] == ["gpu-server", "sh", "-lc", argv[-1]]
    assert '"$HOME"/miniconda3/envs/KNO/bin/python' in argv[-1]
    assert "secret" not in " ".join(argv)
    assert "RA_DESKTOP_TOKEN" in argv[-1]


def test_remote_desktop_prepares_native_workspace_and_ssh_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/srv/project",
        conda_env="KNO",
        plugins=("ra_project.plugin",),
        local_port=41000,
        ssh_options=("ProxyJump=bastion",),
    )

    prepared = prepare_remote_desktop(spec)
    document = json.loads(prepared.workspace_file.read_text(encoding="utf-8"))
    terminal = prepared.terminal_wrapper.read_text(encoding="utf-8")

    assert prepared.local_port == 41000
    assert document["folders"][0]["uri"] == f"ra-remote://{prepared.workspace_id}/"
    profile = document["settings"]["terminal.integrated.profiles.linux"]
    assert profile["ResearchAssistant SSH"]["path"] == str(prepared.terminal_wrapper)
    assert document["settings"]["terminal.integrated.defaultProfile.linux"] == (
        "ResearchAssistant SSH"
    )
    assert "ssh -tt" in terminal
    assert "ProxyJump=bastion" in terminal
    assert "tmux" in terminal
    assert "-n KNO" in terminal
    assert prepared.terminal_wrapper.stat().st_mode & 0o777 == 0o700
    assert prepared.descriptor["plugins"] == ["ra_project.plugin"]


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


def test_desktop_extra_installs_uvicorn_websocket_transport() -> None:
    project_root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    desktop_dependencies = configuration["project"]["optional-dependencies"]["desktop"]

    assert any(dependency.startswith("uvicorn[standard]") for dependency in desktop_dependencies)


def test_connect_remote_launches_local_desktop_with_private_forwarded_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_assistant.remote_connect as module

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    calls: dict[str, object] = {}

    class FakeTunnel:
        def __init__(self, spec, prepared) -> None:
            calls["spec"] = spec
            calls["prepared"] = prepared
            self.prepared = prepared
            self.endpoint = f"http://127.0.0.1:{prepared.local_port}"

        def start(self) -> None:
            calls["started"] = True

        def stop(self) -> None:
            calls["stopped"] = True

    def fake_launch(workspace, **kwargs) -> int:
        calls["workspace"] = workspace
        calls["launch"] = kwargs
        return 0

    monkeypatch.setattr(module, "RemoteDesktopTunnel", FakeTunnel)
    monkeypatch.setattr(module, "launch_desktop", fake_launch)

    spec = RemoteConnectSpec(
        target="gpu-server",
        workspace="/srv/project",
        conda_env="KNO",
        local_port=41001,
    )
    module.connect_remote(spec, development=True)

    assert calls["started"] is True
    assert calls["stopped"] is True
    launch = calls["launch"]
    assert isinstance(launch, dict)
    environment = launch["extra_environment"]
    assert environment["RA_REMOTE_ENDPOINT"] == "http://127.0.0.1:41001"
    assert environment["RA_REMOTE_TOKEN"]
    descriptor = json.loads(environment["RA_REMOTE_SPEC"])
    assert descriptor["target"] == "gpu-server"
    assert descriptor["workspace"] == "/srv/project"
    assert launch["development"] is True


def test_remote_tunnel_exposes_authenticated_fixed_local_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    import research_assistant.remote_connect as module

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    fake_ssh = tmp_path / "ssh"
    fake_ssh.write_text(
        """#!/usr/bin/env python3
import os
import sys

forward = sys.argv[sys.argv.index('-L') + 1]
local_port = forward.split(':')[1]
token = sys.stdin.readline().strip()
if not token:
    raise SystemExit('token missing')
os.environ['RA_DESKTOP_TOKEN'] = token
os.execv(
    sys.executable,
    [
        sys.executable,
        '-m',
        'research_assistant.desktop_server',
        '--root',
        os.environ['RA_FAKE_REMOTE_ROOT'],
        '--port',
        local_port,
        '--connection-mode',
        'ssh',
    ],
)
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    monkeypatch.setenv("RA_FAKE_REMOTE_ROOT", str(tmp_path))
    original_which = module.shutil.which
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: str(fake_ssh) if name == "ssh" else original_which(name),
    )

    spec = RemoteConnectSpec(
        target="fake-server",
        workspace=str(tmp_path),
        local_port=module.find_free_local_port(),
        reconnect=False,
        startup_timeout=20,
    )
    prepared = prepare_remote_desktop(spec)
    tunnel = module.RemoteDesktopTunnel(spec, prepared)
    tunnel.start()
    try:
        request = urllib.request.Request(
            f"{tunnel.endpoint}/api/desktop/health",
            headers={"Authorization": f"Bearer {prepared.token}"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["connection_mode"] == "ssh"
        assert health["workspace"] == str(tmp_path.resolve())
    finally:
        tunnel.stop()
