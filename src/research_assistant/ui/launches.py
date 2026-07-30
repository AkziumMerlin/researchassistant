from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from research_assistant import __file__ as package_file
from research_assistant.artifacts import atomic_write_json
from research_assistant.config import load_config_text
from research_assistant.errors import ResearchAssistantError
from research_assistant.launching import LocalSubprocessLauncher, load_launcher_reference
from research_assistant.planning import Plan, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.ui.workspace import Workspace

MAX_LAUNCHES = 200
MAX_LOG_TAIL_BYTES = 64 * 1024
LAUNCH_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)


class UiLaunchError(ResearchAssistantError):
    pass


class LaunchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_path: str = Field(min_length=1)
    launcher_path: str | None = None
    artifact_root: str | None = None
    resume: bool = True


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(default or {})
    except (OSError, json.JSONDecodeError) as exc:
        raise UiLaunchError(f"cannot read UI launch state {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise UiLaunchError(f"invalid UI launch state in {path}")
    return payload


def _tail_text(path: Path, limit: int = MAX_LOG_TAIL_BYTES) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            data = stream.read(limit)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"[cannot read log: {exc}]"
    text = data.decode("utf-8", errors="replace")
    if size > limit:
        return "[… earlier output omitted …]\n" + text
    return text


def _pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _plan_summary(plan: Plan) -> dict[str, Any]:
    return {
        "study_id": plan.study_id,
        "runs": len(plan.runs),
        "trials": len({run.trial_id for run in plan.runs}),
        "run_ids": [run.run_id for run in plan.runs],
        "trial_ids": sorted({run.trial_id for run in plan.runs}),
    }


class LaunchManager:
    """Persist and supervise detached, schema-validated UI launch requests."""

    def __init__(self, workspace: Workspace, server_plugins: list[str] | None = None) -> None:
        self.workspace = workspace
        self.server_plugins = list(dict.fromkeys(server_plugins or []))
        self.root = workspace.root / ".ra" / "ui-launches"
        self.root.mkdir(parents=True, exist_ok=True)

    def _runtime_root(self, raw_path: str) -> Path:
        if "\\" in raw_path or "\x00" in raw_path:
            raise UiLaunchError("artifact root must use safe POSIX separators")
        relative = PurePosixPath(raw_path)
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise UiLaunchError("artifact root must be a workspace-relative directory")
        candidate = (self.workspace.root / Path(*relative.parts)).resolve(strict=False)
        if not candidate.is_relative_to(self.workspace.root) or candidate == self.workspace.root:
            raise UiLaunchError("artifact root must stay inside the workspace")
        return candidate

    def _launch_dir(self, launch_id: str) -> Path:
        if (
            not launch_id
            or launch_id in {".", ".."}
            or any(character not in LAUNCH_ID_CHARACTERS for character in launch_id)
        ):
            raise UiLaunchError("invalid UI launch identifier")
        path = (self.root / launch_id).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise UiLaunchError("UI launch identifier escapes state root")
        return path

    def _prepare(
        self, payload: LaunchCreateRequest
    ) -> tuple[dict[str, Any], Plan, dict[str, Any]]:
        config_file = self.workspace.read(payload.config_path)
        if not config_file.path.lower().endswith((".yaml", ".yml")):
            raise UiLaunchError("experiment config must be a YAML file")
        source = self.workspace.resolve(config_file.path)
        config = load_config_text(
            config_file.content,
            source,
            allowed_root=self.workspace.root,
        )
        plugins = list(dict.fromkeys([*self.server_plugins, *config.plugins]))
        config = config.model_copy(update={"plugins": plugins})
        registry = load_registry(plugins)
        plan = compile_plan(config, registry)

        launcher_path: str | None = None
        if payload.launcher_path:
            launcher_file = self.workspace.read(payload.launcher_path)
            if not launcher_file.path.lower().endswith((".yaml", ".yml")):
                raise UiLaunchError("launcher policy must be a YAML file")
            launcher_path = launcher_file.path
            launcher_reference = load_launcher_reference(
                self.workspace.resolve(launcher_file.path)
            )
        else:
            launcher_reference = load_launcher_reference(None)
        configured = registry.invoke("launcher", launcher_reference, None)
        if not isinstance(configured, LocalSubprocessLauncher):
            raise UiLaunchError("launcher does not implement the local launcher contract")

        raw_artifact_root = payload.artifact_root or config.artifacts.root
        artifact_root = self._runtime_root(raw_artifact_root)
        plan_payload = _plan_summary(plan)
        request = {
            "schema_version": 1,
            "created_at": _utc_now(),
            "workspace_root": str(self.workspace.root),
            "config_path": config_file.path,
            "launcher_path": launcher_path,
            "artifact_root": str(artifact_root),
            "artifact_root_relative": artifact_root.relative_to(self.workspace.root).as_posix(),
            "resume": payload.resume,
            "config": config.model_dump(mode="json"),
            "launcher": launcher_reference.model_dump(mode="json"),
            "plan": plan_payload,
        }
        return request, plan, plan_payload

    def create(self, payload: LaunchCreateRequest) -> dict[str, Any]:
        request, _plan, _plan_payload = self._prepare(payload)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        launch_id = f"{timestamp}-{uuid4().hex[:10]}"
        launch_dir = self._launch_dir(launch_id)
        launch_dir.mkdir(parents=True, exist_ok=False)
        request["launch_id"] = launch_id
        atomic_write_json(launch_dir / "request.json", request)
        atomic_write_json(
            launch_dir / "state.json",
            {
                "schema_version": 1,
                "launch_id": launch_id,
                "state": "queued",
                "created_at": request["created_at"],
            },
        )

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
            str(launch_dir),
        ]
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
            atomic_write_json(
                launch_dir / "state.json",
                {
                    "schema_version": 1,
                    "launch_id": launch_id,
                    "state": "failed",
                    "created_at": request["created_at"],
                    "finished_at": _utc_now(),
                    "error": f"cannot start scheduler: {exc}",
                },
            )
            raise UiLaunchError(f"cannot start detached scheduler: {exc}") from exc
        atomic_write_json(
            launch_dir / "process.json",
            {
                "schema_version": 1,
                "scheduler_pid": process.pid,
                "spawned_at": _utc_now(),
            },
        )
        return self.detail(launch_id)

    def _run_rows(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        plan = request.get("plan") or {}
        artifact_root = Path(str(request.get("artifact_root", "")))
        study_id = str(plan.get("study_id", ""))
        rows: list[dict[str, Any]] = []
        for run_id in plan.get("run_ids", []):
            run_dir = artifact_root / study_id / str(run_id)
            status = _read_json(
                run_dir / "status.json",
                default={"run_id": run_id, "state": "pending", "stages": {}},
            )
            launcher = _read_json(run_dir / "launcher.json")
            resources = _read_json(run_dir / "resources.json")
            stages = status.get("stages") if isinstance(status.get("stages"), dict) else {}
            gpu = launcher.get("gpu")
            if not isinstance(gpu, dict):
                attempts = resources.get("attempts")
                if isinstance(attempts, list):
                    attempt_id = launcher.get("attempt_id")
                    matching_attempt = next(
                        (
                            attempt
                            for attempt in reversed(attempts)
                            if isinstance(attempt, dict)
                            and (attempt_id is None or attempt.get("attempt_id") == attempt_id)
                        ),
                        None,
                    )
                    if matching_attempt is not None and isinstance(
                        matching_attempt.get("gpu"), dict
                    ):
                        gpu = matching_attempt["gpu"]
            rows.append(
                {
                    "run_id": str(run_id),
                    "state": str(status.get("state", "pending")),
                    "attempt": status.get("attempt"),
                    "updated_at": status.get("updated_at"),
                    "stages": {
                        str(name): str(value.get("state", "pending"))
                        for name, value in stages.items()
                        if isinstance(value, dict)
                    },
                    "gpu": gpu if isinstance(gpu, dict) else None,
                    "worker_pid": launcher.get("worker_pid"),
                }
            )
        return rows

    def _record(
        self,
        launch_dir: Path,
        *,
        include_detail: bool,
        selected_run_id: str | None = None,
    ) -> dict[str, Any]:
        request = _read_json(launch_dir / "request.json")
        state = _read_json(launch_dir / "state.json", default={"state": "queued"})
        process = _read_json(launch_dir / "process.json")
        pid = process.get("scheduler_pid")
        pid_value = int(pid) if isinstance(pid, int) or str(pid).isdigit() else None
        recorded_state = str(state.get("state", "queued"))
        process_alive = _pid_alive(pid_value)
        scheduler_alive = recorded_state in {"queued", "running"} and process_alive
        effective_state = (
            "orphaned"
            if (
                recorded_state in {"queued", "running"}
                and pid_value is not None
                and not process_alive
            )
            else recorded_state
        )
        runs = self._run_rows(request)
        counts: dict[str, int] = {}
        for run in runs:
            counts[run["state"]] = counts.get(run["state"], 0) + 1
        record = {
            "launch_id": str(request.get("launch_id", launch_dir.name)),
            "state": effective_state,
            "recorded_state": recorded_state,
            "created_at": request.get("created_at"),
            "started_at": state.get("started_at"),
            "finished_at": state.get("finished_at"),
            "config_path": request.get("config_path"),
            "launcher_path": request.get("launcher_path"),
            "artifact_root": request.get("artifact_root_relative"),
            "resume": request.get("resume", True),
            "plan": request.get("plan", {}),
            "scheduler_pid": pid_value,
            "scheduler_alive": scheduler_alive,
            "run_counts": counts,
            "error": state.get("error"),
            "exit_code": state.get("exit_code"),
        }
        if include_detail:
            record["runs"] = runs
            record["scheduler_log"] = _tail_text(launch_dir / "scheduler.log")
            record["results"] = state.get("results", {})
            available_run_ids = {run["run_id"] for run in runs}
            if selected_run_id is not None and selected_run_id not in available_run_ids:
                raise UiLaunchError(f"run does not belong to launch {record['launch_id']}")
            if selected_run_id is None:
                preferred = next(
                    (run for run in runs if run["state"] in {"failed", "interrupted"}),
                    None,
                )
                preferred = preferred or next(
                    (run for run in runs if run["state"] == "running"),
                    None,
                )
                preferred = preferred or (runs[0] if runs else None)
                selected_run_id = preferred["run_id"] if preferred else None
            record["selected_run_id"] = selected_run_id
            if selected_run_id is not None:
                artifact_root = Path(str(request["artifact_root"]))
                study_id = str((request.get("plan") or {}).get("study_id", ""))
                worker_log = artifact_root / study_id / selected_run_id / "worker.log"
                record["worker_log"] = _tail_text(worker_log)
            else:
                record["worker_log"] = ""
        return record

    def list(self) -> list[dict[str, Any]]:
        directories = sorted(
            (path for path in self.root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        return [
            self._record(path, include_detail=False)
            for path in directories[:MAX_LAUNCHES]
            if (path / "request.json").is_file()
        ]

    def detail(self, launch_id: str, selected_run_id: str | None = None) -> dict[str, Any]:
        launch_dir = self._launch_dir(launch_id)
        if not launch_dir.is_dir() or not (launch_dir / "request.json").is_file():
            raise UiLaunchError(f"UI launch does not exist: {launch_id}")
        return self._record(
            launch_dir,
            include_detail=True,
            selected_run_id=selected_run_id,
        )
