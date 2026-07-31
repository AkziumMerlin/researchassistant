from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_assistant.artifacts import utc_now
from research_assistant.errors import ResearchAssistantError


class DatasetRegistryError(ResearchAssistantError):
    pass


class DatasetFileRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude: list[str] = Field(default_factory=list)
    required_extensions: list[str] = Field(default_factory=list)
    min_files: int = Field(default=1, ge=0)
    max_files: int | None = Field(default=None, ge=1)


class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1", min_length=1, max_length=80)
    source: str = Field(min_length=1)
    description: str | None = None
    parent_id: str | None = None
    files: DatasetFileRule = Field(default_factory=DatasetFileRule)
    splits: dict[str, list[str]] = Field(default_factory=dict)
    preprocessing: list[dict[str, Any]] = Field(default_factory=list)
    schema_definition: dict[str, Any] = Field(default_factory=dict, alias="schema")
    metadata: dict[str, Any] = Field(default_factory=dict)
    snapshot: bool = True

    @field_validator("splits")
    @classmethod
    def normalize_splits(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            str(name): list(dict.fromkeys(str(pattern) for pattern in patterns if str(pattern)))
            for name, patterns in value.items()
            if str(name)
        }

    @model_validator(mode="after")
    def validate_split_names(self) -> DatasetSpec:
        forbidden = {"all", "*"}
        overlap = forbidden.intersection(name.lower() for name in self.splits)
        if overlap:
            raise ValueError(f"reserved split names are not allowed: {', '.join(sorted(overlap))}")
        return self


def load_dataset_spec(path: str | Path) -> DatasetSpec:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetRegistryError(f"cannot read dataset spec {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DatasetRegistryError(f"invalid dataset YAML {source}: {exc}") from exc
    try:
        return DatasetSpec.model_validate(payload)
    except ValueError as exc:
        raise DatasetRegistryError(str(exc)) from exc


def _safe_workspace_path(workspace: Path, raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise DatasetRegistryError(f"path escapes workspace: {raw}")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) or Path(relative).match(pattern) for pattern in patterns)


def _scan_files(source: Path, rule: DatasetFileRule) -> list[dict[str, Any]]:
    if source.is_file():
        candidates = [source]
        base = source.parent
    elif source.is_dir():
        candidates = [path for path in source.rglob("*") if path.is_file() and not path.is_symlink()]
        base = source
    else:
        raise DatasetRegistryError(f"dataset source does not exist: {source}")
    rows: list[dict[str, Any]] = []
    allowed_extensions = {
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in rule.required_extensions
    }
    for path in sorted(candidates):
        relative = path.relative_to(base).as_posix()
        if rule.include and not _matches(relative, rule.include):
            continue
        if rule.exclude and _matches(relative, rule.exclude):
            continue
        if allowed_extensions and path.suffix.lower() not in allowed_extensions:
            continue
        rows.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if len(rows) < rule.min_files:
        raise DatasetRegistryError(
            f"dataset contains {len(rows)} matching files, expected at least {rule.min_files}"
        )
    if rule.max_files is not None and len(rows) > rule.max_files:
        raise DatasetRegistryError(
            f"dataset contains {len(rows)} matching files, expected at most {rule.max_files}"
        )
    return rows


def _resolve_splits(
    files: list[dict[str, Any]], split_patterns: dict[str, list[str]]
) -> tuple[dict[str, list[str]], list[str]]:
    paths = [str(row["path"]) for row in files]
    resolved: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    for split, patterns in split_patterns.items():
        selected = sorted(path for path in paths if _matches(path, patterns))
        for path in selected:
            previous = owners.get(path)
            if previous is not None:
                raise DatasetRegistryError(
                    f"file {path!r} belongs to both {previous!r} and {split!r}"
                )
            owners[path] = split
        resolved[split] = selected
    unassigned = sorted(set(paths) - set(owners))
    return resolved, unassigned


def _dataset_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


