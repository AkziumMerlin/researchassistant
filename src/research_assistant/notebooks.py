from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nbformat
from jupyter_client import BlockingKernelClient
from jupyter_client.connect import write_connection_file
from jupyter_client.kernelspec import KernelSpecManager

from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError
from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

MAX_NOTEBOOK_BYTES = 64 * 1024 * 1024
Subscriber = tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any] | None]]


class NotebookError(ResearchAssistantError):
    pass


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _enqueue(
    target: asyncio.Queue[dict[str, Any] | None],
    payload: dict[str, Any] | None,
) -> None:
    try:
        target.put_nowait(payload)
        return
    except asyncio.QueueFull:
        pass
    try:
        target.get_nowait()
    except asyncio.QueueEmpty:
        pass
    try:
        target.put_nowait(payload)
    except asyncio.QueueFull:
        pass


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


class NotebookStore:
    def __init__(self, workspace: Workspace, *, max_bytes: int = MAX_NOTEBOOK_BYTES) -> None:
        self.workspace = workspace
        self.max_bytes = max_bytes

    def _path(self, relative_path: str) -> Path:
        if not relative_path.lower().endswith(".ipynb"):
            raise NotebookError("notebook paths must end with .ipynb")
        return self.workspace.resolve(relative_path)

    def read(self, relative_path: str) -> dict[str, Any]:
        path = self._path(relative_path)
        if not path.is_file() or path.is_symlink():
            raise NotebookError(f"notebook does not exist: {relative_path}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise NotebookError(f"cannot read notebook {relative_path}: {exc}") from exc
        if len(data) > self.max_bytes:
            raise NotebookError(
                f"notebook is too large ({len(data)} bytes; limit {self.max_bytes})"
            )
        try:
            notebook = nbformat.reads(data.decode("utf-8"), as_version=4)
        except (UnicodeDecodeError, nbformat.reader.NotJSONError, ValueError) as exc:
            raise NotebookError(f"invalid notebook {relative_path}: {exc}") from exc
        self._ensure_cell_ids(notebook)
        return {
            "path": relative_path,
            "revision": _revision(data),
            "size": len(data),
            "notebook": json.loads(nbformat.writes(notebook, version=4)),
        }

    def create(self, relative_path: str, *, kernel_name: str = "python3") -> dict[str, Any]:
        notebook = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("")],
            metadata={
                "kernelspec": {
                    "name": kernel_name,
                    "display_name": kernel_name,
                    "language": "python",
                }
            },
        )
        self._ensure_cell_ids(notebook)
        return self.write(relative_path, notebook, expected_revision=None)

    def write(
        self,
        relative_path: str,
        notebook_value: Any,
        *,
        expected_revision: str | None,
    ) -> dict[str, Any]:
        path = self._path(relative_path)
        if not path.parent.is_dir():
            parent = path.parent.relative_to(self.workspace.root).as_posix()
            raise NotebookError(f"parent directory does not exist: {parent}")
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise NotebookError(f"path is not a regular file: {relative_path}")
        try:
            notebook = nbformat.from_dict(notebook_value)
            self._ensure_cell_ids(notebook)
            nbformat.validate(notebook)
            text = nbformat.writes(notebook, version=4) + "\n"
            data = text.encode("utf-8")
        except (AttributeError, TypeError, ValueError, nbformat.ValidationError) as exc:
            raise NotebookError(f"invalid notebook document: {exc}") from exc
        if len(data) > self.max_bytes:
            raise NotebookError(
                f"notebook is too large ({len(data)} bytes; limit {self.max_bytes})"
            )

        current_data: bytes | None = None
        if path.exists():
            try:
                current_data = path.read_bytes()
            except OSError as exc:
                raise NotebookError(f"cannot inspect {relative_path}: {exc}") from exc
        current_revision = _revision(current_data) if current_data is not None else None
        if current_revision != expected_revision:
            if current_revision is None:
                detail = "the notebook was removed outside the UI"
            elif expected_revision is None:
                detail = "the notebook already exists"
            else:
                detail = "the notebook changed outside the UI"
            raise WorkspaceConflict(
                f"cannot save {relative_path}: {detail}; reload before saving"
            )

        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_name, mode)
            os.replace(temporary_name, path)
        except OSError as exc:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            raise NotebookError(f"cannot save notebook {relative_path}: {exc}") from exc

        return {
            "path": relative_path,
            "revision": _revision(data),
            "size": len(data),
            "notebook": json.loads(nbformat.writes(notebook, version=4)),
        }

    @staticmethod
    def _ensure_cell_ids(notebook: Any) -> None:
        for cell in notebook.get("cells", []):
            if not cell.get("id"):
                cell["id"] = uuid.uuid4().hex[:12]


