from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from research_assistant.assistant_core import AssistantEngine, AssistantPlan, AssistantRequest
from research_assistant.capabilities import capability_matrix
from research_assistant.cli import _abort
from research_assistant.durable_launches import DurableLaunchManager
from research_assistant.errors import ResearchAssistantError
from research_assistant.migrations import migrate_document, migration_catalog
from research_assistant.notebook_context import NotebookContextStore
from research_assistant.plugins import load_registry
from research_assistant.run_workspace import RunWorkspace
from research_assistant.ui.workspace import Workspace

workspace_v2_app = typer.Typer(
    help="Inspect and control the unified studies, runs, artifacts and analysis workspace."
)


def _echo(value: object, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        typer.echo(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())


def _run(action, *, json_output: bool = False) -> None:
    try:
        value = action()
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(value, json_output)


@workspace_v2_app.command("capabilities")
def capabilities(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _echo(capability_matrix(), json_output)


@workspace_v2_app.command("runs")
def runs(
    artifact_root: Annotated[str, typer.Option("--artifact-root")] = "runs",
    study: Annotated[list[str] | None, typer.Option("--study")] = None,
    state: Annotated[list[str] | None, typer.Option("--state")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=20000)] = 5000,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: RunWorkspace(workspace, artifact_root).catalog(
            study_ids=set(study or []) or None,
            states=set(state or []) or None,
            search=search,
            limit=limit,
        ),
        json_output=json_output,
    )


@workspace_v2_app.command("aggregate")
def aggregate(
    run_id: Annotated[list[str], typer.Option("--run")],
    artifact_root: Annotated[str, typer.Option("--artifact-root")] = "runs",
    metric: Annotated[str | None, typer.Option("--metric")] = None,
    stage: Annotated[str | None, typer.Option("--stage")] = None,
    group_by: Annotated[list[str] | None, typer.Option("--group-by")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: RunWorkspace(workspace, artifact_root).aggregate(
            run_id,
            metric=metric,
            stage=stage,
            group_by=group_by or ["study_id", "trial_id"],
        ),
        json_output=json_output,
    )


@workspace_v2_app.command("lineage")
def lineage(
    run_id: str,
    artifact_root: Annotated[str, typer.Option("--artifact-root")] = "runs",
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: RunWorkspace(workspace, artifact_root).lineage_for_run(run_id),
        json_output=json_output,
    )


@workspace_v2_app.command("context-create")
def context_create(
    run_id: Annotated[list[str] | None, typer.Option("--run")] = None,
    artifact_id: Annotated[list[str] | None, typer.Option("--artifact")] = None,
    artifact_root: Annotated[str, typer.Option("--artifact-root")] = "runs",
    label: Annotated[str | None, typer.Option("--label")] = None,
    notebook: Annotated[str | None, typer.Option("--notebook")] = None,
    kernel: Annotated[str, typer.Option("--kernel")] = "python3",
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: NotebookContextStore(workspace).create(
            run_ids=run_id or [],
            artifact_ids=artifact_id or [],
            artifact_root=artifact_root,
            label=label,
            notebook_path=notebook,
            kernel_name=kernel,
        ),
        json_output=json_output,
    )


@workspace_v2_app.command("contexts")
def contexts(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(lambda: {"contexts": NotebookContextStore(workspace).list()}, json_output=json_output)


@workspace_v2_app.command("plugins")
def plugins(
    module: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    def inspect() -> dict[str, object]:
        registry = load_registry(module or [])
        return {
            "diagnostics": list(getattr(registry, "plugin_diagnostics", [])),
            "migrations": migration_catalog(),
        }

    _run(inspect, json_output=json_output)


@workspace_v2_app.command("migrate")
def migrate(
    source: Path,
    write: Annotated[bool, typer.Option("--write")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    def action() -> dict[str, object]:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ResearchAssistantError("configuration root must be a mapping")
        migrated, report = migrate_document(document)
        if write and report.changed:
            source.write_text(
                yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        return {"document": migrated, "report": report.as_dict(), "written": write and report.changed}

    _run(action, json_output=json_output)


@workspace_v2_app.command("assistant-plan")
def assistant_plan(
    goal: str,
    run_id: Annotated[list[str] | None, typer.Option("--run")] = None,
    artifact_id: Annotated[list[str] | None, typer.Option("--artifact")] = None,
    artifact_root: Annotated[str, typer.Option("--artifact-root")] = "runs",
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    request = AssistantRequest(
        goal=goal,
        run_ids=run_id or [],
        artifact_ids=artifact_id or [],
        artifact_root=artifact_root,
    )
    _echo(
        AssistantEngine(str(workspace.resolve())).plan(request).model_dump(mode="json"),
        json_output,
    )


@workspace_v2_app.command("assistant-apply")
def assistant_apply(
    plan_path: Path,
    allow_writes: Annotated[bool, typer.Option("--allow-writes")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    def action() -> dict[str, object]:
        payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        plan = AssistantPlan.model_validate(payload)
        request = AssistantRequest(goal=plan.goal, allow_writes=allow_writes)
        return AssistantEngine(str(workspace.resolve())).apply(request, plan)

    _run(action, json_output=json_output)


@workspace_v2_app.command("launch-reconcile")
def launch_reconcile(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: DurableLaunchManager(Workspace(workspace)).reconcile(),
        json_output=json_output,
    )


@workspace_v2_app.command("launch-adopt")
def launch_adopt(
    launch_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: DurableLaunchManager(Workspace(workspace)).adopt(launch_id),
        json_output=json_output,
    )


@workspace_v2_app.command("launch-cancel")
def launch_cancel(
    launch_id: str,
    force: Annotated[bool, typer.Option("--force")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        lambda: DurableLaunchManager(Workspace(workspace)).cancel(launch_id, force=force),
        json_output=json_output,
    )


def install(app: typer.Typer) -> None:
    app.add_typer(workspace_v2_app, name="workspace-v2")
