from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from research_assistant.asset_registry import AssetRegistry, AssetRegistryError
from research_assistant.diagnostics import DiagnosticEngine, DiagnosticPolicy
from research_assistant.models import ExperimentConfig
from research_assistant.pipeline_execution import execute_run_cached
from research_assistant.planning import compile_plan
from research_assistant.publication import PublicationSpec, build_publication_bundle
from research_assistant.registry import Registry


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _config(name: str) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "version": 1,
            "experiment": {"name": name},
            "seed": 7,
            "stages": [{"name": "produce", "type": "test/produce"}],
            "artifacts": {"root": "runs"},
        }
    )


def test_stage_cache_reuses_outputs_across_equivalent_studies(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls = {"count": 0}

    def produce(_params, context):
        from research_assistant.execution import StageResult

        calls["count"] += 1
        path = context.run_dir / "value.txt"
        path.write_text("cached", encoding="utf-8")
        return StageResult(metrics={"score": 1.0}, artifacts={"value": str(path)})

    registry = Registry()
    registry.add(
        "stage",
        "test/produce",
        factory=produce,
        schema=EmptyParams,
        metadata={"cacheable": True},
    )
    first = compile_plan(_config("cache-first"), registry).runs[0]
    second = compile_plan(_config("cache-second"), registry).runs[0]
    first_status = execute_run_cached(first, registry, artifact_root=tmp_path / "runs")
    second_status = execute_run_cached(second, registry, artifact_root=tmp_path / "runs")
    assert first_status["stages"]["produce"]["cache_hit"] is False
    assert second_status["stages"]["produce"]["cache_hit"] is True
    restored = tmp_path / "runs" / second.study_id / second.run_id
    artifact = restored / second_status["stages"]["produce"]["artifacts"]["value"]
    assert artifact.read_text(encoding="utf-8") == "cached"
    assert calls["count"] == 1


def _managed_run(root: Path) -> Path:
    run_dir = root / "runs" / "study" / "run-1"
    run_dir.mkdir(parents=True)
    checkpoint = run_dir / "checkpoints" / "fit" / "best.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")
    figure = run_dir / "figures" / "sample.png"
    figure.parent.mkdir()
    figure.write_bytes(b"png")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "study_id": "study",
                "trial_id": "trial",
                "run_id": "run-1",
                "config": {
                    "version": 1,
                    "experiment": {"name": "study"},
                    "seed": 0,
                    "components": {
                        "model": {"type": "test/model", "params": {}},
                        "data": {"type": "test/data", "params": {}},
                    },
                    "stages": [{"name": "fit", "type": "test/fit"}],
                    "artifacts": {"root": "runs"},
                },
                "assignments": {"seed": 0},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "state": "completed",
                "stages": {
                    "fit": {
                        "state": "completed",
                        "artifacts": {
                            "best": "checkpoints/fit/best.pt",
                            "sample": "figures/sample.png",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "resources.json").write_text(
        json.dumps(
            {
                "total": {
                    "wall_seconds": 3600,
                    "gpu_wall_seconds": 1800,
                    "placement_memory_peak_mb": 4096,
                    "device_energy_joules": 3600000,
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "environment.json").write_text(json.dumps({"python": "3.12"}), encoding="utf-8")
    return run_dir


def test_asset_registry_promotes_pins_and_materializes(tmp_path: Path) -> None:
    _managed_run(tmp_path)
    registry = AssetRegistry(tmp_path)
    try:
        result = registry.refresh("runs")
        assert result["registered"] == 2
        checkpoints = registry.list(kind="checkpoint")
        assert len(checkpoints) == 1
        asset_id = checkpoints[0]["asset_id"]
        assert registry.promote(asset_id, "selected")["status"] == "selected"
        assert registry.pin(asset_id)["pinned"] is True
        destination = registry.materialize(asset_id, "exports/model.pt")
        assert destination.read_bytes() == b"checkpoint"
        registry.promote(asset_id, "released")
        with pytest.raises(AssetRegistryError):
            registry.delete(asset_id)
    finally:
        registry.close()


def test_diagnostics_detect_stall_idle_divergence_and_oom(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "launcher.json").write_text(
        json.dumps({"started_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8"
    )
    events = [
        {
            "metric": "train/loss",
            "value": value,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        for value in [1.0, 0.9, 0.8, 0.7, 100.0]
    ]
    metrics = run_dir / "metrics.jsonl"
    metrics.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    os.utime(metrics, (1, 1))
    policy = DiagnosticPolicy(
        warmup_seconds=0,
        metric_stall_seconds=10,
        gpu_idle_seconds=10,
        check_interval_seconds=1,
        divergence_window=3,
        divergence_factor=10,
        on_metric_stall="warn",
        on_gpu_idle="warn",
        on_divergence="warn",
        on_oom="warn",
    )
    engine = DiagnosticEngine(tmp_path, policy)
    now = time.time()
    state = engine.state("run")
    state.idle_since = now - 20
    findings = engine.check(
        run_id="run",
        run_dir=run_dir,
        worker_pid=os.getpid(),
        now=now,
        gpu_utilization_percent=0,
    )
    codes = {finding.code for finding in findings}
    assert {"metric-stall", "gpu-idle", "metric-divergence"} <= codes
    (run_dir / "worker.log").write_text("CUDA out of memory", encoding="utf-8")
    assert engine.classify_exit(run_id="run", run_dir=run_dir, exit_code=1).code == "out-of-memory"


def test_publication_bundle_contains_reproduction_and_checksums(tmp_path: Path) -> None:
    _managed_run(tmp_path)
    report = tmp_path / "reports" / "main"
    report.mkdir(parents=True)
    (report / "table.tex").write_text("table", encoding="utf-8")
    (report / "chart.pdf").write_bytes(b"pdf")
    registry = AssetRegistry(tmp_path)
    try:
        registry.refresh("runs")
        for asset in registry.list(kind="checkpoint"):
            registry.promote(asset["asset_id"], "selected")
    finally:
        registry.close()
    spec = PublicationSpec(
        name="paper",
        artifact_root="runs",
        run_ids=["run-1"],
        reports=["reports/main"],
    )
    output = build_publication_bundle(tmp_path, spec, "publications/paper")
    assert (output / "publication.json").is_file()
    assert (output / "reproduction.sh").stat().st_mode & 0o111
    assert (output / "tables" / "table.tex").is_file()
    assert (output / "figures" / "chart.pdf").is_file()
    assert "checksums.sha256" in {path.name for path in output.iterdir()}
    assert list((output / "checkpoints").iterdir())