@dataclass
class NotebookKernelSession:
    kernel_id: str
    notebook_path: str
    kernel_name: str
    display_name: str
    language: str
    pid: int
    connection_file: Path
    created_at: str
    log_path: Path
    client: BlockingKernelClient | None = field(default=None, repr=False)
    state: str = "starting"
    execution_count: int | None = None
    executions: dict[str, str] = field(default_factory=dict, repr=False)
    subscribers: dict[str, Subscriber] = field(default_factory=dict, repr=False)
    recent_events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=2000),
        repr=False,
    )
    listener: threading.Thread | None = field(default=None, repr=False)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def metadata(self) -> dict[str, Any]:
        with self.lock:
            return {
                "kernel_id": self.kernel_id,
                "notebook_path": self.notebook_path,
                "kernel_name": self.kernel_name,
                "display_name": self.display_name,
                "language": self.language,
                "pid": self.pid,
                "created_at": self.created_at,
                "state": self.state,
                "execution_count": self.execution_count,
                "persistent": True,
            }

    def broadcast(self, event: dict[str, Any]) -> None:
        safe = _json_safe(event)
        with self.lock:
            self.recent_events.append(safe)
            subscribers = list(self.subscribers.values())
        for loop, target in subscribers:
            try:
                loop.call_soon_threadsafe(_enqueue, target, safe)
            except RuntimeError:
                continue


