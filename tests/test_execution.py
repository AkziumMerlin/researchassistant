import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from research_assistant.builtin import register as register_builtin
from research_assistant.config import parse_config
from research_assistant.execution import StageContext, StageResult, execute_run
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry
from research_assistant.registry import Registry
from research_assistant.reporting import collect_summary


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def publish_checkpoint(_params: EmptyParams, context: StageContext) -> StageResult:
    checkpoint = context.run_dir / "checkpoints" / "best.txt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text("7", encoding="utf-8")
    context.log_metrics({"val/loss": 1.0}, step=0)
    context.log_metrics({"val/loss": 0.5}, step=1)
    return StageResult(metrics={"val/loss": 0.5}, artifacts={"best": "checkpoints/best.txt"})


def consume_checkpoint(_params: EmptyParams, context: StageContext) -> StageResult:
    checkpoint_value = float(context.artifact("fit", "best").read_text(encoding="utf-8"))
    configured_value = float(context.component("value"))
    return StageResult(metrics={"test/result": checkpoint_value + configured_value})


def interrupt(_params: EmptyParams, _context: StageContext) -> None:
    raise KeyboardInterrupt


def extended_registry() -> Registry:
    registry = Registry()
    register_builtin(registry)
    registry.add(
        "stage",
        "test/publish",
        factory=publish_checkpoint,
        schema=EmptyParams,
        provider="tests",
    )
    registry.add(
        "stage",
        "test/consume",
        factory=consume_checkpoint,
        schema=EmptyParams,
        provider="tests",
    )
    registry.add(
        "stage",
        "test/interrupt",
        factory=interrupt,
        schema=EmptyParams,
        provider="tests",
    )
    return registry


def test_execute_and_resume(tmp_path: Path) -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "execute"},
            "seed": 0,
            "matrix": {"seed": [0, 1]},
            "stages": [
                {
                    "name": "fit",
                    "type": "core/noop",
                    "params": {"metrics": {"val/loss": 0.5}},
                },
                {"name": "test", "type": "core/noop", "needs": ["fit"]},
            ],
        }
    )
    registry = load_registry()
    plan = compile_plan(config, registry)

    for manifest in plan.runs:
        first = execute_run(manifest, registry, artifact_root=tmp_path)
        second = execute_run(manifest, registry, artifact_root=tmp_path)
        assert first["state"] == "completed"
        assert second["state"] == "completed"

        run_dir = tmp_path / "execute" / manifest.run_id
        metrics = [
            json.loads(line)
            for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert len(metrics) == 1
        assert metrics[0]["metrics"] == {"val/loss": 0.5}

    summary = collect_summary(tmp_path, stage="fit", metric="val/loss")
    assert len(summary) == 1
    assert summary[0]["n"] == 2
    assert summary[0]["mean"] == 0.5
    assert summary[0]["std"] == 0.0


def test_stage_artifacts_progress_metrics_and_component_override(tmp_path: Path) -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "artifacts"},
            "components": {"value": {"type": "core/value", "params": {"value": 1}}},
            "stages": [
                {"name": "fit", "type": "test/publish"},
                {
                    "name": "test",
                    "type": "test/consume",
                    "needs": ["fit"],
                    "components": {"value": {"type": "core/value", "params": {"value": 3}}},
                },
            ],
        }
    )
    registry = extended_registry()
    manifest = compile_plan(config, registry).runs[0]

    status = execute_run(manifest, registry, artifact_root=tmp_path)

    assert status["stages"]["fit"]["artifacts"] == {"best": "checkpoints/best.txt"}
    assert status["stages"]["test"]["metrics"] == {"test/result": 10.0}
    run_dir = tmp_path / "artifacts" / manifest.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["kind"] for event in events] == ["progress", "progress", "final", "final"]
    assert [event.get("step") for event in events[:2]] == [0, 1]
    assert (run_dir / "environment.json").exists()


def test_keyboard_interrupt_is_persisted(tmp_path: Path) -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "interrupt"},
            "stages": [{"name": "fit", "type": "test/interrupt"}],
        }
    )
    registry = extended_registry()
    manifest = compile_plan(config, registry).runs[0]

    with pytest.raises(KeyboardInterrupt):
        execute_run(manifest, registry, artifact_root=tmp_path)

    status_path = tmp_path / "interrupt" / manifest.run_id / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["state"] == "interrupted"
    assert status["stages"]["fit"]["state"] == "interrupted"
