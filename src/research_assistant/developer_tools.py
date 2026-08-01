from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from research_assistant.errors import ResearchAssistantError


class DeveloperToolError(ResearchAssistantError):
    pass


class DeveloperTools:
    def __init__(self, workspace: str | Path, *, trusted: bool = False) -> None:
        self.workspace = Path(workspace).resolve()
        self.trusted = trusted

    def require_trusted(self) -> None:
        if not self.trusted:
            raise DeveloperToolError(
                "trusted developer mode is disabled; start with RA_TRUSTED_DEV=1"
            )

    def _safe_path(self, raw: str | Path) -> Path:
        path = Path(raw)
        resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise DeveloperToolError(f"path escapes workspace: {raw}")
        if resolved.is_relative_to(self.workspace / ".git"):
            raise DeveloperToolError("direct access to .git is not allowed")
        return resolved

    def _run(
        self,
        argv: list[str],
        *,
        timeout: float = 60.0,
        check: bool = True,
    ) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                argv,
                cwd=self.workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except OSError as exc:
            if not check:
                return {
                    "argv": argv,
                    "returncode": 127,
                    "stdout": "",
                    "stderr": str(exc),
                }
            raise DeveloperToolError(f"cannot execute {argv[0]!r}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            if not check:
                return {
                    "argv": argv,
                    "returncode": 124,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or str(exc),
                }
            raise DeveloperToolError(f"command timed out: {argv[0]!r}") from exc
        result = {
            "argv": argv,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise DeveloperToolError(f"command failed: {detail or completed.returncode}")
        return result

    def diagnostics(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trusted": self.trusted,
            "workspace": str(self.workspace),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "conda_prefix": os.environ.get("CONDA_PREFIX"),
        }
        for command in ("git", "conda", "nvidia-smi"):
            result = self._run([command, "--version"], timeout=10, check=False)
            payload[command] = {
                "available": result["returncode"] == 0,
                "version": (result["stdout"] or result["stderr"]).strip().splitlines()[:1],
            }
        return payload

    def git_status(self) -> dict[str, Any]:
        result = self._run(["git", "status", "--porcelain=v1", "--branch"])
        lines = result["stdout"].splitlines()
        return {"summary": lines[0] if lines else "", "entries": lines[1:]}

    def git_diff(self, *, staged: bool = False, path: str | None = None) -> dict[str, Any]:
        argv = ["git", "diff"]
        if staged:
            argv.append("--cached")
        if path is not None:
            safe = self._safe_path(path)
            argv.extend(["--", safe.relative_to(self.workspace).as_posix()])
        return self._run(argv, timeout=30)

    def git_log(self, *, limit: int = 50) -> dict[str, Any]:
        return self._run(
            [
                "git",
                "log",
                f"-{limit}",
                "--date=iso-strict",
                "--pretty=format:%h%x09%ad%x09%an%x09%s",
            ],
            timeout=30,
        )

    def git_branches(self) -> dict[str, Any]:
        return self._run(
            ["git", "branch", "--all", "--format=%(if)%(HEAD)%(then)* %(else)  %(end)%(refname:short)"],
            timeout=30,
        )

    def git_create_branch(self, name: str, *, start_point: str | None = None) -> dict[str, Any]:
        self.require_trusted()
        if not name.startswith(("agent/", "feature/", "fix/", "codex/")):
            raise DeveloperToolError("development branches must use an explicit namespace")
        argv = ["git", "switch", "-c", name]
        if start_point:
            argv.append(start_point)
        return self._run(argv)

    def git_switch(self, name: str) -> dict[str, Any]:
        self.require_trusted()
        return self._run(["git", "switch", name])

    def git_commit(self, message: str, *, paths: list[str], push: bool = False) -> dict[str, Any]:
        self.require_trusted()
        if not message.strip():
            raise DeveloperToolError("commit message is empty")
        if not paths:
            raise DeveloperToolError("explicit commit paths are required")
        relative_paths = [self._safe_path(path).relative_to(self.workspace).as_posix() for path in paths]
        self._run(["git", "add", "--", *relative_paths])
        result = self._run(["git", "commit", "-m", message])
        if push:
            result["push"] = self.git_push()
        return result

    def git_push(self) -> dict[str, Any]:
        self.require_trusted()
        branch = self._run(["git", "branch", "--show-current"])["stdout"].strip()
        if not branch:
            raise DeveloperToolError("cannot push a detached HEAD")
        if branch in {"main", "master"}:
            raise DeveloperToolError("trusted UI refuses to push directly to the default branch")
        return self._run(["git", "push", "-u", "origin", branch], timeout=180)

    def search(
        self,
        query: str,
        *,
        root: str = ".",
        pattern: str = "*",
        case_sensitive: bool = False,
        max_results: int = 1000,
    ) -> dict[str, Any]:
        if not query:
            raise DeveloperToolError("search query is empty")
        search_root = self._safe_path(root)
        if not search_root.is_dir():
            raise DeveloperToolError(f"search root is not a directory: {search_root}")
        needle = query if case_sensitive else query.lower()
        matches: list[dict[str, Any]] = []
        for path in search_root.rglob(pattern):
            if len(matches) >= max_results:
                break
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            if any(part in {".git", ".ra", "node_modules", "__pycache__"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(
                        {
                            "path": path.relative_to(self.workspace).as_posix(),
                            "line": line_number,
                            "text": line[:500],
                        }
                    )
                    if len(matches) >= max_results:
                        break
        return {"matches": matches, "truncated": len(matches) >= max_results}

    def move(self, source: str, destination: str, *, overwrite: bool = False) -> dict[str, Any]:
        self.require_trusted()
        src = self._safe_path(source)
        dst = self._safe_path(destination)
        if not src.exists():
            raise DeveloperToolError(f"source does not exist: {src}")
        if dst.exists() and not overwrite:
            raise DeveloperToolError(f"destination already exists: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and dst.exists():
            if dst.is_dir():
                import shutil

                shutil.rmtree(dst)
            else:
                dst.unlink()
        src.replace(dst)
        return {
            "source": source,
            "destination": dst.relative_to(self.workspace).as_posix(),
        }

    def mkdir(self, path: str) -> dict[str, Any]:
        self.require_trusted()
        target = self._safe_path(path)
        target.mkdir(parents=True, exist_ok=True)
        return {"path": target.relative_to(self.workspace).as_posix()}
