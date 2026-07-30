from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from research_assistant import __version__
from research_assistant.analytics import ChartSpec, MetricIndex, TableSpec
from research_assistant.config import dump_config, load_config
from research_assistant.config_creator import (
    ConfigCreator,
    TerminalPrompt,
    parse_selection,
)
from research_assistant.errors import ResearchAssistantError
from research_assistant.execution import execute_run
from research_assistant.launching import (
    LocalSubprocessLauncher,
    capture_worker_resources,
    load_launcher_reference,
)
from research_assistant.planning import RunManifest, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.reporting import (
    collect_resource_summary,
    collect_summary,
    write_chart_bundle,
    write_table_bundle,
)

app = typer.Typer(
    name="ra",
    help="Local-first, plugin-driven experiment orchestration.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
config_app = typer.Typer(help="Validate and render experiment configurations.")
component_app = typer.Typer(help="Inspect registered components.")
report_app = typer.Typer(help="Aggregate structured run results.")
app.add_typer(config_app, name="config")
app.add_typer(component_app, name="component")
app.add_typer(report_app, name="report")


def _abort(exc: Exception) -> None:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc


def _load(path: Path, overrides: list[str]):
    config = load_config(path, overrides)
    registry = load_registry(config.plugins)
    plan = compile_plan(config, registry)
    return config, registry, plan


@app.command()
def version() -> None:
    """Print the installed ResearchAssistant version."""
    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Show basic runtime diagnostics."""
    payload = {
        "research_assistant": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }
    typer.echo(yaml.safe_dump(payload, sort_keys=False).rstrip())


@app.command()
def ui(
    path: Annotated[Path, typer.Argument()] = Path("."),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
    ssh: Annotated[
        bool,
        typer.Option(
            "--ssh",
            help="Print an SSH forwarding command and do not open a browser on the server.",
        ),
    ] = False,
    ssh_target: Annotated[
        str | None,
        typer.Option("--ssh-target", help="USER@HOST used in the printed tunnel command."),
    ] = None,
) -> None:
    """Open the local browser workbench for a ResearchAssistant project."""
    try:
        from research_assistant.ui.server import run_ui

        ssh_mode = ssh or bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"))
        run_ui(
            path,
            plugins=plugin or [],
            host=host,
            port=port,
            open_browser=open_browser,
            ssh_mode=ssh_mode,
            ssh_target=ssh_target,
        )
    except ResearchAssistantError as exc:
        _abort(exc)


@config_app.command("validate")
def validate_config(
    path: Path,
    set_: Annotated[list[str] | None, typer.Option("--set", help="KEY=VALUE override.")] = None,
) -> None:
    """Validate a config, its plugins, matrix, and stage graph."""
    try:
        config, _, plan = _load(path, set_ or [])
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(f"valid: {config.experiment.name} ({len(plan.runs)} run(s))")


@config_app.command("render")
def render_config(
    path: Path,
    set_: Annotated[list[str] | None, typer.Option("--set", help="KEY=VALUE override.")] = None,
) -> None:
    """Print a composed and validated config."""
    try:
        config = load_config(path, set_ or [])
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(dump_config(config), nl=False)


@config_app.command("create")
def create_config(
    path: Path,
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    component: Annotated[
        list[str] | None,
        typer.Option("--component", help="Preselect KIND=REGISTERED_TYPE."),
    ] = None,
    stage: Annotated[
        list[str] | None,
        typer.Option("--stage", help="Preselect NAME=REGISTERED_TYPE."),
    ] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Interactively build a validated experiment config from registered components."""
    if path.exists() and not overwrite:
        _abort(ResearchAssistantError(f"refusing to overwrite existing file: {path}"))
    plugins = plugin or []
    try:
        registry = load_registry(plugins)
        creator = ConfigCreator(registry=registry, prompt=TerminalPrompt(), plugins=plugins)
        config = creator.build(
            default_name=name or path.stem.replace("_", "-").replace(" ", "-"),
            selected_components=parse_selection(component or [], option="--component"),
            selected_stages=parse_selection(stage or [], option="--stage"),
        )
        compiled = compile_plan(config, registry)
    except ResearchAssistantError as exc:
        _abort(exc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_config(config, compact=True), encoding="utf-8")
    typer.echo(f"created {path} ({len(compiled.runs)} run(s), trial={compiled.runs[0].trial_id})")


@component_app.command("list")
def list_components(
    kind: str | None = typer.Argument(default=None),
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
) -> None:
    """List built-in, installed, and explicitly loaded components."""
    try:
        registry = load_registry(plugin or [])
    except ResearchAssistantError as exc:
        _abort(exc)
    for spec in registry.list(kind):
        typer.echo(f"{spec.kind:12} {spec.name:28} {spec.description}")


@component_app.command("describe")
def describe_component(
    kind: str,
    name: str,
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
) -> None:
    """Print the JSON schema of a component configuration."""
    try:
        registry = load_registry(plugin or [])
        spec = registry.get(kind, name)
        payload = {
            "kind": spec.kind,
            "name": spec.name,
            "description": spec.description,
            "provider": spec.provider,
            "schema": registry.schema(kind, name),
        }
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def plan(
    path: Path,
    set_: Annotated[list[str] | None, typer.Option("--set", help="KEY=VALUE override.")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compile a config into immutable run manifests without executing it."""
    try:
        _, _, compiled = _load(path, set_ or [])
    except ResearchAssistantError as exc:
        _abort(exc)

    if json_output:
        typer.echo(
            json.dumps(
                [run.model_dump(mode="json") for run in compiled.runs],
                indent=2,
                sort_keys=True,
            )
        )
        return

    typer.echo(f"study={compiled.study_id} runs={len(compiled.runs)}")
    for run in compiled.runs:
        assignments = ", ".join(f"{key}={value}" for key, value in run.assignments.items())
        typer.echo(f"  {run.run_id} trial={run.trial_id} {assignments}".rstrip())


@app.command()
def run(
    path: Path,
    set_: Annotated[list[str] | None, typer.Option("--set", help="KEY=VALUE override.")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
    fail_fast: Annotated[bool, typer.Option("--fail-fast/--keep-going")] = True,
) -> None:
    """Execute all runs in a compiled plan locally and sequentially."""
    try:
        _, registry, compiled = _load(path, set_ or [])
    except ResearchAssistantError as exc:
        _abort(exc)

    failures = 0
    for index, manifest in enumerate(compiled.runs, start=1):
        typer.echo(f"[{index}/{len(compiled.runs)}] run {manifest.run_id}")
        try:
            execute_run(manifest, registry, artifact_root=output, resume=resume)
        except Exception as exc:
            failures += 1
            typer.secho(f"run {manifest.run_id} failed: {exc}", fg=typer.colors.RED, err=True)
            if fail_fast:
                raise typer.Exit(code=1) from exc
    if failures:
        raise typer.Exit(code=1)


@app.command()
def launch(
    path: Path,
    launcher: Annotated[Path | None, typer.Option("--launcher")] = None,
    set_: Annotated[list[str] | None, typer.Option("--set", help="Experiment KEY=VALUE.")] = None,
    launcher_set: Annotated[
        list[str] | None, typer.Option("--launcher-set", help="Launcher KEY=VALUE.")
    ] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    """Schedule plan runs as isolated local CPU/GPU subprocesses."""
    try:
        _, registry, compiled = _load(path, set_ or [])
        reference = load_launcher_reference(launcher, launcher_set or [])
        configured = registry.invoke("launcher", reference, None)
        if not isinstance(configured, LocalSubprocessLauncher):
            raise ResearchAssistantError("launcher does not implement the local launcher contract")
        results = configured.launch(
            compiled,
            artifact_root=output,
            resume=resume,
            on_event=typer.echo,
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    if any(exit_code != 0 for exit_code in results.values()):
        raise typer.Exit(code=1)


@app.command("_worker", hidden=True)
def worker(
    manifest_path: Path,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    """Execute one immutable run manifest inside a launcher subprocess."""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = RunManifest.model_validate(payload)
        registry = load_registry(manifest.config.plugins)
        artifact_root = manifest_path.resolve().parents[2]
        try:
            execute_run(manifest, registry, artifact_root=artifact_root, resume=resume)
        finally:
            capture_worker_resources(manifest_path.parent)
    except (OSError, ValueError, ResearchAssistantError) as exc:
        _abort(ResearchAssistantError(str(exc)))


@app.command()
def status(root: Annotated[Path, typer.Argument()] = Path("runs")) -> None:
    """List run statuses under an artifact root."""
    paths = sorted(root.glob("*/*/status.json"))
    if not paths:
        typer.echo(f"no runs found under {root}")
        return
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        typer.echo(f"{payload['run_id']:12} {payload['state']:10} {path.parent}")


@report_app.command("summary")
def report_summary(
    root: Annotated[Path, typer.Argument()] = Path("runs"),
    stage: Annotated[str | None, typer.Option("--stage")] = None,
    metric: Annotated[str | None, typer.Option("--metric")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Aggregate final metrics by trial across seeds."""
    rows = collect_summary(root, stage=stage, metric=metric)
    if json_output:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        typer.echo(f"no matching completed metrics found under {root}")
        return
    typer.echo("study trial      stage        metric                         n mean ± std")
    for row in rows:
        typer.echo(
            f"{row['study_id']:<5} {row['trial_id']:<10} {row['stage']:<12} "
            f"{row['metric']:<30} {row['n']:>2} "
            f"{row['mean']:.6g} ± {row['std']:.3g}"
        )


@report_app.command("resources")
def report_resources(
    root: Annotated[Path, typer.Argument()] = Path("runs"),
    trial: Annotated[list[str] | None, typer.Option("--trial")] = None,
    config_path: Annotated[Path | None, typer.Option("--config")] = None,
    set_: Annotated[list[str] | None, typer.Option("--set", help="Config KEY=VALUE.")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show historical compute and GPU-memory use for exact trial configurations."""
    trial_ids = set(trial or [])
    if config_path is not None:
        try:
            _, _, compiled = _load(config_path, set_ or [])
        except ResearchAssistantError as exc:
            _abort(exc)
        trial_ids.update(run.trial_id for run in compiled.runs)
    rows = collect_resource_summary(root, trial_ids=trial_ids or None)
    if json_output:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        typer.echo(f"no matching completed resource profiles found under {root}")
        return
    typer.echo("study trial      n wall mean  GPU-h/run  peak memory  attempts")
    for row in rows:
        typer.echo(
            f"{row['study_id']:<5} {row['trial_id']:<10} {row['n']:>2} "
            f"{row['wall_seconds_mean']:>8.1f}s {row['gpu_hours_mean']:>10.4f} "
            f"{row['placement_memory_peak_mb_max']:>9.0f}MiB {row['attempts_total']:>9}"
        )


@report_app.command("index")
def report_index(
    root: Annotated[Path, typer.Argument()] = Path("runs"),
    rebuild: Annotated[bool, typer.Option("--rebuild")] = False,
) -> None:
    """Incrementally index run metadata and metric-event tails."""
    index = MetricIndex(root)
    try:
        result = index.rebuild() if rebuild else index.refresh()
        result.update(index.catalog())
    finally:
        index.close()
    typer.echo(yaml.safe_dump(result, sort_keys=False).rstrip())


def _load_report_spec(path: Path, model):
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return model.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ResearchAssistantError(f"invalid report spec {path}: {exc}") from exc


@report_app.command("chart")
def report_chart(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    format_: Annotated[list[str] | None, typer.Option("--format")] = None,
) -> None:
    """Render a saved chart query to a reproducible report bundle."""
    try:
        spec = _load_report_spec(spec_path, ChartSpec)
        index = MetricIndex(spec.artifact_root)
        try:
            index.refresh()
            destination = output or Path("reports") / spec.name
            write_chart_bundle(index, spec, destination, formats=tuple(format_ or ["svg", "pdf"]))
        finally:
            index.close()
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(str(destination))


@report_app.command("table")
def report_table(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Render a saved aggregate query to CSV and a LaTeX table."""
    try:
        spec = _load_report_spec(spec_path, TableSpec)
        index = MetricIndex(spec.artifact_root)
        try:
            index.refresh()
            destination = output or Path("reports") / spec.name
            write_table_bundle(index, spec, destination)
        finally:
            index.close()
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(str(destination))


@app.command()
def init(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Create a minimal plugin project without overwriting existing files."""
    files = {
        path / "configs" / "smoke.yaml": _SMOKE_CONFIG,
        path / "ra_project" / "__init__.py": "",
        path / "ra_project" / "plugin.py": _PLUGIN_TEMPLATE,
    }
    conflicts = [str(file) for file in files if file.exists()]
    if conflicts:
        _abort(ResearchAssistantError(f"refusing to overwrite: {', '.join(conflicts)}"))
    for file, content in files.items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    typer.echo(f"initialized ResearchAssistant project in {path.resolve()}")


_SMOKE_CONFIG = """version: 1
experiment:
  name: smoke
plugins: [ra_project.plugin]
seed: 0
components:
  value:
    type: example/constant
    params:
      value: 1.0
matrix:
  seed: [0, 1, 2]
stages:
  - name: fit
    type: example/measure
  - name: test
    type: core/noop
    needs: [fit]
    params:
      metrics:
        test/example: 1.0
"""


_PLUGIN_TEMPLATE = """from typing import Any

from pydantic import BaseModel, ConfigDict

from research_assistant.execution import StageContext, StageResult
from research_assistant.registry import Registry


class ConstantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float


def build_constant(config: ConstantConfig, _context: Any) -> float:
    return config.value


class MeasureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def measure(_config: MeasureConfig, context: StageContext) -> StageResult:
    value = context.component("value")
    return StageResult(metrics={"train/example": value + float(context.seed or 0)})


def register(registry: Registry) -> None:
    registry.add(
        "value",
        "example/constant",
        factory=build_constant,
        schema=ConstantConfig,
        description="Example project component.",
        provider=__name__,
    )
    registry.add(
        "stage",
        "example/measure",
        factory=measure,
        schema=MeasureConfig,
        description="Example stage using a configured component.",
        provider=__name__,
    )
"""
