from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml

from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError


class AnalysisSessionError(ResearchAssistantError):
    pass


class AnalysisSessionManager:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".ra" / "analysis-sessions"

    def _safe_path(self, raw: str | Path, *, require_file: bool = False) -> Path:
        path = Path(raw)
        resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise AnalysisSessionError(f"path escapes workspace: {raw}")
        if require_file and not resolved.is_file():
            raise AnalysisSessionError(f"file does not exist: {resolved}")
        return resolved

    def _session_dir(self, session_id: str) -> Path:
        if not session_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in session_id
        ):
            raise AnalysisSessionError("invalid analysis session id")
        return self.root / session_id

    def _python_interpreter(self, raw: str | Path) -> Path:
        interpreter = Path(raw).expanduser().resolve()
        if not interpreter.is_file():
            raise AnalysisSessionError(f"Python interpreter does not exist: {interpreter}")
        if re.fullmatch(r"python(?:w)?(?:[0-9]+(?:\.[0-9]+)*)?(?:\.exe)?", interpreter.name) is None:
            raise AnalysisSessionError("analysis interpreter must be a Python executable")
        return interpreter

    def _start(
        self,
        argv: list[str],
        *,
        cwd: str | Path = ".",
        label: str | None = None,
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workdir = self._safe_path(cwd)
        if not workdir.is_dir():
            raise AnalysisSessionError(f"working directory does not exist: {workdir}")
        session_id = f"analysis-{uuid.uuid4().hex[:16]}"
        directory = self._session_dir(session_id)
        directory.mkdir(parents=True)
        stdout_path = directory / "stdout.log"
        stderr_path = directory / "stderr.log"
        with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
            process = subprocess.Popen(
                argv,
                cwd=workdir,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        record = {
            "session_id": session_id,
            "kind": kind,
            "label": label or Path(argv[0]).name,
            "argv": argv,
            "cwd": workdir.relative_to(self.workspace).as_posix() or ".",
            "pid": process.pid,
            "state": "running",
            "started_at": utc_now(),
            "finished_at": None,
            "returncode": None,
            "metadata": metadata or {},
        }
        atomic_write_json(directory / "session.json", record)
        return record

    def start_script(
        self,
        script: str | Path,
        *,
        args: list[str] | None = None,
        cwd: str | Path = ".",
        python: str | Path = sys.executable,
        profile: bool = False,
        label: str | None = None,
    ) -> dict[str, Any]:
        script_path = self._safe_path(script, require_file=True)
        interpreter = self._python_interpreter(python)
        argv = [str(interpreter)]
        if profile:
            profile_path = self.root / "profiles" / f"{uuid.uuid4().hex}.prof"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            argv.extend(["-m", "cProfile", "-o", str(profile_path)])
        argv.extend([str(script_path), *(args or [])])
        return self._start(
            argv,
            cwd=cwd,
            label=label or script_path.name,
            kind="script",
            metadata={"script": script_path.relative_to(self.workspace).as_posix(), "profile": profile},
        )

    def start_scratchpad(
        self,
        code: str,
        *,
        cwd: str | Path = ".",
        python: str | Path = sys.executable,
        label: str | None = None,
    ) -> dict[str, Any]:
        if not code.strip():
            raise AnalysisSessionError("scratchpad code is empty")
        interpreter = self._python_interpreter(python)
        scratch_root = self.workspace / ".ra" / "scratchpads"
        scratch_root.mkdir(parents=True, exist_ok=True)
        path = scratch_root / f"{uuid.uuid4().hex}.py"
        path.write_text(code, encoding="utf-8")
        return self._start(
            [str(interpreter), str(path)],
            cwd=cwd,
            label=label or path.name,
            kind="scratchpad",
            metadata={"script": path.relative_to(self.workspace).as_posix()},
        )

    def _alive(self, pid: int) -> bool:
        try:
            waited, _status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                return False
        except ChildProcessError:
            pass
        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.is_file():
            try:
                fields = proc_stat.read_text(encoding="utf-8").split()
                if len(fields) > 2 and fields[2] == "Z":
                    return False
            except OSError:
                pass
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def status(self, session_id: str) -> dict[str, Any]:
        path = self._session_dir(session_id) / "session.json"
        if not path.is_file():
            raise AnalysisSessionError(f"unknown analysis session {session_id!r}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("state") == "running" and not self._alive(int(record["pid"])):
            record["state"] = "finished"
            record["finished_at"] = record.get("finished_at") or utc_now()
            atomic_write_json(path, record)
        return record

    def list(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("analysis-*/session.json"), reverse=True):
            try:
                rows.append(self.status(path.parent.name))
            except (OSError, json.JSONDecodeError, AnalysisSessionError):
                continue
            if len(rows) >= limit:
                break
        return rows

    def logs(
        self,
        session_id: str,
        *,
        stream: Literal["stdout", "stderr"] = "stdout",
        tail_bytes: int = 200000,
    ) -> str:
        self.status(session_id)
        path = self._session_dir(session_id) / f"{stream}.log"
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            size = path.stat().st_size
            handle.seek(max(0, size - tail_bytes))
            return handle.read().decode("utf-8", errors="replace")

    def stop(self, session_id: str) -> dict[str, Any]:
        record = self.status(session_id)
        if record["state"] != "running":
            return record
        pid = int(record["pid"])
        termination = "already-exited"
        try:
            os.killpg(pid, signal.SIGTERM)
            termination = "sigterm"
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5.0
        while self._alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
                termination = "sigkill"
            except ProcessLookupError:
                pass
        record["state"] = "stopped"
        record["termination"] = termination
        record["finished_at"] = utc_now()
        atomic_write_json(self._session_dir(session_id) / "session.json", record)
        return record


class TaskCatalog:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.path = self.workspace / ".ra" / "tasks.yaml"

    def list(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise AnalysisSessionError(f"cannot read task catalog: {exc}") from exc
        tasks = payload.get("tasks", payload)
        if not isinstance(tasks, dict):
            raise AnalysisSessionError("task catalog must contain a task mapping")
        rows = []
        for name, raw in tasks.items():
            if not isinstance(raw, dict):
                continue
            rows.append(
                {
                    "name": str(name),
                    "script": raw.get("script"),
                    "args": list(raw.get("args") or []),
                    "cwd": raw.get("cwd", "."),
                    "python": raw.get("python", sys.executable),
                    "profile": bool(raw.get("profile", False)),
                    "description": raw.get("description", ""),
                }
            )
        return rows

    def run(self, name: str, manager: AnalysisSessionManager) -> dict[str, Any]:
        task = next((item for item in self.list() if item["name"] == name), None)
        if task is None:
            raise AnalysisSessionError(f"unknown task {name!r}")
        if not task.get("script"):
            raise AnalysisSessionError(f"task {name!r} does not define a script")
        return manager.start_script(
            task["script"],
            args=task["args"],
            cwd=task["cwd"],
            python=task["python"],
            profile=task["profile"],
            label=name,
        )
