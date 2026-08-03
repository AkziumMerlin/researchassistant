from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from research_assistant.artifacts import atomic_write_json
from research_assistant.ui.launch_worker import run as run_launch
from research_assistant.ui.launches import _utc_now


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _worker_pids(request: dict[str, Any]) -> list[int]:
    artifact_root = Path(str(request.get("artifact_root", "")))
    study_id = str((request.get("plan") or {}).get("study_id", ""))
    pids: list[int] = []
    for run_id in (request.get("plan") or {}).get("run_ids", []):
        launcher = _read(artifact_root / study_id / str(run_id) / "launcher.json")
        pid = launcher.get("worker_pid")
        if isinstance(pid, int) and _pid_alive(pid):
            pids.append(pid)
    return pids


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m research_assistant.ui.adoption_worker LAUNCH_DIR")
    launch_dir = Path(sys.argv[1]).resolve()
    request = _read(launch_dir / "request.json")
    launch_id = str(request.get("launch_id", launch_dir.name))
    generation = int(request.get("adoption_generation", 1))
    try:
        while True:
            control = _read(launch_dir / "control.json")
            if control.get("action") == "cancel":
                return
            pids = _worker_pids(request)
            atomic_write_json(
                launch_dir / "lease.json",
                {
                    "schema_version": 1,
                    "launch_id": launch_id,
                    "scheduler_pid": os.getpid(),
                    "generation": generation,
                    "mode": "adoption-wait",
                    "heartbeat_at": _utc_now(),
                    "waiting_for_worker_pids": pids,
                },
            )
            if not pids:
                break
            time.sleep(2.0)
        raise SystemExit(run_launch(launch_dir))
    finally:
        (launch_dir / "lease.json").unlink(missing_ok=True)
        (launch_dir / "adoption.lock").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
