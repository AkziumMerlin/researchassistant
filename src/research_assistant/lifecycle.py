from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError


class LifecycleError(ResearchAssistantError):
    pass


class LifecycleManager:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".ra" / "lifecycle"
        self.state_path = self.root / "state.json"
        self.trash_root = self.workspace / ".ra" / "trash"

    def _safe_path(self, raw: str | Path) -> Path:
        path = Path(raw)
        resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise LifecycleError(f"path escapes workspace: {raw}")
        if resolved == self.workspace:
            raise LifecycleError("workspace root cannot be managed as one result")
        if resolved.is_relative_to(self.workspace / ".git"):
            raise LifecycleError("Git metadata cannot be managed by lifecycle operations")
        if resolved.is_relative_to(self.workspace / ".ra" / "trash"):
            raise LifecycleError("trash storage cannot be managed recursively")
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix()

    def _trash_path(self, raw: str | Path) -> Path:
        path = Path(raw)
        resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.trash_root.resolve()):
            raise LifecycleError(f"invalid trash path: {raw}")
        return resolved

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": 1, "pins": {}, "archives": {}, "trash": {}}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"cannot read lifecycle state: {exc}") from exc
        if not isinstance(value, dict):
            raise LifecycleError("invalid lifecycle state")
        for key in ("pins", "archives", "trash"):
            value.setdefault(key, {})
        return value

    def _save(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, state)

    def state(self) -> dict[str, Any]:
        state = self._load()
        state["quota"] = self.quota()
        return state

    def quota(self) -> dict[str, Any]:
        total = 0
        files = 0
        roots: dict[str, int] = {}
        for name in ("runs", "reports", "publications", ".ra/trash"):
            root = self.workspace / name
            size = 0
            if root.exists():
                for path in root.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        try:
                            size += path.stat().st_size
                            files += 1
                        except OSError:
                            continue
            roots[name] = size
            total += size
        return {"bytes": total, "files": files, "roots": roots}

    def _reference_tokens(self, path: Path) -> list[str]:
        tokens = [self._relative(path)]
        candidates = [path / "manifest.json", path / "status.json"] if path.is_dir() else []
        for candidate in candidates:
            if not candidate.is_file() or candidate.stat().st_size > 16 * 1024 * 1024:
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for key in ("run_id", "trial_id"):
                value = payload.get(key)
                if isinstance(value, str) and len(value) >= 6:
                    tokens.append(value)
        return list(dict.fromkeys(tokens))

    def _references(self, tokens: list[str]) -> list[str]:
        references: list[str] = []
        for root_name in (".ra/selections", "publications", "reports"):
            root = self.workspace / root_name
            if not root.is_dir():
                continue
            for path in root.rglob("*.json"):
                try:
                    if path.stat().st_size > 16 * 1024 * 1024:
                        continue
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if any(token in text for token in tokens):
                    references.append(path.relative_to(self.workspace).as_posix())
                    if len(references) >= 100:
                        return references
        return references

    def protection(self, raw: str | Path) -> dict[str, Any]:
        path = self._safe_path(raw)
        relative = self._relative(path)
        state = self._load()
        references = self._references(self._reference_tokens(path))
        reasons: list[str] = []
        if relative in state["pins"]:
            reasons.append("pinned")
        if references:
            reasons.append("referenced")
        return {
            "path": relative,
            "exists": path.exists(),
            "pinned": relative in state["pins"],
            "archived": relative in state["archives"],
            "references": references,
            "protected": bool(reasons),
            "reasons": reasons,
        }

    def pin(self, raw: str | Path, *, reason: str | None = None) -> dict[str, Any]:
        path = self._safe_path(raw)
        if not path.exists():
            raise LifecycleError(f"cannot pin missing path: {path}")
        relative = self._relative(path)
        state = self._load()
        state["pins"][relative] = {"reason": reason, "created_at": utc_now()}
        self._save(state)
        return {"path": relative, **state["pins"][relative]}

    def unpin(self, raw: str | Path) -> None:
        relative = self._relative(self._safe_path(raw))
        state = self._load()
        state["pins"].pop(relative, None)
        self._save(state)

    def archive(self, raw: str | Path, *, reason: str | None = None) -> dict[str, Any]:
        path = self._safe_path(raw)
        if not path.exists():
            raise LifecycleError(f"cannot archive missing path: {path}")
        relative = self._relative(path)
        state = self._load()
        state["archives"][relative] = {"reason": reason, "created_at": utc_now()}
        self._save(state)
        return {"path": relative, **state["archives"][relative]}

    def unarchive(self, raw: str | Path) -> None:
        relative = self._relative(self._safe_path(raw))
        state = self._load()
        state["archives"].pop(relative, None)
        self._save(state)

    def trash(self, raw: str | Path, *, reason: str | None = None, force: bool = False) -> dict[str, Any]:
        path = self._safe_path(raw)
        if not path.exists():
            raise LifecycleError(f"path does not exist: {path}")
        relative = self._relative(path)
        protection = self.protection(relative)
        if protection["protected"] and not force:
            detail = ", ".join(protection["reasons"])
            raise LifecycleError(f"refusing to trash protected result ({detail}); use force")
        created = utc_now()
        trash_id = hashlib.sha256(f"{relative}\0{created}".encode()).hexdigest()[:20]
        destination = self.trash_root / trash_id / "payload"
        destination.parent.mkdir(parents=True, exist_ok=False)
        os.replace(path, destination)
        state = self._load()
        state["trash"][trash_id] = {
            "trash_id": trash_id,
            "original_path": relative,
            "stored_path": destination.relative_to(self.workspace).as_posix(),
            "reason": reason,
            "created_at": created,
            "forced": force,
            "references": protection["references"],
        }
        state["pins"].pop(relative, None)
        state["archives"].pop(relative, None)
        self._save(state)
        return dict(state["trash"][trash_id])

    def restore(self, trash_id: str, *, overwrite: bool = False) -> dict[str, Any]:
        state = self._load()
        if trash_id not in state["trash"]:
            raise LifecycleError(f"unknown trash item {trash_id!r}")
        item = state["trash"][trash_id]
        stored = self._trash_path(item["stored_path"])
        destination = self._safe_path(item["original_path"])
        if not stored.exists():
            raise LifecycleError("trash payload is missing")
        if destination.exists():
            if not overwrite:
                raise LifecycleError(f"restore destination already exists: {destination}")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stored, destination)
        shutil.rmtree(stored.parent, ignore_errors=True)
        del state["trash"][trash_id]
        self._save(state)
        return {"trash_id": trash_id, "restored_path": self._relative(destination)}

    def gc(self, *, older_than_days: int = 30, dry_run: bool = True) -> dict[str, Any]:
        import datetime as dt

        state = self._load()
        now = dt.datetime.now(dt.UTC)
        selected: list[dict[str, Any]] = []
        reclaimed = 0
        for trash_id, item in list(state["trash"].items()):
            try:
                created = dt.datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                created = now
            if (now - created).days < older_than_days:
                continue
            path = self._trash_path(item["stored_path"])
            size = _size(path)
            selected.append({"trash_id": trash_id, "bytes": size, "original_path": item["original_path"]})
            reclaimed += size
            if not dry_run:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
                shutil.rmtree(path.parent, ignore_errors=True)
                del state["trash"][trash_id]
        if not dry_run:
            self._save(state)
        return {"dry_run": dry_run, "items": selected, "bytes": reclaimed}


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    return total
