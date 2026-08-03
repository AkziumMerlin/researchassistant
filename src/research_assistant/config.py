from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from research_assistant.errors import ConfigError
from research_assistant.migrations import MigrationReport, migrate_document
from research_assistant.models import ExperimentConfig


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _parse_yaml_document(content: str, source: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {source}: {exc}") from exc

    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigError(f"config root must be a mapping: {source}")
    return document


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    return _parse_yaml_document(content, path)


def _guard_path(path: Path, allowed_root: Path | None) -> None:
    if allowed_root is None:
        return
    root = allowed_root.resolve()
    if not path.resolve().is_relative_to(root):
        raise ConfigError(f"config path escapes allowed root {root}: {path}")


def _compose_document(
    current: dict[str, Any],
    path: Path,
    stack: tuple[Path, ...],
    allowed_root: Path | None,
) -> dict[str, Any]:
    current = copy.deepcopy(current)
    parents = current.pop("extends", [])
    if isinstance(parents, str):
        parents = [parents]
    if not isinstance(parents, list) or not all(isinstance(item, str) for item in parents):
        raise ConfigError(f"extends must be a path or a list of paths: {path}")

    merged: dict[str, Any] = {}
    for parent in parents:
        parent_path = (path.parent / parent).resolve()
        merged = _deep_merge(
            merged,
            _load_composed(parent_path, (*stack, path), allowed_root=allowed_root),
        )
    return _deep_merge(merged, current)


def _load_composed(
    path: Path,
    stack: tuple[Path, ...] = (),
    *,
    allowed_root: Path | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    _guard_path(path, allowed_root)
    if path in stack:
        cycle = " -> ".join(str(item) for item in (*stack, path))
        raise ConfigError(f"cyclic config inheritance: {cycle}")

    current = _read_yaml(path)
    return _compose_document(current, path, stack, allowed_root)


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    if not path or any(not key for key in keys):
        raise ConfigError(f"invalid override path: {path!r}")

    node: dict[str, Any] = document
    for key in keys[:-1]:
        child = node.get(key)
        if child is None:
            child = {}
            node[key] = child
        if not isinstance(child, dict):
            raise ConfigError(f"cannot descend into non-mapping override path: {path!r}")
        node = child
    node[keys[-1]] = value


def apply_overrides(document: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for override in overrides:
        if "=" not in override:
            raise ConfigError(f"override must have KEY=VALUE form: {override!r}")
        key, raw_value = override.split("=", 1)
        try:
            value = yaml.safe_load(raw_value)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid override value in {override!r}: {exc}") from exc
        _set_path(result, key, value)
    return result


def migrate_config_document(document: dict[str, Any]) -> tuple[dict[str, Any], MigrationReport]:
    """Return a current-schema copy and an auditable migration report."""
    return migrate_document(document, kind="experiment")


def parse_config(document: dict[str, Any]) -> ExperimentConfig:
    migrated, _report = migrate_config_document(document)
    try:
        return ExperimentConfig.model_validate(migrated)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def load_config(path: str | Path, overrides: list[str] | None = None) -> ExperimentConfig:
    document = _load_composed(Path(path))
    document = apply_overrides(document, overrides or [])
    return parse_config(document)


def load_config_text(
    content: str,
    source_path: str | Path,
    overrides: list[str] | None = None,
    *,
    allowed_root: str | Path | None = None,
) -> ExperimentConfig:
    """Compose and validate unsaved YAML using ``source_path`` for relative inheritance."""
    path = Path(source_path).resolve()
    root = Path(allowed_root).resolve() if allowed_root is not None else None
    _guard_path(path, root)
    current = _parse_yaml_document(content, path)
    document = _compose_document(current, path, (), root)
    document = apply_overrides(document, overrides or [])
    return parse_config(document)


def dump_config(config: ExperimentConfig, *, compact: bool = False) -> str:
    document = config.model_dump(mode="json", exclude_none=True, exclude_defaults=compact)
    if compact:
        document = {"version": config.version, **document}
    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
    )
