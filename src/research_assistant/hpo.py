from __future__ import annotations

import hashlib
import itertools
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
from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError
from research_assistant.jobs import JobService, JobStartRequest


class HpoError(ResearchAssistantError):
    pass


class SearchParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["categorical", "int", "float"]
    choices: list[Any] = Field(default_factory=list)
    low: float | int | None = None
    high: float | int | None = None
    step: float | int | None = None
    log: bool = False
    condition: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_domain(self) -> SearchParameter:
        if self.type == "categorical":
            if not self.choices:
                raise ValueError("categorical parameter requires non-empty choices")
            return self
        if self.low is None or self.high is None:
            raise ValueError(f"{self.type} parameter requires low and high")
        if float(self.low) >= float(self.high):
            raise ValueError("parameter low must be smaller than high")
        if self.step is not None and float(self.step) <= 0:
            raise ValueError("parameter step must be positive")
        if self.log and (float(self.low) <= 0 or float(self.high) <= 0):
            raise ValueError("log-scaled parameters require positive bounds")
        return self


class HpoObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1)
    split: str = "validation"
    stage: str | None = None
    kind: Literal["progress", "final"] = "progress"
    direction: Literal["minimize", "maximize"] = "minimize"
    weight: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def validation_only(self) -> HpoObjective:
        normalized = self.split.lower()
        if "test" in normalized or "ood" in normalized or normalized in {"out", "id_test"}:
            raise ValueError("HPO objectives must use validation data, never test/OOD data")
        return self


class AshaPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    resource_steps: list[int] = Field(default_factory=lambda: [25, 50, 100, 200])
    reduction_factor: int = Field(default=3, ge=2, le=20)
    grace_step: int = Field(default=25, ge=1)

    @field_validator("resource_steps")
    @classmethod
    def ordered_unique(cls, values: list[int]) -> list[int]:
        result = sorted(set(value for value in values if value > 0))
        if not result:
            raise ValueError("ASHA requires at least one positive resource step")
        return result


class HpoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    base_config: str = Field(min_length=1)
    artifact_root: str = "runs"
    search_space: dict[str, SearchParameter]
    objectives: list[HpoObjective] = Field(min_length=1, max_length=4)
    sampler: Literal["random", "grid", "tpe"] = "tpe"
    max_trials: int = Field(default=50, ge=1, le=100000)
    parallelism: int = Field(default=1, ge=1, le=1000)
    seed: int = 0
    startup_trials: int = Field(default=8, ge=1, le=10000)
    good_fraction: float = Field(default=0.25, gt=0.05, lt=0.5)
    max_gpu_hours: float | None = Field(default=None, gt=0)
    max_wall_hours: float | None = Field(default=None, gt=0)
    max_failed_trials: int | None = Field(default=None, ge=0)
    plugins: list[str] = Field(default_factory=list)
    launcher_path: str | None = None
    launcher_overrides: list[str] = Field(default_factory=list)
    config_overrides: list[str] = Field(default_factory=list)
    asha: AshaPolicy = Field(default_factory=AshaPolicy)

    @field_validator("search_space")
    @classmethod
    def non_empty_space(
        cls, value: dict[str, SearchParameter]
    ) -> dict[str, SearchParameter]:
        if not value:
            raise ValueError("search_space cannot be empty")
        return value


