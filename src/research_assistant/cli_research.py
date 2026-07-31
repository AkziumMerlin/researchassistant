from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml

from research_assistant.cli import _abort
from research_assistant.cli_pipeline import app, publication_app
from research_assistant.dataset_registry import (
    DatasetRegistry,
    DatasetRegistryError,
    load_dataset_spec,
)
from research_assistant.errors import ResearchAssistantError
from research_assistant.hpo import HpoController, load_hpo_spec
from research_assistant.publication_plus import (
    build_enhanced_publication_bundle,
    load_enhanced_publication_spec,
    preview_enhanced_publication,
)
from research_assistant.research_log import (
    DecisionInput,
    EvidenceInput,
    HypothesisInput,
    ResearchLog,
)
from research_assistant.selection import (
    evaluate_selection,
    list_selection_locks,
    load_selection_spec,
    lock_selection,
    preview_selection,
)
from research_assistant.statistics_suite import (
    load_statistical_spec,
    write_statistical_report,
)

hpo_app = typer.Typer(help="Run persistent adaptive validation-only hyperparameter searches.")
dataset_app = typer.Typer(help="Version, validate and materialize immutable dataset snapshots.")
selection_app = typer.Typer(help="Lock validation-only architecture and checkpoint selections.")
statistics_app = typer.Typer(help="Build paired statistical comparisons and robustness reports.")
research_app = typer.Typer(help="Track hypotheses, evidence, conclusions and research decisions.")
hypothesis_app = typer.Typer(help="Manage scientific hypotheses.")
decision_app = typer.Typer(help="Manage research decisions.")

app.add_typer(hpo_app, name="hpo")
app.add_typer(dataset_app, name="dataset")
app.add_typer(selection_app, name="selection")
app.add_typer(statistics_app, name="statistics")
app.add_typer(research_app, name="research")
research_app.add_typer(hypothesis_app, name="hypothesis")
research_app.add_typer(decision_app, name="decision")


def _echo(value: object, json_output: bool = False) -> None:
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        typer.echo(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())


def _hpo_controller(spec_path: Path, workspace: Path) -> HpoController:
    spec = load_hpo_spec(spec_path)
    return HpoController(workspace.resolve(), spec)


@hpo_app.command("status")
def hpo_status(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    refresh: Annotated[bool, typer.Option("--refresh/--no-refresh")] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        controller = _hpo_controller(spec_path, workspace)
        result = controller.refresh(prune=False) if refresh else controller.load()
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output)


@hpo_app.command("propose")
def hpo_propose(
    spec_path: Path,
    count: Annotated[int, typer.Option("--count", min=1, max=10000)] = 1,
    launch: Annotated[bool, typer.Option("--launch")] = False,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        controller = _hpo_controller(spec_path, workspace)
        proposals = controller.propose(count)
        result: object = proposals
        if launch:
            result = controller.launch([str(row["trial_id"]) for row in proposals])
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output)


