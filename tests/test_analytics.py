import json
from pathlib import Path

import pytest

from research_assistant.analytics import (
    ChartSpec,
    EvaluationSpec,
    MetricFilter,
    MetricIndex,
    TableSpec,
)
from research_assistant.config import parse_config
from research_assistant.execution import execute_run
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry
from research_assistant.reporting import (
    render_evaluation_latex,
    render_latex_table,
    write_chart_bundle,
    write_evaluation_bundle,
    write_table_bundle,
)


def completed_runs(root: Path) -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "indexed"},
            "seed": 0,
            "matrix": {"seed": [0, 1, 2]},
            "stages": [
                {
                    "name": "test",
                    "type": "core/noop",
                    "params": {"metrics": {"test/error": 0.25}},
                }
            ],
        }
    )
    registry = load_registry()
    for manifest in compile_plan(config, registry).runs:
        execute_run(manifest, registry, artifact_root=root)


def test_incremental_index_chart_and_table(tmp_path: Path) -> None:
    completed_runs(tmp_path)
    index = MetricIndex(tmp_path)
    try:
        first = index.refresh(batch_size=2)
        second = index.refresh(batch_size=2)
        assert first["events_indexed"] == 3
        assert second["events_indexed"] == 0
        assert index.catalog()["run_count"] == 3

        filters = MetricFilter(metrics=["test/error"], kinds=["final"])
        chart = index.chart(
            ChartSpec(filters=filters, group_by="trial_id", uncertainty="std")
        )
        assert chart["points"] == 1
        assert chart["series"][0]["points"][0]["n"] == 3
        assert chart["series"][0]["points"][0]["y"] == 0.25

        spec = TableSpec(
            filters=filters,
            row="study_id",
            column="trial_id",
            caption="Indexed results",
            label="tab:indexed",
        )
        table = index.table(spec)
        latex = render_latex_table(table, spec)
        assert "Indexed results" in latex
        assert "0.25" in latex
        bundle = write_table_bundle(index, spec, tmp_path / "report")
        assert (bundle / "table.tex").is_file()
        assert len(json.loads((bundle / "provenance.json").read_text())["run_ids"]) == 3
    finally:
        index.close()


def test_validation_selected_evaluation_aggregates_target_at_same_step(tmp_path: Path) -> None:
    for seed, target in [(0, 0.2), (1, 0.3), (2, None)]:
        run_id = f"run-{seed}"
        run_dir = tmp_path / "study" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "study_id": "study",
                    "trial_id": "trial",
                    "run_id": run_id,
                    "config": {
                        "seed": seed,
                        "components": {
                            "model": {"type": "example/model"},
                            "data": {"type": "example/dataset"},
                        },
                    },
                    "assignments": {"seed": seed},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "status.json").write_text(
            json.dumps({"state": "completed"}),
            encoding="utf-8",
        )
        events = []
        sequence = 0
        for step, validation in [(0, 0.5), (1, 0.1), (2, 0.4)]:
            sequence += 1
            events.append(
                {
                    "schema_version": 1,
                    "event_id": f"{run_id}-val-{step}",
                    "timestamp": "2026-07-30T00:00:00+00:00",
                    "run_id": run_id,
                    "attempt": 1,
                    "sequence": sequence,
                    "stage": "fit",
                    "kind": "progress",
                    "metric": "val/l2",
                    "value": validation,
                    "step": step,
                    "step_kind": "epoch",
                    "dimensions": {"dataset": "benchmark", "split": "val"},
                }
            )
        if target is not None:
            sequence += 1
            events.append(
                {
                    "schema_version": 1,
                    "event_id": f"{run_id}-test-1",
                    "timestamp": "2026-07-30T00:00:00+00:00",
                    "run_id": run_id,
                    "attempt": 1,
                    "sequence": sequence,
                    "stage": "fit",
                    "kind": "progress",
                    "metric": "test/l2",
                    "value": target,
                    "step": 1,
                    "step_kind": "epoch",
                    "dimensions": {"dataset": "benchmark", "split": "test"},
                }
            )
        (run_dir / "metrics.jsonl").write_text(
            "".join(f"{json.dumps(event)}\n" for event in events),
            encoding="utf-8",
        )

    index = MetricIndex(tmp_path)
    try:
        index.refresh()
        spec = EvaluationSpec(
            name="selected-results",
            selection_metric="val/l2",
            target_metric="test/l2",
            selection_split="val",
            target_split="test",
            group_by=["dataset", "model"],
            caption="Validation-selected results",
            label="tab:selected",
        )
        result = index.evaluate(spec)
        assert result["selected_runs"] == 3
        assert result["eligible_runs"] == 2
        assert result["excluded_runs"] == 1
        assert result["groups"][0]["mean"] == pytest.approx(0.25)
        assert result["groups"][0]["std"] == pytest.approx(0.05 * 2**0.5)
        assert result["groups"][0]["seeds"] == [0, 1]
        assert all(row["selected_step"] == 1 for row in result["runs"])
        latex = render_evaluation_latex(result, spec)
        assert "Validation-selected results" in latex
        bundle = write_evaluation_bundle(index, spec, tmp_path / "selected-report")
        assert (bundle / "table.tex").is_file()
        provenance = json.loads((bundle / "provenance.json").read_text())
        assert len(provenance["eligible_run_ids"]) == 2
        assert len(provenance["excluded_run_ids"]) == 1
    finally:
        index.close()


