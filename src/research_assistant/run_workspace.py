from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from research_assistant.errors import ResearchAssistantError

TERMINAL_RUN_STATES = {"completed", "failed", "interrupted", "cancelled", "preempted"}


class RunWorkspaceError(ResearchAssistantError):
    pass


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _component_name(config: dict[str, Any], kind: str) -> str | None:
    reference = (config.get("components") or {}).get(kind)
    if not isinstance(reference, dict):
        return None
    value = reference.get("type")
    return str(value) if value is not None else None


def _stage_metrics(status: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stages = status.get("stages")
    if not isinstance(stages, dict):
        return rows
    for stage_name, stage_state in stages.items():
        if not isinstance(stage_state, dict):
            continue
        metrics = stage_state.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for metric_name, raw_value in metrics.items():
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "stage": str(stage_name),
                    "metric": str(metric_name),
                    "value": value,
                    "stage_state": str(stage_state.get("state", "unknown")),
                }
            )
    return rows


class RunWorkspace:
    def __init__(self, workspace: str | Path, artifact_root: str | Path = "runs") -> None:
        self.workspace = Path(workspace).resolve()
        raw_root = Path(artifact_root)
        self.root = (
            raw_root.resolve()
            if raw_root.is_absolute()
            else (self.workspace / raw_root).resolve()
        )
        if not self.root.is_relative_to(self.workspace) or self.root == self.workspace:
            raise RunWorkspaceError("artifact root must be a directory inside the workspace")

    def _rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.root.is_dir():
            return rows
        for manifest_path in sorted(self.root.glob("*/*/manifest.json")):
            run_dir = manifest_path.parent
            manifest = _read_mapping(manifest_path)
            if not manifest:
                continue
            status = _read_mapping(run_dir / "status.json")
            resources = _read_mapping(run_dir / "resources.json")
            config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
            experiment = (
                config.get("experiment")
                if isinstance(config.get("experiment"), dict)
                else {}
            )
            total_resources = (
                resources.get("total")
                if isinstance(resources.get("total"), dict)
                else {}
            )
            state = str(status.get("state", "pending"))
            row = {
                "study_id": str(manifest.get("study_id", run_dir.parent.name)),
                "trial_id": str(manifest.get("trial_id", "unknown")),
                "run_id": str(manifest.get("run_id", run_dir.name)),
                "path": run_dir.relative_to(self.workspace).as_posix(),
                "state": state,
                "terminal": state in TERMINAL_RUN_STATES,
                "attempt": status.get("attempt"),
                "updated_at": status.get("updated_at"),
                "seed": config.get("seed"),
                "experiment": str(experiment.get("name", manifest.get("study_id", "unknown"))),
                "tags": list(experiment.get("tags") or []),
                "model": _component_name(config, "model"),
                "dataset": _component_name(config, "data"),
                "recipe": _component_name(config, "recipe"),
                "assignments": dict(manifest.get("assignments") or {}),
                "provenance": dict(manifest.get("provenance") or {}),
                "metrics": _stage_metrics(status),
                "resources": {
                    "wall_seconds": total_resources.get("wall_seconds"),
                    "gpu_wall_seconds": total_resources.get("gpu_wall_seconds"),
                    "placement_memory_peak_mb": total_resources.get(
                        "placement_memory_peak_mb",
                        total_resources.get("process_memory_peak_mb"),
                    ),
                    "device_energy_joules": total_resources.get("device_energy_joules"),
                    "attempts": total_resources.get("attempts"),
                },
            }
            rows.append(row)
        return rows

    def catalog(
        self,
        *,
        study_ids: set[str] | None = None,
        states: set[str] | None = None,
        search: str | None = None,
        limit: int = 5000,
    ) -> dict[str, Any]:
        query = (search or "").strip().lower()
        rows: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        study_counts: dict[str, int] = {}
        for row in self._rows():
            if study_ids and row["study_id"] not in study_ids:
                continue
            if states and row["state"] not in states:
                continue
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("study_id", "trial_id", "run_id", "experiment", "model", "dataset")
            ).lower()
            if query and query not in haystack:
                continue
            counts[row["state"]] = counts.get(row["state"], 0) + 1
            study_counts[row["study_id"]] = study_counts.get(row["study_id"], 0) + 1
            rows.append(row)
        total = len(rows)
        rows.sort(
            key=lambda item: (
                str(item.get("study_id", "")),
                str(item.get("trial_id", "")),
                str(item.get("run_id", "")),
            )
        )
        return {
            "artifact_root": self.root.relative_to(self.workspace).as_posix(),
            "total": total,
            "truncated": total > limit,
            "counts": counts,
            "studies": [
                {"study_id": study_id, "runs": count}
                for study_id, count in sorted(study_counts.items())
            ],
            "runs": rows[:limit],
        }

    def require_runs(self, run_ids: list[str]) -> list[dict[str, Any]]:
        requested = list(dict.fromkeys(run_ids))
        if not requested:
            raise RunWorkspaceError("select at least one run")
        by_id = {row["run_id"]: row for row in self._rows()}
        missing = [run_id for run_id in requested if run_id not in by_id]
        if missing:
            raise RunWorkspaceError(f"unknown run identifiers: {', '.join(missing)}")
        return [by_id[run_id] for run_id in requested]

    def aggregate(
        self,
        run_ids: list[str],
        *,
        metric: str | None = None,
        stage: str | None = None,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        rows = self.require_runs(run_ids)
        dimensions = group_by or ["study_id", "trial_id"]
        allowed = {
            "study_id",
            "trial_id",
            "model",
            "dataset",
            "recipe",
            "state",
            "experiment",
        }
        unknown = [item for item in dimensions if item not in allowed]
        if unknown:
            raise RunWorkspaceError(f"unsupported aggregation dimensions: {', '.join(unknown)}")

        observations: dict[tuple[tuple[str, str], ...], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            for item in row["metrics"]:
                if metric is not None and item["metric"] != metric:
                    continue
                if stage is not None and item["stage"] != stage:
                    continue
                key = tuple((name, str(row.get(name) or "unknown")) for name in dimensions)
                observations[key].append(
                    {
                        "run_id": row["run_id"],
                        "seed": row["seed"],
                        "stage": item["stage"],
                        "metric": item["metric"],
                        "value": item["value"],
                    }
                )

        groups: list[dict[str, Any]] = []
        for key, items in sorted(observations.items()):
            by_metric: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for item in items:
                by_metric[(item["stage"], item["metric"])].append(item)
            for (stage_name, metric_name), metric_items in sorted(by_metric.items()):
                values = [float(item["value"]) for item in metric_items]
                groups.append(
                    {
                        "dimensions": dict(key),
                        "stage": stage_name,
                        "metric": metric_name,
                        "n": len(values),
                        "mean": statistics.fmean(values),
                        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                        "minimum": min(values),
                        "maximum": max(values),
                        "median": statistics.median(values),
                        "run_ids": [item["run_id"] for item in metric_items],
                        "seeds": sorted(
                            item["seed"] for item in metric_items if item["seed"] is not None
                        ),
                    }
                )
        return {
            "artifact_root": self.root.relative_to(self.workspace).as_posix(),
            "selected_runs": [row["run_id"] for row in rows],
            "group_by": dimensions,
            "metric_filter": metric,
            "stage_filter": stage,
            "groups": groups,
        }

    def lineage_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.require_runs([run_id])[0]
        run_dir = self.workspace / row["path"]
        return {
            "run": row,
            "manifest": _read_mapping(run_dir / "manifest.json"),
            "status": _read_mapping(run_dir / "status.json"),
            "launcher": _read_mapping(run_dir / "launcher.json"),
            "resources": _read_mapping(run_dir / "resources.json"),
        }
