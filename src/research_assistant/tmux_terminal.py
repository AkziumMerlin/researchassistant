from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import pty
import select
import shlex
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_assistant.artifacts import utc_now
from research_assistant.terminal import (
    TerminalError,
    _enqueue,
    _render_argv,
    _set_window_size,
    _shell_argv,
)

Subscriber = tuple[asyncio.AbstractEventLoop, asyncio.Queue[bytes | None]]


@dataclass
class TmuxTerminalSession:
    session_id: str
    tmux_name: str
    title: str
    cwd: Path
    shell_argv: list[str]
    cols: int
    rows: int
    created_at: str
    max_buffer_bytes: int
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    master_fd: int | None = field(default=None, repr=False)
    pane_pid: int | None = None
    state: str = "running"
    exit_code: int | None = None
    closed_requested: bool = False
    detached_requested: bool = False
    buffer: bytearray = field(default_factory=bytearray, repr=False)
    subscribers: dict[str, Subscriber] = field(default_factory=dict, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    reader: threading.Thread | None = field(default=None, repr=False)

    def metadata(self) -> dict[str, Any]:
        with self.lock:
            return {
                "session_id": self.session_id,
                "title": self.title,
                "cwd": str(self.cwd),
                "shell": _render_argv(self.shell_argv),
                "pid": self.pane_pid,
                "cols": self.cols,
                "rows": self.rows,
                "created_at": self.created_at,
                "state": self.state,
                "exit_code": self.exit_code,
                "persistent": True,
                "backend": "tmux",
                "tmux_session": self.tmux_name,
            }

    def append_output(self, data: bytes) -> None:
        with self.lock:
            self.buffer.extend(data)
            overflow = len(self.buffer) - self.max_buffer_bytes
            if overflow > 0:
                del self.buffer[:overflow]
            subscribers = list(self.subscribers.values())
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_enqueue, queue, data)
            except RuntimeError:
                continue

    def broadcast_attachment_exit(self) -> None:
        with self.lock:
            subscribers = list(self.subscribers.values())
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_enqueue, queue, None)
            except RuntimeError:
                continue