@hpo_app.command("step")
def hpo_step(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Refresh observations, prune ASHA losers and fill available search slots."""
    try:
        result = _hpo_controller(spec_path, workspace).step()
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output)


@hpo_app.command("best")
def hpo_best(
    spec_path: Path,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000)] = 20,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        rows = _hpo_controller(spec_path, workspace).best()[:limit]
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(rows, json_output)


@dataset_app.command("register")
def dataset_register(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    registry = DatasetRegistry(workspace.resolve())
    try:
        result = registry.register(load_dataset_spec(spec_path))
    except ResearchAssistantError as exc:
        _abort(exc)
    finally:
        registry.close()
    _echo(result, json_output)


@dataset_app.command("list")
def dataset_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    name: Annotated[str | None, typer.Option("--name")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000)] = 1000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    registry = DatasetRegistry(workspace.resolve())
    try:
        result = registry.list(name=name, search=search, limit=limit)
    finally:
        registry.close()
    _echo(result, json_output)


@dataset_app.command("show")
def dataset_show(
    dataset_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = DatasetRegistry(workspace.resolve())
    try:
        result = registry.require(dataset_id)
    except DatasetRegistryError as exc:
        _abort(exc)
    finally:
        registry.close()
    _echo(result)


@dataset_app.command("validate")
def dataset_validate(
    dataset_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    snapshot: Annotated[bool, typer.Option("--snapshot")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    registry = DatasetRegistry(workspace.resolve())
    try:
        result = registry.validate(dataset_id, against_source=not snapshot)
    finally:
        registry.close()
    _echo(result, json_output)


@dataset_app.command("materialize")
def dataset_materialize(
    dataset_id: str,
    destination: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    registry = DatasetRegistry(workspace.resolve())
    try:
        path = registry.materialize(dataset_id, destination, overwrite=overwrite)
    except DatasetRegistryError as exc:
        _abort(exc)
    finally:
        registry.close()
    typer.echo(str(path))


@dataset_app.command("lineage")
def dataset_lineage(
    dataset_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    registry = DatasetRegistry(workspace.resolve())
    try:
        result = registry.lineage(dataset_id)
    finally:
        registry.close()
    _echo(result)


@selection_app.command("preview")
def selection_preview(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        result = preview_selection(workspace.resolve(), load_selection_spec(spec_path))
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output)


@selection_app.command("lock")
def selection_lock(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        result = lock_selection(
            workspace.resolve(), load_selection_spec(spec_path), overwrite=overwrite
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output)


@selection_app.command("evaluate")
def selection_evaluate(
    name_or_path: str,
    output: Annotated[Path, typer.Option("--output")] = Path("reports/selection"),
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        result = evaluate_selection(workspace.resolve(), name_or_path, output=output)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result, json_output)


@selection_app.command("list")
def selection_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    _echo(list_selection_locks(workspace.resolve()))


@statistics_app.command("run")
def statistics_run(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    try:
        spec = load_statistical_spec(spec_path)
        destination = output or Path("reports") / spec.name
        result = write_statistical_report(workspace.resolve(), spec, destination)
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(str(result))


@hypothesis_app.command("create")
def hypothesis_create(
    title: Annotated[str, typer.Option("--title")],
    statement: Annotated[str, typer.Option("--statement")],
    expected: Annotated[str | None, typer.Option("--expected")] = None,
    criteria: Annotated[str | None, typer.Option("--criteria")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag")] = None,
    status: Annotated[
        Literal["draft", "active", "supported", "refuted", "inconclusive", "archived"],
        typer.Option("--status"),
    ] = "draft",
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.create_hypothesis(
            HypothesisInput(
                title=title,
                statement=statement,
                expected_outcome=expected,
                decision_criteria=criteria,
                tags=tag or [],
                status=status,
            )
        )
    finally:
        log.close()
    _echo(result)


@hypothesis_app.command("list")
def hypothesis_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    status: Annotated[
        Literal["draft", "active", "supported", "refuted", "inconclusive", "archived"] | None,
        typer.Option("--status"),
    ] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.list_hypotheses(status=status, search=search)
    finally:
        log.close()
    _echo(result)


@hypothesis_app.command("show")
def hypothesis_show(
    hypothesis_id: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.require_hypothesis(hypothesis_id)
    finally:
        log.close()
    _echo(result)


@hypothesis_app.command("conclude")
def hypothesis_conclude(
    hypothesis_id: str,
    status: Literal["supported", "refuted", "inconclusive", "archived"],
    conclusion: Annotated[str, typer.Option("--conclusion")],
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.update_hypothesis(
            hypothesis_id, status=status, conclusion=conclusion
        )
    finally:
        log.close()
    _echo(result)


@hypothesis_app.command("evidence")
def hypothesis_evidence(
    hypothesis_id: str,
    kind: Literal["run", "report", "selection", "publication", "dataset", "note"],
    reference: str,
    supports: Annotated[
        Literal["support", "contradict", "neutral"], typer.Option("--supports")
    ] = "neutral",
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.add_evidence(
            EvidenceInput(
                hypothesis_id=hypothesis_id,
                kind=kind,
                reference=reference,
                supports=supports,
                summary=summary,
            )
        )
    finally:
        log.close()
    _echo(result)


@decision_app.command("record")
def decision_record(
    title: Annotated[str, typer.Option("--title")],
    choice: Annotated[str, typer.Option("--choice")],
    rationale: Annotated[str, typer.Option("--rationale")],
    alternative: Annotated[list[str] | None, typer.Option("--alternative")] = None,
    next_action: Annotated[str | None, typer.Option("--next-action")] = None,
    hypothesis_id: Annotated[str | None, typer.Option("--hypothesis")] = None,
    reference: Annotated[list[str] | None, typer.Option("--reference")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.record_decision(
            DecisionInput(
                title=title,
                choice=choice,
                rationale=rationale,
                alternatives=alternative or [],
                next_action=next_action,
                hypothesis_id=hypothesis_id,
                references=reference or [],
            )
        )
    finally:
        log.close()
    _echo(result)


@decision_app.command("list")
def decision_list(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    log = ResearchLog(workspace.resolve())
    try:
        result = log.list_decisions()
    finally:
        log.close()
    _echo(result)


@research_app.command("export")
def research_export(
    output: Annotated[Path, typer.Option("--output")] = Path("reports/research-log.json"),
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    workspace_path = workspace.resolve()
    target = output.resolve() if output.is_absolute() else (workspace_path / output).resolve()
    if not target.is_relative_to(workspace_path):
        _abort(ResearchAssistantError("research export path escapes workspace"))
    log = ResearchLog(workspace_path)
    try:
        payload = log.export()
    finally:
        log.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    typer.echo(str(target))


@publication_app.command("preview-full")
def publication_preview_full(
    spec_path: Path,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    try:
        spec = load_enhanced_publication_spec(spec_path)
        result = preview_enhanced_publication(workspace.resolve(), spec)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(result)


@publication_app.command("build-full")
def publication_build_full(
    spec_path: Path,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    try:
        spec = load_enhanced_publication_spec(spec_path)
        destination = output or Path("publications") / spec.name
        result = build_enhanced_publication_bundle(
            workspace.resolve(), spec, destination
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    typer.echo(str(result))


if importlib.util.find_spec("fastapi") is not None:
    from research_assistant.research_ui import install as install_research_ui

    install_research_ui()
