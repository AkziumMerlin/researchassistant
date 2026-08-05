from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from research_assistant.desktop import desktop_environment, resolve_desktop_command
from research_assistant.desktop_server import create_desktop_app


def test_desktop_api_requires_session_token(tmp_path: Path) -> None:
    app = create_desktop_app(tmp_path, token="secret")
    client = TestClient(app)

    assert client.get("/api/desktop/health").status_code == 401
    response = client.get(
        "/api/desktop/health",
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["frontend"] == "theia-electron"
    assert payload["headless"] is True


def test_desktop_sidecar_does_not_serve_retired_browser_ui(tmp_path: Path) -> None:
    app = create_desktop_app(tmp_path, token="secret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    assert client.get("/", headers=headers).status_code == 404
    assert client.get("/assets/index.js", headers=headers).status_code == 404
    assert client.get("/api/bootstrap", headers=headers).status_code == 200


def test_desktop_environment_is_explicit_and_deduplicated(tmp_path: Path) -> None:
    environment = desktop_environment(
        tmp_path,
        plugins=["project.plugin", "project.plugin", "other.plugin"],
        environ={"PATH": "/bin"},
    )

    assert environment["RA_WORKSPACE"] == str(tmp_path.resolve())
    assert json.loads(environment["RA_PLUGINS"]) == ["project.plugin", "other.plugin"]
    assert environment["RA_PYTHON"]


def test_resolve_desktop_command_prefers_explicit_executable(tmp_path: Path) -> None:
    executable = tmp_path / "ResearchAssistant"
    executable.write_text("", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    command = resolve_desktop_command(
        workspace,
        executable=executable,
        environ={},
        package_root=tmp_path,
    )

    assert command.argv == (str(executable.resolve()), str(workspace.resolve()))
    assert command.development is False


def test_resolve_desktop_command_finds_electron_builder_linux_output(tmp_path: Path) -> None:
    executable = (
        tmp_path
        / "desktop"
        / "application"
        / "dist"
        / "linux-unpacked"
        / "research-assistant"
    )
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    command = resolve_desktop_command(workspace, environ={}, package_root=tmp_path)

    assert command.argv == (str(executable), str(workspace.resolve()))
    assert command.development is False


def test_desktop_api_exposes_bounded_binary_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"\x00\x01remote")
    app = create_desktop_app(tmp_path, token="secret", connection_mode="ssh")
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    listing = client.get("/api/desktop/files/readdir", headers=headers)
    assert listing.status_code == 200
    assert {entry["name"] for entry in listing.json()["entries"]} >= {"data.bin"}

    read = client.get(
        "/api/desktop/files/read",
        params={"path": "data.bin"},
        headers=headers,
    )
    assert read.status_code == 200
    assert read.json()["content_base64"] == "AAFyZW1vdGU="

    write = client.post(
        "/api/desktop/files/write",
        json={
            "path": "nested.txt",
            "content_base64": "dGhlaWE=",
            "create": True,
            "overwrite": True,
        },
        headers=headers,
    )
    assert write.status_code == 200
    assert (tmp_path / "nested.txt").read_text(encoding="utf-8") == "theia"

    escaped = client.get(
        "/api/desktop/files/stat",
        params={"path": "../outside"},
        headers=headers,
    )
    assert escaped.status_code == 400


def test_resolve_desktop_command_accepts_theia_workspace_file(tmp_path: Path) -> None:
    executable = tmp_path / "ResearchAssistant"
    executable.write_text("", encoding="utf-8")
    workspace = tmp_path / "remote.theia-workspace"
    workspace.write_text('{"folders": []}', encoding="utf-8")

    command = resolve_desktop_command(
        workspace,
        executable=executable,
        environ={},
        package_root=tmp_path,
    )

    assert command.argv[-1] == str(workspace.resolve())


def test_desktop_api_exposes_pollable_notebook_events(tmp_path: Path) -> None:
    app = create_desktop_app(tmp_path, token="secret")
    client = TestClient(app)
    response = client.get(
        "/api/notebooks/kernels/missing/events",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 400
    assert "kernel" in response.json()["detail"].lower()


def test_desktop_notebook_events_filter_one_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_desktop_app(tmp_path, token="secret")
    session = SimpleNamespace(
        lock=threading.RLock(),
        state="idle",
        recent_events=[
            {"type": "execution_complete", "cell_id": "cell-a", "parent_id": "old"},
            {"type": "stream", "cell_id": "cell-a", "parent_id": "new"},
            {"type": "execution_complete", "cell_id": "cell-a", "parent_id": "new"},
        ],
    )
    monkeypatch.setattr(app.state.notebook_kernels, "require", lambda _kernel_id: session)
    client = TestClient(app)

    response = client.get(
        "/api/notebooks/kernels/kernel/events",
        params={"cell_id": "cell-a", "parent_id": "new"},
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert [event["parent_id"] for event in response.json()["events"]] == ["new", "new"]
