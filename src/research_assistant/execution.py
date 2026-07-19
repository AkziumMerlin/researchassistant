from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_assistant.artifacts import RunStore, utc_now
from research_assistant.errors import ExecutionError
from research_assistant.models import ComponentRef, StageConfig
from research_assistant.planning import RunManifest, topological_stages
from research_assistant.registry import Registry


@dataclass(slots=True)
class StageResult:
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StageContext:
    manifest: RunManifest
    stage: StageConfig
    run_dir: Path
    registry: Registry
    _component_cache: dict[str, Any] = field(default_factory=dict)

    @property
    def seed(self) -> int | None:
        return self.manifest.config.seed

    def component(self, kind: str) -> Any:
        if kind not in self.manifest.config.components:
            raise ExecutionError(f"run does not define a {kind!r} component")
        if kind not in self._component_cache:
            reference = self.manifest.config.components[kind]
            self._component_cache[kind] = self.registry.invoke(kind, reference, self)
        return self._component_cache[kind]


def _normalize_result(value: Any) -> StageResult:
    if value is None:
        return StageResult()
    if isinstance(value, StageResult):
        return value
    if isinstance(value, dict):
        return StageResult(metrics={key: float(item) for key, item in value.items()})
    raise ExecutionError("stage handlers must return None, dict[str, number], or StageResult")


def execute_run(
    manifest: RunManifest,
    registry: Registry,
    *,
    artifact_root: str | Path | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    store = RunStore(manifest, root=artifact_root)
    store.prepare()
    status = store.load_status()

    if status["state"] == "completed":
        if resume:
            return status
        raise ExecutionError(f"run {manifest.run_id} is already completed")

    if not resume and status["state"] != "pending":
        raise ExecutionError(
            f"run {manifest.run_id} already has state {status['state']!r}; use --resume"
        )

    status["state"] = "running"
    status.setdefault("started_at", utc_now())
    store.save_status(status)

    stages = {stage.name: stage for stage in manifest.config.stages}
    try:
        for name in topological_stages(manifest.config):
            previous = status["stages"].get(name, {})
            if resume and previous.get("state") == "completed":
                continue

            unmet = [
                dependency
                for dependency in stages[name].needs
                if status["stages"].get(dependency, {}).get("state") != "completed"
            ]
            if unmet:
                raise ExecutionError(
                    f"stage {name!r} has incomplete dependencies: {', '.join(unmet)}"
                )

            status["stages"][name] = {"state": "running", "started_at": utc_now()}
            store.save_status(status)
            context = StageContext(
                manifest=manifest,
                stage=stages[name],
                run_dir=store.run_dir,
                registry=registry,
            )
            reference = ComponentRef(type=stages[name].type, params=stages[name].params)
            result = _normalize_result(registry.invoke("stage", reference, context))
            store.log_metrics(name, result.metrics)
            status["stages"][name] = {
                "state": "completed",
                "started_at": status["stages"][name]["started_at"],
                "finished_at": utc_now(),
                "metrics": result.metrics,
                "artifacts": result.artifacts,
            }
            store.save_status(status)
    except Exception as exc:
        failed_stage = next(
            (
                stage_name
                for stage_name, stage_status in status["stages"].items()
                if stage_status.get("state") == "running"
            ),
            None,
        )
        if failed_stage is not None:
            status["stages"][failed_stage].update(
                {
                    "state": "failed",
                    "finished_at": utc_now(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        status["state"] = "failed"
        status["error"] = f"{type(exc).__name__}: {exc}"
        status["traceback"] = traceback.format_exc()
        store.save_status(status)
        raise

    status["state"] = "completed"
    status["finished_at"] = utc_now()
    status.pop("error", None)
    status.pop("traceback", None)
    store.save_status(status)
    return status