class TmuxTerminalSessionManager:
    """Persistent terminal sessions owned by a workspace-scoped tmux server."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        tmux_executable: str,
        max_buffer_bytes: int = 2_000_000,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.tmux_executable = str(Path(tmux_executable).expanduser().resolve())
        self.max_buffer_bytes = max_buffer_bytes
        digest = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:16]
        self.server_label = f"ra-{digest}"
        self._sessions: dict[str, TmuxTerminalSession] = {}
        self._lock = threading.RLock()
        self._restore_sessions()

    @property
    def default_shell(self) -> str:
        configured = os.environ.get("SHELL")
        if configured and Path(configured).is_file():
            return configured
        for candidate in ("bash", "zsh", "sh"):
            resolved = shutil_which(candidate)
            if resolved:
                return resolved
        return "/bin/sh"

    @property
    def persistence_backend(self) -> str:
        return "tmux"

    @property
    def persistent(self) -> bool:
        return True

    def _tmux_argv(self, *arguments: str) -> list[str]:
        return [self.tmux_executable, "-L", self.server_label, *arguments]

    def _tmux(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            self._tmux_argv(*arguments),
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise TerminalError(detail or f"tmux command failed with code {completed.returncode}")
        return completed

    def _cwd(self, value: str | Path | None) -> Path:
        if value is None or str(value).strip() == "":
            result = self.workspace
        else:
            candidate = Path(value).expanduser()
            result = (
                candidate.resolve()
                if candidate.is_absolute()
                else (self.workspace / candidate).resolve()
            )
        if not result.is_dir():
            raise TerminalError(f"terminal working directory does not exist: {result}")
        return result

    def _session_names(self) -> list[str]:
        completed = self._tmux("list-sessions", "-F", "#{session_name}", check=False)
        if completed.returncode != 0:
            return []
        return [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip().startswith("term-")
        ]

    def _session_exists(self, tmux_name: str) -> bool:
        completed = self._tmux("has-session", "-t", tmux_name, check=False)
        return completed.returncode == 0

    def _show_option(self, tmux_name: str, option: str) -> str | None:
        completed = self._tmux(
            "show-options",
            "-qv",
            "-t",
            tmux_name,
            option,
            check=False,
        )
        if completed.returncode != 0:
            return None
        value = completed.stdout.rstrip("\n")
        return value or None

    def _pane_snapshot(self, tmux_name: str) -> dict[str, Any]:
        completed = self._tmux(
            "list-panes",
            "-t",
            f"{tmux_name}:0.0",
            "-F",
            "#{pane_dead}\t#{pane_pid}\t#{pane_current_path}\t#{pane_dead_status}",
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {"dead": True, "pid": None, "cwd": None, "exit_code": None}
        values = completed.stdout.splitlines()[0].split("\t", 3)
        while len(values) < 4:
            values.append("")
        return {
            "dead": values[0] == "1",
            "pid": int(values[1]) if values[1].isdigit() else None,
            "cwd": values[2] or None,
            "exit_code": int(values[3]) if values[3].lstrip("-").isdigit() else None,
        }

    def _window_size(self, tmux_name: str) -> tuple[int, int]:
        completed = self._tmux(
            "display-message",
            "-p",
            "-t",
            tmux_name,
            "#{window_width}\t#{window_height}",
            check=False,
        )
        if completed.returncode == 0:
            values = completed.stdout.strip().split("\t", 1)
            if len(values) == 2 and values[0].isdigit() and values[1].isdigit():
                return int(values[0]), int(values[1])
        return 100, 30

    def _capture_history(self, tmux_name: str) -> bytes:
        completed = subprocess.run(
            self._tmux_argv(
                "capture-pane",
                "-p",
                "-e",
                "-S",
                "-10000",
                "-t",
                f"{tmux_name}:0.0",
            ),
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return b""
        return completed.stdout[-self.max_buffer_bytes :]

    def _restore_one(self, tmux_name: str) -> TmuxTerminalSession:
        session_id = self._show_option(tmux_name, "@ra-id") or tmux_name.removeprefix("term-")
        title = self._show_option(tmux_name, "@ra-title") or "Terminal"
        cwd_value = self._show_option(tmux_name, "@ra-cwd") or str(self.workspace)
        shell_json = self._show_option(tmux_name, "@ra-shell-json")
        created_at = self._show_option(tmux_name, "@ra-created-at") or utc_now()
        try:
            shell_argv = json.loads(shell_json) if shell_json else [self.default_shell]
        except (TypeError, ValueError):
            shell_argv = [self.default_shell]
        if not isinstance(shell_argv, list) or not all(
            isinstance(value, str) for value in shell_argv
        ):
            shell_argv = [self.default_shell]
        cols, rows = self._window_size(tmux_name)
        pane = self._pane_snapshot(tmux_name)
        cwd = Path(str(pane.get("cwd") or cwd_value)).expanduser().resolve()
        session = TmuxTerminalSession(
            session_id=session_id,
            tmux_name=tmux_name,
            title=title,
            cwd=cwd,
            shell_argv=list(shell_argv),
            cols=cols,
            rows=rows,
            created_at=created_at,
            max_buffer_bytes=self.max_buffer_bytes,
            pane_pid=pane["pid"],
            state="exited" if pane["dead"] else "running",
            exit_code=pane["exit_code"],
        )
        session.buffer.extend(self._capture_history(tmux_name))
        self._start_attachment(session)
        return session

    def _restore_sessions(self) -> None:
        for tmux_name in self._session_names():
            try:
                session = self._restore_one(tmux_name)
            except (OSError, TerminalError, subprocess.SubprocessError, ValueError):
                continue
            self._sessions[session.session_id] = session

    def _discover_sessions(self) -> None:
        names = set(self._session_names())
        with self._lock:
            known_names = {session.tmux_name for session in self._sessions.values()}
            missing = names - known_names
            stale_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if session.tmux_name not in names and session.closed_requested
            ]
            for session_id in stale_ids:
                self._sessions.pop(session_id, None)
        for tmux_name in sorted(missing):
            try:
                session = self._restore_one(tmux_name)
            except (OSError, TerminalError, subprocess.SubprocessError, ValueError):
                continue
            with self._lock:
                self._sessions[session.session_id] = session

    def _update_tmux_environment(self) -> None:
        for name in (
            "PATH",
            "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV",
            "LD_LIBRARY_PATH",
            "PYTHONPATH",
            "CUDA_VISIBLE_DEVICES",
        ):
            value = os.environ.get(name)
            if value is None:
                continue
            self._tmux("set-environment", "-g", name, value, check=False)

    def create(
        self,
        *,
        cwd: str | Path | None = None,
        shell: str | None = None,
        title: str | None = None,
        cols: int = 100,
        rows: int = 30,
    ) -> dict[str, Any]:
        if not 2 <= cols <= 500 or not 2 <= rows <= 300:
            raise TerminalError("terminal dimensions are outside the supported range")
        resolved_cwd = self._cwd(cwd)
        shell_argv = _shell_argv(shell)
        session_id = uuid.uuid4().hex[:12]
        tmux_name = f"term-{session_id}"
        resolved_title = (title or Path(shell_argv[0]).name or "Terminal").strip()[:120]
        created_at = utc_now()
        command = shlex.join(shell_argv)

        self._tmux(
            "new-session",
            "-d",
            "-s",
            tmux_name,
            "-c",
            str(resolved_cwd),
            "-x",
            str(cols),
            "-y",
            str(rows),
            command,
        )
        self._update_tmux_environment()
        options = {
            "@ra-id": session_id,
            "@ra-title": resolved_title,
            "@ra-cwd": str(resolved_cwd),
            "@ra-shell-json": json.dumps(shell_argv, ensure_ascii=False),
            "@ra-created-at": created_at,
        }
        for option, value in options.items():
            self._tmux("set-option", "-t", tmux_name, option, value)
        self._tmux("set-option", "-t", tmux_name, "status", "off", check=False)
        self._tmux(
            "set-option",
            "-p",
            "-t",
            f"{tmux_name}:0.0",
            "remain-on-exit",
            "on",
            check=False,
        )
        self._tmux(
            "set-option",
            "-w",
            "-t",
            f"{tmux_name}:0",
            "history-limit",
            "100000",
            check=False,
        )
        pane = self._pane_snapshot(tmux_name)
        session = TmuxTerminalSession(
            session_id=session_id,
            tmux_name=tmux_name,
            title=resolved_title,
            cwd=resolved_cwd,
            shell_argv=shell_argv,
            cols=cols,
            rows=rows,
            created_at=created_at,
            max_buffer_bytes=self.max_buffer_bytes,
            pane_pid=pane["pid"],
            state="exited" if pane["dead"] else "running",
            exit_code=pane["exit_code"],
        )
        with self._lock:
            self._sessions[session_id] = session
        self._start_attachment(session)
        return session.metadata()

    def _start_attachment(self, session: TmuxTerminalSession) -> None:
        with session.lock:
            if session.process is not None and session.process.poll() is None:
                return
            if not self._session_exists(session.tmux_name):
                session.state = "exited"
                return
            master_fd, slave_fd = pty.openpty()
            _set_window_size(slave_fd, session.rows, session.cols)
            environment = os.environ.copy()
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLORTERM": "truecolor",
                    "TERM_PROGRAM": "ResearchAssistant",
                }
            )
            try:
                process = subprocess.Popen(
                    self._tmux_argv("attach-session", "-t", session.tmux_name),
                    cwd=session.cwd,
                    env=environment,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    start_new_session=True,
                    close_fds=True,
                )
            except Exception:
                os.close(master_fd)
                raise
            finally:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass
            session.process = process
            session.master_fd = master_fd
            session.detached_requested = False
            pane = self._pane_snapshot(session.tmux_name)
            session.pane_pid = pane["pid"]
            session.state = "exited" if pane["dead"] else "running"
            session.exit_code = pane["exit_code"]
            reader = threading.Thread(
                target=self._reader_loop,
                args=(session, process, master_fd),
                name=f"ra-tmux-terminal-{session.session_id}",
                daemon=True,
            )
            session.reader = reader
        reader.start()

    def _reader_loop(
        self,
        session: TmuxTerminalSession,
        process: subprocess.Popen[bytes],
        master_fd: int,
    ) -> None:
        try:
            while True:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if ready:
                    try:
                        data = os.read(master_fd, 65536)
                    except OSError as exc:
                        if exc.errno in {errno.EIO, errno.EBADF}:
                            break
                        raise
                    if not data:
                        break
                    session.append_output(data)
                if process.poll() is not None and not ready:
                    break
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            pane = self._pane_snapshot(session.tmux_name)
            with session.lock:
                if session.process is process:
                    session.process = None
                    session.master_fd = None
                session.pane_pid = pane["pid"]
                session.exit_code = pane["exit_code"]
                if session.closed_requested:
                    session.state = "closed"
                elif pane["dead"]:
                    session.state = "exited"
                else:
                    session.state = "running"
                detached = session.detached_requested
            if not detached:
                session.broadcast_attachment_exit()

    def _ensure_attachment(self, session: TmuxTerminalSession) -> None:
        with session.lock:
            process = session.process
        if process is None or process.poll() is not None:
            self._start_attachment(session)

    def require(self, session_id: str) -> TmuxTerminalSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            self._discover_sessions()
            with self._lock:
                session = self._sessions.get(session_id)
        if session is None:
            raise TerminalError(f"unknown terminal session {session_id!r}")
        return session

    def _refresh(self, session: TmuxTerminalSession) -> None:
        if not self._session_exists(session.tmux_name):
            with session.lock:
                session.state = "closed" if session.closed_requested else "exited"
                session.pane_pid = None
            return
        pane = self._pane_snapshot(session.tmux_name)
        cols, rows = self._window_size(session.tmux_name)
        with session.lock:
            session.pane_pid = pane["pid"]
            session.cwd = Path(str(pane.get("cwd") or session.cwd)).expanduser().resolve()
            session.exit_code = pane["exit_code"]
            session.state = "exited" if pane["dead"] else "running"
            session.cols = cols
            session.rows = rows

    def list(self) -> list[dict[str, Any]]:
        self._discover_sessions()
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            self._refresh(session)
        return sorted(
            (session.metadata() for session in sessions),
            key=lambda item: item["created_at"],
        )

    def write(self, session_id: str, data: bytes) -> None:
        if len(data) > 1_000_000:
            raise TerminalError("terminal input is too large")
        session = self.require(session_id)
        self._refresh(session)
        if session.state != "running":
            raise TerminalError("terminal session is not running")
        self._ensure_attachment(session)
        with session.lock:
            fd = session.master_fd
        if fd is None:
            raise TerminalError("terminal attachment is unavailable")
        view = memoryview(data)
        while view:
            try:
                written = os.write(fd, view)
            except OSError as exc:
                raise TerminalError(f"cannot write to terminal: {exc}") from exc
            view = view[written:]

    def resize(self, session_id: str, *, cols: int, rows: int) -> dict[str, Any]:
        if not 2 <= cols <= 500 or not 2 <= rows <= 300:
            raise TerminalError("terminal dimensions are outside the supported range")
        session = self.require(session_id)
        self._ensure_attachment(session)
        with session.lock:
            fd = session.master_fd
            process = session.process
            session.cols = cols
            session.rows = rows
        if fd is not None:
            _set_window_size(fd, rows, cols)
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass
        self._tmux(
            "resize-window",
            "-t",
            session.tmux_name,
            "-x",
            str(cols),
            "-y",
            str(rows),
            check=False,
        )
        return session.metadata()

    def subscribe(
        self,
        session_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, asyncio.Queue[bytes | None], bytes, dict[str, Any]]:
        session = self.require(session_id)
        self._refresh(session)
        self._ensure_attachment(session)
        token = uuid.uuid4().hex
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=512)
        with session.lock:
            replay = bytes(session.buffer)
            metadata = session.metadata()
            session.subscribers[token] = (loop, queue)
            if session.state != "running":
                queue.put_nowait(None)
        return token, queue, replay, metadata

    def unsubscribe(self, session_id: str, token: str) -> None:
        try:
            session = self.require(session_id)
        except TerminalError:
            return
        with session.lock:
            session.subscribers.pop(token, None)

    def buffer(self, session_id: str) -> bytes:
        session = self.require(session_id)
        with session.lock:
            return bytes(session.buffer)

    def _detach_attachment(self, session: TmuxTerminalSession) -> None:
        with session.lock:
            session.detached_requested = True
            process = session.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        reader = session.reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)

    def close(self, session_id: str) -> dict[str, Any]:
        session = self.require(session_id)
        with session.lock:
            session.closed_requested = True
        self._tmux("kill-session", "-t", session.tmux_name, check=False)
        self._detach_attachment(session)
        with session.lock:
            session.state = "closed"
            session.pane_pid = None
        return session.metadata()

    def remove(self, session_id: str) -> dict[str, Any]:
        metadata = self.close(session_id)
        with self._lock:
            self._sessions.pop(session_id, None)
        return metadata

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            try:
                self._detach_attachment(session)
            except (OSError, TerminalError, subprocess.SubprocessError):
                continue


def shutil_which(command: str) -> str | None:
    from shutil import which

    return which(command)
