from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml

from research_assistant.asset_registry import AssetRegistry, AssetRegistryError
from research_assistant.cli import _abort
from research_assistant.cli_ext import app, job_app
from research_assistant.diagnostics import (
    DiagnosticPolicy,
    diagnostic_catalog,
    load_diagnostic_policy,
)
from research_assistant.errors import ResearchAssistantError
from research_assistant.jobs import JobService
from research_assistant.pipeline_integration import install as install_pipeline
from research_assistant.publication import (
    build_publication_bundle,
    load_publication_spec,
    preview_publication,
)
from research_assistant.stage_cache import StageCache

install_pipeline()

cache_app = typer.Typer(help="Inspect and prune the content-addressed stage cache.")
asset_app = typer.Typer(help="Manage the artifact and checkpoint registry.")
diagnostic_app = typer.Typer(help="Inspect diagnostics and configure automatic interventions.")
publication_app = typer.Typer(help="Build reproducible publication bundles.")
app.add_typer(cache_app, name="cache")
app.add_typer(asset_app, name="asset")
app.add_typer(diagnostic_app, name="diagnostics")
app.add_typer(publication_app, name="publication")


def _asset_registry(workspace: Path) -> AssetRegistry:
    return AssetRegistry(workspace.resolve())


@job_app.command("adopt")
def job_adopt(
    job_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Attach a replacement scheduler to living workers of an orphaned job."""
    try:
        service = JobService(workspace, plugin or [])
        result = service.adopt(job_id)  # type: ignore[attr-defined]
    except ResearchAssistantError as exc:
        _abort(exc)
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        typer.echo(yaml.safe_dump(result, sort_keys=False).rstrip())


@cache_app.command("stats")
def cache_stats(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Show cache mode, entry count and content-addressed storage size."""
    try:
        from research_assistant.plugins import load_registry

        cache = StageCache(workspace.resolve(), load_registry())
        typer.echo(yaml.safe_dump(cache.stats(), sort_keys=False).rstrip())
    except ResearchAssistantError as exc:
        _abort(exc)


@cache_app.command("prune")
def cache_prune(
    keep_entries: Annotated[int, typer.Option("--keep", min=0)] = 10000,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Remove old entries and unreferenced cache objects."""
    from research_assistant.plugins import load_registry

    cache = StageCache(workspace.resolve(), load_registry())
    typer.echo(yaml.safe_dump(cache.prune(keep_entries=keep_entries), sort_keys=False).rstrip())


@asset_app.command("refresh")
def asset_refresh(
    artifact_root: Annotated[Path, typer.Argument()] = Path("runs"),
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Index named artifacts and checkpoints and ingest their immutable objects."""
    registry = _asset_registry(workspace)
    try:
        result = registry.refresh(artifact_root)
    except ResearchAssistantError as exc:
        _abort(exc)
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(result, sort_keys=False).rstrip())


@asset_app.command("list")
def asset_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    kind: Annotated[Literal["artifact", "checkpoint"] | None, typer.Option("--kind")] = None,
    status: Annotated[
        Literal["candidate", "selected", "released", "archived"] | None,
        typer.Option("--status"),
    ] = None,
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000)] = 1000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List registry assets without traversing run directories in the client."""
    registry = _asset_registry(workspace)
    try:
        rows = registry.list(kind=kind, status=status, run_id=run_id, search=search, limit=limit)
    finally:
        registry.close()
    if json_output:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        typer.echo("no matching assets")
        return
    typer.echo("asset                            kind       status    pin run          name")
    for row in rows:
        typer.echo(
            f"{row['asset_id']:<32} {row['kind']:<10} {row['status']:<9} "
            f"{'yes' if row['pinned'] else 'no ':<3} {str(row.get('run_id') or '—')[:12]:<12} "
            f"{row['name']}"
        )


@asset_app.command("show")
def asset_show(
    asset_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        row = registry.get(asset_id)
    except AssetRegistryError as exc:
        _abort(exc)
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(row, sort_keys=False).rstrip())


@asset_app.command("promote")
def asset_promote(
    asset_id: str,
    status: Literal["candidate", "selected", "released", "archived"],
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        row = registry.promote(asset_id, status)
    except AssetRegistryError as exc:
        _abort(exc)
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(row, sort_keys=False).rstrip())


@asset_app.command("pin")
def asset_pin(
    asset_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        row = registry.pin(asset_id, True)
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(row, sort_keys=False).rstrip())


@asset_app.command("unpin")
def asset_unpin(
    asset_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        row = registry.pin(asset_id, False)
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(row, sort_keys=False).rstrip())


@asset_app.command("materialize")
def asset_materialize(
    asset_id: str,
    destination: Path,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        path = registry.materialize(asset_id, destination, overwrite=overwrite)
    finally:
        registry.close()
    typer.echo(str(path))


@asset_app.command("delete")
def asset_delete(
    asset_id: str,
    delete_source: Annotated[bool, typer.Option("--delete-source")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        registry.delete(asset_id, delete_source=delete_source)
    except AssetRegistryError as exc:
        _abort(exc)
    finally:
        registry.close()


@asset_app.command("retention")
def asset_retention(
    keep: Annotated[int, typer.Option("--keep-candidates-per-trial", min=0)] = 3,
    delete_sources: Annotated[bool, typer.Option("--delete-sources")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        result = registry.enforce_retention(
            keep_candidates_per_trial=keep,
            delete_sources=delete_sources,
        )
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(result, sort_keys=False).rstrip())


@asset_app.command("gc")
def asset_gc(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = _asset_registry(workspace)
    try:
        result = registry.gc()
    finally:
        registry.close()
    typer.echo(yaml.safe_dump(result, sort_keys=False).rstrip())


@diagnostic_app.command("show")
def diagnostics_show(
    artifact_root: Annotated[Path, typer.Argument()] = Path("runs"),
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000)] = 1000,
) -> None:
    root = (workspace.resolve() / artifact_root).resolve()
    typer.echo(yaml.safe_dump(diagnostic_catalog(root, limit=limit), sort_keys=False).rstrip())


@diagnostic_app.command("policy")
def diagnostics_policy(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    typer.echo(
        yaml.safe_dump(
            load_diagnostic_policy(workspace.resolve()).model_dump(mode="json"),
            sort_keys=False,
        ).rstrip()
    )


@diagnostic_app.command("init")
def diagnostics_init(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    path = workspace.resolve() / ".ra" / "diagnostics.yaml"
    if path.exists() and not overwrite:
        _abort(ResearchAssistantError(f"diagnostic policy already exists: {path}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(DiagnosticPolicy().model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    typer.echo(str(path))


@publication_app.command("preview")
def publication_preview(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    try:
        spec = load_publication_spec(spec_path)
        result = preview_publication(workspace.resolve(), spec)
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(yaml.safe_dump(result, sort_keys=False).rstrip())


@publication_app.command("build")
def publication_build(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    try:
        spec = load_publication_spec(spec_path)
        destination = output or Path("publications") / spec.name
        path = build_publication_bundle(workspace.resolve(), spec, destination)
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(str(path))


if importlib.util.find_spec("fastapi") is not None:
    from research_assistant.pipeline_ui import install as install_pipeline_ui

    install_pipeline_ui()
