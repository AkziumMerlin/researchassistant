from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml

from research_assistant.analysis_sessions import AnalysisSessionManager, TaskCatalog
from research_assistant.cli import _abort
from research_assistant.cli_explorer import app
from research_assistant.cli_research_workspace import install as install_research_workspace_cli
from research_assistant.developer_tools import DeveloperTools
from research_assistant.errors import ResearchAssistantError
from research_assistant.lifecycle import LifecycleManager
from research_assistant.scientific_artifacts import ScientificArtifactCatalog
from research_assistant.workspaces import (
    WorkspaceCatalog,
    conda_environments,
    export_environment,
    inspect_interpreter,
)

workspace_app = typer.Typer(help="Manage local/SSH workspaces and Python or Conda environments.")
artifact_app = typer.Typer(help="Catalog and inspect multidimensional scientific artifacts.")
lifecycle_app = typer.Typer(help="Pin, archive, trash, restore and garbage-collect results safely.")
analysis_app = typer.Typer(help="Run and inspect detached analysis sessions and project tasks.")
dev_app = typer.Typer(help="Trusted local developer tools for Git and workspace maintenance.")

app.add_typer(workspace_app, name="workspace")
app.add_typer(artifact_app, name="artifact")
app.add_typer(lifecycle_app, name="lifecycle")
app.add_typer(analysis_app, name="analysis")
app.add_typer(dev_app, name="dev")

install_research_workspace_cli(workspace_app, analysis_app)


def _echo(value: object, json_output: bool = False) -> None:
    if isinstance(value, str) and not json_output:
        typer.echo(value)
    elif json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        typer.echo(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())


def _trusted() -> bool:
    return os.environ.get("RA_TRUSTED_DEV", "").lower() in {"1", "true", "yes", "on"}


def _run(action, *, json_output: bool = False) -> None:
    try:
        value = action()
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(value, json_output)


