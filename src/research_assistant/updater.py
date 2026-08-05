from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from research_assistant.errors import ResearchAssistantError


class UpdateError(ResearchAssistantError):
    """Raised when a safe source or desktop update cannot be completed."""


@dataclass(frozen=True)
class UpdateCommand:
    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class UpdateResult:
    mode: str
    repository: Path
    branch: str
    remote: str
    commands: tuple[UpdateCommand, ...]
    dry_run: bool
    packaged: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "repository": str(self.repository),
            "branch": self.branch,
            "remote": self.remote,
            "dry_run": self.dry_run,
            "packaged": self.packaged,
            "commands": [list(command.argv) for command in self.commands],
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _looks_like_checkout(path: Path) -> bool:
    return (
        (path / ".git").exists()
        and (path / "pyproject.toml").is_file()
        and (path / "src" / "research_assistant").is_dir()
        and (path / "desktop" / "package.json").is_file()
    )


def find_repository(path: str | Path | None = None) -> Path:
    if path is not None:
        candidate = Path(path).expanduser().resolve()
        if not _looks_like_checkout(candidate):
            raise UpdateError(f"not a ResearchAssistant Git checkout: {candidate}")
        return candidate

    candidates: list[Path] = []
    current = Path.cwd().resolve()
    candidates.extend((current, *current.parents))
    package_root = Path(__file__).resolve().parents[2]
    candidates.extend((package_root, *package_root.parents))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _looks_like_checkout(candidate):
            return candidate
    raise UpdateError(
        "cannot locate the ResearchAssistant Git checkout; pass --repo /path/to/researchassistant"
    )


def _run_text(
    argv: Sequence[str],
    *,
    cwd: Path,
    runner: Runner,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = runner(
            list(argv),
            cwd=cwd,
            env=dict(os.environ if env is None else env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise UpdateError(f"cannot execute {argv[0]}: {exc}") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "").strip()
        rendered = " ".join(argv)
        raise UpdateError(f"command failed ({completed.returncode}): {rendered}\n{detail}")
    return (completed.stdout or "").strip()


def _git_state(
    repository: Path,
    *,
    remote: str,
    allow_dirty: bool,
    runner: Runner,
) -> str:
    if shutil.which("git") is None:
        raise UpdateError("Git is not installed or is not available on PATH")
    branch = _run_text(
        ("git", "symbolic-ref", "--quiet", "--short", "HEAD"),
        cwd=repository,
        runner=runner,
    )
    if not branch:
        raise UpdateError("cannot update a checkout in detached-HEAD state")
    remotes = _run_text(("git", "remote"), cwd=repository, runner=runner).splitlines()
    if remote not in remotes:
        raise UpdateError(f"Git remote {remote!r} does not exist in {repository}")
    if not allow_dirty:
        dirty = _run_text(
            ("git", "status", "--porcelain", "--untracked-files=normal"),
            cwd=repository,
            runner=runner,
        )
        if dirty:
            raise UpdateError(
                "the ResearchAssistant checkout has local changes; "
                "commit/stash them or use --allow-dirty"
            )
    return branch


def _git_tracks_path(repository: Path, relative_path: str, *, runner: Runner) -> bool:
    tracked = _run_text(
        ("git", "ls-files", "--stage", "--", relative_path),
        cwd=repository,
        runner=runner,
    )
    return bool(tracked)


def _execute_plan(
    commands: Sequence[UpdateCommand],
    *,
    dry_run: bool,
    runner: Runner,
) -> None:
    if dry_run:
        return
    for command in commands:
        _run_text(command.argv, cwd=command.cwd, runner=runner)


def _source_plan(repository: Path, *, remote: str, branch: str) -> list[UpdateCommand]:
    return [
        UpdateCommand(("git", "fetch", "--prune", remote), repository),
        UpdateCommand(("git", "merge", "--ff-only", f"{remote}/{branch}"), repository),
    ]


def update_server(
    repository: str | Path | None = None,
    *,
    remote: str = "origin",
    allow_dirty: bool = False,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
) -> UpdateResult:
    """Fast-forward only the server-side source checkout.

    This deliberately never invokes pip, npm, Theia, Electron, or package builders.
    """
    root = find_repository(repository)
    branch = _git_state(root, remote=remote, allow_dirty=allow_dirty, runner=runner)
    commands = _source_plan(root, remote=remote, branch=branch)
    _execute_plan(commands, dry_run=dry_run, runner=runner)
    return UpdateResult(
        mode="server",
        repository=root,
        branch=branch,
        remote=remote,
        commands=tuple(commands),
        dry_run=dry_run,
    )


def update_local(
    repository: str | Path | None = None,
    *,
    remote: str = "origin",
    allow_dirty: bool = False,
    dry_run: bool = False,
    package: bool = True,
    python: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> UpdateResult:
    """Fast-forward source, reinstall Python, and rebuild/package the local Theia UI."""
    root = find_repository(repository)
    branch = _git_state(root, remote=remote, allow_dirty=allow_dirty, runner=runner)
    npm = shutil.which("npm")
    if npm is None:
        raise UpdateError("npm is required for a local desktop update but is not available on PATH")
    interpreter = str(Path(python).expanduser().resolve()) if python else sys.executable
    if not Path(interpreter).is_file():
        raise UpdateError(f"Python interpreter does not exist: {interpreter}")

    commands = _source_plan(root, remote=remote, branch=branch)
    commands.append(
        UpdateCommand(
            (
                interpreter,
                "-m",
                "pip",
                "install",
                "-e",
                f"{root}[desktop,reports]",
            ),
            root,
        )
    )
    lockfile = root / "desktop" / "package-lock.json"
    use_ci = lockfile.is_file() and _git_tracks_path(
        root,
        "desktop/package-lock.json",
        runner=runner,
    )
    install_command = "ci" if use_ci else "install"
    commands.append(UpdateCommand((npm, install_command, "--prefix", "desktop"), root))
    commands.append(UpdateCommand((npm, "run", "build", "--prefix", "desktop"), root))
    if package:
        commands.append(UpdateCommand((npm, "run", "package", "--prefix", "desktop"), root))
    _execute_plan(commands, dry_run=dry_run, runner=runner)
    return UpdateResult(
        mode="local",
        repository=root,
        branch=branch,
        remote=remote,
        commands=tuple(commands),
        dry_run=dry_run,
        packaged=package,
    )
