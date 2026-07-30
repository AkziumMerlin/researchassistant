import json
from pathlib import Path

from research_assistant.advanced_analytics import (
    AdvancedChartSpec,
    advanced_chart,
    write_advanced_chart_bundle,
)
from research_assistant.analytics import MetricIndex


def _write_run(
    root: Path,
    *,
    run_id: str,
    trial_id: str,
    seed: int,
    model: str,
    dataset: str,
    offset: float,
) -> None:
    run_dir = root / "study" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "study_id": "study",
                "trial_id": trial_id,
                "run_id": run_id,
                "assignments": {},
                "config": {
                    "seed": seed,
                    "components": {
                        "model": {"type": model, "params": {}},
                        "data": {"type": dataset, "params": {}},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps({"run_id": run_id, "state": "completed", "updated_at": "now"}),
        encoding="utf-8",
    )
    sequence = 0
    events = []
    for step in range(3):
        for metric, value in {
            "gradient": offset + step + 1,
            "error": 2 * (offset + step + 1),
            "loss": offset + 0.1 * step,
        }.items():
            sequence += 1
            events.append(
                {
                    "schema_version": 1,
                    "event_id": f"{run_id}-{sequence}",
                    "timestamp": "2026-07-31T01:00:00+00:00",
                    "run_id": run_id,
                    "attempt": 1,
                    "sequence": sequence,
                    "stage": "test",
                    "kind": "progress",
                    "metric": metric,
                    "value": value,
                    "step": step,
                    "step_kind": "epoch",
                    "dimensions": {"dataset": dataset, "split": "test"},
                }
            )
    (run_dir / "metrics.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def test_scatter_histogram_heatmap_and_composite(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _write_run(
        root,
        run_id="run-a",
        trial_id="trial-a",
        seed=0,
        model="models/a",
        dataset="data/one",
        offset=0.0,
    )
    _write_run(
        root,
        run_id="run-b",
        trial_id="trial-b",
        seed=1,
        model="models/b",
        dataset="data/two",
        offset=2.0,
    )
    index = MetricIndex(root)
    try:
        assert index.refresh()["events_indexed"] == 18

        scatter = advanced_chart(
            index,
            AdvancedChartSpec(
                chart_type="scatter",
                x_metric="gradient",
                y_metric="error",
                group_by="model",
            ),
        )
        assert scatter["points"] == 6
        assert {series["name"] for series in scatter["series"]} == {"models/a", "models/b"}
        assert all(
            point["y"] == 2 * point["x"]
            for series in scatter["series"]
            for point in series["points"]
        )

        histogram = advanced_chart(
            index,
            AdvancedChartSpec(chart_type="histogram", metric="loss", bins=4),
        )
        assert histogram["points"] == 6
        assert sum(bin_["count"] for bin_ in histogram["series"][0]["bins"]) == 3

        heatmap = advanced_chart(
            index,
            AdvancedChartSpec(
                chart_type="heatmap",
                metric="loss",
                x_group="dataset",
                y_group="model",
            ),
        )
        assert len(heatmap["cells"]) == 2
        assert set(heatmap["x"]) == {"data/one", "data/two"}

        composite = advanced_chart(
            index,
            AdvancedChartSpec(
                chart_type="composite",
                panels=[
                    {
                        "chart_type": "line",
                        "filters": {"metrics": ["loss"], "kinds": ["progress"]},
                        "group_by": "trial_id",
                        "max_points": 20,
                    },
                    {
                        "chart_type": "scatter",
                        "x_metric": "gradient",
                        "y_metric": "error",
                    },
                ],
            ),
        )
        assert [panel["chart_type"] for panel in composite["panels"]] == ["line", "scatter"]
        assert composite["points"] == 12

        bundle = write_advanced_chart_bundle(
            index,
            AdvancedChartSpec(chart_type="histogram", metric="loss", bins=4),
            tmp_path / "report",
            formats=(),
        )
        assert (bundle / "spec.yaml").is_file()
        assert (bundle / "data.json").is_file()
        assert (bundle / "provenance.json").is_file()
    finally:
        index.close()
