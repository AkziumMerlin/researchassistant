from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_assistant.analytics import ChartSpec, MetricFilter, MetricIndex

_ACTIVE_STATES = {"pending", "queued", "scheduled", "starting", "running"}
_TOTAL_STEP_KEYS = ("max_epochs", "num_epochs", "epochs", "total_steps", "max_steps")
_RESOURCE_TOKENS = ("gpu", "memory", "vram", "utilization", "power", "temperature")


class LiveMetricSpec(BaseModel):
    """Bounded query for the live multi-run metric dashboard."""

    model_config = ConfigDict(extra="forbid")

    metrics: list[str] = Field(default_factory=list, max_length=12)
    stages: list[str] = Field(default_factory=list, max_length=20)
    kinds: list[Literal["progress", "final", "resource"]] = Field(
        default_factory=lambda: ["progress"],
        max_length=3,
    )
    states: list[str] = Field(default_factory=list, max_length=20)
    trial_ids: list[str] = Field(default_factory=list, max_length=500)
    run_ids: list[str] = Field(default_factory=list, max_length=5000)
    models: list[str] = Field(default_factory=list, max_length=100)
    datasets: list[str] = Field(default_factory=list, max_length=100)
    splits: list[str] = Field(default_factory=list, max_length=20)
    search: str = Field(default="", max_length=200)
    active_only: bool = True
    group_by: Literal["run_id", "seed", "model", "trial_id"] = "run_id"
    aggregate: Literal["mean", "min", "max"] = "mean"
    uncertainty: Literal["none", "std", "sem", "range"] = "none"
    max_points: int = Field(default=800, ge=20, le=5000)
    max_series: int = Field(default=80, ge=1, le=250)
    y_scale: Literal["linear", "log"] = "linear"
    cursor: dict[str, int] = Field(default_factory=dict, max_length=5000)

    @field_validator(
        "metrics", "stages", "states", "trial_ids", "run_ids", "models", "datasets", "splits"
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @field_validator("cursor")
    @classmethod
    def valid_cursor(cls, value: dict[str, int]) -> dict[str, int]:
        return {str(run_id): max(0, int(sequence)) for run_id, sequence in value.items()}


def _placeholders(values: list[Any]) -> str:
    return ",".join("?" for _ in values)


def _parse_json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _find_total_steps(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in _TOTAL_STEP_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                return candidate
        for key, child in value.items():
            if key in {"components", "model", "architecture"}:
                continue
            candidate = _find_total_steps(child)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for child in value:
            candidate = _find_total_steps(child)
            if candidate is not None:
                return candidate
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _estimated_remaining_seconds(
    *,
    first_time: Any,
    last_time: Any,
    first_step: Any,
    last_step: Any,
    total_steps: int | None,
) -> float | None:
    start = _parse_time(first_time)
    finish = _parse_time(last_time)
    if start is None or finish is None or total_steps is None:
        return None
    try:
        initial_step = float(first_step)
        current_step = float(last_step)
    except (TypeError, ValueError):
        return None
    completed = current_step - initial_step
    remaining = total_steps - current_step
    elapsed = (finish - start).total_seconds()
    if completed <= 0 or remaining <= 0 or elapsed <= 0:
        return None
    return elapsed / completed * remaining


def _scope_rows(
    index: MetricIndex,
    allowed_run_ids: list[str],
    spec: LiveMetricSpec,
) -> list[dict[str, Any]]:
    if not allowed_run_ids:
        return []
    clauses = [f"run_id IN ({_placeholders(allowed_run_ids)})"]
    parameters: list[Any] = [*allowed_run_ids]
    if spec.run_ids:
        clauses.append(f"run_id IN ({_placeholders(spec.run_ids)})")
        parameters.extend(spec.run_ids)
    if spec.trial_ids:
        clauses.append(f"trial_id IN ({_placeholders(spec.trial_ids)})")
        parameters.extend(spec.trial_ids)
    if spec.models:
        clauses.append(f"COALESCE(model, trial_id) IN ({_placeholders(spec.models)})")
        parameters.extend(spec.models)
    if spec.datasets:
        clauses.append(f"COALESCE(dataset, 'unknown') IN ({_placeholders(spec.datasets)})")
        parameters.extend(spec.datasets)
    states = spec.states or (sorted(_ACTIVE_STATES) if spec.active_only else [])
    if states:
        clauses.append(f"state IN ({_placeholders(states)})")
        parameters.extend(states)
    if spec.search.strip():
        needle = f"%{spec.search.strip()}%"
        clauses.append(
            "(run_id LIKE ? OR trial_id LIKE ? OR COALESCE(model, '') LIKE ? "
            "OR COALESCE(dataset, '') LIKE ? OR assignments_json LIKE ? OR config_json LIKE ?)"
        )
        parameters.extend([needle] * 6)
    with index._lock:  # noqa: SLF001 - dashboard is an extension of the same index
        rows = index._connection.execute(  # noqa: SLF001
            f"""
            SELECT run_id, study_id, trial_id, seed, state,
                   COALESCE(model, trial_id) AS model,
                   COALESCE(dataset, 'unknown') AS dataset,
                   config_json, assignments_json, updated_at
            FROM runs WHERE {' AND '.join(clauses)}
            ORDER BY state, trial_id, seed, run_id
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def _catalog(index: MetricIndex, allowed_run_ids: list[str]) -> dict[str, Any]:
    if not allowed_run_ids:
        return {
            "metrics": [],
            "stages": [],
            "kinds": [],
            "states": [],
            "trials": [],
            "models": [],
            "datasets": [],
            "splits": [],
        }
    placeholders = _placeholders(allowed_run_ids)
    with index._lock:  # noqa: SLF001
        connection = index._connection  # noqa: SLF001
        run_rows = connection.execute(
            f"""
            SELECT DISTINCT trial_id, state, COALESCE(model, trial_id) AS model,
                            COALESCE(dataset, 'unknown') AS dataset
            FROM runs WHERE run_id IN ({placeholders})
            """,
            allowed_run_ids,
        ).fetchall()
        event_rows = connection.execute(
            f"""
            SELECT metric, stage, kind, split, COUNT(*) AS n
            FROM metric_events WHERE run_id IN ({placeholders})
            GROUP BY metric, stage, kind, split
            ORDER BY n DESC, metric, stage
            """,
            allowed_run_ids,
        ).fetchall()
    metrics: dict[str, int] = {}
    progress_metrics: dict[str, int] = {}
    for row in event_rows:
        name = str(row["metric"])
        count = int(row["n"])
        metrics[name] = metrics.get(name, 0) + count
        if str(row["kind"]) == "progress":
            progress_metrics[name] = progress_metrics.get(name, 0) + count
    return {
        "metrics": [
            name
            for name, _count in sorted(metrics.items(), key=lambda item: (-item[1], item[0]))
        ],
        "progress_metrics": [
            name
            for name, _count in sorted(
                progress_metrics.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "stages": sorted({str(row["stage"]) for row in event_rows}),
        "kinds": sorted({str(row["kind"]) for row in event_rows}),
        "states": sorted({str(row["state"]) for row in run_rows}),
        "trials": sorted({str(row["trial_id"]) for row in run_rows}),
        "models": sorted({str(row["model"]) for row in run_rows}),
        "datasets": sorted({str(row["dataset"]) for row in run_rows}),
        "splits": sorted({str(row["split"]) for row in event_rows if row["split"] is not None}),
    }


def _default_metrics(catalog: dict[str, Any]) -> list[str]:
    metrics = list(catalog.get("progress_metrics") or catalog.get("metrics") or [])
    preferred_tokens = ("val/", "validation", "loss", "error", "rel_l2", "accuracy")
    preferred = [
        metric
        for metric in metrics
        if any(token in metric.lower() for token in preferred_tokens)
        and not any(token in metric.lower() for token in _RESOURCE_TOKENS)
    ]
    ordinary = [
        metric
        for metric in metrics
        if not any(token in metric.lower() for token in _RESOURCE_TOKENS)
    ]
    return list(dict.fromkeys([*preferred, *ordinary, *metrics]))[:4]


def _current_cursor(index: MetricIndex, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    with index._lock:  # noqa: SLF001
        rows = index._connection.execute(  # noqa: SLF001
            f"""
            SELECT run_id, MAX(sequence) AS sequence FROM metric_events
            WHERE run_id IN ({_placeholders(run_ids)}) GROUP BY run_id
            """,
            run_ids,
        ).fetchall()
    return {str(row["run_id"]): int(row["sequence"] or 0) for row in rows}


def _changed_metrics(
    index: MetricIndex,
    run_ids: list[str],
    metrics: list[str],
    prior_cursor: dict[str, int],
    current_cursor: dict[str, int],
) -> list[str]:
    if not prior_cursor or set(prior_cursor) != set(current_cursor):
        return metrics
    changed_runs = [
        run_id
        for run_id in run_ids
        if current_cursor.get(run_id, 0) > prior_cursor.get(run_id, 0)
    ]
    if not changed_runs or not metrics:
        return []
    minimum = min(prior_cursor.get(run_id, 0) for run_id in changed_runs)
    with index._lock:  # noqa: SLF001
        rows = index._connection.execute(  # noqa: SLF001
            f"""
            SELECT run_id, metric, sequence FROM metric_events
            WHERE run_id IN ({_placeholders(changed_runs)})
              AND metric IN ({_placeholders(metrics)}) AND sequence > ?
            """,
            [*changed_runs, *metrics, minimum],
        ).fetchall()
    changed = {
        str(row["metric"])
        for row in rows
        if int(row["sequence"]) > prior_cursor.get(str(row["run_id"]), 0)
    }
    return [metric for metric in metrics if metric in changed]


def _latest_rows(
    index: MetricIndex,
    run_ids: list[str],
    spec: LiveMetricSpec,
    metrics: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]]]:
    if not run_ids:
        return {}, {}
    clauses = [f"e.run_id IN ({_placeholders(run_ids)})"]
    parameters: list[Any] = [*run_ids]
    if spec.stages:
        clauses.append(f"e.stage IN ({_placeholders(spec.stages)})")
        parameters.extend(spec.stages)
    if spec.kinds:
        clauses.append(f"e.kind IN ({_placeholders(spec.kinds)})")
        parameters.extend(spec.kinds)
    if spec.splits:
        clauses.append(f"e.split IN ({_placeholders(spec.splits)})")
        parameters.extend(spec.splits)
    selected_metrics = list(dict.fromkeys(metrics))
    metric_clause = ""
    if selected_metrics:
        metric_clause = f"AND e.metric IN ({_placeholders(selected_metrics)})"
        parameters.extend(selected_metrics)
    with index._lock:  # noqa: SLF001
        connection = index._connection  # noqa: SLF001
        rows = connection.execute(
            f"""
            WITH ranked AS (
                SELECT e.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY e.run_id, e.metric
                           ORDER BY e.attempt DESC, e.sequence DESC
                       ) AS rank
                FROM metric_events e WHERE {' AND '.join(clauses)} {metric_clause}
            ), progress AS (
                SELECT run_id, MIN(timestamp) AS first_time, MAX(timestamp) AS last_time,
                       MIN(step) AS first_step, MAX(step) AS last_step
                FROM metric_events e WHERE {' AND '.join(clauses)} {metric_clause}
                GROUP BY run_id
            )
            SELECT ranked.run_id, ranked.metric, ranked.value, ranked.step, ranked.step_kind,
                   ranked.sequence, ranked.timestamp, progress.first_time, progress.last_time,
                   progress.first_step, progress.last_step
            FROM ranked JOIN progress ON progress.run_id=ranked.run_id
            WHERE ranked.rank=1 ORDER BY ranked.run_id, ranked.metric
            """,
            [*parameters, *parameters],
        ).fetchall()
        resource_rows = connection.execute(
            f"""
            WITH ranked AS (
                SELECT e.run_id, e.metric, e.value,
                       ROW_NUMBER() OVER (
                           PARTITION BY e.run_id, e.metric
                           ORDER BY e.attempt DESC, e.sequence DESC
                       ) AS rank
                FROM metric_events e
                WHERE e.run_id IN ({_placeholders(run_ids)})
                  AND e.kind='resource'
            )
            SELECT run_id, metric, value FROM ranked WHERE rank=1
            ORDER BY run_id, metric
            """,
            run_ids,
        ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        run = latest.setdefault(
            str(row["run_id"]),
            {
                "metrics": {},
                "step": row["last_step"],
                "step_kind": row["step_kind"],
                "first_time": row["first_time"],
                "last_time": row["last_time"],
                "first_step": row["first_step"],
                "last_step": row["last_step"],
            },
        )
        run["metrics"][str(row["metric"])] = {
            "value": float(row["value"]),
            "step": row["step"],
            "sequence": int(row["sequence"]),
            "timestamp": row["timestamp"],
        }
    resources: dict[str, dict[str, float]] = {}
    for row in resource_rows:
        resources.setdefault(str(row["run_id"]), {})[str(row["metric"])] = float(row["value"])
    return latest, resources


def live_dashboard(
    index: MetricIndex,
    *,
    allowed_run_ids: list[str],
    spec: LiveMetricSpec,
) -> dict[str, Any]:
    """Return a bounded snapshot or only changed metric panels after a cursor."""

    allowed_run_ids = list(dict.fromkeys(allowed_run_ids))
    catalog = _catalog(index, allowed_run_ids)
    metrics = spec.metrics or _default_metrics(catalog)
    scope_rows = _scope_rows(index, allowed_run_ids, spec)
    run_ids = [str(row["run_id"]) for row in scope_rows]
    cursor = _current_cursor(index, run_ids)
    changed_metrics = (
        _changed_metrics(index, run_ids, metrics, spec.cursor, cursor) if run_ids else []
    )

    panels: list[dict[str, Any]] = []
    for metric in changed_metrics:
        filters = MetricFilter(
            run_ids=run_ids,
            stages=spec.stages,
            metrics=[metric],
            kinds=spec.kinds,
            states=spec.states or (sorted(_ACTIVE_STATES) if spec.active_only else []),
            models=spec.models,
            datasets=spec.datasets,
            splits=spec.splits,
        )
        chart = index.chart(
            ChartSpec(
                name=f"live-{metric}",
                artifact_root=str(index.root),
                filters=filters,
                chart_type="line",
                group_by=spec.group_by,
                aggregate=spec.aggregate,
                uncertainty=spec.uncertainty,
                max_points=spec.max_points,
                max_series=spec.max_series,
                y_scale=spec.y_scale,
                title=metric,
                y_label=metric,
            )
        )
        panels.append({"metric": metric, "chart": chart})

    latest, resources = _latest_rows(index, run_ids, spec, metrics)
    runs: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    for row in scope_rows:
        run_id = str(row["run_id"])
        state = str(row["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
        progress = latest.get(run_id, {})
        config = _parse_json_mapping(row.get("config_json"))
        total_steps = _find_total_steps(config)
        eta_seconds = _estimated_remaining_seconds(
            first_time=progress.get("first_time"),
            last_time=progress.get("last_time"),
            first_step=progress.get("first_step"),
            last_step=progress.get("last_step"),
            total_steps=total_steps,
        )
        runs.append(
            {
                "run_id": run_id,
                "study_id": str(row["study_id"]),
                "trial_id": str(row["trial_id"]),
                "seed": row["seed"],
                "state": state,
                "model": str(row["model"]),
                "dataset": str(row["dataset"]),
                "assignments": _parse_json_mapping(row.get("assignments_json")),
                "updated_at": row.get("updated_at"),
                "step": progress.get("step"),
                "step_kind": progress.get("step_kind"),
                "total_steps": total_steps,
                "eta_seconds": eta_seconds,
                "metrics": progress.get("metrics", {}),
                "resources": resources.get(run_id, {}),
            }
        )

    return {
        "spec": spec.model_dump(mode="json", exclude={"cursor"}),
        "selected_metrics": metrics,
        "cursor": cursor,
        "changed": bool(changed_metrics),
        "changed_metrics": changed_metrics,
        "panels": panels,
        "catalog": catalog,
        "summary": {
            "runs": len(runs),
            "job_runs": len(allowed_run_ids),
            "states": state_counts,
            "series_limit": spec.max_series,
            "points_limit": spec.max_points,
        },
        "runs": runs,
    }
