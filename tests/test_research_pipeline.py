from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from research_assistant.dataset_registry import (
    DatasetRegistry,
    DatasetRegistryError,
    DatasetSpec,
)
from research_assistant.hpo import HpoController, HpoObjective, HpoSpec
from research_assistant.publication_plus import (
    EnhancedPublicationSpec,
    build_enhanced_publication_bundle,
)
from research_assistant.research_log import (
    DecisionInput,
    EvidenceInput,
    HypothesisInput,
    ResearchLog,
)
from research_assistant.selection import (
    SelectionSpec,
    evaluate_selection,
    lock_selection,
    preview_selection,
)
from research_assistant.statistics_suite import (
    StatisticalSpec,
    analyze_statistics,
    write_statistical_report,
)


def _event(
    run_id: str,
    *,
    sequence: int,
    metric: str,
    value: float,
    step: int,
    split: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": f"{run_id}-{metric}-{split}-{sequence}",
        "timestamp": f"2026-07-31T00:00:{sequence:02d}+00:00",
        "run_id": run_id,
        "attempt": 1,
        "sequence": sequence,
        "stage": "fit",
        "kind": "progress",
        "metric": metric,
        "value": value,
        "step": step,
        "step_kind": "epoch",
        "dimensions": {"dataset": "benchmark", "split": split},
    }


