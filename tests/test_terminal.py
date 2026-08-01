from __future__ import annotations

import time
from pathlib import Path

import pytest

from research_assistant.terminal import TerminalError, TerminalSessionManager


def _wait_for_output(
    manager: TerminalSessionManager,
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
