from __future__ import annotations

import traceback
from collections.abc import Callable, Mapping
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
    resume: bool = True
    stage_outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    _metric_logger: Callable[..., None] | None = None
    _component_cache: dict[str, Any] = field(default_factory=dict)

    @property
    def seed(self) -> int | None:
        return self.manifest.config.seed

    def component(self, kind: str) -> Any:
        reference = self.stage.components.get(kind)
        if reference is None:
            reference = self.manifest.config.components.get(kind)
        if reference is None:
            raise ExecutionError(f"run does not define a {kind!r} component")
        if kind not in self._component_cache:
            self._component_cache[kind] = self.registry.invoke(kind, reference, self)
        return self._component_cache[kind]

    def log_metrics(self, metrics: Mapping[str, float], *, step: int | float | None = None) -> None:
        """Append progress metrics while a long-running stage is still active."""
        if self._metric_logger is None:
            raise ExecutionError("metric logging is unavailable in this stage context")
        normalized = {str(key): float(value) for key, value in metrics.items()}
        self._metric_logger(self.stage.name, normalized, step=step, kind="progress")

    def artifact(self, stage: str, name: str) -> Path:
        """Resolve a named artifact published by a completed dependency stage."""
        if stage not in self.stage_outputs:
            raise ExecutionError(f"stage {stage!r} has no completed output")
        artifacts = self.stage_outputs[stage].get("artifacts") or {}
        if name not in artifacts:
            available = ", ".join(sorted(artifacts)) or "none"
            raise ExecutionError(
                f"stage {stage!r} has no artifact {name!r}; available: {available}"
            )
        path = (self.run_dir / str(artifacts[name])).resolve()
        if not path.is_relative_to(self.run_dir.resolve()):
            raise ExecutionError(f"artifact {stage}.{name} escapes the run directory")
        if not path.exists():
            raise ExecutionError(f"artifact {stage}.{name} does not exist: {path}")
        return path

    def output_metrics(self, stage: str) -> dict[str, float]:
        if stage not in self.stage_outputs:
            raise ExecutionError(f"stage {stage!r} has no completed output")
        return {
            str(key): float(value)
            for key, value in (self.stage_outputs[stage].get("metrics") or {}).items()
        }


def _normalize_result(value: Any) -> StageResult:
    if value is None:
        return StageResult()
    if isinstance(value, StageResult):
        return value
    if isinstance(value, dict):
        return StageResult(metrics={key: float(item) for key, item in value.items()})
    raise ExecutionError("stage handlers must return None, dict[str, number], or StageResult")


def _normalize_artifacts(result: StageResult, run_dir: Path) -> StageResult:
    normalized: dict[str, str] = {}
    root = run_dir.resolve()
    for name, raw_path in result.artifacts.items():
        path = Path(raw_path)
        path = path.resolve() if path.is_absolute() else (run_dir / path).resolve()
        if not path.is_relative_to(root):
            raise ExecutionError(f"artifact {name!r} must be stored inside {run_dir}")
        if not path.exists():
            raise ExecutionError(f"artifact {name!r} does not exist: {path}")
        normalized[str(name)] = path.relative_to(root).as_posix()
    return StageResult(metrics=dict(result.metrics), artifacts=normalized)


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
                resume=resume,
                stage_outputs={
                    stage_name: dict(stage_status)
                    for stage_name, stage_status in status["stages"].items()
                    if stage_status.get("state") == "completed"
                },
                _metric_logger=store.log_metrics,
            )
            reference = ComponentRef(type=stages[name].type, params=stages[name].params)
            result = _normalize_artifacts(
                _normalize_result(registry.invoke("stage", reference, context)), store.run_dir
            )
            store.log_metrics(name, result.metrics, kind="final")
            status["stages"][name] = {
                "state": "completed",
                "started_at": status["stages"][name]["started_at"],
                "finished_at": utc_now(),
                "metrics": result.metrics,
                "artifacts": result.artifacts,
            }
            store.save_status(status)
    except BaseException as exc:
        interrupted = isinstance(exc, KeyboardInterrupt) or (
            isinstance(exc, SystemExit) and exc.code in {130, "130"}
        )
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
                    "state": "interrupted" if interrupted else "failed",
                    "finished_at": utc_now(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        status["state"] = "interrupted" if interrupted else "failed"
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