class DatasetRegistry:
    """Immutable dataset snapshots with split manifests and lineage."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = self.workspace / ".ra" / "datasets"
        self.database = self.workspace / ".ra" / "datasets.sqlite3"
        self.objects = self.root / "objects" / "sha256"
        self.manifests = self.root / "manifests"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._schema()

    def close(self) -> None:
        self.connection.close()

    def _schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                digest TEXT NOT NULL,
                source_path TEXT NOT NULL,
                object_path TEXT,
                manifest_path TEXT NOT NULL,
                parent_id TEXT,
                created_at TEXT NOT NULL,
                file_count INTEGER NOT NULL,
                total_bytes INTEGER NOT NULL,
                snapshot INTEGER NOT NULL,
                description TEXT,
                metadata_json TEXT NOT NULL,
                UNIQUE(name, version, digest)
            );
            CREATE INDEX IF NOT EXISTS dataset_name_idx ON datasets(name, version);
            """
        )
        self.connection.commit()

    def _snapshot(self, source: Path, files: list[dict[str, Any]], digest: str) -> Path:
        destination = self.objects / digest[:2] / digest
        if destination.exists():
            return destination
        temporary = destination.with_name(destination.name + f".tmp-{uuid4().hex}")
        temporary.mkdir(parents=True, exist_ok=False)
        base = source.parent if source.is_file() else source
        try:
            for row in files:
                relative = Path(str(row["path"]))
                _copy_file(base / relative, temporary / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination

    def register(self, spec: DatasetSpec) -> dict[str, Any]:
        source = _safe_workspace_path(self.workspace, spec.source)
        files = _scan_files(source, spec.files)
        splits, unassigned = _resolve_splits(files, spec.splits)
        manifest_payload = {
            "schema_version": 1,
            "name": spec.name,
            "version": spec.version,
            "description": spec.description,
            "parent_id": spec.parent_id,
            "files": files,
            "splits": splits,
            "unassigned": unassigned,
            "preprocessing": spec.preprocessing,
            "schema": spec.schema_definition,
            "metadata": spec.metadata,
        }
        digest = _dataset_digest(manifest_payload)
        dataset_id = f"{spec.name}:{spec.version}:{digest[:16]}"
        if spec.parent_id is not None and self.get(spec.parent_id) is None:
            raise DatasetRegistryError(f"parent dataset does not exist: {spec.parent_id}")
        object_path = self._snapshot(source, files, digest) if spec.snapshot else None
        self.manifests.mkdir(parents=True, exist_ok=True)
        manifest_path = self.manifests / f"{digest}.json"
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(
                    {
                        **manifest_payload,
                        "dataset_id": dataset_id,
                        "digest": digest,
                        "source": source.relative_to(self.workspace).as_posix(),
                        "snapshot_path": (
                            object_path.relative_to(self.workspace).as_posix()
                            if object_path is not None
                            else None
                        ),
                        "created_at": utc_now(),
                    },
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        self.connection.execute(
            """
            INSERT INTO datasets(
                dataset_id, name, version, digest, source_path, object_path, manifest_path,
                parent_id, created_at, file_count, total_bytes, snapshot, description, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                source_path=excluded.source_path,
                object_path=COALESCE(excluded.object_path, datasets.object_path),
                description=excluded.description,
                metadata_json=excluded.metadata_json
            """,
            (
                dataset_id,
                spec.name,
                spec.version,
                digest,
                source.relative_to(self.workspace).as_posix(),
                object_path.relative_to(self.workspace).as_posix() if object_path else None,
                manifest_path.relative_to(self.workspace).as_posix(),
                spec.parent_id,
                utc_now(),
                len(files),
                sum(int(row["size"]) for row in files),
                int(spec.snapshot),
                spec.description,
                json.dumps(spec.metadata, sort_keys=True),
            ),
        )
        self.connection.commit()
        return self.require(dataset_id)

    def get(self, dataset_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)
        ).fetchone()
        return self._row(row) if row else None

    def require(self, dataset_id: str) -> dict[str, Any]:
        row = self.get(dataset_id)
        if row is None:
            raise DatasetRegistryError(f"dataset does not exist: {dataset_id}")
        return row

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["snapshot"] = bool(value["snapshot"])
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        manifest_path = self.workspace / str(value["manifest_path"])
        try:
            value["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            value["manifest"] = {}
        return value

    def list(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        parameters: list[Any] = []
        if name:
            clauses.append("name = ?")
            parameters.append(name)
        if search:
            clauses.append("(dataset_id LIKE ? OR name LIKE ? OR description LIKE ?)")
            needle = f"%{search}%"
            parameters.extend([needle, needle, needle])
        parameters.append(max(1, min(limit, 10000)))
        rows = self.connection.execute(
            f"""
            SELECT * FROM datasets
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [self._row(row) for row in rows]

    def validate(self, dataset_id: str, *, against_source: bool = True) -> dict[str, Any]:
        record = self.require(dataset_id)
        manifest = record["manifest"]
        expected = {str(row["path"]): row for row in manifest.get("files", [])}
        root_raw = record["object_path"] if record["snapshot"] else record["source_path"]
        if not against_source and record["object_path"]:
            root_raw = record["object_path"]
        root = self.workspace / str(root_raw)
        missing: list[str] = []
        changed: list[dict[str, Any]] = []
        for relative, row in expected.items():
            path = root / relative
            if not path.is_file():
                missing.append(relative)
                continue
            actual_size = path.stat().st_size
            actual_digest = _sha256_file(path)
            if actual_size != int(row["size"]) or actual_digest != str(row["sha256"]):
                changed.append(
                    {
                        "path": relative,
                        "expected_size": int(row["size"]),
                        "actual_size": actual_size,
                        "expected_sha256": str(row["sha256"]),
                        "actual_sha256": actual_digest,
                    }
                )
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        } if root.is_dir() else ({root.name} if root.is_file() else set())
        extra = sorted(actual - set(expected))
        split_paths = [
            path
            for paths in (manifest.get("splits") or {}).values()
            for path in paths
        ]
        split_duplicates = sorted(
            {path for path in split_paths if split_paths.count(path) > 1}
        )
        return {
            "dataset_id": dataset_id,
            "valid": not missing and not changed and not split_duplicates,
            "missing": missing,
            "changed": changed,
            "extra": extra,
            "split_duplicates": split_duplicates,
            "file_count": len(expected),
        }

    def materialize(
        self,
        dataset_id: str,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        record = self.require(dataset_id)
        if not record["object_path"]:
            raise DatasetRegistryError("dataset was registered without an immutable snapshot")
        source = self.workspace / str(record["object_path"])
        target = _safe_workspace_path(self.workspace, destination)
        if target.exists():
            if not overwrite:
                raise DatasetRegistryError(f"destination exists: {target}")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.copytree(source, target, copy_function=shutil.copy2)
        return target

    def lineage(self, dataset_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        current = self.require(dataset_id)
        seen: set[str] = set()
        while current and current["dataset_id"] not in seen:
            seen.add(current["dataset_id"])
            result.append(current)
            parent_id = current.get("parent_id")
            current = self.get(str(parent_id)) if parent_id else None
        return result

    def export_manifest(self, dataset_id: str, destination: str | Path) -> Path:
        record = self.require(dataset_id)
        target = _safe_workspace_path(self.workspace, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(record["manifest"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target
