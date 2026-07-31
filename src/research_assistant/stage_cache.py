from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_assistant import __version__
from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.execution import StageResult
from research_assistant.models import StageConfig
from research_assistant.planning import RunManifest
from research_assistant.registry import Registry

_CACHE_MODES = {"off", "read", "write", "readwrite"}


def _stable_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink():
            raise ValueError(f"stage-cache artifacts cannot contain symlinks: {item}")
        relative = item.relative_to(path).as_posix()
        if item.is_dir():
            rows.append({"path": relative, "kind": "directory"})
        elif item.is_file():
            rows.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size": item.stat().st_size,
                    "sha256": _sha256_file(item),
                }
            )
    return rows


def artifact_digest(path: Path) -> tuple[str, str, int]:
    if path.is_file():
        return _sha256_file(path), "file", path.stat().st_size
    if path.is_dir():
        manifest = _tree_manifest(path)
        size = sum(int(row.get("size", 0)) for row in manifest)
        return hashlib.sha256(_stable_json(manifest)).hexdigest(), "directory", size
    raise ValueError(f"cannot cache missing artifact: {path}")


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_artifact(source: Path, destination: Path, kind: str) -> None:
    if kind == "file":
        _copy_file(source, destination)
        return
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, copy_function=shutil.copy2)


def _source_fingerprint(factory: Any) -> dict[str, Any]:
    module = getattr(factory, "__module__", None)
    qualified = getattr(factory, "__qualname__", repr(factory))
    path: Path | None = None
    try:
        raw = inspect.getsourcefile(factory) or inspect.getfile(factory)
        if raw:
            path = Path(raw).resolve()
    except (OSError, TypeError):
        path = None
    result: dict[str, Any] = {"module": module, "qualified_name": qualified}
    if path is not None and path.is_file():
        try:
            result.update({"path": str(path), "sha256": _sha256_file(path)})
        except OSError:
            result["path"] = str(path)
    return result


def _component_fingerprints(
    registry: Registry,
    stage: StageConfig,
    manifest: RunManifest,
) -> list[dict[str, Any]]:
    effective = dict(manifest.config.components)
    effective.update(stage.components)
    rows: list[dict[str, Any]] = []
    stage_spec = registry.get("stage", stage.type)
    rows.append(
        {
            "kind": "stage",
            "type": stage.type,
            "provider": stage_spec.provider,
            "source": _source_fingerprint(stage_spec.factory),
        }
    )
    for kind, reference in sorted(effective.items()):
        spec = registry.get(kind, reference.type)
        rows.append(
            {
                "kind": kind,
                "type": reference.type,
                "provider": spec.provider,
                "source": _source_fingerprint(spec.factory),
            }
        )
    return rows


def _cache_mode() -> str:
    value = os.environ.get("RA_STAGE_CACHE", "readwrite").strip().lower()
    return value if value in _CACHE_MODES else "readwrite"


@dataclass(frozen=True, slots=True)
class CacheHit:
    key: str
    metrics: dict[str, float]
    artifacts: dict[str, str]
    created_at: str | None


