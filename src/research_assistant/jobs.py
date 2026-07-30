from __future__ import annotations

import json
import mimetypes
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant import __file__ as package_file
from research_assistant.artifacts import atomic_write_json
from research_assistant.errors import ResearchAssistantError
from research_assistant.ui.launches import (
    LaunchCreateRequest,
    LaunchManager,
    _pid_alive,
    _read_json,
    _utc_now,
)
from research_assistant.ui.workspace import Workspace

MAX_LOG_PAGE_BYTES = 256 * 1024
MAX_METRIC_TAIL_BYTES = 4 * 1024 * 1024
MAX_ARTIFACTS = 5000


class JobError(ResearchAssistantError):
    pass


class JobStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_path: str = Field(min_length=1)
    launcher_path: str | None = None
    artifact_root: str | None = None
    resume: bool = True
    overrides: list[str] = Field(default_factory=list)
    launcher_overrides: list[str] = Field(default_factory=list)

    def launch_request(self) -> LaunchCreateRequest:
        return LaunchCreateRequest.model_validate(self.model_dump(mode="python"))


class LogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["scheduler", "worker"]
    run_id: str | None = None
    start: int
    end: int
    size: int
    next_cursor: int
    eof: bool
    text: str


_TERMINAL_STATES = {"completed", "failed", "cancelled", "interrupted"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
_TEXT_SUFFIXES = {
    ".txt",
    ".log",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".md",
    ".tex",
    ".html",
}
_PREVIEW_TOKENS = {
    "prediction": ("prediction", "predictions", "pred", "output"),
    "error_map": ("error_map", "error-map", "residual", "absolute_error", "error"),
    "sample": ("sample", "input", "target", "ground_truth", "truth"),
}


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _process_matches(pid: int, required_arguments: Iterable[str]) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    arguments = {part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part}
    return all(argument in arguments for argument in required_arguments)


def _terminate_process_group(pid: int, *, force: bool = False) -> None:
    if pid <= 1 or pid == os.getpid() or not _pid_alive(pid):
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        process_group = os.getpgid(pid)
    except (OSError, ProcessLookupError):
        process_group = None
    try:
        if process_group == pid:
            os.killpg(process_group, sig)
        else:
            os.kill(pid, sig)
    except (OSError, ProcessLookupError, PermissionError):
        return


def _wait_dead(pids: Iterable[int], timeout: float) -> set[int]:
    pending = {pid for pid in pids if _pid_alive(pid)}
    deadline = time.monotonic() + max(0.0, timeout)
    while pending and time.monotonic() < deadline:
        time.sleep(0.05)
        pending = {pid for pid in pending if _pid_alive(pid)}
    return pending


def _semantic_kind(path: Path) -> str | None:
    normalized = path.as_posix().lower()
    for kind, tokens in _PREVIEW_TOKENS.items():
        if any(token in normalized for token in tokens):
            return kind
    return None


class JobService:
    """One persistent detached-job store shared by CLI and browser workflows."""

    def __init__(self, workspace: str | Path, plugins: list[str] | None = None) -> None:
        self.workspace = Workspace(workspace)
        self.plugins = list(dict.fromkeys(plugins or []))
        self.manager = LaunchManager(self.workspace, self.plugins)

    def preview(self, payload: JobStartRequest) -> dict[str, Any]:
        return self.manager.preview(payload.launch_request())

    def start(self, payload: JobStartRequest) -> dict[str, Any]:
        return self._normalize(self.manager.create(payload.launch_request()))

    def list(self) -> list[dict[str, Any]]:
        return [self._normalize(item) for item in self.manager.list()]

    def detail(self, job_id: str, run_id: str | None = None) -> dict[str, Any]:
        return self._normalize(self.manager.detail(job_id, run_id))

    @staticmethod
    def _normalize(record: dict[str, Any]) -> dict[str, Any]:
        result = dict(record)
        launch_id = result.get("launch_id")
        if launch_id is not None:
            result["job_id"] = launch_id
        return result

    def _job_dir(self, job_id: str) -> Path:
        return self.manager._launch_dir(job_id)  # noqa: SLF001 - shared internal store

    def _request(self, job_id: str) -> tuple[Path, dict[str, Any]]:
        job_dir = self._job_dir(job_id)
        request_path = job_dir / "request.json"
        if not request_path.is_file():
            raise JobError(f"job does not exist: {job_id}")
        request = _read_json(request_path)
        recorded_workspace = Path(str(request.get("workspace_root", ""))).resolve()
        if recorded_workspace != self.workspace.root:
            raise JobError("persisted job belongs to a different workspace")
        return job_dir, request

    def _run_dir(self, job_id: str, run_id: str) -> Path:
        _job_dir, request = self._request(job_id)
        plan = request.get("plan") if isinstance(request.get("plan"), dict) else {}
        allowed = {str(value) for value in plan.get("run_ids", [])}
        if run_id not in allowed:
            raise JobError(f"run does not belong to job {job_id}: {run_id}")
        root = Path(str(request.get("artifact_root", ""))).resolve()
        if root == self.workspace.root or not root.is_relative_to(self.workspace.root):
            raise JobError("persisted artifact root escapes the workspace")
        study_id = str(plan.get("study_id", ""))
        candidate = (root / study_id / run_id).resolve()
        if not candidate.is_relative_to(root):
            raise JobError("run path escapes the configured artifact root")
        return candidate

    def cancel(self, job_id: str, *, grace_seconds: float = 2.0) -> dict[str, Any]:
        job_dir, request = self._request(job_id)
        detail = self.manager.detail(job_id)
        if detail.get("state") == "completed":
            raise JobError(f"completed job cannot be cancelled: {job_id}")

        pids: set[int] = set()
        for row in detail.get("runs", []):
            pid = _safe_int(row.get("worker_pid"))
            if pid is None or not _pid_alive(pid):
                continue
            run_id = str(row.get("run_id", ""))
            manifest_path = str(self._run_dir(job_id, run_id) / "manifest.json")
            if not _process_matches(pid, {"_worker", manifest_path}):
                raise JobError(
                    f"refusing to signal worker PID {pid}: process identity does not match"
                )
            pids.add(pid)
        scheduler_pid = _safe_int(detail.get("scheduler_pid"))
        if scheduler_pid is not None and _pid_alive(scheduler_pid):
            if not _process_matches(
                scheduler_pid,
                {"research_assistant.ui.launch_worker", str(job_dir)},
            ):
                raise JobError(
                    f"refusing to signal scheduler PID {scheduler_pid}: "
                    "process identity does not match"
                )
        else:
            scheduler_pid = None

        for pid in sorted(pids):
            _terminate_process_group(pid)
        if scheduler_pid is not None:
            _terminate_process_group(scheduler_pid)
        pending = _wait_dead([*pids, *([scheduler_pid] if scheduler_pid else [])], grace_seconds)
        for pid in sorted(pending):
            _terminate_process_group(pid, force=True)
        _wait_dead(pending, 0.5)

        now = _utc_now()
        for run_id in (request.get("plan") or {}).get("run_ids", []):
            run_dir = self._run_dir(job_id, str(run_id))
            status_path = run_dir / "status.json"
            status = _read_json(status_path)
            if status and str(status.get("state", "pending")) not in _TERMINAL_STATES:
                status.update(
                    {
                        "state": "interrupted",
                        "updated_at": now,
                        "error": "cancelled by user",
                    }
                )
                atomic_write_json(status_path, status)
            launcher_path = run_dir / "launcher.json"
            launcher = _read_json(launcher_path)
            if launcher:
                launcher.update({"state": "cancelled", "finished_at": now, "exit_code": -15})
                atomic_write_json(launcher_path, launcher)

        prior_state = _read_json(job_dir / "state.json")
        atomic_write_json(
            job_dir / "state.json",
            {
                "schema_version": 1,
                "launch_id": job_id,
                "state": "cancelled",
                "created_at": request.get("created_at"),
                "started_at": prior_state.get("started_at"),
                "finished_at": now,
                "exit_code": -15,
                "error": "cancelled by user",
            },
        )
        return self.detail(job_id)

    def recover(self, job_id: str) -> dict[str, Any]:
        job_dir, request = self._request(job_id)
        detail = self.manager.detail(job_id)
        if detail.get("scheduler_alive"):
            raise JobError(f"job scheduler is already running: {job_id}")
        if detail.get("recorded_state") == "completed":
            raise JobError(f"completed job does not need recovery: {job_id}")

        request["resume"] = True
        request["recovered_at"] = _utc_now()
        atomic_write_json(job_dir / "request.json", request)
        with (job_dir / "scheduler.log").open("a", encoding="utf-8") as stream:
            stream.write(f"\n--- recovery requested at {request['recovered_at']} ---\n")

        environment = os.environ.copy()
        source_root = str(Path(package_file).resolve().parents[1])
        python_paths = [
            str(self.workspace.root),
            source_root,
            *(environment.get("PYTHONPATH", "").split(os.pathsep)),
        ]
        environment["PYTHONPATH"] = os.pathsep.join(
            dict.fromkeys(path for path in python_paths if path)
        )
        command = [
            sys.executable,
            "-m",
            "research_assistant.ui.launch_worker",
            str(job_dir),
        ]
        queued_state = {
            "schema_version": 1,
            "launch_id": job_id,
            "state": "queued",
            "created_at": request.get("created_at"),
            "recovered_at": request["recovered_at"],
        }
        atomic_write_json(job_dir / "state.json", queued_state)
        try:
            with (job_dir / "scheduler.log").open("ab", buffering=0) as log_stream:
                process = subprocess.Popen(
                    command,
                    cwd=self.workspace.root,
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    start_new_session=True,
                    close_fds=True,
                )
        except OSError as exc:
            atomic_write_json(
                job_dir / "state.json",
                {
                    **queued_state,
                    "state": "failed",
                    "finished_at": _utc_now(),
                    "error": f"cannot recover detached scheduler: {exc}",
                },
            )
            raise JobError(f"cannot recover detached scheduler: {exc}") from exc

        atomic_write_json(
            job_dir / "process.json",
            {
                "schema_version": 1,
                "scheduler_pid": process.pid,
                "spawned_at": _utc_now(),
                "recovery": True,
            },
        )
        return self.detail(job_id)

    def log_page(
        self,
        job_id: str,
        *,
        source: Literal["scheduler", "worker"] = "scheduler",
        run_id: str | None = None,
        cursor: int | None = None,
        limit: int = 64 * 1024,
        tail: bool = False,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_LOG_PAGE_BYTES:
            raise JobError(f"log page limit must be between 1 and {MAX_LOG_PAGE_BYTES}")
        job_dir, _request = self._request(job_id)
        if source == "scheduler":
            path = job_dir / "scheduler.log"
        else:
            if run_id is None:
                raise JobError("worker log requires run_id")
            path = self._run_dir(job_id, run_id) / "worker.log"
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = 0
        except OSError as exc:
            raise JobError(f"cannot inspect log {path}: {exc}") from exc

        if tail:
            start = max(0, size - limit)
        else:
            start = max(0, min(size, int(cursor or 0)))
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                data = stream.read(limit)
        except FileNotFoundError:
            data = b""
        except OSError as exc:
            raise JobError(f"cannot read log {path}: {exc}") from exc
        end = start + len(data)
        return LogPage(
            source=source,
            run_id=run_id,
            start=start,
            end=end,
            size=size,
            next_cursor=end,
            eof=end >= size,
            text=data.decode("utf-8", errors="replace"),
        ).model_dump(mode="json")

    def metrics(
        self,
        job_id: str,
        run_id: str,
        *,
        since_sequence: int = 0,
        limit: int = 500,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 5000:
            raise JobError("metric event limit must be between 1 and 5000")
        path = self._run_dir(job_id, run_id) / "metrics.jsonl"
        try:
            size = path.stat().st_size
            start = max(0, size - MAX_METRIC_TAIL_BYTES)
            with path.open("rb") as stream:
                stream.seek(start)
                data = stream.read()
        except FileNotFoundError:
            data = b""
            size = 0
            start = 0
        except OSError as exc:
            raise JobError(f"cannot read metrics for {run_id}: {exc}") from exc

        lines = data.splitlines()
        if start > 0 and lines:
            lines = lines[1:]
        events: list[dict[str, Any]] = []
        for raw in lines:
            try:
                event = json.loads(raw)
                sequence = int(event.get("sequence", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if sequence <= since_sequence:
                continue
            events.append(event)
        events = events[-limit:]
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            raw_dimensions = event.get("dimensions")
            dimensions = raw_dimensions if isinstance(raw_dimensions, dict) else {}
            key = " · ".join(
                str(value)
                for value in (
                    event.get("stage", "unknown"),
                    event.get("metric", "metric"),
                    dimensions.get("split"),
                    dimensions.get("dataset"),
                )
                if value is not None and value != ""
            )
            latest[key] = event
        return {
            "run_id": run_id,
            "events": events,
            "latest": latest,
            "last_sequence": max(
                (int(item.get("sequence", 0)) for item in events),
                default=since_sequence,
            ),
            "source_size": size,
            "tail_truncated": start > 0,
        }

    def artifacts(self, job_id: str, run_id: str, *, limit: int = 1000) -> dict[str, Any]:
        if limit < 1 or limit > MAX_ARTIFACTS:
            raise JobError(f"artifact limit must be between 1 and {MAX_ARTIFACTS}")
        run_dir = self._run_dir(job_id, run_id)
        rows: list[dict[str, Any]] = []
        total = 0
        if run_dir.is_dir():
            for path in sorted(run_dir.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                relative = path.relative_to(run_dir)
                total += 1
                if len(rows) >= limit:
                    continue
                suffix = path.suffix.lower()
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                if suffix in _IMAGE_SUFFIXES:
                    preview = "image"
                elif suffix in _TEXT_SUFFIXES:
                    preview = "text"
                else:
                    preview = "download"
                rows.append(
                    {
                        "path": relative.as_posix(),
                        "name": path.name,
                        "size": size,
                        "mime": mime,
                        "preview": preview,
                        "semantic_kind": _semantic_kind(relative),
                    }
                )
        return {
            "job_id": job_id,
            "run_id": run_id,
            "artifacts": rows,
            "total": total,
            "truncated": total > len(rows),
        }

    def artifact_path(self, job_id: str, run_id: str, relative_path: str) -> Path:
        if not relative_path or "\x00" in relative_path or "\\" in relative_path:
            raise JobError("invalid artifact path")
        run_dir = self._run_dir(job_id, run_id)
        candidate = (run_dir / relative_path).resolve()
        if not candidate.is_relative_to(run_dir.resolve()) or not candidate.is_file():
            raise JobError(f"artifact does not exist: {relative_path}")
        return candidate

    def artifact_preview(
        self,
        job_id: str,
        run_id: str,
        relative_path: str,
        *,
        cursor: int = 0,
        limit: int = 64 * 1024,
    ) -> dict[str, Any]:
        path = self.artifact_path(job_id, run_id, relative_path)
        suffix = path.suffix.lower()
        if suffix not in _TEXT_SUFFIXES:
            return {
                "path": relative_path,
                "size": path.stat().st_size,
                "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "preview": "binary",
            }
        size = path.stat().st_size
        start = max(0, min(size, cursor))
        with path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(min(max(1, limit), MAX_LOG_PAGE_BYTES))
        return {
            "path": relative_path,
            "size": size,
            "start": start,
            "end": start + len(data),
            "eof": start + len(data) >= size,
            "text": data.decode("utf-8", errors="replace"),
            "preview": "text",
        }
