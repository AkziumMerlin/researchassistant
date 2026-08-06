from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml

from research_assistant.errors import ResearchAssistantError
from research_assistant.project_import import import_project, scan_project

_INSTALLED = False
project_app = typer.Typer(
    help="Scan and import an existing experiment project without rewriting its source."
)


def _abort(exc: Exception) -> None:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc


def _echo(value: object, *, json_output: bool = False) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return
    typer.echo(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())


def _summary(plan) -> str:
    summary = plan.summary()
    return (
        f"found {summary['python']} Python component candidate(s), "
        f"{summary['legacy_configs']} legacy config(s); "
        f"{summary['recommended']} recommended for import"
    )


@project_app.command("scan")
def project_scan(
    path: Annotated[Path, typer.Argument()] = Path("."),
    include_python: Annotated[bool, typer.Option("--python/--no-python")] = True,
    include_configs: Annotated[bool, typer.Option("--configs/--no-configs")] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect source files and old YAMLs without importing or executing project code."""
    try:
        plan = scan_project(
            path,
            include_python=include_python,
            include_configs=include_configs,
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    if not json_output:
        typer.echo(_summary(plan), err=True)
    _echo(plan, json_output=json_output)


@project_app.command("import")
def project_import(
    path: Annotated[Path, typer.Argument()] = Path("."),
    candidate: Annotated[
        list[str] | None,
        typer.Option("--candidate", help="Import only this candidate ID; repeat as needed."),
    ] = None,
    import_all: Annotated[
        bool,
        typer.Option("--all", help="Include medium/low-confidence candidates too."),
    ] = False,
    include_python: Annotated[bool, typer.Option("--python/--no-python")] = True,
    include_configs: Annotated[bool, typer.Option("--configs/--no-configs")] = True,
    replace: Annotated[bool, typer.Option("--replace")] = False,
    validate_python: Annotated[
        bool,
        typer.Option("--validate-python/--no-validate-python"),
    ] = True,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Register selected components and wrap old YAML configs in one operation."""
    try:
        plan = scan_project(
            path,
            include_python=include_python,
            include_configs=include_configs,
        )
        if dry_run:
            if not json_output:
                typer.echo(_summary(plan), err=True)
            _echo(plan, json_output=json_output)
            return

        if candidate is not None:
            selected_count = len(candidate)
        elif import_all:
            selected_count = sum(
                not item.already_registered for item in plan.candidates
            )
        else:
            selected_count = sum(item.selected for item in plan.candidates)
        if selected_count == 0:
            _echo(
                {
                    "message": "nothing new to import",
                    "summary": plan.summary(),
                    "warnings": plan.warnings,
                },
                json_output=json_output,
            )
            return

        if not yes:
            if not sys.stdin.isatty():
                raise ResearchAssistantError(
                    "project import needs confirmation; rerun with --yes or use --dry-run"
                )
            typer.echo(_summary(plan))
            if not typer.confirm(f"Import {selected_count} selected item(s)?"):
                raise typer.Abort()

        result = import_project(
            path,
            candidate_ids=candidate,
            import_all=import_all,
            replace=replace,
            validate_python=validate_python,
            include_python=include_python,
            include_configs=include_configs,
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output=json_output)
    if result.summary()["failed"]:
        raise typer.Exit(code=1)


def install(app) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    app.add_typer(project_app, name="project")
    _INSTALLED = True
