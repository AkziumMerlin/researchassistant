from __future__ import annotations

import json
from pathlib import Path

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
    assert response.json()["workspace"] == str(tmp_path.resolve())


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
