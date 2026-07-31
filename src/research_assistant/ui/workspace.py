from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from research_assistant.errors import ResearchAssistantError

MAX_EDITABLE_BYTES = 2 * 1024 * 1024
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
