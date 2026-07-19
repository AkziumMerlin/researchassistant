from __future__ import annotations

import copy
import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.config import parse_config
from research_assistant.errors import ConfigError
from research_assistant.models import ExperimentConfig
from research_assistant.registry import Registry


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    study_id: str
    trial_id: str
    run_id: str
    assignments: dict[str, Any] = Field(default_factory=dict)
    config: ExperimentConfig


@dataclass(frozen=True, slots=True)
class Plan:
    study_id: str
    runs: tuple[RunManifest, ...]


def _canonical_hash(value: Any, length: int = 12) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _set_existing_path(document: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    node: Any = document
    for key in keys[:-1]:
        if not isinstance(node, dict) or key not in node:
            raise ConfigError(f"matrix path does not exist: {path!r}")
        node = node[key]
    if not isinstance(node, dict) or keys[-1] not in node:
        raise ConfigError(f"matrix path does not exist: {path!r}")
    node[keys[-1]] = value


def _validate_dag(config: ExperimentConfig) -> None:
    dependencies = {stage.name: set(stage.needs) for stage in config.stages}
    ready: list[str] = sorted(name for name, needs in dependencies.items() if not needs)
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for name, needs in dependencies.items():
            if current in needs:
                needs.remove(current)
                if not needs and name not in visited and name not in ready:
                    ready.append(name)
                    ready.sort()
    if len(visited) != len(dependencies):
        cycle_nodes = sorted(set(dependencies) - set(visited))
        raise ConfigError(f"stage dependency cycle detected: {', '.join(cycle_nodes)}")


def _validate_components(config: ExperimentConfig, registry: Registry) -> None:
    for kind, reference in config.components.items():
        registry.validate(kind, reference)
    for stage in config.stages:
        registry.validate("stage", {"type": stage.type, "params": stage.params})


def compile_plan(config: ExperimentConfig, registry: Registry) -> Plan:
    _validate_dag(config)

    keys = sorted(config.matrix)
    values: list[list[Any]] = []
    for key in keys:
        choices = config.matrix[key]
        if not choices:
            raise ConfigError(f"matrix axis {key!r} cannot be empty")
        values.append(choices)

    combinations = itertools.product(*values) if keys else [()]
    study_id = config.experiment.name
    runs: list[RunManifest] = []
    seen_ids: set[str] = set()

    for combination in combinations:
        assignments = dict(zip(keys, combination, strict=True))
        document = copy.deepcopy(config.model_dump(mode="python"))
        document["matrix"] = {}
        for path, value in assignments.items():
            _set_existing_path(document, path, value)
        resolved = parse_config(document)
        _validate_components(resolved, registry)

        run_payload = resolved.model_dump(mode="json", exclude_none=True)
        run_payload.pop("artifacts", None)
        trial_payload = copy.deepcopy(run_payload)
        trial_payload.pop("seed", None)
        trial_id = _canonical_hash(trial_payload, length=10)
        run_id = _canonical_hash(run_payload)
        if run_id in seen_ids:
            raise ConfigError(
                f"matrix produced duplicate runs; remove duplicate axis values (run_id={run_id})"
            )
        seen_ids.add(run_id)
        runs.append(
            RunManifest(
                study_id=study_id,
                trial_id=trial_id,
                run_id=run_id,
                assignments=assignments,
                config=resolved,
            )
        )

    return Plan(study_id=study_id, runs=tuple(runs))


def topological_stages(config: ExperimentConfig) -> list[str]:
    dependencies = {stage.name: set(stage.needs) for stage in config.stages}
    result: list[str] = []
    while dependencies:
        ready = [name for name, needs in dependencies.items() if not needs]
        if not ready:
            raise ConfigError("stage dependency cycle detected")
        for name in sorted(ready):
            result.append(name)
            dependencies.pop(name)
        completed = set(ready)
        for needs in dependencies.values():
            needs.difference_update(completed)
    return result