@workspace_app.command("list")
def workspace_list(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _run(lambda: WorkspaceCatalog().list(), json_output=json_output)


@workspace_app.command("add")
def workspace_add(
    name: str,
    path: Path,
    python: Annotated[Path | None, typer.Option("--python")] = None,
    conda_env: Annotated[str | None, typer.Option("--conda-env")] = None,
    ssh_target: Annotated[str | None, typer.Option("--ssh-target")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: WorkspaceCatalog().add(
            name,
            path,
            python=python,
            conda_env=conda_env,
            ssh_target=ssh_target,
        ),
        json_output=json_output,
    )


@workspace_app.command("remove")
def workspace_remove(name: str) -> None:
    def action() -> dict[str, str]:
        WorkspaceCatalog().remove(name)
        return {"removed": name}

    _run(action)


@workspace_app.command("conda")
def workspace_conda(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _run(conda_environments, json_output=json_output)


@workspace_app.command("inspect")
def workspace_inspect(
    python: Annotated[Path, typer.Option("--python")] = Path(sys.executable),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(lambda: inspect_interpreter(python), json_output=json_output)


@workspace_app.command("export-env")
def workspace_export_environment(
    destination: Path,
    python: Annotated[Path, typer.Option("--python")] = Path(sys.executable),
    explicit_conda: Annotated[bool, typer.Option("--conda-explicit/--pip-freeze")] = True,
) -> None:
    _run(lambda: {"path": str(export_environment(destination, python=python, explicit_conda=explicit_conda))})


@artifact_app.command("list")
def artifact_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    kind: Annotated[str | None, typer.Option("--kind")] = None,
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    sample_id: Annotated[str | None, typer.Option("--sample")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000)] = 2000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: ScientificArtifactCatalog(workspace).list(
            kind=kind, run_id=run_id, sample_id=sample_id, search=search, limit=limit
        ),
        json_output=json_output,
    )


@artifact_app.command("register")
def artifact_register(
    path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    kind: Annotated[str | None, typer.Option("--kind")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    stage: Annotated[str | None, typer.Option("--stage")] = None,
    sample_id: Annotated[str | None, typer.Option("--sample")] = None,
    role: Annotated[str | None, typer.Option("--role")] = None,
    dimension: Annotated[list[str] | None, typer.Option("--dimension")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: ScientificArtifactCatalog(workspace).register(
            path,
            kind=kind,  # type: ignore[arg-type]
            name=name,
            run_id=run_id,
            stage=stage,
            sample_id=sample_id,
            role=role,
            dimensions=dimension or [],
            tags=tag or [],
        ),
        json_output=json_output,
    )


@artifact_app.command("discover")
def artifact_discover(
    root: Annotated[list[str] | None, typer.Option("--root")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    limit: Annotated[int, typer.Option("--limit", min=1, max=100000)] = 10000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: ScientificArtifactCatalog(workspace).discover(root, limit=limit),
        json_output=json_output,
    )


@artifact_app.command("show")
def artifact_show(
    artifact_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
) -> None:
    _run(lambda: ScientificArtifactCatalog(workspace).require(artifact_id, refresh=refresh))


@artifact_app.command("slice")
def artifact_slice(
    artifact_id: str,
    select: Annotated[list[str] | None, typer.Option("--select")] = None,
    key: Annotated[str | None, typer.Option("--key")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000000)] = 100000,
) -> None:
    _run(
        lambda: ScientificArtifactCatalog(workspace).slice(
            artifact_id, selection=select or [], key=key, max_elements=limit
        )
    )


@artifact_app.command("compare")
def artifact_compare(
    left_id: str,
    right_id: str,
    key: Annotated[str | None, typer.Option("--key")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: ScientificArtifactCatalog(workspace).compare(left_id, right_id, key=key))


@lifecycle_app.command("state")
def lifecycle_state(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).state())


@lifecycle_app.command("protect")
def lifecycle_protect(
    path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).protection(path))


@lifecycle_app.command("pin")
def lifecycle_pin(
    path: Path,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).pin(path, reason=reason))


@lifecycle_app.command("unpin")
def lifecycle_unpin(
    path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    def action() -> dict[str, str]:
        LifecycleManager(workspace).unpin(path)
        return {"unpinned": str(path)}

    _run(action)


@lifecycle_app.command("archive")
def lifecycle_archive(
    path: Path,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).archive(path, reason=reason))


@lifecycle_app.command("unarchive")
def lifecycle_unarchive(
    path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    def action() -> dict[str, str]:
        LifecycleManager(workspace).unarchive(path)
        return {"unarchived": str(path)}

    _run(action)


@lifecycle_app.command("trash")
def lifecycle_trash(
    path: Path,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).trash(path, reason=reason, force=force))


@lifecycle_app.command("restore")
def lifecycle_restore(
    trash_id: str,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).restore(trash_id, overwrite=overwrite))


@lifecycle_app.command("gc")
def lifecycle_gc(
    older_than_days: Annotated[int, typer.Option("--older-than-days", min=0)] = 30,
    apply: Annotated[bool, typer.Option("--apply")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).gc(older_than_days=older_than_days, dry_run=not apply))


@lifecycle_app.command("quota")
def lifecycle_quota(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: LifecycleManager(workspace).quota())


@analysis_app.command("list")
def analysis_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: AnalysisSessionManager(workspace).list())


