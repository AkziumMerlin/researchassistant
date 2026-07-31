from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_assistant.analytics import MetricIndex
from research_assistant.artifacts import utc_now
from research_assistant.errors import ResearchAssistantError
from research_assistant.selection import load_selection_lock


class StatisticalError(ResearchAssistantError):
    pass


class StatisticalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="statistical-analysis", min_length=1, max_length=160)
    artifact_root: str = "runs"
    metric: str = Field(min_length=1)
    split: str | None = None
    stage: str | None = None
    kind: Literal["progress", "final", "resource"] | None = None
    direction: Literal["minimize", "maximize"] = "minimize"
    group_by: Literal["model", "trial_id", "study_id", "dataset"] = "model"
    paired_by: list[Literal["seed", "dataset", "split", "study_id"]] = Field(
        default_factory=lambda: ["seed", "dataset"]
    )
    baseline: str | None = None
    run_ids: list[str] = Field(default_factory=list)
    selection_lock: str | None = None
    confidence: float = Field(default=0.95, gt=0.5, lt=1.0)
    bootstrap_samples: int = Field(default=5000, ge=100, le=200000)
    permutation_samples: int = Field(default=20000, ge=100, le=500000)
    correction: Literal["none", "bonferroni", "holm", "fdr_bh"] = "holm"
    missing_pair_policy: Literal["drop", "error"] = "drop"
    seed: int = 0
    max_runs: int = Field(default=10000, ge=1, le=100000)

    @field_validator("paired_by", "run_ids")
    @classmethod
    def unique_values(cls, value: list[Any]) -> list[Any]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def valid_pairing(self) -> StatisticalSpec:
        if not self.paired_by:
            raise ValueError("paired_by must contain at least one key")
        return self


def load_statistical_spec(path: str | Path) -> StatisticalSpec:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StatisticalError(f"cannot read statistical spec {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise StatisticalError(f"invalid statistical YAML {source}: {exc}") from exc
    try:
        return StatisticalSpec.model_validate(payload)
    except ValueError as exc:
        raise StatisticalError(str(exc)) from exc


def _safe_root(workspace: Path, raw: str) -> Path:
    path = (workspace / raw).resolve()
    if not path.is_relative_to(workspace) or path == workspace:
        raise StatisticalError("artifact root must be a workspace subdirectory")
    return path


def _selected_run_ids(workspace: Path, spec: StatisticalSpec) -> list[str]:
    if spec.selection_lock:
        lock = load_selection_lock(workspace, spec.selection_lock)
        locked = [str(value) for value in lock.get("selected_run_ids") or []]
        if spec.run_ids:
            return sorted(set(locked).intersection(spec.run_ids))
        return locked
    return list(spec.run_ids)


def _latest_values(index: MetricIndex, spec: StatisticalSpec, run_ids: list[str]) -> list[dict[str, Any]]:
    clauses = ["e.metric = ?"]
    parameters: list[Any] = [spec.metric]
    if spec.split is not None:
        clauses.append("COALESCE(e.split, '') = ?")
        parameters.append(spec.split)
    if spec.stage is not None:
        clauses.append("e.stage = ?")
        parameters.append(spec.stage)
    if spec.kind is not None:
        clauses.append("e.kind = ?")
        parameters.append(spec.kind)
    if run_ids:
        clauses.append(f"e.run_id IN ({','.join('?' for _ in run_ids)})")
        parameters.extend(run_ids)
    with index._lock:  # noqa: SLF001
        rows = index._connection.execute(  # noqa: SLF001
            f"""
            WITH ranked AS (
                SELECT
                    e.run_id, e.metric, e.value, e.step, e.stage, e.kind,
                    COALESCE(e.split, 'unknown') AS split,
                    r.study_id, r.trial_id, r.seed,
                    COALESCE(r.model, r.trial_id) AS model,
                    COALESCE(r.dataset, e.dataset, 'unknown') AS dataset,
                    ROW_NUMBER() OVER (
                        PARTITION BY e.run_id
                        ORDER BY e.step DESC, e.sequence DESC
                    ) AS rank
                FROM metric_events e JOIN runs r ON r.run_id = e.run_id
                WHERE {' AND '.join(clauses)}
            )
            SELECT * FROM ranked WHERE rank = 1
            ORDER BY model, trial_id, dataset, seed
            LIMIT ?
            """,
            [*parameters, spec.max_runs],
        ).fetchall()
    return [dict(row) for row in rows]


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bootstrap_ci(
    values: list[float], *, confidence: float, samples: int, rng: random.Random
) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    if len(values) == 1:
        return values[0], values[0]
    means = [
        statistics.fmean(rng.choice(values) for _ in range(len(values)))
        for _ in range(samples)
    ]
    alpha = (1.0 - confidence) / 2.0
    return _percentile(means, alpha), _percentile(means, 1.0 - alpha)


def _paired_effect(differences: list[float]) -> float | None:
    if len(differences) < 2:
        return None
    spread = statistics.stdev(differences)
    if spread == 0:
        return math.inf if statistics.fmean(differences) != 0 else 0.0
    return statistics.fmean(differences) / spread


def _paired_permutation_p(
    differences: list[float], *, samples: int, rng: random.Random
) -> float | None:
    if not differences:
        return None
    observed = abs(statistics.fmean(differences))
    n = len(differences)
    if n <= 18:
        total = 1 << n
        extreme = 0
        for mask in range(total):
            value = statistics.fmean(
                difference if mask & (1 << index) else -difference
                for index, difference in enumerate(differences)
            )
            extreme += abs(value) >= observed - 1e-15
        return extreme / total
    extreme = 0
    for _ in range(samples):
        value = statistics.fmean(
            difference if rng.random() < 0.5 else -difference
            for difference in differences
        )
        extreme += abs(value) >= observed - 1e-15
    return (extreme + 1) / (samples + 1)


def _adjust_pvalues(rows: list[dict[str, Any]], method: str) -> None:
    indices = [index for index, row in enumerate(rows) if row.get("p_value") is not None]
    if not indices:
        return
    values = [(index, float(rows[index]["p_value"])) for index in indices]
    m = len(values)
    if method == "none":
        for index, value in values:
            rows[index]["p_adjusted"] = value
        return
    if method == "bonferroni":
        for index, value in values:
            rows[index]["p_adjusted"] = min(1.0, value * m)
        return
    ordered = sorted(values, key=lambda item: item[1])
    if method == "holm":
        running = 0.0
        for rank, (index, value) in enumerate(ordered):
            adjusted = min(1.0, (m - rank) * value)
            running = max(running, adjusted)
            rows[index]["p_adjusted"] = running
        return
    if method == "fdr_bh":
        running = 1.0
        for reverse_rank, (index, value) in enumerate(reversed(ordered), start=1):
            rank = m - reverse_rank + 1
            adjusted = min(running, value * m / rank)
            running = adjusted
            rows[index]["p_adjusted"] = min(1.0, adjusted)


def _pair_key(row: dict[str, Any], fields: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field) if row.get(field) is not None else "unknown") for field in fields)