class NotebookKernelManager:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.root = workspace.root / ".ra" / "notebook-kernels"
        self.root.mkdir(parents=True, exist_ok=True)
        self.specs = KernelSpecManager()
        self._sessions: dict[str, NotebookKernelSession] = {}
        self._lock = threading.RLock()
        self._restore()

    def available_kernels(self) -> list[dict[str, Any]]:
        result = []
        for name, record in sorted(self.specs.get_all_specs().items()):
            spec = record.get("spec") if isinstance(record, dict) else None
            if not isinstance(spec, dict):
                continue
            result.append(
                {
                    "name": name,
                    "display_name": str(spec.get("display_name") or name),
                    "language": str(spec.get("language") or ""),
                    "metadata": _json_safe(spec.get("metadata") or {}),
                }
            )
        return result

    def list(self) -> list[dict[str, Any]]:
        self._prune_dead()
        with self._lock:
            sessions = list(self._sessions.values())
        return sorted((session.metadata() for session in sessions), key=lambda item: item["created_at"])

    def require(self, kernel_id: str) -> NotebookKernelSession:
        with self._lock:
            session = self._sessions.get(kernel_id)
        if session is None:
            raise NotebookError(f"unknown notebook kernel {kernel_id!r}")
        if not _pid_alive(session.pid):
            with session.lock:
                session.state = "dead"
            raise NotebookError(f"notebook kernel {kernel_id!r} is no longer running")
        return session

    def start(
        self,
        notebook_path: str,
        *,
        kernel_name: str | None = None,
        reuse: bool = True,
    ) -> dict[str, Any]:
        self.workspace.resolve(notebook_path)
        requested = kernel_name or "python3"
        if reuse:
            for item in self.list():
                if (
                    item["notebook_path"] == notebook_path
                    and item["kernel_name"] == requested
                    and item["state"] != "dead"
                ):
                    return item
        kernel_id = uuid.uuid4().hex[:12]
        session = self._launch(kernel_id, notebook_path, requested)
        with self._lock:
            self._sessions[kernel_id] = session
        return session.metadata()

    def _launch(
        self,
        kernel_id: str,
        notebook_path: str,
        kernel_name: str,
    ) -> NotebookKernelSession:
        try:
            spec = self.specs.get_kernel_spec(kernel_name)
        except Exception as exc:
            raise NotebookError(f"kernel spec was not found: {kernel_name}") from exc

        session_root = self.root / kernel_id
        session_root.mkdir(parents=True, exist_ok=True)
        connection_file = session_root / "connection.json"
        result = write_connection_file(fname=str(connection_file), ip="127.0.0.1")
        if isinstance(result, tuple):
            connection_file = Path(result[0])
        replacements = {
            "connection_file": str(connection_file),
            "resource_dir": str(spec.resource_dir or ""),
            "prefix": sys.prefix,
        }

        def expand(value: str) -> str:
            rendered = value
            for key, replacement in replacements.items():
                rendered = rendered.replace("{" + key + "}", replacement)
            return rendered

        argv = [expand(str(value)) for value in spec.argv]
        environment = os.environ.copy()
        environment.update({str(key): expand(str(value)) for key, value in spec.env.items()})
        environment.update(
            {
                "RA_NOTEBOOK_KERNEL": kernel_id,
                "RA_WORKSPACE": str(self.workspace.root),
            }
        )
        log_path = session_root / "kernel.log"
        log_handle = log_path.open("ab", buffering=0)
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.workspace.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            log_handle.close()
            shutil.rmtree(session_root, ignore_errors=True)
            raise
        finally:
            log_handle.close()

        session = NotebookKernelSession(
            kernel_id=kernel_id,
            notebook_path=notebook_path,
            kernel_name=kernel_name,
            display_name=str(spec.display_name or kernel_name),
            language=str(spec.language or ""),
            pid=process.pid,
            connection_file=connection_file,
            created_at=utc_now(),
            log_path=log_path,
        )
        self._write_state(session)
        try:
            self._connect(session, wait=True)
        except Exception as exc:
            self._terminate_pid(process.pid)
            shutil.rmtree(session_root, ignore_errors=True)
            raise NotebookError(
                f"kernel {kernel_name!r} did not become ready; see {log_path}: {exc}"
            ) from exc
        return session

    def _connect(self, session: NotebookKernelSession, *, wait: bool) -> None:
        client = BlockingKernelClient(connection_file=str(session.connection_file))
        client.load_connection_file()
        client.start_channels()
        if wait:
            client.wait_for_ready(timeout=20)
        session.client = client
        session.state = "idle"
        session.stop_event.clear()
        listener = threading.Thread(
            target=self._listen,
            args=(session,),
            name=f"ra-notebook-{session.kernel_id}",
            daemon=True,
        )
        session.listener = listener
        listener.start()
        self._write_state(session)

    def _listen(self, session: NotebookKernelSession) -> None:
        while not session.stop_event.is_set() and _pid_alive(session.pid):
            client = session.client
            if client is None:
                break
            received = False
            try:
                message = client.get_iopub_msg(timeout=0.1)
                received = True
                self._handle_message(session, message)
            except queue.Empty:
                pass
            except Exception as exc:
                session.broadcast({"type": "transport_error", "detail": str(exc)})
                break
            try:
                message = client.get_shell_msg(timeout=0.01)
                received = True
                self._handle_message(session, message)
            except queue.Empty:
                pass
            except Exception as exc:
                session.broadcast({"type": "transport_error", "detail": str(exc)})
                break
            if not received:
                time.sleep(0.01)
        if not _pid_alive(session.pid):
            with session.lock:
                session.state = "dead"
            session.broadcast({"type": "kernel_dead", "kernel": session.metadata()})
            self._write_state(session)

    def _handle_message(
        self,
        session: NotebookKernelSession,
        message: dict[str, Any],
    ) -> None:
        header = message.get("header") or {}
        parent = message.get("parent_header") or {}
        content = message.get("content") or {}
        message_type = str(header.get("msg_type") or message.get("msg_type") or "message")
        parent_id = str(parent.get("msg_id") or "")
        with session.lock:
            cell_id = session.executions.get(parent_id)

        if message_type == "status":
            execution_state = str(content.get("execution_state") or "unknown")
            with session.lock:
                session.state = execution_state
            session.broadcast(
                {
                    "type": "status",
                    "state": execution_state,
                    "cell_id": cell_id,
                    "parent_id": parent_id or None,
                }
            )
            if execution_state == "idle" and parent_id:
                with session.lock:
                    finished_cell = session.executions.pop(parent_id, cell_id)
                session.broadcast(
                    {
                        "type": "execution_complete",
                        "cell_id": finished_cell,
                        "parent_id": parent_id,
                    }
                )
            return

        event: dict[str, Any] = {
            "type": message_type,
            "cell_id": cell_id,
            "parent_id": parent_id or None,
            "content": _json_safe(content),
        }
        if message_type in {"execute_input", "execute_result", "execute_reply"}:
            execution_count = content.get("execution_count")
            if isinstance(execution_count, int):
                with session.lock:
                    session.execution_count = execution_count
                event["execution_count"] = execution_count
        session.broadcast(event)

    def execute(
        self,
        kernel_id: str,
        *,
        cell_id: str,
        code: str,
        store_history: bool = True,
    ) -> dict[str, Any]:
        if len(code.encode("utf-8")) > 4 * 1024 * 1024:
            raise NotebookError("notebook cell source is too large")
        session = self.require(kernel_id)
        client = session.client
        if client is None:
            raise NotebookError("kernel client is not connected")
        message_id = client.execute(
            code,
            silent=False,
            store_history=store_history,
            allow_stdin=False,
            stop_on_error=True,
        )
        with session.lock:
            session.executions[message_id] = cell_id
            session.state = "busy"
        session.broadcast(
            {
                "type": "execution_started",
                "cell_id": cell_id,
                "parent_id": message_id,
            }
        )
        return {"message_id": message_id, "cell_id": cell_id}

    def interrupt(self, kernel_id: str) -> dict[str, Any]:
        session = self.require(kernel_id)
        try:
            os.killpg(session.pid, signal.SIGINT)
        except ProcessLookupError as exc:
            raise NotebookError("kernel process no longer exists") from exc
        return session.metadata()

    def restart(self, kernel_id: str) -> dict[str, Any]:
        session = self.require(kernel_id)
        notebook_path = session.notebook_path
        kernel_name = session.kernel_name
        self.shutdown(kernel_id, remove_record=True)
        replacement = self._launch(kernel_id, notebook_path, kernel_name)
        with self._lock:
            self._sessions[kernel_id] = replacement
        return replacement.metadata()

    def shutdown(self, kernel_id: str, *, remove_record: bool = True) -> dict[str, Any]:
        session = self.require(kernel_id)
        metadata = session.metadata()
        client = session.client
        if client is not None:
            try:
                client.shutdown(restart=False)
            except Exception:
                pass
        deadline = time.monotonic() + 3
        while _pid_alive(session.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if _pid_alive(session.pid):
            self._terminate_pid(session.pid)
        self._detach_session(session)
        with session.lock:
            session.state = "dead"
        with self._lock:
            self._sessions.pop(kernel_id, None)
        if remove_record:
            shutil.rmtree(self.root / kernel_id, ignore_errors=True)
        return {**metadata, "state": "dead"}

    def subscribe(
        self,
        kernel_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, asyncio.Queue[dict[str, Any] | None], list[dict[str, Any]]]:
        session = self.require(kernel_id)
        token = uuid.uuid4().hex
        target: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1024)
        with session.lock:
            session.subscribers[token] = (loop, target)
            replay = list(session.recent_events)
        return token, target, replay

    def unsubscribe(self, kernel_id: str, token: str) -> None:
        with self._lock:
            session = self._sessions.get(kernel_id)
        if session is None:
            return
        with session.lock:
            session.subscribers.pop(token, None)

    def detach(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            self._detach_session(session)

    def _detach_session(self, session: NotebookKernelSession) -> None:
        session.stop_event.set()
        if session.listener is not None:
            session.listener.join(timeout=1)
        client = session.client
        session.client = None
        if client is not None:
            try:
                client.stop_channels()
            except Exception:
                pass
        with session.lock:
            session.subscribers.clear()

    def _restore(self) -> None:
        for state_path in sorted(self.root.glob("*/state.json")):
            try:
                value = json.loads(state_path.read_text(encoding="utf-8"))
                pid = int(value["pid"])
                connection_file = Path(value["connection_file"])
                if not _pid_alive(pid) or not connection_file.is_file():
                    shutil.rmtree(state_path.parent, ignore_errors=True)
                    continue
                session = NotebookKernelSession(
                    kernel_id=str(value["kernel_id"]),
                    notebook_path=str(value["notebook_path"]),
                    kernel_name=str(value["kernel_name"]),
                    display_name=str(value.get("display_name") or value["kernel_name"]),
                    language=str(value.get("language") or ""),
                    pid=pid,
                    connection_file=connection_file,
                    created_at=str(value.get("created_at") or utc_now()),
                    log_path=Path(value.get("log_path") or state_path.parent / "kernel.log"),
                )
                self._connect(session, wait=True)
            except Exception:
                continue
            self._sessions[session.kernel_id] = session

    def _prune_dead(self) -> None:
        with self._lock:
            dead = [
                kernel_id
                for kernel_id, session in self._sessions.items()
                if not _pid_alive(session.pid)
            ]
        for kernel_id in dead:
            with self._lock:
                session = self._sessions.pop(kernel_id, None)
            if session is not None:
                self._detach_session(session)
                shutil.rmtree(self.root / kernel_id, ignore_errors=True)

    def _write_state(self, session: NotebookKernelSession) -> None:
        state_path = self.root / session.kernel_id / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            state_path,
            {
                **session.metadata(),
                "connection_file": str(session.connection_file),
                "log_path": str(session.log_path),
            },
        )

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 2
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