def test_index_waits_for_complete_jsonl_line(tmp_path: Path) -> None:
    completed_runs(tmp_path)
    metrics_path = next(tmp_path.glob("*/*/metrics.jsonl"))
    index = MetricIndex(tmp_path)
    try:
        index.refresh()
        payload = {
            "schema_version": 1,
            "event_id": "late-event",
            "timestamp": "2026-07-20T00:00:00+00:00",
            "run_id": metrics_path.parent.name,
            "attempt": 1,
            "sequence": 99,
            "stage": "fit",
            "kind": "progress",
            "metric": "train/loss",
            "value": 0.5,
            "step": 1,
            "step_kind": "epoch",
            "dimensions": {},
        }
        encoded = json.dumps(payload)
        with metrics_path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
        assert index.refresh()["events_indexed"] == 0
        with metrics_path.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        assert index.refresh()["events_indexed"] == 1
    finally:
        index.close()


def test_chart_bundle_renders_vector_and_document_formats(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    completed_runs(tmp_path)
    index = MetricIndex(tmp_path)
    try:
        index.refresh()
        spec = ChartSpec(
            filters=MetricFilter(metrics=["test/error"], kinds=["final"]),
            chart_type="bar",
            title="Indexed results",
        )
        bundle = write_chart_bundle(
            index,
            spec,
            tmp_path / "chart-report",
            formats=("svg", "pdf"),
        )
        assert (bundle / "chart.svg").is_file()
        assert (bundle / "chart.pdf").is_file()
        assert (bundle / "data.json").is_file()
        assert (bundle / "provenance.json").is_file()
    finally:
        index.close()


def test_many_run_index_is_incremental_and_chart_payload_is_bounded(tmp_path: Path) -> None:
    runs = 120
    steps = 250
    for run_number in range(runs):
        run_id = f"run-{run_number:04d}"
        run_dir = tmp_path / "scale" / run_id
        run_dir.mkdir(parents=True)
        manifest = {
            "study_id": "scale",
            "trial_id": f"trial-{run_number:04d}",
            "run_id": run_id,
            "assignments": {"seed": run_number},
            "config": {
                "seed": run_number,
                "components": {"model": {"type": "test/model", "params": {}}},
            },
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "status.json").write_text(
            json.dumps({"state": "completed", "updated_at": "now"}), encoding="utf-8"
        )
        events = []
        for step in range(steps):
            events.append(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event_id": f"{run_id}-{step}",
                        "timestamp": "2026-07-20T00:00:00+00:00",
                        "run_id": run_id,
                        "attempt": 1,
                        "sequence": step + 1,
                        "stage": "fit",
                        "kind": "progress",
                        "metric": "val/loss",
                        "value": run_number + step / steps,
                        "step": step,
                        "step_kind": "epoch",
                        "dimensions": {},
                    }
                )
            )
        (run_dir / "metrics.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")

    index = MetricIndex(tmp_path)
    try:
        assert index.refresh(batch_size=128)["events_indexed"] == runs * steps
    finally:
        index.close()

    reopened = MetricIndex(tmp_path)
    try:
        assert reopened.refresh(batch_size=128)["events_indexed"] == 0
        catalog = reopened.catalog(limit=20)
        assert len(catalog["trials"]) == 20
        assert catalog["cardinality"]["trials"] == runs
        assert catalog["truncated"]["trials"] is True
        chart = reopened.chart(
            ChartSpec(
                filters=MetricFilter(metrics=["val/loss"], kinds=["progress"]),
                group_by="model",
                max_points=50,
            )
        )
        assert len(chart["series"]) == 1
        assert len(chart["series"][0]["points"]) <= 50
        assert chart["series"][0]["points"][0]["n"] >= runs

        run_chart = reopened.chart(
            ChartSpec(
                filters=MetricFilter(metrics=["val/loss"], kinds=["progress"]),
                group_by="run_id",
                max_points=50,
                max_series=25,
            )
        )
        assert run_chart["series_total"] == runs
        assert run_chart["series_count"] == 25
        assert run_chart["truncated"] is True
        assert run_chart["points"] <= 25 * 50

        table = reopened.table(
            TableSpec(
                filters=MetricFilter(metrics=["val/loss"], kinds=["progress"]),
                row="trial_id",
                column="model",
                max_rows=15,
                max_columns=5,
            )
        )
        evaluation = reopened.evaluate(
            EvaluationSpec(
                selection_metric="val/loss",
                target_metric="val/loss",
                group_by=["model"],
                max_runs=25,
            )
        )
        assert evaluation["selected_runs"] == 25
        assert evaluation["eligible_runs"] == 25
        assert evaluation["truncated"] is True
        assert table["row_total"] == runs
        assert len(table["rows"]) == 15
        assert table["truncated"] is True
    finally:
        reopened.close()
