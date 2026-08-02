from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from research_assistant.errors import ResearchAssistantError

MAX_EDITABLE_BYTES = 2 * 1024 * 1024
MAX_DIRECTORY_PAGE = 1000
MAX_SEARCH_PAGE = 1000
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ra",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "runs",
}


class WorkspaceError(ResearchAssistantError):
    pass


class WorkspaceConflict(WorkspaceError):
    pass


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    path: str
    content: str
    revision: str
    size: int


class Workspace:
    """A bounded UTF-8 file workspace with optimistic, atomic writes."""

    def __init__(self, root: str | Path, *, max_file_bytes: int = MAX_EDITABLE_BYTES) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max_file_bytes
        if not self.root.is_dir():
            raise WorkspaceError(f"workspace is not a directory: {self.root}")

    def resolve(self, relative_path: str, *, allow_root: bool = False) -> Path:
        if "\\" in relative_path or "\x00" in relative_path:
            raise WorkspaceError("workspace paths must use safe POSIX separators")
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkspaceError(f"path escapes workspace: {relative_path!r}")
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            raise WorkspaceError(f"path is excluded from the editor: {relative_path!r}")
        if not relative.parts and not allow_root:
            raise WorkspaceError("a file path is required")

        candidate = (self.root / Path(*relative.parts)).resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise WorkspaceError(f"path escapes workspace: {relative_path!r}")
        return candidate

    def _directory_has_children(self, path: Path) -> bool:
        try:
            with os.scandir(path) as iterator:
                for item in iterator:
                    if item.is_symlink():
                        continue
                    if item.is_dir(follow_symlinks=False):
                        if item.name not in IGNORED_DIRECTORIES:
                            return True
                    elif item.is_file(follow_symlinks=False):
                        return True
        except OSError:
            return False
        return False

    def _entry(self, path: Path, *, include_children: bool = True) -> dict[str, Any] | None:
        if path.is_symlink():
            return None
        relative = path.relative_to(self.root).as_posix()
        try:
            if path.is_dir():
                if path.name in IGNORED_DIRECTORIES:
                    return None
                return {
                    "path": relative,
                    "name": path.name,
                    "kind": "directory",
                    "has_children": self._directory_has_children(path)
                    if include_children
                    else True,
                }
            if not path.is_file():
                return None
            size = path.stat().st_size
        except OSError:
            return None
        return {
            "path": relative,
            "name": path.name,
            "kind": "file",
            "size": size,
            "editable": size <= self.max_file_bytes,
            "notebook": path.suffix.lower() == ".ipynb",
        }

    def directory(
        self,
        relative_path: str = "",
        *,
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        if offset < 0:
            raise WorkspaceError("directory offset must be non-negative")
        if not 1 <= limit <= MAX_DIRECTORY_PAGE:
            raise WorkspaceError(
                f"directory limit must be between 1 and {MAX_DIRECTORY_PAGE}"
            )
        directory = self.resolve(relative_path, allow_root=True)
        if not directory.is_dir() or directory.is_symlink():
            raise WorkspaceError(f"workspace directory does not exist: {relative_path or '.'}")

        entries: list[dict[str, Any]] = []
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda item: (
                    0 if item.is_dir() and not item.is_symlink() else 1,
                    item.name.casefold(),
                    item.name,
                ),
            )
        except OSError as exc:
            raise WorkspaceError(f"cannot list {relative_path or '.'}: {exc}") from exc

        for child in children:
            entry = self._entry(child)
            if entry is not None:
                entries.append(entry)

        page = entries[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "path": PurePosixPath(relative_path).as_posix()
            if relative_path
            else "",
            "entries": page,
            "offset": offset,
            "limit": limit,
            "total": len(entries),
            "next_offset": next_offset if next_offset < len(entries) else None,
        }

    def search(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        terms = [term for term in query.casefold().split() if term]
        if not terms:
            raise WorkspaceError("workspace search query must not be empty")
        if offset < 0:
            raise WorkspaceError("search offset must be non-negative")
        if not 1 <= limit <= MAX_SEARCH_PAGE:
            raise WorkspaceError(f"search limit must be between 1 and {MAX_SEARCH_PAGE}")

        wanted = offset + limit
        matches: list[dict[str, Any]] = []
        truncated = False
        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            current = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in IGNORED_DIRECTORIES and not (current / name).is_symlink()
            )
            relative_dir = current.relative_to(self.root)
            for name in [*dirnames, *sorted(filenames)]:
                path = current / name
                if path.is_symlink():
                    continue
                relative = (relative_dir / name).as_posix()
                haystack = relative.casefold()
                if not all(term in haystack for term in terms):
                    continue
                entry = self._entry(path, include_children=False)
                if entry is None:
                    continue
                if len(matches) < wanted:
                    matches.append(entry)
                else:
                    truncated = True
                    break
            if truncated:
                break

        page = matches[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "query": query,
            "entries": page,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset if truncated or next_offset < len(matches) else None,
            "truncated": truncated,
        }

    def entries(self, *, limit: int = 5000) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        truncated = False
        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            current = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in IGNORED_DIRECTORIES and not (current / name).is_symlink()
            )
            relative_dir = current.relative_to(self.root)
            for name in dirnames:
                relative = (relative_dir / name).as_posix()
                entries.append({"path": relative, "name": name, "kind": "directory"})
                if len(entries) >= limit:
                    truncated = True
                    break
            if truncated:
                break
            for name in sorted(filenames):
                file_path = current / name
                if file_path.is_symlink():
                    continue
                relative = (relative_dir / name).as_posix()
                try:
                    size = file_path.stat().st_size
                except OSError:
                    continue
                entries.append(
                    {
                        "path": relative,
                        "name": name,
                        "kind": "file",
                        "size": size,
                        "editable": size <= self.max_file_bytes,
                        "notebook": file_path.suffix.lower() == ".ipynb",
                    }
                )
                if len(entries) >= limit:
                    truncated = True
                    break
            if truncated:
                break
        return {"entries": entries, "truncated": truncated}

    def read(self, relative_path: str) -> WorkspaceFile:
        path = self.resolve(relative_path)
        if not path.is_file() or path.is_symlink():
            raise WorkspaceError(f"file does not exist: {relative_path}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise WorkspaceError(f"cannot read {relative_path}: {exc}") from exc
        if len(data) > self.max_file_bytes:
            raise WorkspaceError(
                f"file is too large for the editor ({len(data)} bytes; limit {self.max_file_bytes})"
            )
        if b"\x00" in data:
            raise WorkspaceError(f"binary files are not editable: {relative_path}")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"file is not UTF-8 text: {relative_path}") from exc
        return WorkspaceFile(
            path=relative_path,
            content=content,
            revision=_revision(data),
            size=len(data),
        )

    def write(
        self,
        relative_path: str,
        content: str,
        expected_revision: str | None,
    ) -> WorkspaceFile:
        path = self.resolve(relative_path)
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise WorkspaceError(
                "content is too large for the editor "
                f"({len(data)} bytes; limit {self.max_file_bytes})"
            )
        if not path.parent.is_dir():
            relative_parent = path.parent.relative_to(self.root)
            raise WorkspaceError(f"parent directory does not exist: {relative_parent}")
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise WorkspaceError(f"path is not a regular file: {relative_path}")

        current_data: bytes | None = None
        if path.exists():
            try:
                current_data = path.read_bytes()
            except OSError as exc:
                raise WorkspaceError(f"cannot inspect {relative_path}: {exc}") from exc
        current_revision = _revision(current_data) if current_data is not None else None
        if current_revision != expected_revision:
            if current_revision is None:
                detail = "the file was removed outside the UI"
            elif expected_revision is None:
                detail = "the file already exists"
            else:
                detail = "the file changed outside the UI"
            raise WorkspaceConflict(f"cannot save {relative_path}: {detail}; reload before saving")

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
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise WorkspaceError(f"cannot save {relative_path}: {exc}") from exc
        return WorkspaceFile(
            path=relative_path,
            content=content,
            revision=_revision(data),
            size=len(data),
        )
