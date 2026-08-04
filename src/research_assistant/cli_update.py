from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from research_assistant.cli import _abort
from research_assistant.errors import ResearchAssistantError
from research_assistant.updater import update_local, update_server

update_app = typer.Typer(
    help="Update the ResearchAssistant source checkout or the complete local desktop installation."
)


def _emit(result: object, json_output: bool) -> None:
    payload = result.as_dict() if hasattr(result, "as_dict") else result
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return
    assert isinstance(payload, dict)
    typer.echo(
        f"{payload['mode']} update: {payload['repository']} "
        f"({payload['remote']}/{payload['branch']})"
    )
    for argv in payload["commands"]:
        typer.echo("  " + " ".join(str(value) for value in argv))
    if payload["dry_run"]:
        typer.echo("Dry run: no commands were executed.")


def _run(action, *, json_output: bool) -> None:
    try:
        result = action()
    except ResearchAssistantError as exc:
        _abort(exc)
    _emit(result, json_output)


@update_app.command("server")
def server_update(
    repo: Annotated[
        Path | None,
        typer.Option("--repo", help="ResearchAssistant Git checkout."),
    ] = None,
    remote: Annotated[
        str,
        typer.Option("--remote", help="Git remote to fast-forward from."),
    ] = "origin",
    allow_dirty: Annotated[
        bool,
        typer.Option(
            "--allow-dirty",
            help="Allow a non-clean worktree; Git conflicts still abort.",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the update plan only.")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fast-forward only the repository used on an SSH server."""
    _run(
        lambda: update_server(
            repo,
            remote=remote,
            allow_dirty=allow_dirty,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )


@update_app.command("local")
def local_update(
    repo: Annotated[
        Path | None,
        typer.Option("--repo", help="ResearchAssistant Git checkout."),
    ] = None,
    remote: Annotated[
        str,
        typer.Option("--remote", help="Git remote to fast-forward from."),
    ] = "origin",
    allow_dirty: Annotated[
        bool,
        typer.Option(
            "--allow-dirty",
            help="Allow a non-clean worktree; Git conflicts still abort.",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the update plan only.")] = False,
    package: Annotated[
        bool,
        typer.Option(
            "--package/--no-package",
            help="Also rebuild the packaged Electron executable (enabled by default).",
        ),
    ] = True,
    python: Annotated[
        Path,
        typer.Option("--python", help="Python interpreter/Conda environment to reinstall into."),
    ] = Path(sys.executable),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fast-forward source, reinstall Python, and rebuild the local Theia/Electron UI."""
    _run(
        lambda: update_local(
            repo,
            remote=remote,
            allow_dirty=allow_dirty,
            dry_run=dry_run,
            package=package,
            python=python,
        ),
        json_output=json_output,
    )


def install(app: Any) -> None:
    app.add_typer(update_app, name="update")
