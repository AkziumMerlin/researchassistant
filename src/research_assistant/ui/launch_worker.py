from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from research_assistant.artifacts import atomic_write_json
from research_assistant.errors import ResearchAssistantError
from research_assistant.launching import LocalSubprocessLauncher
from research_assistant.models import ComponentRef, ExperimentConfig
from research_assistant.planning import Plan, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.ui.launches import _utc_now


def _load_request(launch_dir: Path) -> dict[str, Any]:
    path = launch_dir / "request.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchAssistantError(f"cannot read launch request {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResearchAssistantError(f"launch request must be a mapping: {path}")
    return payload


def run(launch_dir: Path) -> int:
    launch_dir = launch_dir.resolve()
    request = _load_request(launch_dir)
    launch_id = str(request.get("launch_id", launch_dir.name))
    created_at = request.get("created_at")
    state_path = launch_dir / "state.json"
    started_at = _utc_now()
    atomic_write_json(
        state_path,
        {
            "schema_version": 1,
            "launch_id": launch_id,
            "state": "running",
            "created_at": created_at,
            "started_at": started_at,
        },
    )
    try:
        config = ExperimentConfig.model_validate(request["config"])
        launcher_reference = ComponentRef.model_validate(request["launcher"])
        workspace_root = Path(str(request["workspace_root"])).resolve()
        artifact_root = Path(str(request["artifact_root"])).resolve()
        if not artifact_root.is_relative_to(workspace_root) or artifact_root == workspace_root:
            raise ResearchAssistantError("artifact root escapes the launch workspace")

        registry = load_registry(config.plugins)
        plan = compile_plan(config, registry)
        provenance = request.get("provenance")
        if isinstance(provenance, dict) and provenance:
            plan = Plan(
                study_id=plan.study_id,
                runs=tuple(
                    manifest.model_copy(update={"provenance": provenance})
                    for manifest in plan.runs
                ),
            )
        expected_runs = list((request.get("plan") or {}).get("run_ids", []))
        if [manifest.run_id for manifest in plan.runs] != expected_runs:
            raise ResearchAssistantError(
                "compiled plan no longer matches the persisted launch request"
            )
        configured = registry.invoke("launcher", launcher_reference, None)
        if not isinstance(configured, LocalSubprocessLauncher):
            raise ResearchAssistantError("launcher does not implement the local launcher contract")

        print(
            f"launch {launch_id}: study={plan.study_id} runs={len(plan.runs)} "
            f"artifacts={artifact_root}",
            flush=True,
        )
        results = configured.launch(
            plan,
            artifact_root=artifact_root,
            resume=bool(request.get("resume", True)),
            on_event=lambda message: print(message, flush=True),
        )
        failed = {run_id: code for run_id, code in results.items() if code != 0}
        state = "failed" if failed else "completed"
        exit_code = 1 if failed else 0
        atomic_write_json(
            state_path,
            {
                "schema_version": 1,
                "launch_id": launch_id,
                "state": state,
                "created_at": created_at,
                "started_at": started_at,
                "finished_at": _utc_now(),
                "exit_code": exit_code,
                "results": results,
                **({"error": f"{len(failed)} run(s) failed"} if failed else {}),
            },
        )
        print(f"launch {launch_id}: {state}", flush=True)
        return exit_code
    except Exception as exc:
        traceback.print_exc()
        atomic_write_json(
            state_path,
            {
                "schema_version": 1,
                "launch_id": launch_id,
                "state": "failed",
                "created_at": created_at,
                "started_at": started_at,
                "finished_at": _utc_now(),
                "exit_code": 1,
                "error": str(exc),
            },
        )
        return 1


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m research_assistant.ui.launch_worker LAUNCH_DIR")
    raise SystemExit(run(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