def _write_run(
    root: Path,
    *,
    run_id: str,
    trial_id: str,
    seed: int,
    model: str,
    validation: list[float],
    test: list[float],
) -> None:
    run_dir = root / "study" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "study_id": "study",
        "trial_id": trial_id,
        "run_id": run_id,
        "assignments": {"seed": seed},
        "provenance": {},
        "config": {
            "version": 1,
            "experiment": {"name": "study", "tags": []},
            "plugins": [],
            "seed": seed,
            "components": {
                "model": {"type": model, "params": {}},
                "data": {"type": "example/data", "params": {}},
            },
            "matrix": {},
            "stages": [{"name": "fit", "type": "example/fit", "needs": [], "components": {}, "params": {}}],
            "resources": {"accelerator": "cpu", "devices": 1},
            "artifacts": {"root": str(root)},
            "logging": {"tensorboard": {"enabled": False, "directory": "tensorboard", "flush_seconds": 30}},
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps({"run_id": run_id, "state": "completed", "updated_at": "2026-07-31T00:01:00+00:00"}),
        encoding="utf-8",
    )
    events = []
    sequence = 0
    for step, value in enumerate(validation):
        sequence += 1
        events.append(
            _event(
                run_id,
                sequence=sequence,
                metric="loss",
                value=value,
                step=step,
                split="validation",
            )
        )
    for step, value in enumerate(test):
        sequence += 1
        events.append(
            _event(
                run_id,
                sequence=sequence,
                metric="loss",
                value=value,
                step=step,
                split="test",
            )
        )
    (run_dir / "metrics.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def test_dataset_snapshot_validation_and_lineage(tmp_path: Path) -> None:
    source = tmp_path / "data" / "benchmark"
    for split in ("train", "validation", "test"):
        path = source / split / f"{split}.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(split.encode())

    registry = DatasetRegistry(tmp_path)
    try:
        first = registry.register(
            DatasetSpec(
                name="benchmark",
                version="1",
                source="data/benchmark",
                splits={
                    "train": ["train/**"],
                    "validation": ["validation/**"],
                    "test": ["test/**"],
                },
            )
        )
        assert first["snapshot"] is True
        assert registry.validate(first["dataset_id"])["valid"] is True
        materialized = registry.materialize(first["dataset_id"], "exports/benchmark")
        assert (materialized / "train" / "train.bin").read_bytes() == b"train"

        second = registry.register(
            DatasetSpec(
                name="benchmark",
                version="2",
                source="data/benchmark",
                parent_id=first["dataset_id"],
                splits={
                    "train": ["train/**"],
                    "validation": ["validation/**"],
                    "test": ["test/**"],
                },
            )
        )
        assert [row["dataset_id"] for row in registry.lineage(second["dataset_id"])] == [
            second["dataset_id"],
            first["dataset_id"],
        ]

        with pytest.raises(DatasetRegistryError):
            registry.register(
                DatasetSpec(
                    name="overlap",
                    version="1",
                    source="data/benchmark",
                    splits={"train": ["**/*"], "validation": ["validation/**"]},
                )
            )
    finally:
        registry.close()


def test_hpo_proposals_are_persistent_and_validation_only(tmp_path: Path) -> None:
    base = {
        "version": 1,
        "experiment": {"name": "base", "tags": []},
        "components": {"model": {"type": "example/model", "params": {"width": 32}}},
        "matrix": {},
        "stages": [
            {
                "name": "fit",
                "type": "example/fit",
                "needs": [],
                "components": {},
                "params": {"lr": 0.001},
            }
        ],
    }
    (tmp_path / "experiment.yaml").write_text(
        yaml.safe_dump(base, sort_keys=False), encoding="utf-8"
    )
    spec = HpoSpec(
        name="search",
        base_config="experiment.yaml",
        search_space={
            "components.model.params.width": {
                "type": "categorical",
                "choices": [32, 64, 96],
            },
            "stages.0.params.lr": {
                "type": "float",
                "low": 1e-4,
                "high": 1e-2,
                "log": True,
            },
        },
        objectives=[{"metric": "loss", "split": "validation"}],
        sampler="tpe",
        max_trials=5,
        parallelism=2,
        seed=7,
    )
    controller = HpoController(tmp_path, spec)
    rows = controller.propose(3)
    assert len(rows) == 3
    assert len({row["assignment_digest"] for row in rows}) == 3
    assert all((tmp_path / row["config_path"]).is_file() for row in rows)
    assert len(HpoController(tmp_path, spec).load()["trials"]) == 3

    with pytest.raises(ValidationError):
        HpoObjective(metric="loss", split="test")


def test_selection_lock_test_gate_and_statistics(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for seed in (0, 1):
        _write_run(
            runs,
            run_id=f"a-{seed}",
            trial_id="trial-a",
            seed=seed,
            model="example/a",
            validation=[0.8, 0.3, 0.4],
            test=[0.9, 0.35, 0.5],
        )
        _write_run(
            runs,
            run_id=f"b-{seed}",
            trial_id="trial-b",
            seed=seed,
            model="example/b",
            validation=[0.8, 0.2, 0.25],
            test=[0.9, 0.22, 0.4],
        )

    spec = SelectionSpec(
        name="final",
        selection_metric="loss",
        selection_split="validation",
        target_metrics=["loss"],
        test_splits=["test"],
        direction="minimize",
        group_by=["study_id", "dataset"],
        required_seeds=[0, 1],
        min_seeds=2,
        promote_checkpoints=False,
    )
    preview = preview_selection(tmp_path, spec)
    assert preview["winners"][0]["trial_id"] == "trial-b"
    lock = lock_selection(tmp_path, spec)
    assert lock["selected_trial_ids"] == ["trial-b"]
    evaluation = evaluate_selection(tmp_path, "final", output="reports/final")
    assert {row["run_id"] for row in evaluation["values"]} == {"b-0", "b-1"}
    assert all(row["step"] == 1 for row in evaluation["values"])

    statistical = StatisticalSpec(
        name="models",
        metric="loss",
        split="test",
        group_by="model",
        paired_by=["seed", "dataset"],
        baseline="example/a",
        bootstrap_samples=200,
        permutation_samples=200,
        correction="holm",
        seed=1,
    )
    result = analyze_statistics(tmp_path, statistical)
    assert len(result["summary"]) == 2
    assert result["comparisons"][0]["candidate"] == "example/b"
    assert result["comparisons"][0]["pairs"] == 2
    report = write_statistical_report(tmp_path, statistical, "reports/models")
    assert (report / "analysis.json").is_file()
    assert (report / "summary.tex").is_file()

    with pytest.raises(ValidationError):
        SelectionSpec(
            name="leak",
            selection_metric="loss",
            selection_split="test",
        )


def test_research_log_and_enhanced_publication(tmp_path: Path) -> None:
    source = tmp_path / "data" / "benchmark"
    (source / "train").mkdir(parents=True)
    (source / "train" / "sample.bin").write_bytes(b"data")
    datasets = DatasetRegistry(tmp_path)
    try:
        dataset = datasets.register(
            DatasetSpec(
                name="benchmark",
                version="1",
                source="data/benchmark",
                splits={"train": ["train/**"]},
            )
        )
    finally:
        datasets.close()

    log = ResearchLog(tmp_path)
    try:
        hypothesis = log.create_hypothesis(
            HypothesisInput(
                title="Better architecture",
                statement="Architecture B reduces validation error.",
                expected_outcome="Lower validation loss.",
                decision_criteria="Select B if paired validation improves.",
                status="active",
            )
        )
        log.add_evidence(
            EvidenceInput(
                hypothesis_id=hypothesis["hypothesis_id"],
                kind="dataset",
                reference=dataset["dataset_id"],
                supports="neutral",
            )
        )
        log.record_decision(
            DecisionInput(
                title="Use benchmark snapshot",
                choice=dataset["dataset_id"],
                rationale="It is checksum-verified.",
                hypothesis_id=hypothesis["hypothesis_id"],
            )
        )
        log.update_hypothesis(
            hypothesis["hypothesis_id"],
            status="supported",
            conclusion="Validation criterion was met.",
        )
    finally:
        log.close()

    runs = tmp_path / "runs"
    _write_run(
        runs,
        run_id="publication-run",
        trial_id="publication-trial",
        seed=0,
        model="example/model",
        validation=[0.5, 0.2],
        test=[0.6, 0.25],
    )
    spec = EnhancedPublicationSpec(
        name="paper",
        title="Paper",
        artifact_root="runs",
        run_ids=["publication-run"],
        dataset_ids=[dataset["dataset_id"]],
        include_research_log=True,
        strict_consistency=True,
        template="generic",
    )
    bundle = build_enhanced_publication_bundle(tmp_path, spec, "publications/paper")
    assert (bundle / "paper.tex").is_file()
    assert (bundle / "datasets").is_dir()
    assert (bundle / "research" / "research-log.json").is_file()
    assert (bundle / "bundle-lock.json").is_file()
    assert (bundle / "checksums.sha256").is_file()


def test_cli_and_ui_surface_new_workflows() -> None:
    from research_assistant.cli_research import app

    names = {group.name for group in app.registered_groups}
    assert {"hpo", "dataset", "selection", "statistics", "research"}.issubset(names)

    script = (
        Path(__file__).parents[1]
        / "ui/frontend/src/extensions/research-extension.js"
    )
    source = script.read_text(encoding="utf-8")
    for label in (
        "Adaptive HPO",
        "Datasets",
        "Selection",
        "Statistics",
        "Hypotheses",
        "Publication",
    ):
        assert label in source
