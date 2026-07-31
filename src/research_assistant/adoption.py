from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_assistant import __file__ as package_file
from research_assistant.artifacts import atomic_write_json
from research_assistant.jobs import JobError, JobService
from research_assistant.ui.launches import _pid_alive, _read_json, _utc_now


def _safe_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 1 else None


def _live_workers(record: dict[str, Any]) -> list[int]:
    result: list[int] = []
    for run in record.get("runs", []):
        if not isinstance(run, dict):
            continue
        pid = _safe_pid(run.get("worker_pid"))
        if pid is not None and _pid_alive(pid):
            result.append(pid)
    return result


def _lock_path(job_dir: Path) -> Path:
    return job_dir / "adoption.lock"


def _acquire_lock(job_dir: Path) -> bool:
    path = _lock_path(job_dir)
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            payload = _read_json(path)
            pid = _safe_pid(payload.get("scheduler_pid"))
            if pid is not None and _pid_alive(pid):
                return False
            path.unlink(missing_ok=True)
            continue
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"created_at": _utc_now(), "owner_pid": os.getpid()}, stream)
                stream.write("\n")
            return True
    return False


def adopt_job(
    service: JobService,
    job_id: str,
    *,
    require_live_worker: bool = True,
) -> dict[str, Any]:
    job_dir, request = service._request(job_id)  # noqa: SLF001 - same persistent job store
    detail = service.manager.detail(job_id)
    if detail.get("scheduler_alive"):
        return service._normalize(detail)  # noqa: SLF001
    if detail.get("recorded_state") == "completed" or detail.get("state") == "completed":
        raise JobError(f"completed job does not need adoption: {job_id}")
    workers = _live_workers(detail)
    if require_live_worker and not workers:
        raise JobError(f"job has no living worker to adopt: {job_id}")
    if not _acquire_lock(job_dir):
        return service._normalize(service.manager.detail(job_id))  # noqa: SLF001

    environment = os.environ.copy()
    source_root = str(Path(package_file).resolve().parents[1])
    python_paths = [
        str(service.workspace.root),
        source_root,
        *(environment.get("PYTHONPATH", "").split(os.pathsep)),
    ]
    environment["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys(path for path in python_paths if path)
    )
    command = [sys.executable, "-m", "research_assistant.ui.launch_worker", str(job_dir)]
    now = _utc_now()
    request["resume"] = True
    request["adopted_at"] = now
    atomic_write_json(job_dir / "request.json", request)
    with (job_dir / "scheduler.log").open("a", encoding="utf-8") as stream:
        stream.write(f"\n--- scheduler adoption requested at {now}; workers={workers} ---\n")
    try:
        with (job_dir / "scheduler.log").open("ab", buffering=0) as log_stream:
            process = subprocess.Popen(
                command,
                cwd=service.workspace.root,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        _lock_path(job_dir).unlink(missing_ok=True)
        raise JobError(f"cannot start adopting scheduler: {exc}") from exc

    atomic_write_json(
        _lock_path(job_dir),
        {
            "created_at": now,
            "scheduler_pid": process.pid,
            "workers": workers,
        },
    )
    atomic_write_json(
        job_dir / "process.json",
        {
            "schema_version": 1,
            "scheduler_pid": process.pid,
            "spawned_at": now,
            "adoption": True,
            "workers": workers,
        },
    )
    state = _read_json(job_dir / "state.json")
    state.update(
        {
            "schema_version": 1,
            "launch_id": job_id,
            "state": "adopting",
            "adopted_at": now,
            "adopted_workers": workers,
        }
    )
    atomic_write_json(job_dir / "state.json", state)
    return service._normalize(service.manager.detail(job_id))  # noqa: SLF001


def maybe_adopt(service: JobService, record: dict[str, Any]) -> dict[str, Any]:
    normalized = service._normalize(record)  # noqa: SLF001
    if normalized.get("scheduler_alive"):
        return normalized
    state = str(normalized.get("state", normalized.get("recorded_state", "unknown")))
    if state in {"completed", "failed", "cancelled"}:
        return normalized
    if not _live_workers(normalized):
        return normalized
    try:
        return adopt_job(service, str(normalized["job_id"]), require_live_worker=True)
    except JobError:
        return normalized
