from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from research_assistant.errors import ConfigError

Migration = Callable[[dict[str, Any]], dict[str, Any]]
CURRENT_CONFIG_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class MigrationStep:
    kind: str
    source: int
    target: int
    description: str


@dataclass(frozen=True, slots=True)
class MigrationReport:
    kind: str
    source_version: int
    target_version: int
    changed: bool
    steps: tuple[MigrationStep, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [asdict(step) for step in self.steps]
        return payload


_MIGRATIONS: dict[tuple[str, int], tuple[int, str, Migration]] = {}


def register_migration(
    kind: str,
    source: int,
    target: int,
    description: str,
) -> Callable[[Migration], Migration]:
    if target != source + 1:
        raise ValueError("schema migrations must advance exactly one version")

    def decorator(function: Migration) -> Migration:
        key = (kind, source)
        if key in _MIGRATIONS:
            raise ValueError(f"migration already registered for {kind} version {source}")
        _MIGRATIONS[key] = (target, description, function)
        return function

    return decorator


@register_migration(
    "experiment",
    0,
    1,
    "Normalize legacy artifact_root/seeds fields and declare schema version 1.",
)
def _experiment_v0_to_v1(document: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(document)
    migrated["version"] = 1

    if "artifact_root" in migrated:
        artifacts = migrated.setdefault("artifacts", {})
        if not isinstance(artifacts, dict):
            raise ConfigError("legacy artifact_root cannot be merged into non-mapping artifacts")
        artifacts.setdefault("root", migrated.pop("artifact_root"))

    if "seeds" in migrated:
        raw_seeds = migrated.pop("seeds")
        if not isinstance(raw_seeds, list) or not raw_seeds:
            raise ConfigError("legacy seeds must be a non-empty list")
        matrix = migrated.setdefault("matrix", {})
        if not isinstance(matrix, dict):
            raise ConfigError("legacy seeds cannot be merged into non-mapping matrix")
        matrix.setdefault("seed", raw_seeds)
        migrated.setdefault("seed", raw_seeds[0])

    return migrated


def migrate_document(
    document: dict[str, Any],
    *,
    kind: str = "experiment",
    target_version: int = CURRENT_CONFIG_SCHEMA,
) -> tuple[dict[str, Any], MigrationReport]:
    migrated = copy.deepcopy(document)
    raw_version = migrated.get("version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
        raise ConfigError(f"invalid {kind} schema version: {raw_version!r}")
    source_version = raw_version
    if source_version > target_version:
        raise ConfigError(
            f"{kind} schema version {source_version} is newer than supported version "
            f"{target_version}; upgrade ResearchAssistant"
        )

    steps: list[MigrationStep] = []
    version = source_version
    while version < target_version:
        entry = _MIGRATIONS.get((kind, version))
        if entry is None:
            raise ConfigError(
                f"no migration path for {kind} schema version {version} -> {version + 1}"
            )
        next_version, description, function = entry
        migrated = function(migrated)
        migrated["version"] = next_version
        steps.append(MigrationStep(kind, version, next_version, description))
        version = next_version

    return migrated, MigrationReport(
        kind=kind,
        source_version=source_version,
        target_version=target_version,
        changed=bool(steps),
        steps=tuple(steps),
    )


def migration_catalog() -> list[dict[str, Any]]:
    return [
        {
            "kind": kind,
            "source": source,
            "target": target,
            "description": description,
        }
        for (kind, source), (target, description, _function) in sorted(_MIGRATIONS.items())
    ]
