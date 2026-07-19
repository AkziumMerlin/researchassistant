from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def collect_summary(
    root: str | Path,
    *,
    stage: str | None = None,
    metric: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate final stage metrics by study and trial across seeds."""
    groups: dict[tuple[str, str, str, str], list[tuple[int | None, float]]] = defaultdict(list)
    root = Path(root)

    for status_path in sorted(root.glob("*/*/status.json")):
        run_dir = status_path.parent
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            status_data = json.loads(status_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if status_data.get("state") != "completed":
            continue

        study_id = str(manifest.get("study_id", "unknown"))
        trial_id = str(manifest.get("trial_id", "unknown"))
        seed = (manifest.get("config") or {}).get("seed")
        for stage_name, stage_status in (status_data.get("stages") or {}).items():
            if stage is not None and stage_name != stage:
                continue
            if stage_status.get("state") != "completed":
                continue
            for metric_name, raw_value in (stage_status.get("metrics") or {}).items():
                if metric is not None and metric_name != metric:
                    continue
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                groups[(study_id, trial_id, str(stage_name), str(metric_name))].append(
                    (seed, value)
                )

    rows: list[dict[str, Any]] = []
    for (study_id, trial_id, stage_name, metric_name), observations in sorted(groups.items()):
        values = [value for _, value in observations]
        rows.append(
            {
                "study_id": study_id,
                "trial_id": trial_id,
                "stage": stage_name,
                "metric": metric_name,
                "n": len(values),
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
                "seeds": sorted(seed for seed, _ in observations if seed is not None),
            }
        )
    return rows


def collect_resource_summary(
    root: str | Path,
    *,
    trial_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate completed resource profiles by exact seed-independent trial identity."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    root = Path(root)
    for resources_path in sorted(root.glob("*/*/resources.json")):
        run_dir = resources_path.parent
        try:
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if status.get("state") != "completed":
            continue
        study_id = str(manifest.get("study_id", "unknown"))
        trial_id = str(manifest.get("trial_id", "unknown"))
        if trial_ids is not None and trial_id not in trial_ids:
            continue
        total = resources.get("total") or {}
        try:
            observation = {
                "wall_seconds": float(total.get("wall_seconds", 0)),
                "gpu_wall_seconds": float(total.get("gpu_wall_seconds", 0)),
                "process_memory_peak_mb": float(total.get("process_memory_peak_mb", 0)),
                "placement_memory_peak_mb": float(
                    total.get("placement_memory_peak_mb", total.get("process_memory_peak_mb", 0))
                ),
                "device_active_seconds": float(total.get("device_active_seconds", 0)),
                "device_energy_joules": float(total.get("device_energy_joules", 0)),
                "attempts": int(total.get("attempts", 0)),
                "seed": (manifest.get("config") or {}).get("seed"),
            }
        except (TypeError, ValueError):
            continue
        groups[(study_id, trial_id)].append(observation)

    rows: list[dict[str, Any]] = []
    for (study_id, trial_id), observations in sorted(groups.items()):
        wall = [item["wall_seconds"] for item in observations]
        gpu_wall = [item["gpu_wall_seconds"] for item in observations]
        memory = [item["process_memory_peak_mb"] for item in observations]
        placement_memory = [item["placement_memory_peak_mb"] for item in observations]
        active = [item["device_active_seconds"] for item in observations]
        energy = [item["device_energy_joules"] for item in observations]
        rows.append(
            {
                "study_id": study_id,
                "trial_id": trial_id,
                "n": len(observations),
                "wall_seconds_mean": statistics.fmean(wall),
                "wall_seconds_std": statistics.stdev(wall) if len(wall) > 1 else 0.0,
                "gpu_hours_mean": statistics.fmean(gpu_wall) / 3600,
                "gpu_hours_total": sum(gpu_wall) / 3600,
                "process_memory_peak_mb_mean": statistics.fmean(memory),
                "process_memory_peak_mb_max": max(memory),
                "placement_memory_peak_mb_mean": statistics.fmean(placement_memory),
                "placement_memory_peak_mb_max": max(placement_memory),
                "device_active_seconds_mean": statistics.fmean(active),
                "device_energy_kwh_mean": statistics.fmean(energy) / 3_600_000,
                "attempts_total": sum(item["attempts"] for item in observations),
                "seeds": sorted(
                    item["seed"] for item in observations if item["seed"] is not None
                ),
            }
        )
    return rows
