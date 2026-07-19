from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml

from research_assistant import __version__
from research_assistant.config import dump_config, load_config
from research_assistant.errors import ResearchAssistantError
from research_assistant.execution import execute_run
from research_assistant.launching import (
    LocalSubprocessLauncher,
    capture_worker_resources,
    load_launcher_reference,
)
from research_assistant.planning import RunManifest, compile_plan
from research_assistant.plugins import load_registry
from research_assistant.reporting import collect_resource_summary, collect_summary

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
