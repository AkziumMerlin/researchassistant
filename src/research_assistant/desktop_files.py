from __future__ import annotations

import base64
import os
import shutil
import stat as stat_module
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.errors import ResearchAssistantError

MAX_REMOTE_FILE_BYTES = 64 * 1024 * 1024
MAX_REMOTE_SNAPSHOT_ENTRIES = 100_000


class DesktopFileError(ResearchAssistantError):
    pass


class DesktopFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesktopWriteRequest(DesktopFileRequest):
    path: str
    content_base64: str
    create: bool = True
    overwrite: bool = True


class DesktopPathRequest(DesktopFileRequest):
    path: str


class DesktopDeleteRequest(DesktopPathRequest):
    recursive: bool = False


class DesktopMoveRequest(DesktopFileRequest):
    source: str
    target: str
    overwrite: bool = False


class DesktopSnapshotRequest(DesktopPathRequest):
    recursive: bool = False
    limit: int = Field(default=20_000, ge=1, le=MAX_REMOTE_SNAPSHOT_ENTRIES)


class DesktopFileWorkspace:
    """General-purpose desktop filesystem constrained to one workspace root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise DesktopFileError(f"workspace is not a directory: {self.root}")

    def resolve(
        self,
        relative_path: str,
        *,
        allow_root: bool = False,
        require_exists: bool = False,
    ) -> Path:
        if "\\" in relative_path or "\x00" in relative_path:
            raise DesktopFileError("desktop file paths must use safe POSIX separators")
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise DesktopFileError(f"path escapes workspace: {relative_path!r}")
        if not relative.parts:
            if allow_root:
                return self.root
            raise DesktopFileError("a file path is required")

        candidate = self.root.joinpath(*relative.parts)
        parent = candidate.parent.resolve(strict=False)
        if not parent.is_relative_to(self.root):
            raise DesktopFileError(f"path escapes workspace: {relative_path!r}")
        if candidate.exists() or candidate.is_symlink():
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(self.root):
                raise DesktopFileError(
                    f"path escapes workspace through a symlink: {relative_path!r}"
                )
        if require_exists and not (candidate.exists() or candidate.is_symlink()):
            raise DesktopFileError(f"path does not exist: {relative_path or '.'}")
        return candidate

    @staticmethod
    def _kind(path: Path) -> Literal["file", "directory", "symlink", "unknown"]:
        try:
            mode = path.lstat().st_mode
        except OSError:
            return "unknown"
        if stat_module.S_ISLNK(mode):
            return "symlink"
        if stat_module.S_ISDIR(mode):
            return "directory"
        if stat_module.S_ISREG(mode):
            return "file"
        return "unknown"

    def stat(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path, allow_root=True, require_exists=True)
        try:
            raw = path.stat()
        except OSError as exc:
            raise DesktopFileError(f"cannot stat {relative_path or '.'}: {exc}") from exc
        return {
            "path": relative_path,
            "type": self._kind(path),
            "ctime_ms": int(raw.st_ctime_ns // 1_000_000),
            "mtime_ms": int(raw.st_mtime_ns // 1_000_000),
            "size": int(raw.st_size),
            "mode": int(raw.st_mode & 0o777),
        }

    def readdir(self, relative_path: str) -> dict[str, Any]:
        directory = self.resolve(relative_path, allow_root=True, require_exists=True)
        if not directory.is_dir() or directory.is_symlink():
            raise DesktopFileError(f"not a directory: {relative_path or '.'}")
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as exc:
            raise DesktopFileError(f"cannot list {relative_path or '.'}: {exc}") from exc
        entries = []
        for child in children:
            kind = self._kind(child)
            if kind == "unknown":
                continue
            entries.append({"name": child.name, "type": kind})
        return {"path": relative_path, "entries": entries}

    def read(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path, require_exists=True)
        if not path.is_file():
            raise DesktopFileError(f"not a regular file: {relative_path}")
        try:
            size = path.stat().st_size
            if size > MAX_REMOTE_FILE_BYTES:
                raise DesktopFileError(
                    f"file is too large ({size} bytes; limit {MAX_REMOTE_FILE_BYTES})"
                )
            data = path.read_bytes()
        except OSError as exc:
            raise DesktopFileError(f"cannot read {relative_path}: {exc}") from exc
        return {
            "path": relative_path,
            "size": len(data),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }

    def write(
        self,
        relative_path: str,
        data: bytes,
        *,
        create: bool,
        overwrite: bool,
    ) -> dict[str, Any]:
        if len(data) > MAX_REMOTE_FILE_BYTES:
            raise DesktopFileError(
                f"file is too large ({len(data)} bytes; limit {MAX_REMOTE_FILE_BYTES})"
            )
        path = self.resolve(relative_path)
        exists = path.exists() or path.is_symlink()
        if exists and not overwrite:
            raise DesktopFileError(f"path already exists: {relative_path}")
        if not exists and not create:
            raise DesktopFileError(f"path does not exist: {relative_path}")
        if exists and (not path.is_file() or path.is_symlink()):
            raise DesktopFileError(f"not a regular file: {relative_path}")
        if not path.parent.is_dir():
            raise DesktopFileError(
                f"parent directory does not exist: {path.parent.relative_to(self.root).as_posix()}"
            )

        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_name, mode)
            os.replace(temporary_name, path)
        except OSError as exc:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise DesktopFileError(f"cannot write {relative_path}: {exc}") from exc
        return self.stat(relative_path)

    def mkdir(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path)
        try:
            path.mkdir()
        except OSError as exc:
            raise DesktopFileError(f"cannot create directory {relative_path}: {exc}") from exc
        return self.stat(relative_path)

    def delete(self, relative_path: str, *, recursive: bool) -> dict[str, Any]:
        path = self.resolve(relative_path, require_exists=True)
        if path.is_symlink() or path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                raise DesktopFileError(f"cannot delete {relative_path}: {exc}") from exc
        elif path.is_dir():
            try:
                if recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            except OSError as exc:
                raise DesktopFileError(f"cannot delete {relative_path}: {exc}") from exc
        else:
            raise DesktopFileError(f"unsupported file type: {relative_path}")
        return {"path": relative_path, "deleted": True}

    def rename(self, source: str, target: str, *, overwrite: bool) -> dict[str, Any]:
        source_path = self.resolve(source, require_exists=True)
        target_path = self.resolve(target)
        target_exists = target_path.exists() or target_path.is_symlink()
        if target_exists and not overwrite:
            raise DesktopFileError(f"target already exists: {target}")
        if not target_path.parent.is_dir():
            raise DesktopFileError(f"target parent does not exist: {target}")
        try:
            if overwrite and target_exists:
                if target_path.is_dir() and not target_path.is_symlink():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            os.replace(source_path, target_path)
        except OSError as exc:
            raise DesktopFileError(f"cannot rename {source} to {target}: {exc}") from exc
        return self.stat(target)

    def copy(self, source: str, target: str, *, overwrite: bool) -> dict[str, Any]:
        source_path = self.resolve(source, require_exists=True)
        target_path = self.resolve(target)
        target_exists = target_path.exists() or target_path.is_symlink()
        if target_exists and not overwrite:
            raise DesktopFileError(f"target already exists: {target}")
        if not target_path.parent.is_dir():
            raise DesktopFileError(f"target parent does not exist: {target}")
        try:
            if overwrite and target_exists:
                if target_path.is_dir() and not target_path.is_symlink():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            if source_path.is_dir() and not source_path.is_symlink():
                shutil.copytree(source_path, target_path, symlinks=True)
            else:
                shutil.copy2(source_path, target_path, follow_symlinks=False)
        except OSError as exc:
            raise DesktopFileError(f"cannot copy {source} to {target}: {exc}") from exc
        return self.stat(target)

    def snapshot(self, relative_path: str, *, recursive: bool, limit: int) -> dict[str, Any]:
        root = self.resolve(relative_path, allow_root=True, require_exists=True)
        entries: list[dict[str, Any]] = []

        def append(path: Path) -> bool:
            relative = path.relative_to(self.root).as_posix()
            try:
                raw = path.stat()
            except OSError:
                return True
            entries.append(
                {
                    "path": relative,
                    "type": self._kind(path),
                    "mtime_ms": int(raw.st_mtime_ns // 1_000_000),
                    "size": int(raw.st_size),
                }
            )
            return len(entries) < limit

        if not append(root):
            return {"entries": entries, "truncated": True}
        if root.is_dir() and not root.is_symlink():
            iterator = root.rglob("*") if recursive else root.iterdir()
            try:
                for child in iterator:
                    if not append(child):
                        return {"entries": entries, "truncated": True}
            except OSError as exc:
                raise DesktopFileError(f"cannot snapshot {relative_path or '.'}: {exc}") from exc
        entries.sort(key=lambda row: str(row["path"]))
        return {"entries": entries, "truncated": False}


def register_desktop_file_routes(app) -> None:
    try:
        from fastapi import Query
    except ImportError as exc:  # pragma: no cover
        raise DesktopFileError("desktop API dependencies are missing") from exc

    workspace = DesktopFileWorkspace(app.state.workspace.root)
    app.state.desktop_files = workspace

    @app.get("/api/desktop/files/stat")
    def desktop_file_stat(path: str = Query(default="")) -> dict[str, Any]:
        return workspace.stat(path)

    @app.get("/api/desktop/files/read")
    def desktop_file_read(path: str = Query(min_length=1)) -> dict[str, Any]:
        return workspace.read(path)

    @app.get("/api/desktop/files/readdir")
    def desktop_file_readdir(path: str = Query(default="")) -> dict[str, Any]:
        return workspace.readdir(path)

    @app.post("/api/desktop/files/write")
    def desktop_file_write(payload: DesktopWriteRequest) -> dict[str, Any]:
        try:
            data = base64.b64decode(payload.content_base64, validate=True)
        except ValueError as exc:
            raise DesktopFileError("invalid base64 file content") from exc
        return workspace.write(
            payload.path,
            data,
            create=payload.create,
            overwrite=payload.overwrite,
        )

    @app.post("/api/desktop/files/mkdir")
    def desktop_file_mkdir(payload: DesktopPathRequest) -> dict[str, Any]:
        return workspace.mkdir(payload.path)

    @app.post("/api/desktop/files/delete")
    def desktop_file_delete(payload: DesktopDeleteRequest) -> dict[str, Any]:
        return workspace.delete(payload.path, recursive=payload.recursive)

    @app.post("/api/desktop/files/rename")
    def desktop_file_rename(payload: DesktopMoveRequest) -> dict[str, Any]:
        return workspace.rename(payload.source, payload.target, overwrite=payload.overwrite)

    @app.post("/api/desktop/files/copy")
    def desktop_file_copy(payload: DesktopMoveRequest) -> dict[str, Any]:
        return workspace.copy(payload.source, payload.target, overwrite=payload.overwrite)

    @app.post("/api/desktop/files/snapshot")
    def desktop_file_snapshot(payload: DesktopSnapshotRequest) -> dict[str, Any]:
        return workspace.snapshot(payload.path, recursive=payload.recursive, limit=payload.limit)
