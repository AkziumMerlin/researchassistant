from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_assistant import __file__ as package_file
from research_assistant.artifacts import atomic_write_json
from research_assistant.ui.launches import (
    LaunchManager,
    UiLaunchError,
    _pid_alive,
    _read_json,
    _utc_now,
)

_ACTIVE_STATES = {"queued", "running", "adopting", "cancelling", "orphaned"}
_TERMINAL_RUN_STATES = {"completed", "failed", "interrupted", "cancelled", "preempted"}
_RECOVERABLE_STATES = {"orphaned", "failed", "cancelled", "interrupted"}


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _terminate_process_group(pid: int, signal_number: int) -> None:
    if pid <= 0:
        return
    try:
        os.killpg(pid, signal_number)
    except ProcessLookupError:
        return
    except (PermissionError, OSError):
        try:
            os.kill(pid, signal_number)
        except (ProcessLookupError, PermissionError, OSError):
            return


class DurableLaunchManager(LaunchManager):
    """Launch manager with persisted leases, recovery and explicit process control."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reconcile()

    def _lease(self, launch_dir: Path) -> dict[str, Any]:
        return _read_json(launch_dir / "lease.json")

    def _spawn_supervisor(self, launch_dir: Path, module: str) -> int:
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
        command = [sys.executable, "-m", module, str(launch_dir)]
        log_path = launch_dir / "scheduler.log"
        try:
            with log_path.open("ab", buffering=0) as log_stream:
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
            raise UiLaunchError(f"cannot start durable launch supervisor: {exc}") from exc
        atomic_write_json(
            launch_dir / "process.json",
            {
                "schema_version": 2,
                "scheduler_pid": process.pid,
                "spawned_at": _utc_now(),
                "supervisor": module,
            },
        )
        return process.pid

    def _reconcile_launch_dir(self, launch_dir: Path) -> None:
        if not (launch_dir / "request.json").is_file():
            return
        state = _read_json(launch_dir / "state.json", default={"state": "queued"})
        recorded = str(state.get("state", "queued"))
        if recorded not in _ACTIVE_STATES:
            return
        process = _read_json(launch_dir / "process.json")
        raw_pid = process.get("scheduler_pid")
        pid = int(raw_pid) if isinstance(raw_pid, int) or str(raw_pid).isdigit() else None
        if pid is not None and _pid_alive(pid):
            return

        request = _read_json(launch_dir / "request.json")
        runs = self._run_rows(request)
        states = [str(row.get("state", "pending")) for row in runs]
        worker_alive = any(
            isinstance(row.get("worker_pid"), int) and _pid_alive(int(row["worker_pid"]))
            for row in runs
        )
        if states and all(value == "completed" for value in states):
            reconciled = "completed"
        elif states and all(value in _TERMINAL_RUN_STATES for value in states):
            reconciled = (
                "failed" if any(value != "completed" for value in states) else "completed"
            )
        elif worker_alive:
            reconciled = "orphaned"
        else:
            reconciled = "orphaned"
        if recorded == reconciled:
            return
        atomic_write_json(
            launch_dir / "state.json",
            {
                **state,
                "schema_version": 2,
                "state": reconciled,
                "reconciled_at": _utc_now(),
                "previous_state": recorded,
                **(
                    {"finished_at": state.get("finished_at") or _utc_now()}
                    if reconciled in {"completed", "failed"}
                    else {}
                ),
            },
        )

    def reconcile(self) -> dict[str, Any]:
        reconciled: list[str] = []
        if not self.root.is_dir():
            return {"reconciled": reconciled}
        for launch_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            before = _read_json(launch_dir / "state.json").get("state")
            self._reconcile_launch_dir(launch_dir)
            after = _read_json(launch_dir / "state.json").get("state")
            if before != after:
                reconciled.append(launch_dir.name)
        return {"reconciled": reconciled}

    def _record(
        self,
        launch_dir: Path,
        *,
        include_detail: bool,
        selected_run_id: str | None = None,
    ) -> dict[str, Any]:
        self._reconcile_launch_dir(launch_dir)
        record = super()._record(
            launch_dir,
            include_detail=include_detail,
            selected_run_id=selected_run_id,
        )
        lease = self._lease(launch_dir)
        heartbeat = _parse_timestamp(lease.get("heartbeat_at"))
        age = (datetime.now(UTC) - heartbeat).total_seconds() if heartbeat else None
        state = str(record.get("state", "unknown"))
        record.update(
            {
                "lease": lease,
                "heartbeat_age_seconds": age,
                "heartbeat_fresh": age is not None and age <= 15,
                "recoverable": state in _RECOVERABLE_STATES,
                "cancellable": state in {"queued", "running", "adopting", "orphaned"},
            }
        )
        return record

    def adopt(self, launch_id: str) -> dict[str, Any]:
        launch_dir = self._launch_dir(launch_id)
        if not launch_dir.is_dir() or not (launch_dir / "request.json").is_file():
            raise UiLaunchError(f"UI launch does not exist: {launch_id}")
        self._reconcile_launch_dir(launch_dir)
        current = super()._record(launch_dir, include_detail=True)
        if current.get("scheduler_alive"):
            raise UiLaunchError(f"launch {launch_id} already has a live scheduler")
        state = str(current.get("state", "unknown"))
        if state not in _RECOVERABLE_STATES:
            raise UiLaunchError(
                f"launch {launch_id} cannot be adopted from state {state!r}"
            )

        lock_path = launch_dir / "adoption.lock"
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise UiLaunchError(f"launch {launch_id} is already being adopted") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"launch_id": launch_id, "created_at": _utc_now()}))
            stream.write("\n")

        (launch_dir / "control.json").unlink(missing_ok=True)
        request = _read_json(launch_dir / "request.json")
        request["resume"] = True
        request["adopted_at"] = _utc_now()
        request["adoption_generation"] = int(request.get("adoption_generation", 0)) + 1
        atomic_write_json(launch_dir / "request.json", request)
        previous = _read_json(launch_dir / "state.json")
        atomic_write_json(
            launch_dir / "state.json",
            {
                **previous,
                "schema_version": 2,
                "launch_id": launch_id,
                "state": "adopting",
                "adopted_at": request["adopted_at"],
                "previous_state": previous.get("state"),
            },
        )
        try:
            self._spawn_supervisor(launch_dir, "research_assistant.ui.adoption_worker")
        except Exception:
            lock_path.unlink(missing_ok=True)
            raise
        return self.detail(launch_id)

    def retry(self, launch_id: str) -> dict[str, Any]:
        return self.adopt(launch_id)

    def cancel(self, launch_id: str, *, force: bool = False) -> dict[str, Any]:
        launch_dir = self._launch_dir(launch_id)
        if not launch_dir.is_dir() or not (launch_dir / "request.json").is_file():
            raise UiLaunchError(f"UI launch does not exist: {launch_id}")
        detail = super()._record(launch_dir, include_detail=True)
        signal_number = signal.SIGKILL if force else signal.SIGTERM
        scheduler_pid = detail.get("scheduler_pid")
        if isinstance(scheduler_pid, int):
            _terminate_process_group(scheduler_pid, signal_number)
        for row in detail.get("runs", []):
            worker_pid = row.get("worker_pid")
            if isinstance(worker_pid, int):
                _terminate_process_group(worker_pid, signal_number)
        atomic_write_json(
            launch_dir / "control.json",
            {
                "schema_version": 1,
                "action": "cancel",
                "force": force,
                "requested_at": _utc_now(),
            },
        )
        previous = _read_json(launch_dir / "state.json")
        atomic_write_json(
            launch_dir / "state.json",
            {
                **previous,
                "schema_version": 2,
                "launch_id": launch_id,
                "state": "cancelled",
                "previous_state": previous.get("state"),
                "finished_at": _utc_now(),
                "cancelled_at": _utc_now(),
                "force": force,
            },
        )
        (launch_dir / "lease.json").unlink(missing_ok=True)
        (launch_dir / "adoption.lock").unlink(missing_ok=True)
        return self.detail(launch_id)
