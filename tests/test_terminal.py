from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from research_assistant.terminal import TerminalError, TerminalSessionManager
from research_assistant.tmux_terminal import TmuxTerminalSessionManager
from research_assistant.ui.server import create_app


def _wait_for_output(
    manager,
    session_id: str,
    needle: bytes,
    timeout: float = 5.0,
) -> bytes:
    deadline = time.monotonic() + timeout
    output = b""
    while time.monotonic() < deadline:
        output = manager.buffer(session_id)
        if needle in output:
            return output
        time.sleep(0.05)
    raise AssertionError(f"terminal output did not contain {needle!r}: {output!r}")


def test_terminal_session_accepts_input_and_resizes(tmp_path: Path) -> None:
    manager = TerminalSessionManager(tmp_path)
    session = manager.create(shell="/bin/sh", cols=80, rows=24)
    session_id = session["session_id"]

    try:
        manager.write(session_id, b"printf 'ra-terminal-ok\\n'\n")
        output = _wait_for_output(manager, session_id, b"ra-terminal-ok")
        assert b"ra-terminal-ok" in output

        resized = manager.resize(session_id, cols=132, rows=41)
        assert resized["cols"] == 132
        assert resized["rows"] == 41
        assert resized["state"] == "running"
    finally:
        closed = manager.remove(session_id)

    assert closed["state"] == "closed"
    assert manager.list() == []


def test_terminal_uses_workspace_as_default_cwd(tmp_path: Path) -> None:
    manager = TerminalSessionManager(tmp_path)
    session = manager.create(shell="/bin/sh")
    try:
        assert session["cwd"] == str(tmp_path.resolve())
    finally:
        manager.shutdown()


def test_terminal_rejects_missing_shell(tmp_path: Path) -> None:
    manager = TerminalSessionManager(tmp_path)
    with pytest.raises(TerminalError, match="was not found"):
        manager.create(shell="/definitely/missing/ra-shell")


def test_tmux_terminal_survives_manager_restart(tmp_path: Path) -> None:
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is not installed")

    nested = tmp_path / "nested"
    nested.mkdir()
    first = TmuxTerminalSessionManager(tmp_path, tmux_executable=tmux)
    session = first.create(shell="/bin/sh", cols=90, rows=26)
    session_id = session["session_id"]
    second = None

    try:
        first.write(
            session_id,
            b"export RA_PERSISTED=alive; cd nested; printf 'before-restart\\n'\n",
        )
        _wait_for_output(first, session_id, b"before-restart")
        first.shutdown()

        second = TmuxTerminalSessionManager(tmp_path, tmux_executable=tmux)
        restored = {item["session_id"]: item for item in second.list()}
        assert session_id in restored
        assert restored[session_id]["persistent"] is True
        assert restored[session_id]["backend"] == "tmux"

        second.write(
            session_id,
            b"printf 'after-restart:%s:%s\\n' \"$RA_PERSISTED\" \"$PWD\"\n",
        )
        output = _wait_for_output(second, session_id, b"after-restart:alive:")
        assert str(nested).encode() in output
    finally:
        if second is not None:
            try:
                second.remove(session_id)
            except TerminalError:
                second.shutdown()
        else:
            try:
                first.remove(session_id)
            except TerminalError:
                first.shutdown()


def test_terminal_ui_rest_and_websocket_round_trip(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    assert hasattr(app.state, "terminal_manager")
    assert any(getattr(route, "path", None) == "/api/terminals" for route in app.routes)

    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "/api/extensions/" not in index.text
        assert "connect-src 'self' ws: wss:" in index.headers["content-security-policy"]

        terminal_catalog = client.get("/api/terminals")
        assert terminal_catalog.status_code == 200
        if shutil.which("tmux") is not None:
            assert terminal_catalog.json()["persistent"] is True
            assert terminal_catalog.json()["backend"] == "tmux"

        created = client.post(
            "/api/terminals",
            json={"shell": "/bin/sh", "cols": 80, "rows": 24},
        )
        assert created.status_code == 200
        session = created.json()
        session_id = session["session_id"]

        output = bytearray()
        with client.websocket_connect(f"/api/terminals/{session_id}/ws") as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["session"]["session_id"] == session_id
            websocket.send_text(
                json.dumps({"type": "input", "data": "printf 'ra-ws-ok\\n'\n"})
            )
            deadline = time.monotonic() + 5
            while b"ra-ws-ok" not in output and time.monotonic() < deadline:
                message = websocket.receive()
                if message.get("bytes"):
                    output.extend(message["bytes"])
            assert b"ra-ws-ok" in output
            websocket.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 36}))
            time.sleep(0.05)

        sessions = client.get("/api/terminals").json()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        assert current["cols"] == 120
        assert current["rows"] == 36

        closed = client.delete(f"/api/terminals/{session_id}")
        assert closed.status_code == 200
        assert closed.json()["state"] == "closed"