def analyze_statistics(workspace: str | Path, spec: StatisticalSpec) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    root = _safe_root(workspace_path, spec.artifact_root)
    index = MetricIndex(root)
    try:
        refresh = index.refresh()
        values = _latest_values(index, spec, _selected_run_ids(workspace_path, spec))
    finally:
        index.close()
    if not values:
        raise StatisticalError("no metric values match the statistical specification")
    rng = random.Random(spec.seed)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in values:
        groups[str(row.get(spec.group_by) or "unknown")].append(row)
    summary: list[dict[str, Any]] = []
    for name, rows in sorted(groups.items()):
        numeric = [float(row["value"]) for row in rows]
        lower, upper = _bootstrap_ci(
            numeric,
            confidence=spec.confidence,
            samples=spec.bootstrap_samples,
            rng=rng,
        )
        summary.append(
            {
                "group": name,
                "n": len(numeric),
                "mean": statistics.fmean(numeric),
                "std": statistics.stdev(numeric) if len(numeric) > 1 else 0.0,
                "median": statistics.median(numeric),
                "minimum": min(numeric),
                "maximum": max(numeric),
                "ci_low": lower,
                "ci_high": upper,
            }
        )
    baseline = spec.baseline
    if baseline is None:
        summary_ordered = sorted(
            summary,
            key=lambda row: (
                float(row["mean"]) if spec.direction == "minimize" else -float(row["mean"]),
                str(row["group"]),
            ),
        )
        baseline = str(summary_ordered[0]["group"])
    if baseline not in groups:
        raise StatisticalError(f"baseline group is absent: {baseline}")
    baseline_map = {
        _pair_key(row, spec.paired_by): float(row["value"])
        for row in groups[baseline]
    }
    comparisons: list[dict[str, Any]] = []
    for name, rows in sorted(groups.items()):
        if name == baseline:
            continue
        candidate_map = {
            _pair_key(row, spec.paired_by): float(row["value"])
            for row in rows
        }
        common = sorted(set(baseline_map).intersection(candidate_map))
        missing_baseline = sorted(set(candidate_map) - set(baseline_map))
        missing_candidate = sorted(set(baseline_map) - set(candidate_map))
        if spec.missing_pair_policy == "error" and (missing_baseline or missing_candidate):
            raise StatisticalError(
                f"incomplete pairing for {baseline} vs {name}: "
                f"{len(missing_baseline)} missing baseline, "
                f"{len(missing_candidate)} missing candidate"
            )
        raw_differences = [candidate_map[key] - baseline_map[key] for key in common]
        oriented = [
            difference if spec.direction == "minimize" else -difference
            for difference in raw_differences
        ]
        lower, upper = _bootstrap_ci(
            raw_differences,
            confidence=spec.confidence,
            samples=spec.bootstrap_samples,
            rng=rng,
        ) if raw_differences else (math.nan, math.nan)
        comparison = {
            "baseline": baseline,
            "candidate": name,
            "pairs": len(common),
            "mean_difference": (
                statistics.fmean(raw_differences) if raw_differences else None
            ),
            "ci_low": lower if raw_differences else None,
            "ci_high": upper if raw_differences else None,
            "effect_dz": _paired_effect(raw_differences),
            "p_value": _paired_permutation_p(
                raw_differences, samples=spec.permutation_samples, rng=rng
            ),
            "candidate_wins": sum(value < 0 for value in oriented),
            "baseline_wins": sum(value > 0 for value in oriented),
            "ties": sum(value == 0 for value in oriented),
            "missing_baseline": [list(key) for key in missing_baseline],
            "missing_candidate": [list(key) for key in missing_candidate],
        }
        comparisons.append(comparison)
    _adjust_pvalues(comparisons, spec.correction)
    missing_cells: list[dict[str, Any]] = []
    all_keys = set().union(*({_pair_key(row, spec.paired_by) for row in rows} for rows in groups.values()))
    for group, rows in sorted(groups.items()):
        present = {_pair_key(row, spec.paired_by) for row in rows}
        missing = sorted(all_keys - present)
        if missing:
            missing_cells.append({"group": group, "missing": [list(key) for key in missing]})
    digest_payload = {
        "spec": spec.model_dump(mode="json"),
        "run_ids": sorted(str(row["run_id"]) for row in values),
        "values": [(str(row["run_id"]), float(row["value"])) for row in values],
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "analysis_digest": digest,
        "spec": spec.model_dump(mode="json"),
        "index": refresh,
        "baseline": baseline,
        "values": values,
        "summary": summary,
        "comparisons": comparisons,
        "missing_cells": missing_cells,
    }