def load_hpo_spec(path: str | Path) -> HpoSpec:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HpoError(f"cannot read HPO spec {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise HpoError(f"invalid HPO YAML {source}: {exc}") from exc
    try:
        return HpoSpec.model_validate(payload)
    except ValueError as exc:
        raise HpoError(str(exc)) from exc


def _safe_path(workspace: Path, raw: str | Path) -> Path:
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise HpoError(f"path escapes workspace: {raw}")
    return resolved


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    node: Any = document
    for key in keys[:-1]:
        if isinstance(node, list):
            try:
                node = node[int(key)]
            except (ValueError, IndexError) as exc:
                raise HpoError(f"invalid list path in search parameter: {path}") from exc
        elif isinstance(node, dict) and key in node:
            node = node[key]
        else:
            raise HpoError(f"search parameter path does not exist: {path}")
    final = keys[-1]
    if isinstance(node, list):
        try:
            node[int(final)] = value
        except (ValueError, IndexError) as exc:
            raise HpoError(f"invalid list path in search parameter: {path}") from exc
    elif isinstance(node, dict) and final in node:
        node[final] = value
    else:
        raise HpoError(f"search parameter path does not exist: {path}")


def _condition_matches(assignments: dict[str, Any], condition: dict[str, Any]) -> bool:
    return all(assignments.get(path) == expected for path, expected in condition.items())


def _grid_values(parameter: SearchParameter) -> list[Any]:
    if parameter.type == "categorical":
        return list(parameter.choices)
    assert parameter.low is not None and parameter.high is not None
    if parameter.step is None:
        return [parameter.low, parameter.high]
    values: list[Any] = []
    current = float(parameter.low)
    high = float(parameter.high)
    while current <= high + 1e-12 and len(values) < 100000:
        values.append(int(round(current)) if parameter.type == "int" else current)
        current += float(parameter.step)
    return values


def _sample_random(parameter: SearchParameter, rng: random.Random) -> Any:
    if parameter.type == "categorical":
        return rng.choice(parameter.choices)
    assert parameter.low is not None and parameter.high is not None
    low = float(parameter.low)
    high = float(parameter.high)
    if parameter.log:
        raw = math.exp(rng.uniform(math.log(low), math.log(high)))
    else:
        raw = rng.uniform(low, high)
    if parameter.step is not None:
        raw = low + round((raw - low) / float(parameter.step)) * float(parameter.step)
        raw = min(high, max(low, raw))
    if parameter.type == "int":
        return int(round(raw))
    return float(raw)


def _score(observation: dict[str, Any], objectives: list[HpoObjective]) -> float | None:
    values = observation.get("objective_values") or {}
    total = 0.0
    used = 0
    for objective in objectives:
        raw = values.get(objective.metric)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        oriented = value if objective.direction == "minimize" else -value
        total += objective.weight * oriented
        used += 1
    return total / used if used else None


def _tpe_sample(
    parameter: SearchParameter,
    path: str,
    observations: list[dict[str, Any]],
    spec: HpoSpec,
    rng: random.Random,
) -> Any:
    scored = [
        (score, item)
        for item in observations
        if (score := _score(item, spec.objectives)) is not None
        and path in (item.get("assignments") or {})
    ]
    if len(scored) < spec.startup_trials:
        return _sample_random(parameter, rng)
    scored.sort(key=lambda item: item[0])
    good_count = max(2, int(math.ceil(len(scored) * spec.good_fraction)))
    good = [item[1]["assignments"][path] for item in scored[:good_count]]
    if parameter.type == "categorical":
        counts: dict[str, int] = defaultdict(int)
        rendered: dict[str, Any] = {}
        for value in good:
            key = json.dumps(value, sort_keys=True)
            counts[key] += 1
            rendered[key] = value
        choices = list(parameter.choices)
        weights = [
            counts.get(json.dumps(choice, sort_keys=True), 0) + 1
            for choice in choices
        ]
        return rng.choices(choices, weights=weights, k=1)[0]
    numeric = [float(value) for value in good]
    center = rng.choice(numeric)
    spread = statistics.pstdev(numeric) if len(numeric) > 1 else 0.0
    assert parameter.low is not None and parameter.high is not None
    low = float(parameter.low)
    high = float(parameter.high)
    fallback = (high - low) / max(8.0, math.sqrt(len(numeric)))
    raw = rng.gauss(center, max(spread, fallback))
    raw = min(high, max(low, raw))
    if parameter.step is not None:
        raw = low + round((raw - low) / float(parameter.step)) * float(parameter.step)
    return int(round(raw)) if parameter.type == "int" else float(raw)


def _pareto_front(observations: list[dict[str, Any]], objectives: list[HpoObjective]) -> list[str]:
    complete = [
        item
        for item in observations
        if all(objective.metric in (item.get("objective_values") or {}) for objective in objectives)
    ]
    result: list[str] = []
    for candidate in complete:
        candidate_values = candidate["objective_values"]
        dominated = False
        for other in complete:
            if other is candidate:
                continue
            other_values = other["objective_values"]
            no_worse = True
            strictly_better = False
            for objective in objectives:
                a = float(candidate_values[objective.metric])
                b = float(other_values[objective.metric])
                if objective.direction == "minimize":
                    no_worse &= b <= a
                    strictly_better |= b < a
                else:
                    no_worse &= b >= a
                    strictly_better |= b > a
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            result.append(str(candidate["trial_id"]))
    return sorted(result)


class HpoController:
    """Persistent adaptive search controller producing ordinary ResearchAssistant jobs."""

    def __init__(self, workspace: str | Path, spec: HpoSpec) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.spec = spec
        self.root = self.workspace / ".ra" / "hpo" / spec.name
        self.configs = self.root / "configs"
        self.state_path = self.root / "state.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.configs.mkdir(parents=True, exist_ok=True)

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "name": self.spec.name,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "spec": self.spec.model_dump(mode="json"),
            "trials": [],
            "pareto_front": [],
            "next_sequence": 0,
        }

    def load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return self._initial_state()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise HpoError(f"cannot read HPO state {self.state_path}: {exc}") from exc
        if payload.get("spec") != self.spec.model_dump(mode="json"):
            raise HpoError("HPO specification changed after state creation; use a new search name")
        return payload

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now()
        state["pareto_front"] = _pareto_front(state["trials"], self.spec.objectives)
        atomic_write_json(self.state_path, state)

    def _assignments(self, state: dict[str, Any], sequence: int) -> dict[str, Any]:
        rng = random.Random(self.spec.seed + sequence * 104729)
        paths = sorted(self.spec.search_space)
        if self.spec.sampler == "grid":
            axes = [_grid_values(self.spec.search_space[path]) for path in paths]
            all_combinations = itertools.product(*axes)
            for index, values in enumerate(all_combinations):
                if index == sequence:
                    raw = dict(zip(paths, values, strict=True))
                    return {
                        path: value
                        for path, value in raw.items()
                        if _condition_matches(raw, self.spec.search_space[path].condition)
                    }
            raise HpoError("grid search space is exhausted")
        assignments: dict[str, Any] = {}
        for path in paths:
            parameter = self.spec.search_space[path]
            if not _condition_matches(assignments, parameter.condition):
                continue
            if self.spec.sampler == "tpe":
                value = _tpe_sample(parameter, path, state["trials"], self.spec, rng)
            else:
                value = _sample_random(parameter, rng)
            assignments[path] = value
        return assignments

    def propose(self, count: int = 1) -> list[dict[str, Any]]:
        state = self.load()
        existing_hashes = {
            str(item["assignment_digest"]) for item in state["trials"]
        }
        proposals: list[dict[str, Any]] = []
        attempts = 0
        while len(proposals) < count and len(state["trials"]) < self.spec.max_trials:
            sequence = int(state["next_sequence"])
            state["next_sequence"] = sequence + 1
            attempts += 1
            assignments = self._assignments(state, sequence)
            digest = hashlib.sha256(
                json.dumps(assignments, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if digest in existing_hashes:
                if attempts > max(1000, count * 100):
                    break
                continue
            trial_id = f"trial-{sequence:05d}-{digest[:8]}"
            config_path = self._write_config(trial_id, assignments)
            row = {
                "trial_id": trial_id,
                "sequence": sequence,
                "assignments": assignments,
                "assignment_digest": digest,
                "config_path": config_path.relative_to(self.workspace).as_posix(),
                "state": "proposed",
                "created_at": utc_now(),
                "job_id": None,
                "run_ids": [],
                "objective_values": {},
                "failure": None,
            }
            state["trials"].append(row)
            existing_hashes.add(digest)
            proposals.append(row)
        self.save(state)
        return proposals

    def _write_config(self, trial_id: str, assignments: dict[str, Any]) -> Path:
        base_path = _safe_path(self.workspace, self.spec.base_config)
        try:
            document = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise HpoError(f"cannot read base config {base_path}: {exc}") from exc
        if not isinstance(document, dict):
            raise HpoError("base experiment config must be a mapping")
        document["matrix"] = {}
        experiment = document.setdefault("experiment", {})
        base_name = str(experiment.get("name", "experiment"))
        experiment["name"] = f"{base_name}-{self.spec.name}-{trial_id}"
        tags = list(experiment.get("tags") or [])
        experiment["tags"] = list(dict.fromkeys([*tags, "hpo", self.spec.name, trial_id]))
        for path, value in assignments.items():
            _set_path(document, path, value)
        path = self.configs / f"{trial_id}.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    def launch(self, trial_ids: list[str] | None = None) -> list[dict[str, Any]]:
        state = self.load()
        service = JobService(self.workspace, self.spec.plugins)
        selected = [
            row
            for row in state["trials"]
            if row["state"] == "proposed"
            and (not trial_ids or row["trial_id"] in set(trial_ids))
        ]
        launched: list[dict[str, Any]] = []
        active = sum(row["state"] in {"queued", "running"} for row in state["trials"])
        slots = max(0, self.spec.parallelism - active)
        for row in selected[:slots]:
            result = service.start(
                JobStartRequest(
                    config_path=str(row["config_path"]),
                    launcher_path=self.spec.launcher_path,
                    artifact_root=self.spec.artifact_root,
                    resume=True,
                    overrides=self.spec.config_overrides,
                    launcher_overrides=self.spec.launcher_overrides,
                )
            )
            row["job_id"] = result.get("job_id")
            row["state"] = str(result.get("state", "queued"))
            plan = result.get("plan") or {}
            row["run_ids"] = list(plan.get("run_ids") or [])
            row["launched_at"] = utc_now()
            launched.append(dict(row))
        self.save(state)
        return launched

    def _resource_totals(self, state: dict[str, Any]) -> tuple[float, float]:
        root = _safe_path(self.workspace, self.spec.artifact_root)
        gpu_seconds = 0.0
        wall_seconds = 0.0
        allowed_run_ids = {
            str(run_id)
            for trial in state.get("trials", [])
            for run_id in trial.get("run_ids", [])
        }
        if not root.is_dir() or not allowed_run_ids:
            return 0.0, 0.0
        for path in root.glob("*/*/resources.json"):
            if path.parent.name not in allowed_run_ids:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                total = payload.get("total") or {}
                gpu_seconds += float(total.get("gpu_wall_seconds", 0.0))
                wall_seconds += float(total.get("wall_seconds", 0.0))
            except (OSError, ValueError, TypeError):
                continue
        return gpu_seconds / 3600.0, wall_seconds / 3600.0

    def _budget_open(self, state: dict[str, Any]) -> bool:
        failed = sum(row["state"] == "failed" for row in state["trials"])
        if self.spec.max_failed_trials is not None and failed >= self.spec.max_failed_trials:
            return False
        gpu_hours, wall_hours = self._resource_totals(state)
        if self.spec.max_gpu_hours is not None and gpu_hours >= self.spec.max_gpu_hours:
            return False
        if self.spec.max_wall_hours is not None and wall_hours >= self.spec.max_wall_hours:
            return False
        return len(state["trials"]) < self.spec.max_trials

    def refresh(self, *, prune: bool = True) -> dict[str, Any]:
        state = self.load()
        service = JobService(self.workspace, self.spec.plugins)
        jobs = {str(row["job_id"]): row for row in service.list()}
        for trial in state["trials"]:
            job_id = trial.get("job_id")
            if not job_id or str(job_id) not in jobs:
                continue
            job = jobs[str(job_id)]
            trial["state"] = str(job.get("state", trial["state"]))
            trial["run_ids"] = list((job.get("plan") or {}).get("run_ids") or trial["run_ids"])
            if trial["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                trial["finished_at"] = job.get("finished_at") or utc_now()
        self._observe_metrics(state)
        pruned = self._asha_prune(state, service) if prune and self.spec.asha.enabled else []
        self.save(state)
        gpu_hours, wall_hours = self._resource_totals(state)
        return {
            "name": self.spec.name,
            "trials": state["trials"],
            "pareto_front": state["pareto_front"],
            "gpu_hours": gpu_hours,
            "wall_hours": wall_hours,
            "budget_open": self._budget_open(state),
            "pruned": pruned,
        }

    def _observe_metrics(self, state: dict[str, Any]) -> None:
        root = _safe_path(self.workspace, self.spec.artifact_root)
        index = MetricIndex(root)
        try:
            index.refresh()
            for trial in state["trials"]:
                run_ids = list(trial.get("run_ids") or [])
                if not run_ids:
                    continue
                values: dict[str, list[float]] = defaultdict(list)
                for objective in self.spec.objectives:
                    clauses = [
                        f"e.run_id IN ({','.join('?' for _ in run_ids)})",
                        "e.metric = ?",
                        "COALESCE(e.split, '') = ?",
                        "e.kind = ?",
                    ]
                    parameters: list[Any] = [
                        *run_ids,
                        objective.metric,
                        objective.split,
                        objective.kind,
                    ]
                    if objective.stage:
                        clauses.append("e.stage = ?")
                        parameters.append(objective.stage)
                    order = "ASC" if objective.direction == "minimize" else "DESC"
                    with index._lock:  # noqa: SLF001
                        rows = index._connection.execute(  # noqa: SLF001
                            f"""
                            WITH ranked AS (
                                SELECT e.run_id, e.value, e.step,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY e.run_id
                                           ORDER BY e.value {order}, e.step DESC, e.sequence DESC
                                       ) AS rank
                                FROM metric_events e WHERE {' AND '.join(clauses)}
                            )
                            SELECT * FROM ranked WHERE rank = 1
                            """,
                            parameters,
                        ).fetchall()
                    values[objective.metric].extend(float(row["value"]) for row in rows)
                trial["objective_values"] = {
                    metric: statistics.fmean(items)
                    for metric, items in values.items()
                    if items
                }
        finally:
            index.close()

    def _asha_prune(self, state: dict[str, Any], service: JobService) -> list[str]:
        root = _safe_path(self.workspace, self.spec.artifact_root)
        primary = self.spec.objectives[0]
        index = MetricIndex(root)
        pruned: list[str] = []
        try:
            index.refresh()
            for rung in self.spec.asha.resource_steps:
                if rung < self.spec.asha.grace_step:
                    continue
                rows: list[tuple[dict[str, Any], float]] = []
                for trial in state["trials"]:
                    if trial["state"] not in {"queued", "running"}:
                        continue
                    run_ids = list(trial.get("run_ids") or [])
                    if not run_ids:
                        continue
                    with index._lock:  # noqa: SLF001
                        events = index._connection.execute(  # noqa: SLF001
                            f"""
                            SELECT e.value FROM metric_events e
                            WHERE e.run_id IN ({','.join('?' for _ in run_ids)})
                              AND e.metric = ? AND COALESCE(e.split, '') = ?
                              AND e.step >= ?
                              {('AND e.stage = ?' if primary.stage else '')}
                            ORDER BY e.step DESC, e.sequence DESC
                            LIMIT ?
                            """,
                            [
                                *run_ids,
                                primary.metric,
                                primary.split,
                                rung,
                                *([primary.stage] if primary.stage else []),
                                len(run_ids),
                            ],
                        ).fetchall()
                    if events:
                        rows.append((trial, statistics.fmean(float(row["value"]) for row in events)))
                if len(rows) < self.spec.asha.reduction_factor:
                    continue
                reverse = primary.direction == "maximize"
                rows.sort(key=lambda item: item[1], reverse=reverse)
                keep = max(1, math.ceil(len(rows) / self.spec.asha.reduction_factor))
                for trial, _value in rows[keep:]:
                    job_id = trial.get("job_id")
                    if not job_id:
                        continue
                    try:
                        service.cancel(str(job_id))
                    except ResearchAssistantError:
                        continue
                    trial["state"] = "pruned"
                    trial["pruned_at_step"] = rung
                    trial["finished_at"] = utc_now()
                    pruned.append(str(trial["trial_id"]))
        finally:
            index.close()
        return pruned

    def step(self) -> dict[str, Any]:
        status = self.refresh(prune=True)
        state = self.load()
        if not self._budget_open(state):
            return status
        active = sum(row["state"] in {"queued", "running"} for row in state["trials"])
        needed = max(0, self.spec.parallelism - active)
        if needed:
            proposals = self.propose(needed)
            self.launch([str(row["trial_id"]) for row in proposals])
        return self.refresh(prune=False)

    def best(self) -> list[dict[str, Any]]:
        state = self.load()
        complete = [
            row for row in state["trials"] if _score(row, self.spec.objectives) is not None
        ]
        complete.sort(key=lambda row: (_score(row, self.spec.objectives), row["trial_id"]))
        return complete
