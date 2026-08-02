from __future__ import annotations

import asyncio
import errno
import os
import pty
import select
import shlex
import shutil
import signal
import struct
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_assistant.artifacts import utc_now
from research_assistant.errors import ResearchAssistantError

try:
    import fcntl
    import termios
except ImportError as exc:  # pragma: no cover - ResearchAssistant targets POSIX hosts
    raise RuntimeError("interactive terminals require a POSIX operating system") from exc


class TerminalError(ResearchAssistantError):
    pass


def _enqueue(queue: asyncio.Queue[bytes | None], payload: bytes | None) -> None:
    try:
        queue.put_nowait(payload)
        return
    except asyncio.QueueFull:
        pass
    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:
        pass
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        pass


def _set_window_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _default_shell() -> str:
    configured = os.environ.get("SHELL")
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("bash") or shutil.which("zsh") or shutil.which("sh") or "/bin/sh"


def _shell_argv(value: str | None) -> list[str]:
    raw = value.strip() if value and value.strip() else _default_shell()
    argv = shlex.split(raw)
    if not argv:
        raise TerminalError("shell command must not be empty")
    executable = argv[0]
    if "/" not in executable:
        resolved = shutil.which(executable)
        if resolved is None:
            raise TerminalError(f"shell executable was not found: {executable}")
        argv[0] = resolved
    else:
        resolved_path = Path(executable).expanduser()
        if not resolved_path.is_file():
            raise TerminalError(f"shell executable was not found: {executable}")
        argv[0] = str(resolved_path)
    return argv


def _render_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(value) for value in argv)


Subscriber = tuple[asyncio.AbstractEventLoop, asyncio.Queue[bytes | None]]


@dataclass
class TerminalSession:
    session_id: str
    title: str
    cwd: Path
    shell_argv: list[str]
    process: subprocess.Popen[bytes]
    master_fd: int
    cols: int
    rows: int
    created_at: str
    max_buffer_bytes: int
    state: str = "running"
    exit_code: int | None = None
    closed_requested: bool = False
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
                "pid": self.process.pid,
                "cols": self.cols,
                "rows": self.rows,
                "created_at": self.created_at,
                "state": self.state,
                "exit_code": self.exit_code,
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

    def broadcast_exit(self) -> None:
        with self.lock:
            subscribers = list(self.subscribers.values())
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_enqueue, queue, None)
            except RuntimeError:
                continue


class TerminalSessionManager:
    def __init__(self, workspace: str | Path, *, max_buffer_bytes: int = 2_000_000) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.max_buffer_bytes = max_buffer_bytes
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.RLock()

    @property
    def default_shell(self) -> str:
        return _default_shell()

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
        argv = _shell_argv(shell)
        master_fd, slave_fd = pty.openpty()
        try:
            _set_window_size(slave_fd, rows, cols)
            environment = os.environ.copy()
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLORTERM": "truecolor",
                    "TERM_PROGRAM": "ResearchAssistant",
                    "PWD": str(resolved_cwd),
                }
            )
            process = subprocess.Popen(
                argv,
                cwd=resolved_cwd,
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        session_id = uuid.uuid4().hex[:12]
        session = TerminalSession(
            session_id=session_id,
            title=(title or Path(argv[0]).name or "Terminal").strip()[:120],
            cwd=resolved_cwd,
            shell_argv=argv,
            process=process,
            master_fd=master_fd,
            cols=cols,
            rows=rows,
            created_at=utc_now(),
            max_buffer_bytes=self.max_buffer_bytes,
        )
        reader = threading.Thread(
            target=self._reader_loop,
            args=(session,),
            name=f"ra-terminal-{session_id}",
            daemon=True,
        )
        session.reader = reader
        with self._lock:
            self._sessions[session_id] = session
        reader.start()
        return session.metadata()

    def _reader_loop(self, session: TerminalSession) -> None:
        try:
            while True:
                ready, _, _ = select.select([session.master_fd], [], [], 0.2)
                if ready:
                    try:
                        data = os.read(session.master_fd, 65536)
                    except OSError as exc:
                        if exc.errno in {errno.EIO, errno.EBADF}:
                            break
                        raise
                    if not data:
                        break
                    session.append_output(data)
                if session.process.poll() is not None and not ready:
                    break
        finally:
            return_code = session.process.poll()
            if return_code is None:
                try:
                    return_code = session.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    return_code = None
            with session.lock:
                session.exit_code = return_code
                session.state = "closed" if session.closed_requested else "exited"
            try:
                os.close(session.master_fd)
            except OSError:
                pass
            session.broadcast_exit()

    def require(self, session_id: str) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise TerminalError(f"unknown terminal session {session_id!r}")
        return session

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return sorted(
            (session.metadata() for session in sessions),
            key=lambda item: item["created_at"],
        )

    def write(self, session_id: str, data: bytes) -> None:
        if len(data) > 1_000_000:
            raise TerminalError("terminal input is too large")
        session = self.require(session_id)
        with session.lock:
            if session.state != "running":
                raise TerminalError("terminal session is not running")
            fd = session.master_fd
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
        with session.lock:
            if session.state != "running":
                return session.metadata()
            _set_window_size(session.master_fd, rows, cols)
            session.cols = cols
            session.rows = rows
            pid = session.process.pid
        try:
            os.killpg(pid, signal.SIGWINCH)
        except ProcessLookupError:
            pass
        return session.metadata()

    def subscribe(
        self,
        session_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, asyncio.Queue[bytes | None], bytes, dict[str, Any]]:
        session = self.require(session_id)
        token = uuid.uuid4().hex
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=512)
        with session.lock:
            replay = bytes(session.buffer)
            metadata = session.metadata()
            if session.state == "running":
                session.subscribers[token] = (loop, queue)
            else:
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

    def close(self, session_id: str) -> dict[str, Any]:
        session = self.require(session_id)
        with session.lock:
            session.closed_requested = True
            running = session.process.poll() is None
            pid = session.process.pid
        if running:
            try:
                os.killpg(pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                session.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    session.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    session.process.wait(timeout=2)
        if session.reader is not None:
            session.reader.join(timeout=2)
        return session.metadata()

    def remove(self, session_id: str) -> dict[str, Any]:
        metadata = self.close(session_id)
        with self._lock:
            self._sessions.pop(session_id, None)
        return metadata

    def shutdown(self) -> None:
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            try:
                self.close(session_id)
            except (OSError, TerminalError, subprocess.SubprocessError):
                continue