class StageCache:
    """Content-addressed cache for complete stage outputs.

    Cache keys include the resolved stage, effective component references, dependency output
    fingerprints, seed/assignments, plugin list, provenance and provider source hashes. A stage
    provider may opt out with ``metadata={"cacheable": False}``.
    """

    def __init__(self, workspace: Path, registry: Registry) -> None:
        self.workspace = workspace.resolve()
        configured = os.environ.get("RA_STAGE_CACHE_ROOT")
        self.root = (
            Path(configured).expanduser().resolve()
            if configured
            else self.workspace / ".ra" / "stage-cache"
        )
        self.entries = self.root / "entries"
        self.objects = self.root / "objects" / "sha256"
        self.mode = _cache_mode()
        self.namespace = os.environ.get("RA_STAGE_CACHE_NAMESPACE", "default")
        self.registry = registry

    @property
    def can_read(self) -> bool:
        return self.mode in {"read", "readwrite"}

    @property
    def can_write(self) -> bool:
        return self.mode in {"write", "readwrite"}

    def cacheable(self, stage: StageConfig) -> bool:
        if self.mode == "off":
            return False
        metadata = dict(self.registry.get("stage", stage.type).metadata or {})
        return bool(metadata.get("cacheable", True))

    def key(
        self,
        manifest: RunManifest,
        stage: StageConfig,
        run_dir: Path,
        completed_stages: Mapping[str, Mapping[str, Any]],
    ) -> str:
        dependencies: dict[str, Any] = {}
        for dependency in stage.needs:
            status = dict(completed_stages.get(dependency) or {})
            artifacts: dict[str, Any] = {}
            for name, relative in sorted((status.get("artifacts") or {}).items()):
                path = (run_dir / str(relative)).resolve()
                digest, kind, size = artifact_digest(path)
                artifacts[str(name)] = {"sha256": digest, "kind": kind, "size": size}
            dependencies[dependency] = {
                "cache_key": status.get("cache_key"),
                "metrics": status.get("metrics") or {},
                "artifacts": artifacts,
            }
        effective_components = dict(manifest.config.components)
        effective_components.update(stage.components)
        payload = {
            "schema_version": 1,
            "namespace": self.namespace,
            "research_assistant": __version__,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "plugins": list(manifest.config.plugins),
            "seed": manifest.config.seed,
            "assignments": manifest.assignments,
            "provenance": manifest.provenance,
            "stage": stage.model_dump(mode="json"),
            "effective_components": {
                kind: reference.model_dump(mode="json")
                for kind, reference in sorted(effective_components.items())
            },
            "providers": _component_fingerprints(self.registry, stage, manifest),
            "dependencies": dependencies,
        }
        return hashlib.sha256(_stable_json(payload)).hexdigest()

    def _entry_path(self, key: str) -> Path:
        return self.entries / key[:2] / key / "entry.json"

    def _object_path(self, digest: str, kind: str) -> Path:
        suffix = ".dir" if kind == "directory" else ".blob"
        return self.objects / digest[:2] / f"{digest}{suffix}"

    def restore(self, key: str, stage_name: str, run_dir: Path) -> CacheHit | None:
        if not self.can_read:
            return None
        entry_path = self._entry_path(key)
        try:
            payload = json.loads(entry_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        if payload.get("key") != key:
            return None
        destination_root = run_dir / ".ra-cache" / stage_name / key[:12]
        temporary = destination_root.with_name(destination_root.name + f".tmp-{uuid4().hex}")
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.mkdir(parents=True, exist_ok=True)
        restored_subpaths: dict[str, str] = {}
        try:
            for name, record in sorted((payload.get("artifacts") or {}).items()):
                digest = str(record["sha256"])
                kind = str(record["kind"])
                source = self._object_path(digest, kind)
                if not source.exists():
                    return None
                leaf = str(record.get("leaf") or name)
                destination = temporary / str(name) / leaf
                _copy_artifact(source, destination, kind)
                restored_subpaths[str(name)] = destination.relative_to(temporary).as_posix()
            destination_root.parent.mkdir(parents=True, exist_ok=True)
            if destination_root.exists():
                shutil.rmtree(destination_root)
            temporary.replace(destination_root)
            restored = {
                name: (destination_root / relative).relative_to(run_dir).as_posix()
                for name, relative in restored_subpaths.items()
            }
        except (OSError, ValueError, KeyError):
            shutil.rmtree(temporary, ignore_errors=True)
            return None
        return CacheHit(
            key=key,
            metrics={
                str(name): float(value)
                for name, value in (payload.get("metrics") or {}).items()
            },
            artifacts=restored,
            created_at=payload.get("created_at"),
        )

    def store(
        self,
        key: str,
        stage_name: str,
        result: StageResult,
        run_dir: Path,
    ) -> None:
        if not self.can_write:
            return
        entry_path = self._entry_path(key)
        if entry_path.is_file():
            return
        records: dict[str, Any] = {}
        for name, relative in sorted(result.artifacts.items()):
            source = (run_dir / relative).resolve()
            if not source.is_relative_to(run_dir.resolve()):
                raise ValueError(f"cached artifact escapes run directory: {source}")
            digest, kind, size = artifact_digest(source)
            object_path = self._object_path(digest, kind)
            if not object_path.exists():
                object_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = object_path.with_name(object_path.name + f".tmp-{uuid4().hex}")
                shutil.rmtree(temporary, ignore_errors=True)
                if kind == "file":
                    _copy_file(source, temporary)
                else:
                    shutil.copytree(source, temporary, copy_function=shutil.copy2)
                try:
                    temporary.replace(object_path)
                except FileExistsError:
                    shutil.rmtree(temporary, ignore_errors=True)
            records[str(name)] = {
                "sha256": digest,
                "kind": kind,
                "size": size,
                "leaf": source.name,
            }
        payload = {
            "schema_version": 1,
            "key": key,
            "stage": stage_name,
            "created_at": utc_now(),
            "metrics": dict(result.metrics),
            "artifacts": records,
        }
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_entry = entry_path.with_name(f"entry.tmp-{uuid4().hex}.json")
        atomic_write_json(temporary_entry, payload)
        try:
            temporary_entry.replace(entry_path)
        except FileExistsError:
            temporary_entry.unlink(missing_ok=True)

    def stats(self) -> dict[str, Any]:
        entries = 0
        objects = 0
        bytes_total = 0
        if self.entries.is_dir():
            entries = sum(1 for path in self.entries.glob("*/*/entry.json") if path.is_file())
        if self.objects.is_dir():
            for path in self.objects.glob("*/*"):
                if path.is_file():
                    objects += 1
                    bytes_total += path.stat().st_size
                elif path.is_dir():
                    objects += 1
                    bytes_total += sum(
                        item.stat().st_size for item in path.rglob("*") if item.is_file()
                    )
        return {
            "mode": self.mode,
            "namespace": self.namespace,
            "root": str(self.root),
            "entries": entries,
            "objects": objects,
            "bytes": bytes_total,
        }

    def prune(self, *, keep_entries: int = 10000) -> dict[str, int]:
        paths = sorted(
            (path for path in self.entries.glob("*/*/entry.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        removed_entries = 0
        for path in paths[max(0, keep_entries) :]:
            shutil.rmtree(path.parent, ignore_errors=True)
            removed_entries += 1
        referenced: set[tuple[str, str]] = set()
        for path in self.entries.glob("*/*/entry.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            for record in (payload.get("artifacts") or {}).values():
                referenced.add((str(record.get("sha256")), str(record.get("kind"))))
        removed_objects = 0
        for path in self.objects.glob("*/*"):
            name = path.name
            if name.endswith(".blob"):
                key = (name[:-5], "file")
            elif name.endswith(".dir"):
                key = (name[:-4], "directory")
            else:
                continue
            if key not in referenced:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                removed_objects += 1
        return {"entries_removed": removed_entries, "objects_removed": removed_objects}