def write_statistical_report(
    workspace: str | Path,
    spec: StatisticalSpec,
    destination: str | Path,
) -> Path:
    workspace_path = Path(workspace).resolve()
    target = Path(destination)
    target = target.resolve() if target.is_absolute() else (workspace_path / target).resolve()
    if not target.is_relative_to(workspace_path):
        raise StatisticalError("statistical report destination escapes workspace")
    target.mkdir(parents=True, exist_ok=True)
    result = analyze_statistics(workspace_path, spec)
    (target / "analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (target / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        fieldnames = [
            "group", "n", "mean", "std", "median", "minimum", "maximum", "ci_low", "ci_high"
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result["summary"])
    with (target / "comparisons.csv").open("w", encoding="utf-8", newline="") as stream:
        fieldnames = [
            "baseline", "candidate", "pairs", "mean_difference", "ci_low", "ci_high",
            "effect_dz", "p_value", "p_adjusted", "candidate_wins", "baseline_wins", "ties",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["comparisons"])
    lines = [
        r"\begin{tabular}{lrrrrrr}",
        r"\hline",
        r"Group & $n$ & Mean & Std. & Median & CI low & CI high \\",
        r"\hline",
    ]
    for row in result["summary"]:
        lines.append(
            f"{row['group']} & {row['n']} & {row['mean']:.6g} & {row['std']:.6g} & "
            f"{row['median']:.6g} & {row['ci_low']:.6g} & {row['ci_high']:.6g} \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}", ""])
    (target / "summary.tex").write_text("\n".join(lines), encoding="utf-8")
    return target
