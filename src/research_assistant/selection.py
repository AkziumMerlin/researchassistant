from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_assistant.analytics import MetricIndex
from research_assistant.artifacts import utc_now
from research_assistant.asset_registry import AssetRegistry
from research_assistant.errors import ResearchAssistantError


class SelectionError(ResearchAssistantError):
    pass


class SelectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    artifact_root: str = "runs"
    selection_metric: str = Field(min_length=1)
    selection_split: str = "validation"
    target_metrics: list[str] = Field(default_factory=list)
    test_splits: list[str] = Field(default_factory=lambda: ["test", "ood"])
    stage: str | None = None
    direction: Literal["minimize", "maximize"] = "minimize"
    checkpoint_alignment: Literal["same_step", "latest"] = "same_step"
    group_by: list[
        Literal["study_id", "dataset", "model"]
    ] = Field(default_factory=lambda: ["study_id", "dataset", "model"])
    required_seeds: list[int] = Field(default_factory=list)
    min_seeds: int = Field(default=1, ge=1, le=1000)
    allowed_states: list[str] = Field(default_factory=lambda: ["completed"])
    promote_checkpoints: bool = True
    strict_test_lock: bool = True

    @field_validator("target_metrics", "test_splits", "allowed_states")
    @classmethod
    def unique_strings(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in value if item))

    @model_validator(mode="after")
    def validation_only(self) -> SelectionSpec:
        normalized = self.selection_split.lower()
        forbidden = {"test", "ood", "out", "out_of_distribution", "id_test"}
        if normalized in forbidden or "test" in normalized or "ood" in normalized:
            raise ValueError("selection_split must be validation-only; test/OOD leakage is forbidden")
        if self.selection_split in self.test_splits:
            raise ValueError("selection_split cannot also be a target test split")
        if len(self.group_by) != len(set(self.group_by)):
            raise ValueError("group_by fields must be unique")
        return self


