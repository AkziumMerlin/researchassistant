from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from research_assistant.artifacts import RunStore, utc_now
from research_assistant.errors import ExecutionError
from research_assistant.execution import (
    StageContext,
    _normalize_artifacts,
    _normalize_result,
)
from research_assistant.models import ComponentRef
from research_assistant.planning import RunManifest, topological_stages
from research_assistant.registry import Registry
from research_assistant.stage_cache import StageCache


def execute_run_cached(
    manifest: RunManifest,
    registry: Registry,
    *,
    artifact_root: str | Path | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Execute a run with conservative content-addressed stage reuse."""
    store = RunStore(manifest, root=artifact_root)
    store.prepare()
    status = store.load_status()

    if status["state"] == "completed":
        if resume:
            store.close()
            return status
        store.close()
        raise ExecutionError(f"run {manifest.run_id} is already completed")

    if not resume and status["state"] != "pending":
        store.close()
        raise ExecutionError(
            f"run {manifest.run_id} already has state {status['state']!r}; use --resume"
        )

    status["attempt"] = int(status.get("attempt", 0)) + 1
    store.begin_attempt(status["attempt"])
    status["state"] = "running"
    status.setdefault("started_at", utc_now())
    store.save_status(status)

    stages = {stage.name: stage for stage in manifest.config.stages}
    resolved_artifact_root = Path(artifact_root or manifest.config.artifacts.root).resolve()
    cache = StageCache(resolved_artifact_root.parent, registry)
    try:
        for name in topological_stages(manifest.config):
            stage = stages[name]
            previous = status["stages"].get(name, {})
            if resume and previous.get("state") == "completed":
                continue

            unmet = [
                dependency
                for dependency in stage.needs
                if status["stages"].get(dependency, {}).get("state") != "completed"
            ]
            if unmet:
                raise ExecutionError(
                    f"stage {name!r} has incomplete dependencies: {', '.join(unmet)}"
                )

            completed = {
                stage_name: dict(stage_status)
                for stage_name, stage_status in status["stages"].items()
                if stage_status.get("state") == "completed"
            }
            cache_key: str | None = None
            cache_error: str | None = None
            if cache.cacheable(stage):
                try:
                    cache_key = cache.key(manifest, stage, store.run_dir, completed)
                    hit = cache.restore(cache_key, name, store.run_dir)
                except (OSError, ValueError, KeyError) as exc:
                    hit = None
                    cache_error = f"{type(exc).__name__}: {exc}"
                if hit is not None:
                    store.log_metrics(name, hit.metrics, kind="final")
                    status["stages"][name] = {
                        "state": "completed",
                        "started_at": utc_now(),
                        "finished_at": utc_now(),
                        "metrics": hit.metrics,
                        "artifacts": hit.artifacts,
                        "cache_key": hit.key,
                        "cache_hit": True,
                        "cache_created_at": hit.created_at,
                    }
                    store.save_status(status)
                    continue

            status["stages"][name] = {
                "state": "running",
                "started_at": utc_now(),
                **({"cache_key": cache_key} if cache_key else {}),
                **({"cache_error": cache_error} if cache_error else {}),
            }
            store.save_status(status)
            context = StageContext(
                manifest=manifest,
                stage=stage,
                run_dir=store.run_dir,
                registry=registry,
                resume=resume,
                stage_outputs=completed,
                _metric_logger=store.log_metrics,
            )
            reference = ComponentRef(type=stage.type, params=stage.params)
            result = _normalize_artifacts(
                _normalize_result(registry.invoke("stage", reference, context)), store.run_dir
            )
            store.log_metrics(name, result.metrics, kind="final")
            if cache_key is not None:
                try:
                    cache.store(cache_key, name, result, store.run_dir)
                except (OSError, ValueError, KeyError) as exc:
                    cache_error = f"{type(exc).__name__}: {exc}"
            status["stages"][name] = {
                "state": "completed",
                "started_at": status["stages"][name]["started_at"],
                "finished_at": utc_now(),
                "metrics": result.metrics,
                "artifacts": result.artifacts,
                **({"cache_key": cache_key, "cache_hit": False} if cache_key else {}),
                **({"cache_error": cache_error} if cache_error else {}),
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
        store.close()
        raise

    status["state"] = "completed"
    status["finished_at"] = utc_now()
    status.pop("error", None)
    status.pop("traceback", None)
    store.save_status(status)
    store.close()
    return status