@analysis_app.command("run")
def analysis_run(
    script: Path,
    arg: Annotated[list[str] | None, typer.Option("--arg")] = None,
    cwd: Annotated[Path, typer.Option("--cwd")] = Path("."),
    python: Annotated[Path, typer.Option("--python")] = Path(sys.executable),
    profile: Annotated[bool, typer.Option("--profile")] = False,
    label: Annotated[str | None, typer.Option("--label")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(
        lambda: AnalysisSessionManager(workspace).start_script(
            script, args=arg or [], cwd=cwd, python=python, profile=profile, label=label
        )
    )


@analysis_app.command("scratchpad")
def analysis_scratchpad(
    code: Annotated[str, typer.Option("--code")],
    cwd: Annotated[Path, typer.Option("--cwd")] = Path("."),
    python: Annotated[Path, typer.Option("--python")] = Path(sys.executable),
    label: Annotated[str | None, typer.Option("--label")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: AnalysisSessionManager(workspace).start_scratchpad(code, cwd=cwd, python=python, label=label))


@analysis_app.command("task-list")
def analysis_task_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: TaskCatalog(workspace).list())


@analysis_app.command("task-run")
def analysis_task_run(
    name: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: TaskCatalog(workspace).run(name, AnalysisSessionManager(workspace)))


@analysis_app.command("status")
def analysis_status(
    session_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: AnalysisSessionManager(workspace).status(session_id))


@analysis_app.command("logs")
def analysis_logs(
    session_id: str,
    stream: Annotated[Literal["stdout", "stderr"], typer.Option("--stream")] = "stdout",
    tail_bytes: Annotated[int, typer.Option("--tail-bytes", min=1, max=10000000)] = 200000,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: AnalysisSessionManager(workspace).logs(session_id, stream=stream, tail_bytes=tail_bytes))


@analysis_app.command("stop")
def analysis_stop(
    session_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: AnalysisSessionManager(workspace).stop(session_id))


def _dev(workspace: Path) -> DeveloperTools:
    return DeveloperTools(workspace, trusted=_trusted())


@dev_app.command("diagnostics")
def dev_diagnostics(workspace: Annotated[Path, typer.Option("--workspace")] = Path(".")) -> None:
    _run(lambda: _dev(workspace).diagnostics())


@dev_app.command("status")
def dev_status(workspace: Annotated[Path, typer.Option("--workspace")] = Path(".")) -> None:
    _run(lambda: _dev(workspace).git_status())


@dev_app.command("diff")
def dev_diff(
    staged: Annotated[bool, typer.Option("--staged")] = False,
    path: Annotated[str | None, typer.Option("--path")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: _dev(workspace).git_diff(staged=staged, path=path))


@dev_app.command("log")
def dev_log(
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 50,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: _dev(workspace).git_log(limit=limit))


@dev_app.command("branches")
def dev_branches(workspace: Annotated[Path, typer.Option("--workspace")] = Path(".")) -> None:
    _run(lambda: _dev(workspace).git_branches())


@dev_app.command("branch")
def dev_branch(
    name: str,
    start_point: Annotated[str | None, typer.Option("--start-point")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: _dev(workspace).git_create_branch(name, start_point=start_point))


@dev_app.command("switch")
def dev_switch(name: str, workspace: Annotated[Path, typer.Option("--workspace")] = Path(".")) -> None:
    _run(lambda: _dev(workspace).git_switch(name))


@dev_app.command("commit")
def dev_commit(
    message: Annotated[str, typer.Option("--message", "-m")],
    path: Annotated[list[str], typer.Option("--path")],
    push: Annotated[bool, typer.Option("--push")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: _dev(workspace).git_commit(message, paths=path, push=push))


@dev_app.command("push")
def dev_push(workspace: Annotated[Path, typer.Option("--workspace")] = Path(".")) -> None:
    _run(lambda: _dev(workspace).git_push())


@dev_app.command("search")
def dev_search(
    query: str,
    root: Annotated[str, typer.Option("--root")] = ".",
    pattern: Annotated[str, typer.Option("--pattern")] = "*",
    case_sensitive: Annotated[bool, typer.Option("--case-sensitive")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000)] = 1000,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(
        lambda: _dev(workspace).search(
            query, root=root, pattern=pattern, case_sensitive=case_sensitive, max_results=limit
        )
    )


@dev_app.command("move")
def dev_move(
    source: str,
    destination: str,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _run(lambda: _dev(workspace).move(source, destination, overwrite=overwrite))


@dev_app.command("mkdir")
def dev_mkdir(path: str, workspace: Annotated[Path, typer.Option("--workspace")] = Path(".")) -> None:
    _run(lambda: _dev(workspace).mkdir(path))
