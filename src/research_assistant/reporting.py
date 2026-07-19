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
