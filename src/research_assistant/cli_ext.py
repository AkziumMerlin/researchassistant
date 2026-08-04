from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml

from research_assistant.advanced_analytics import (
    AdvancedChartSpec,
    write_advanced_chart_bundle,
)
from research_assistant.analytics import EvaluationSpec, MetricIndex
from research_assistant.cli import _abort, _load_report_spec, app, report_app
from research_assistant.errors import ResearchAssistantError
from research_assistant.jobs import JobService, JobStartRequest
from research_assistant.reporting import write_evaluation_bundle

job_app = typer.Typer(help="Manage persistent detached experiment jobs shared with the browser UI.")
app.add_typer(job_app, name="job")


def _service(workspace: Path, plugins: list[str] | None = None) -> JobService:
    return JobService(workspace, plugins or [])


def _echo_record(record: dict, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(record, indent=2, sort_keys=True))
    else:
        typer.echo(yaml.safe_dump(record, sort_keys=False).rstrip())


@job_app.command("start")
def job_start(
    config: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    launcher: Annotated[Path | None, typer.Option("--launcher")] = None,
    artifact_root: Annotated[str | None, typer.Option("--output", "--artifact-root")] = None,
    set_: Annotated[list[str] | None, typer.Option("--set", help="Experiment KEY=VALUE.")] = None,
    launcher_set: Annotated[
        list[str] | None,
        typer.Option("--launcher-set", help="Launcher KEY=VALUE."),
    ] = None,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
    preview: Annotated[bool, typer.Option("--preview")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate and start a detached scheduler that survives terminal and SSH disconnects."""
    try:
        root = workspace.resolve()
        request = JobStartRequest(
            config_path=config.resolve().relative_to(root).as_posix(),
            launcher_path=(launcher.resolve().relative_to(root).as_posix() if launcher else None),
            artifact_root=artifact_root,
            resume=resume,
            overrides=set_ or [],
            launcher_overrides=launcher_set or [],
        )
        service = _service(root, plugin)
        result = service.preview(request) if preview else service.start(request)
    except (ValueError, OSError, ResearchAssistantError) as exc:
        _abort(ResearchAssistantError(str(exc)))
    _echo_record(result, json_output=json_output)


@job_app.command("list")
def job_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List persistent jobs, including orphaned schedulers."""
    try:
        rows = _service(workspace, plugin).list()
    except ResearchAssistantError as exc:
        _abort(exc)
    if json_output:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        typer.echo("no jobs found")
        return
    typer.echo("job                              state       runs config")
    for row in rows:
        plan = row.get("plan") or {}
        typer.echo(
            f"{str(row.get('job_id', '')):<32} {str(row.get('state', 'unknown')):<11} "
            f"{int(plan.get('runs', 0)):>4} {row.get('config_path') or '—'}"
        )


@job_app.command("show")
def job_show(
    job_id: str,
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show scheduler, run, GPU, and stage state for one job."""
    try:
        record = _service(workspace, plugin).detail(job_id, run_id)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo_record(record, json_output=json_output)


@job_app.command("cancel")
def job_cancel(
    job_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    grace_seconds: Annotated[float, typer.Option("--grace", min=0.0, max=60.0)] = 2.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Terminate only the scheduler and workers recorded for this ResearchAssistant job."""
    try:
        record = _service(workspace, plugin).cancel(job_id, grace_seconds=grace_seconds)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo_record(record, json_output=json_output)


@job_app.command("recover")
def job_recover(
    job_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Restart an orphaned, failed, or cancelled scheduler from its immutable request."""
    try:
        record = _service(workspace, plugin).recover(job_id)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo_record(record, json_output=json_output)


@job_app.command("log")
def job_log(
    job_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    source: Annotated[Literal["scheduler", "worker"], typer.Option("--source")] = "scheduler",
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    cursor: Annotated[int | None, typer.Option("--cursor", min=0)] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=262144)] = 65536,
    tail: Annotated[bool, typer.Option("--tail")] = True,
    follow: Annotated[bool, typer.Option("--follow")] = False,
    poll_seconds: Annotated[float, typer.Option("--poll", min=0.1, max=60.0)] = 1.0,
) -> None:
    """Read scheduler or worker logs by byte cursor; optionally follow until the job stops."""
    service = _service(workspace, plugin)
    current = cursor
    first = True
    try:
        while True:
            page = service.log_page(
                job_id,
                source=source,
                run_id=run_id,
                cursor=current,
                limit=limit,
                tail=tail and first and current is None,
            )
            first = False
            if page["text"]:
                typer.echo(page["text"], nl=False)
                sys.stdout.flush()
            current = int(page["next_cursor"])
            if not follow:
                break
            state = str(service.detail(job_id).get("state", "unknown"))
            if page["eof"] and state in {"completed", "failed", "cancelled"}:
                break
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None
    except ResearchAssistantError as exc:
        _abort(exc)


@job_app.command("metrics")
def job_metrics(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run")],
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    since_sequence: Annotated[int, typer.Option("--since", min=0)] = 0,
    limit: Annotated[int, typer.Option("--limit", min=1, max=5000)] = 500,
) -> None:
    """Print live structured metric events for one run."""
    try:
        result = _service(workspace, plugin).metrics(
            job_id,
            run_id,
            since_sequence=since_sequence,
            limit=limit,
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@job_app.command("artifacts")
def job_artifacts(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run")],
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=5000)] = 1000,
) -> None:
    """List run artifacts with preview and semantic classifications."""
    try:
        result = _service(workspace, plugin).artifacts(job_id, run_id, limit=limit)
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@report_app.command("evaluate")
def report_evaluate(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Select checkpoints by validation metric and aggregate a separate target metric."""
    try:
        spec = _load_report_spec(spec_path, EvaluationSpec)
        index = MetricIndex(spec.artifact_root)
        try:
            index.refresh()
            evaluation = index.evaluate(spec)
            if output is not None:
                write_evaluation_bundle(index, spec, output)
        finally:
            index.close()
    except ResearchAssistantError as exc:
        _abort(exc)
    if json_output or output is None:
        typer.echo(json.dumps(evaluation, indent=2, sort_keys=True))
    if output is not None:
        typer.echo(str(output))


@report_app.command("advanced-chart")
def report_advanced_chart(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    formats: Annotated[
        list[str] | None,
        typer.Option("--format", help="Repeat svg, pdf, or png; use none for data only."),
    ] = None,
) -> None:
    """Export scatter, histogram, heatmap, or composite chart bundles."""
    try:
        spec = _load_report_spec(spec_path, AdvancedChartSpec)
        index = MetricIndex(spec.artifact_root)
        try:
            index.refresh()
            destination = output or Path("reports") / spec.name
            requested = tuple(formats or ["svg", "pdf", "png"])
            if requested == ("none",):
                requested = ()
            write_advanced_chart_bundle(
                index,
                spec,
                destination,
                formats=requested,
            )
        finally:
            index.close()
    except (OSError, ResearchAssistantError) as exc:
        _abort(ResearchAssistantError(str(exc)))
    typer.echo(str(destination))