def load_selection_spec(path: str | Path) -> SelectionSpec:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SelectionError(f"cannot read selection spec {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SelectionError(f"invalid selection YAML {source}: {exc}") from exc
    try:
        return SelectionSpec.model_validate(payload)
    except ValueError as exc:
        raise SelectionError(str(exc)) from exc


def _safe_root(workspace: Path, raw: str) -> Path:
    root = (workspace / raw).resolve()
    if not root.is_relative_to(workspace) or root == workspace:
        raise SelectionError("artifact root must be a subdirectory of the workspace")
    return root


def _best_by_run(index: MetricIndex, spec: SelectionSpec) -> list[dict[str, Any]]:
    clauses = [
        "e.metric = ?",
        "COALESCE(e.split, '') = ?",
        f"r.state IN ({','.join('?' for _ in spec.allowed_states)})",
    ]
    parameters: list[Any] = [
        spec.selection_metric,
        spec.selection_split,
        *spec.allowed_states,
    ]
    if spec.stage:
        clauses.append("e.stage = ?")
        parameters.append(spec.stage)
    direction_sql = "ASC" if spec.direction == "minimize" else "DESC"
    with index._lock:  # noqa: SLF001 - selection is a first-party index consumer
        rows = index._connection.execute(  # noqa: SLF001
            f"""
            WITH ranked AS (
                SELECT
                    e.run_id, r.study_id, r.trial_id, r.seed, r.model, r.dataset,
                    e.stage, e.metric, e.value, e.step, e.attempt, e.sequence,
                    ROW_NUMBER() OVER (
                        PARTITION BY e.run_id
                        ORDER BY e.value {direction_sql}, e.step DESC, e.sequence DESC
                    ) AS rank
                FROM metric_events e
                JOIN runs r ON r.run_id = e.run_id
                WHERE {' AND '.join(clauses)}
            )
            SELECT * FROM ranked WHERE rank = 1
            ORDER BY study_id, dataset, model, trial_id, seed
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def _group_key(row: dict[str, Any], fields: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field) if row.get(field) is not None else "unknown") for field in fields)


def _trial_summary(rows: list[dict[str, Any]], spec: SelectionSpec) -> list[dict[str, Any]]:
    grouped: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(_group_key(row, spec.group_by), str(row["trial_id"]))].append(row)
    summaries: list[dict[str, Any]] = []
    required = set(spec.required_seeds)
    for (group, trial_id), trial_rows in grouped.items():
        seeds = {int(row["seed"]) for row in trial_rows if row.get("seed") is not None}
        missing = sorted(required - seeds)
        eligible = len(seeds) >= spec.min_seeds and not missing
        values = [float(row["value"]) for row in trial_rows if math.isfinite(float(row["value"]))]
        if not values:
            eligible = False
        summaries.append(
            {
                "group": dict(zip(spec.group_by, group, strict=True)),
                "group_key": group,
                "trial_id": trial_id,
                "eligible": eligible,
                "seeds": sorted(seeds),
                "missing_seeds": missing,
                "n": len(values),
                "mean": statistics.fmean(values) if values else None,
                "std": statistics.stdev(values) if len(values) > 1 else 0.0 if values else None,
                "runs": trial_rows,
            }
        )
    return summaries


def preview_selection(workspace: str | Path, spec: SelectionSpec) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    root = _safe_root(workspace_path, spec.artifact_root)
    index = MetricIndex(root)
    try:
        refresh = index.refresh()
        rows = _best_by_run(index, spec)
    finally:
        index.close()
    summaries = _trial_summary(rows, spec)
    candidates = [row for row in summaries if row["eligible"]]
    winners: list[dict[str, Any]] = []
    for group in sorted({tuple(row["group_key"]) for row in candidates}):
        options = [row for row in candidates if tuple(row["group_key"]) == group]
        reverse = spec.direction == "maximize"
        options.sort(
            key=lambda row: (
                -float(row["mean"]) if reverse else float(row["mean"]),
                float(row["std"] or 0.0),
                str(row["trial_id"]),
            )
        )
        if options:
            winners.append(options[0])
    return {
        "name": spec.name,
        "selection_metric": spec.selection_metric,
        "selection_split": spec.selection_split,
        "direction": spec.direction,
        "index": refresh,
        "runs": len(rows),
        "trials": len(summaries),
        "eligible_trials": len(candidates),
        "rejected_trials": [row for row in summaries if not row["eligible"]],
        "winners": winners,
    }


def _lock_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _selected_checkpoint_assets(
    workspace: Path,
    winner_runs: list[dict[str, Any]],
    promote: bool,
    artifact_root: str,
) -> list[dict[str, Any]]:
    selected_ids = {str(row["run_id"]) for row in winner_runs}
    registry = AssetRegistry(workspace)
    try:
        registry.refresh(artifact_root)
        assets = [
            row
            for row in registry.list(kind="checkpoint", limit=10000)
            if str(row.get("run_id")) in selected_ids
        ]
        chosen: list[dict[str, Any]] = []
        for run_id in sorted(selected_ids):
            candidates = [row for row in assets if str(row.get("run_id")) == run_id]
            if not candidates:
                continue
            candidates.sort(
                key=lambda row: (
                    "best" not in str(row.get("name", "")).lower(),
                    -int(row.get("size", 0)),
                    str(row.get("asset_id")),
                )
            )
            asset = candidates[0]
            if promote:
                asset = registry.promote(str(asset["asset_id"]), "selected")
                registry.pin(str(asset["asset_id"]), True)
            chosen.append(asset)
        return chosen
    finally:
        registry.close()


def lock_selection(
    workspace: str | Path,
    spec: SelectionSpec,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    preview = preview_selection(workspace_path, spec)
    winners = preview["winners"]
    if not winners:
        raise SelectionError("no eligible validation-only winner could be selected")
    winner_runs = [
        run
        for winner in winners
        for run in winner["runs"]
    ]
    checkpoints = _selected_checkpoint_assets(
        workspace_path,
        winner_runs,
        spec.promote_checkpoints,
        spec.artifact_root,
    )
    payload = {
        "schema_version": 1,
        "name": spec.name,
        "created_at": utc_now(),
        "protocol": spec.model_dump(mode="json"),
        "selection_only": {
            "metric": spec.selection_metric,
            "split": spec.selection_split,
            "direction": spec.direction,
        },
        "test_locked": bool(spec.strict_test_lock),
        "winners": winners,
        "checkpoints": checkpoints,
        "selected_run_ids": sorted({str(row["run_id"]) for row in winner_runs}),
        "selected_trial_ids": sorted({str(row["trial_id"]) for row in winner_runs}),
    }
    payload["lock_digest"] = _lock_digest(payload)
    directory = workspace_path / ".ra" / "selections"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{spec.name}.json"
    if path.exists() and not overwrite:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("lock_digest") != payload["lock_digest"]:
            raise SelectionError(
                f"selection lock already exists with different content: {path}; use --overwrite"
            )
        return existing
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def load_selection_lock(workspace: str | Path, name_or_path: str | Path) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    raw = Path(name_or_path)
    path = raw if raw.suffix == ".json" else workspace_path / ".ra" / "selections" / f"{raw}.json"
    path = path.resolve() if path.is_absolute() else (workspace_path / path).resolve()
    if not path.is_relative_to(workspace_path) or not path.is_file():
        raise SelectionError(f"selection lock does not exist inside workspace: {name_or_path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SelectionError(f"cannot read selection lock {path}: {exc}") from exc
    digest = payload.pop("lock_digest", None)
    actual = _lock_digest(payload)
    payload["lock_digest"] = digest
    if digest != actual:
        raise SelectionError(f"selection lock checksum mismatch: {path}")
    return payload


def evaluate_selection(
    workspace: str | Path,
    name_or_path: str | Path,
    *,
    output: str | Path | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    lock = load_selection_lock(workspace_path, name_or_path)
    protocol = SelectionSpec.model_validate(lock["protocol"])
    run_ids = list(lock.get("selected_run_ids") or [])
    metrics = protocol.target_metrics or [protocol.selection_metric]
    if not protocol.test_splits:
        raise SelectionError("selection protocol defines no target test splits")
    root = _safe_root(workspace_path, protocol.artifact_root)
    selected_steps = {
        str(run["run_id"]): run.get("step")
        for winner in lock.get("winners") or []
        for run in winner.get("runs") or []
    }
    index = MetricIndex(root)
    try:
        index.refresh()
        placeholders_runs = ",".join("?" for _ in run_ids)
        placeholders_metrics = ",".join("?" for _ in metrics)
        placeholders_splits = ",".join("?" for _ in protocol.test_splits)
        with index._lock:  # noqa: SLF001
            rows = index._connection.execute(  # noqa: SLF001
                f"""
                SELECT e.*, r.study_id, r.trial_id, r.seed, r.model, r.dataset
                FROM metric_events e JOIN runs r ON r.run_id = e.run_id
                WHERE e.run_id IN ({placeholders_runs})
                  AND e.metric IN ({placeholders_metrics})
                  AND COALESCE(e.split, '') IN ({placeholders_splits})
                  {('AND e.stage = ?' if protocol.stage else '')}
                ORDER BY e.run_id, e.metric, e.split, e.step DESC, e.sequence DESC
                """,
                [
                    *run_ids,
                    *metrics,
                    *protocol.test_splits,
                    *([protocol.stage] if protocol.stage else []),
                ],
            ).fetchall()
    finally:
        index.close()
    grouped_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        grouped_rows[
            (
                str(row["run_id"]),
                str(row["metric"]),
                str(row.get("split") or "unknown"),
            )
        ].append(row)
    values: list[dict[str, Any]] = []
    missing_alignment: list[dict[str, Any]] = []
    for key, candidates in sorted(grouped_rows.items()):
        if protocol.checkpoint_alignment == "latest":
            values.append(candidates[0])
            continue
        selected_step = selected_steps.get(key[0])
        match = next(
            (
                row
                for row in candidates
                if selected_step is not None
                and row.get("step") is not None
                and abs(float(row["step"]) - float(selected_step)) < 1e-12
            ),
            None,
        )
        if match is None:
            missing_alignment.append(
                {
                    "run_id": key[0],
                    "metric": key[1],
                    "split": key[2],
                    "selected_step": selected_step,
                }
            )
        else:
            values.append(match)
    if missing_alignment:
        raise SelectionError(
            "target metrics are missing at validation-selected checkpoint steps: "
            + json.dumps(missing_alignment[:20], sort_keys=True)
        )
    aggregate: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in values:
        key = (
            str(row.get("dataset") or "unknown"),
            str(row["metric"]),
            str(row.get("split") or "unknown"),
        )
        aggregate[key].append(float(row["value"]))
    summary = [
        {
            "dataset": key[0],
            "metric": key[1],
            "split": key[2],
            "n": len(items),
            "mean": statistics.fmean(items),
            "std": statistics.stdev(items) if len(items) > 1 else 0.0,
        }
        for key, items in sorted(aggregate.items())
    ]
    result = {
        "schema_version": 1,
        "evaluated_at": utc_now(),
        "selection_name": lock["name"],
        "selection_digest": lock["lock_digest"],
        "run_ids": run_ids,
        "values": values,
        "summary": summary,
    }
    if output is not None:
        target = Path(output)
        target = target.resolve() if target.is_absolute() else (workspace_path / target).resolve()
        if not target.is_relative_to(workspace_path):
            raise SelectionError("selection evaluation output escapes workspace")
        target.mkdir(parents=True, exist_ok=True)
        (target / "evaluation.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with (target / "evaluation.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=["dataset", "metric", "split", "n", "mean", "std"]
            )
            writer.writeheader()
            writer.writerows(summary)
        lines = [
            r"\begin{tabular}{lllrrr}",
            r"\hline",
            r"Dataset & Metric & Split & $n$ & Mean & Std. \\",
            r"\hline",
        ]
        for row in summary:
            lines.append(
                f"{row['dataset']} & {row['metric']} & {row['split']} & "
                f"{row['n']} & {row['mean']:.6g} & {row['std']:.6g} \\\\"
            )
        lines.extend([r"\hline", r"\end{tabular}", ""])
        (target / "evaluation.tex").write_text("\n".join(lines), encoding="utf-8")
    return result


def list_selection_locks(workspace: str | Path) -> list[dict[str, Any]]:
    root = Path(workspace).resolve() / ".ra" / "selections"
    result: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            payload = load_selection_lock(workspace, path)
        except SelectionError:
            continue
        result.append(
            {
                "name": payload.get("name"),
                "created_at": payload.get("created_at"),
                "lock_digest": payload.get("lock_digest"),
                "selected_runs": len(payload.get("selected_run_ids") or []),
                "selected_trials": len(payload.get("selected_trial_ids") or []),
                "path": path.relative_to(Path(workspace).resolve()).as_posix(),
            }
        )
    return result
