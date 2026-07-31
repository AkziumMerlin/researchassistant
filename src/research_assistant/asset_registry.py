from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from research_assistant.artifacts import utc_now
from research_assistant.checkpoints import CHECKPOINT_SUFFIXES
from research_assistant.errors import ResearchAssistantError

AssetKind = Literal["artifact", "checkpoint"]
AssetStatus = Literal["candidate", "selected", "released", "archived"]


class AssetRegistryError(ResearchAssistantError):
    pass


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink():
            raise AssetRegistryError(f"registered directories cannot contain symlinks: {item}")
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


def _digest(path: Path) -> tuple[str, str, int]:
    if path.is_file():
        return _sha256_file(path), "file", path.stat().st_size
    if path.is_dir():
        rows = _tree_rows(path)
        digest = hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return digest, "directory", sum(int(row.get("size", 0)) for row in rows)
    raise AssetRegistryError(f"asset does not exist: {path}")


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_object(source: Path, destination: Path, object_kind: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if object_kind == "file":
        _copy_file(source, destination)
    else:
        shutil.copytree(source, destination, copy_function=shutil.copy2)


class AssetRegistry:
    """SQLite catalog plus content-addressed object storage for run assets."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.state_root = self.workspace / ".ra"
        self.database = self.state_root / "assets.sqlite3"
        self.objects = self.state_root / "objects" / "sha256"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._schema()

    def close(self) -> None:
        self.connection.close()

    def _schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                digest TEXT NOT NULL,
                object_kind TEXT NOT NULL,
                size INTEGER NOT NULL,
                study_id TEXT,
                trial_id TEXT,
                run_id TEXT,
                stage TEXT,
                name TEXT NOT NULL,
                source_path TEXT NOT NULL UNIQUE,
                object_path TEXT NOT NULL,
                mime TEXT,
                status TEXT NOT NULL DEFAULT 'candidate',
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS assets_run_idx ON assets(run_id, stage, kind);
            CREATE INDEX IF NOT EXISTS assets_status_idx ON assets(status, pinned, kind);
            CREATE INDEX IF NOT EXISTS assets_digest_idx ON assets(digest);
            """
        )
        self.connection.commit()

    def _object_path(self, digest: str, object_kind: str) -> Path:
        suffix = ".dir" if object_kind == "directory" else ".blob"
        return self.objects / digest[:2] / f"{digest}{suffix}"

    def _ingest_object(self, source: Path, digest: str, object_kind: str) -> Path:
        destination = self._object_path(digest, object_kind)
        if destination.exists():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + f".tmp-{uuid4().hex}")
        if temporary.exists():
            shutil.rmtree(temporary) if temporary.is_dir() else temporary.unlink()
        _copy_object(source, temporary, object_kind)
        try:
            temporary.replace(destination)
        except FileExistsError:
            if temporary.is_dir():
                shutil.rmtree(temporary, ignore_errors=True)
            else:
                temporary.unlink(missing_ok=True)
        return destination

    def _register(
        self,
        *,
        source: Path,
        kind: AssetKind,
        study_id: str | None,
        trial_id: str | None,
        run_id: str | None,
        stage: str | None,
        name: str,
        metadata: dict[str, Any],
    ) -> str:
        source = source.resolve()
        if not source.is_relative_to(self.workspace):
            raise AssetRegistryError(f"asset escapes workspace: {source}")
        digest, object_kind, size = _digest(source)
        object_path = self._ingest_object(source, digest, object_kind)
        identity = f"{kind}:{run_id}:{stage}:{name}:{digest}".encode()
        asset_id = hashlib.sha256(identity).hexdigest()[:32]
        relative_source = source.relative_to(self.workspace).as_posix()
        relative_object = object_path.relative_to(self.workspace).as_posix()
        now = utc_now()
        existing = self.connection.execute(
            "SELECT status, pinned, archived, created_at FROM assets WHERE source_path=?",
            (relative_source,),
        ).fetchone()
        status = str(existing["status"]) if existing else "candidate"
        pinned = int(existing["pinned"]) if existing else 0
        archived = int(existing["archived"]) if existing else 0
        created_at = str(existing["created_at"]) if existing else now
        self.connection.execute(
            """
            INSERT INTO assets (
                asset_id, kind, digest, object_kind, size, study_id, trial_id, run_id,
                stage, name, source_path, object_path, mime, status, pinned, archived,
                created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
                asset_id=excluded.asset_id, kind=excluded.kind, digest=excluded.digest,
                object_kind=excluded.object_kind, size=excluded.size,
                study_id=excluded.study_id, trial_id=excluded.trial_id,
                run_id=excluded.run_id, stage=excluded.stage, name=excluded.name,
                object_path=excluded.object_path, mime=excluded.mime,
                updated_at=excluded.updated_at, metadata_json=excluded.metadata_json
            """,
            (
                asset_id,
                kind,
                digest,
                object_kind,
                size,
                study_id,
                trial_id,
                run_id,
                stage,
                name,
                relative_source,
                relative_object,
                mimetypes.guess_type(source.name)[0],
                status,
                pinned,
                archived,
                created_at,
                now,
                json.dumps(metadata, sort_keys=True, ensure_ascii=False),
            ),
        )
        return asset_id

    def refresh(self, artifact_root: str | Path = "runs") -> dict[str, int]:
        root = Path(artifact_root)
        root = root.resolve() if root.is_absolute() else (self.workspace / root).resolve()
        if not root.is_relative_to(self.workspace):
            raise AssetRegistryError("artifact root escapes workspace")
        seen: set[str] = set()
        registered = 0
        skipped = 0
        for manifest_path in sorted(root.glob("*/*/manifest.json")):
            run_dir = manifest_path.parent
            manifest = _read_mapping(manifest_path)
            status = _read_mapping(run_dir / "status.json")
            study_id = str(manifest.get("study_id", run_dir.parent.name))
            trial_id = str(manifest.get("trial_id", "unknown"))
            run_id = str(manifest.get("run_id", run_dir.name))
            stages = status.get("stages") if isinstance(status.get("stages"), dict) else {}
            for stage_name, stage_status in stages.items():
                if not isinstance(stage_status, dict):
                    continue
                artifacts = stage_status.get("artifacts")
                if not isinstance(artifacts, dict):
                    continue
                for name, relative in artifacts.items():
                    source = (run_dir / str(relative)).resolve()
                    if not source.is_relative_to(run_dir.resolve()) or not source.exists():
                        skipped += 1
                        continue
                    kind: AssetKind = (
                        "checkpoint"
                        if source.is_file() and source.suffix.lower() in CHECKPOINT_SUFFIXES
                        else "artifact"
                    )
                    try:
                        self._register(
                            source=source,
                            kind=kind,
                            study_id=study_id,
                            trial_id=trial_id,
                            run_id=run_id,
                            stage=str(stage_name),
                            name=str(name),
                            metadata={
                                "stage_state": stage_status.get("state"),
                                "run_state": status.get("state"),
                                "artifact_name": str(name),
                            },
                        )
                    except (OSError, AssetRegistryError):
                        skipped += 1
                        continue
                    seen.add(source.relative_to(self.workspace).as_posix())
                    registered += 1
            for source in sorted(run_dir.glob("checkpoints/**/*")):
                if not source.is_file() or source.suffix.lower() not in CHECKPOINT_SUFFIXES:
                    continue
                relative = source.relative_to(run_dir)
                stage = relative.parts[1] if len(relative.parts) > 2 else None
                source_key = source.relative_to(self.workspace).as_posix()
                if source_key in seen:
                    continue
                try:
                    self._register(
                        source=source,
                        kind="checkpoint",
                        study_id=study_id,
                        trial_id=trial_id,
                        run_id=run_id,
                        stage=stage,
                        name=source.stem,
                        metadata={"run_state": status.get("state"), "discovered": True},
                    )
                except (OSError, AssetRegistryError):
                    skipped += 1
                    continue
                seen.add(source_key)
                registered += 1
        self.connection.commit()
        return {"registered": registered, "skipped": skipped, "total": self.count()}

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])

    def list(
        self,
        *,
        kind: AssetKind | None = None,
        status: AssetStatus | None = None,
        run_id: str | None = None,
        pinned: bool | None = None,
        search: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        parameters: list[Any] = []
        if kind:
            clauses.append("kind=?")
            parameters.append(kind)
        if status:
            clauses.append("status=?")
            parameters.append(status)
        if run_id:
            clauses.append("run_id=?")
            parameters.append(run_id)
        if pinned is not None:
            clauses.append("pinned=?")
            parameters.append(int(pinned))
        if search:
            clauses.append("(name LIKE ? OR source_path LIKE ? OR trial_id LIKE ?)")
            needle = f"%{search}%"
            parameters.extend([needle, needle, needle])
        parameters.append(max(1, min(limit, 10000)))
        rows = self.connection.execute(
            f"SELECT * FROM assets WHERE {' AND '.join(clauses)} "
            "ORDER BY pinned DESC, status DESC, updated_at DESC LIMIT ?",
            parameters,
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["pinned"] = bool(item["pinned"])
            item["archived"] = bool(item["archived"])
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def get(self, asset_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM assets WHERE asset_id=?", (asset_id,)
        ).fetchone()
        if row is None:
            raise AssetRegistryError(f"unknown asset: {asset_id}")
        item = dict(row)
        item["pinned"] = bool(item["pinned"])
        item["archived"] = bool(item["archived"])
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def promote(self, asset_id: str, status: AssetStatus) -> dict[str, Any]:
        if status not in {"candidate", "selected", "released", "archived"}:
            raise AssetRegistryError(f"invalid asset status: {status}")
        self.get(asset_id)
        self.connection.execute(
            "UPDATE assets SET status=?, archived=?, updated_at=? WHERE asset_id=?",
            (status, int(status == "archived"), utc_now(), asset_id),
        )
        self.connection.commit()
        return self.get(asset_id)

    def pin(self, asset_id: str, value: bool = True) -> dict[str, Any]:
        self.get(asset_id)
        self.connection.execute(
            "UPDATE assets SET pinned=?, updated_at=? WHERE asset_id=?",
            (int(value), utc_now(), asset_id),
        )
        self.connection.commit()
        return self.get(asset_id)

    def materialize(
        self,
        asset_id: str,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        item = self.get(asset_id)
        source = self.workspace / str(item["object_path"])
        target = Path(destination)
        target = target.resolve() if target.is_absolute() else (self.workspace / target).resolve()
        if not target.is_relative_to(self.workspace):
            raise AssetRegistryError("materialization destination escapes workspace")
        if target.exists():
            if not overwrite:
                raise AssetRegistryError(f"destination exists: {target}")
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        _copy_object(source, target, str(item["object_kind"]))
        return target

    def delete(self, asset_id: str, *, delete_source: bool = False) -> None:
        item = self.get(asset_id)
        if item["pinned"] or item["status"] == "released":
            raise AssetRegistryError("pinned or released assets cannot be deleted")
        source = self.workspace / str(item["source_path"])
        if delete_source and source.exists():
            shutil.rmtree(source) if source.is_dir() else source.unlink()
        self.connection.execute("DELETE FROM assets WHERE asset_id=?", (asset_id,))
        self.connection.commit()

    def enforce_retention(
        self,
        *,
        keep_candidates_per_trial: int = 3,
        delete_sources: bool = False,
    ) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT asset_id, trial_id, kind, pinned, status, source_path,
                   ROW_NUMBER() OVER (
                     PARTITION BY trial_id, kind ORDER BY updated_at DESC
                   ) AS rank
            FROM assets WHERE status='candidate' AND pinned=0
            """
        ).fetchall()
        removed = 0
        for row in rows:
            if int(row["rank"]) <= keep_candidates_per_trial:
                continue
            self.delete(str(row["asset_id"]), delete_source=delete_sources)
            removed += 1
        return {"removed": removed}

    def gc(self) -> dict[str, int]:
        referenced = {
            str(row[0])
            for row in self.connection.execute("SELECT DISTINCT object_path FROM assets")
        }
        removed = 0
        bytes_removed = 0
        for path in self.objects.glob("*/*"):
            relative = path.relative_to(self.workspace).as_posix()
            if relative in referenced:
                continue
            if path.is_dir():
                size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
                shutil.rmtree(path)
            else:
                size = path.stat().st_size
                path.unlink()
            removed += 1
            bytes_removed += size
        return {"objects_removed": removed, "bytes_removed": bytes_removed}

    def stats(self) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT kind, status, COUNT(*) n, SUM(size) bytes FROM assets GROUP BY kind, status"
        ).fetchall()
        return {
            "database": str(self.database),
            "objects": str(self.objects),
            "total": self.count(),
            "groups": [dict(row) for row in rows],
        }
