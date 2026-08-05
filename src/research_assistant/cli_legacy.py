from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from research_assistant.errors import ResearchAssistantError
from research_assistant.legacy import (
    ProjectRegistrationCatalog,
    RegistrationCatalogDocument,
    discover_python_symbols,
    find_project_root,
    suggest_legacy_entrypoint,
)
from research_assistant.plugins import load_registry

_INSTALLED = False
legacy_app = typer.Typer(
    help="Register project-local Python components and wrap existing experiment configs."
)
python_app = typer.Typer(help="Discover and register callables from project .py files.")
config_app = typer.Typer(help="Register existing YAML configs through their original runner.")
legacy_app.add_typer(python_app, name="python")
legacy_app.add_typer(config_app, name="config")


def _root(project: Path) -> Path:
    root = project.expanduser().resolve()
    if not root.is_dir():
        raise ResearchAssistantError(f"project root is not a directory: {root}")
    return root


def _echo(value: object, *, json_output: bool = False) -> None:
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        typer.echo(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())


def _abort(exc: Exception) -> None:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc


def _restore_catalog(
    catalog: ProjectRegistrationCatalog,
    previous: RegistrationCatalogDocument,
    existed: bool,
) -> None:
    if existed:
        catalog.save(previous)
        return
    catalog.path.unlink(missing_ok=True)
    try:
        catalog.path.parent.rmdir()
    except OSError:
        pass


@legacy_app.command("list")
def list_registrations(
    project: Annotated[Path, typer.Option("--project", "-p")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List project-local Python components and legacy config wrappers."""
    try:
        document = ProjectRegistrationCatalog(_root(project)).load()
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(document.model_dump(mode="json"), json_output=json_output)


@python_app.command("discover")
def discover_python(
    path: Path,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List public top-level classes and functions without executing the file."""
    try:
        root = _root(project)
        source = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not source.is_relative_to(root):
            raise ResearchAssistantError(f"Python path escapes project root: {path}")
        rows = discover_python_symbols(source)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo({"path": source.relative_to(root).as_posix(), "symbols": rows}, json_output=json_output)


@python_app.command("register")
def register_python(
    path: Path,
    symbol: Annotated[str, typer.Option("--symbol", "-s")],
    kind: Annotated[str, typer.Option("--kind", "-k")] = "model",
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    catalog_name: Annotated[str, typer.Option("--catalog")] = "component",
    editor: Annotated[str | None, typer.Option("--editor")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path("."),
    replace: Annotated[bool, typer.Option("--replace")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Register one class or function from a .py file as a typed component."""
    try:
        root = _root(project)
        registered_name = name or f"local/{symbol.lower().replace('_', '-')}"
        catalog = ProjectRegistrationCatalog(root)
        existed = catalog.path.is_file()
        previous = catalog.load()
        try:
            registration = catalog.add_python(
                kind=kind,
                name=registered_name,
                path=path,
                symbol=symbol,
                description=description,
                catalog=catalog_name,
                editor=editor,
                replace=replace,
            )
            registry = load_registry([], project_root=root)
            spec = registry.get(kind, registered_name)
        except Exception:
            _restore_catalog(catalog, previous, existed)
            raise
        payload = {
            "registration": registration.model_dump(mode="json"),
            "provider": spec.provider,
            "schema": spec.schema.model_json_schema(),
            "catalog_path": catalog.path.relative_to(root).as_posix(),
        }
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(payload, json_output=json_output)


@python_app.command("remove")
def remove_python(
    kind: str,
    name: str,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path("."),
) -> None:
    """Remove one project-local Python component registration."""
    try:
        removed = ProjectRegistrationCatalog(_root(project)).remove_python(kind, name)
        if not removed:
            raise ResearchAssistantError(f"unknown registered {kind} component {name!r}")
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(f"removed {kind} {name}")


@config_app.command("register")
def register_config(
    path: Path,
    entrypoint: Annotated[Path | None, typer.Option("--entrypoint", "-e")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    argument: Annotated[list[str] | None, typer.Option("--argument", "-a")] = None,
    working_directory: Annotated[Path, typer.Option("--cwd")] = Path("."),
    description: Annotated[str, typer.Option("--description")] = "",
    project: Annotated[Path, typer.Option("--project", "-p")] = Path("."),
    replace: Annotated[bool, typer.Option("--replace")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a current config that executes an existing YAML through its old runner."""
    try:
        root = _root(project)
        wrapper = output or Path("configs") / "registered" / f"{name or path.stem}.yaml"
        resolved_entrypoint = entrypoint or suggest_legacy_entrypoint(root)
        if resolved_entrypoint is None:
            raise ResearchAssistantError(
                "no legacy YAML runner was found; pass --entrypoint, for example "
                "examples/train_from_yaml.py"
            )
        catalog = ProjectRegistrationCatalog(root)
        registration, _content = catalog.add_legacy_config(
            path=path,
            entrypoint=resolved_entrypoint,
            output=wrapper,
            name=name,
            arguments=argument or [],
            working_directory=working_directory,
            description=description,
            replace=replace,
        )
        payload = {
            "registration": registration.model_dump(mode="json"),
            "catalog_path": catalog.path.relative_to(root).as_posix(),
            "wrapper": registration.output,
            "command": f"ra run {registration.output}",
        }
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(payload, json_output=json_output)


@config_app.command("remove")
def remove_config(
    name: str,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path("."),
) -> None:
    """Remove a legacy config registration without deleting its source or wrapper."""
    try:
        removed = ProjectRegistrationCatalog(_root(project)).remove_legacy_config(name)
        if not removed:
            raise ResearchAssistantError(f"unknown registered legacy config {name!r}")
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(f"removed legacy config {name}")


@legacy_app.command("root")
def show_root(start: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Show the nearest project containing a registration catalog."""
    root = find_project_root(start)
    if root is None:
        _abort(ResearchAssistantError("no .research-assistant/registrations.yaml was found"))
    typer.echo(str(root))


def install(app) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    app.add_typer(legacy_app, name="legacy")
    _INSTALLED = True
