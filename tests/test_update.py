from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_assistant.updater import UpdateError, find_repository, update_local, update_server


def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "researchassistant"
    (root / ".git").mkdir(parents=True)
    (root / "src" / "research_assistant").mkdir(parents=True)
    (root / "desktop").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='research-assistant'\n")
    (root / "desktop" / "package.json").write_text("{}\n")
    (root / "desktop" / "package-lock.json").write_text("{}\n")
    return root


class FakeRunner:
    def __init__(self, *, dirty: bool = False) -> None:
        self.dirty = dirty
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, **_kwargs):
        command = tuple(str(value) for value in argv)
        self.calls.append(command)
        stdout = ""
        if command[:4] == ("git", "symbolic-ref", "--quiet", "--short"):
            stdout = "main\n"
        elif command == ("git", "remote"):
            stdout = "origin\n"
        elif command[:3] == ("git", "status", "--porcelain"):
            stdout = " M README.md\n" if self.dirty else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def test_find_repository_walks_up_from_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = checkout(tmp_path)
    child = root / "desktop" / "application"
    child.mkdir(parents=True)
    monkeypatch.chdir(child)

    assert find_repository() == root


def test_server_update_only_fast_forwards_git(tmp_path: Path) -> None:
    root = checkout(tmp_path)
    runner = FakeRunner()

    result = update_server(root, runner=runner)

    assert result.mode == "server"
    assert result.branch == "main"
    assert ("git", "fetch", "--prune", "origin") in runner.calls
    assert ("git", "merge", "--ff-only", "origin/main") in runner.calls
    assert not any("pip" in command or "npm" in command for command in runner.calls)


def test_local_update_reinstalls_and_rebuilds_desktop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = checkout(tmp_path)
    runner = FakeRunner()
    python = tmp_path / "python"
    python.write_text("")
    npm = tmp_path / "npm"
    npm.write_text("")
    monkeypatch.setattr("research_assistant.updater.shutil.which", lambda name: str(npm))

    result = update_local(root, python=python, runner=runner)

    assert result.mode == "local"
    assert result.packaged is True
    assert (str(python), "-m", "pip", "install", "-e", f"{root}[desktop,reports]") in runner.calls
    assert (str(npm), "ci", "--prefix", "desktop") in runner.calls
    assert (str(npm), "run", "build", "--prefix", "desktop") in runner.calls
    assert (str(npm), "run", "package", "--prefix", "desktop") in runner.calls


def test_local_update_can_skip_packaging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = checkout(tmp_path)
    runner = FakeRunner()
    python = tmp_path / "python"
    python.write_text("")
    npm = tmp_path / "npm"
    npm.write_text("")
    monkeypatch.setattr("research_assistant.updater.shutil.which", lambda name: str(npm))

    update_local(root, python=python, package=False, runner=runner)

    assert not any(command[1:3] == ("run", "package") for command in runner.calls)


def test_update_rejects_dirty_worktree(tmp_path: Path) -> None:
    root = checkout(tmp_path)

    with pytest.raises(UpdateError, match="local changes"):
        update_server(root, runner=FakeRunner(dirty=True))


def test_dry_run_validates_but_does_not_execute_update_commands(tmp_path: Path) -> None:
    root = checkout(tmp_path)
    runner = FakeRunner()

    result = update_server(root, dry_run=True, runner=runner)

    assert result.dry_run is True
    assert ("git", "fetch", "--prune", "origin") not in runner.calls
    assert ("git", "merge", "--ff-only", "origin/main") not in runner.calls


def test_update_commands_are_registered_in_root_cli() -> None:
    from typer.testing import CliRunner

    from research_assistant.cli_workbench import app

    runner = CliRunner()
    assert runner.invoke(app, ["update", "--help"]).exit_code == 0
    assert runner.invoke(app, ["update", "server", "--help"]).exit_code == 0
    assert runner.invoke(app, ["update", "local", "--help"]).exit_code == 0
