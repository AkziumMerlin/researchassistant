import json
from pathlib import Path

import pytest

from research_assistant.analytics import MetricIndex
from research_assistant.live_metrics import LiveMetricSpec, live_dashboard


def _write_run(
    root: Path,
    *,
    run_id: str,
    trial_id: str,
    seed: int,
    state: str,
    model: str = "example/model",
) -> Path:
    run_dir = root / "study" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "study_id": "study",
                "trial_id": trial_id,
                "run_id": run_id,
                "assignments": {"seed": seed, "width": 64},
                "config": {
                    "seed": seed,
                    "components": {"model": {"type": model}, "data": {"type": "example/data"}},
                    "stages": [{"name": "fit", "params": {"epochs": 10}}],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "state": state,
                "updated_at": "2026-07-31T00:00:02+00:00",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _append_event(
    run_dir: Path,
    *,
    sequence: int,
    metric: str,
    value: float,
    step: int,
    split: str,
) -> None:
    payload = {
        "schema_version": 1,
        "event_id": f"{run_dir.name}-{metric}-{sequence}",
        "timestamp": f"2026-07-31T00:00:0{step}+00:00",
        "run_id": run_dir.name,
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
    with (run_dir / "metrics.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload) + "\n")


def test_live_dashboard_is_job_scoped_and_incremental(tmp_path: Path) -> None:
    run0 = _write_run(tmp_path, run_id="run-0", trial_id="trial-a", seed=0, state="running")
    run1 = _write_run(tmp_path, run_id="run-1", trial_id="trial-a", seed=1, state="running")
    _write_run(tmp_path, run_id="run-2", trial_id="trial-b", seed=2, state="completed")
    for run_dir in (run0, run1):
        for step in range(3):
            _append_event(
                run_dir,
                sequence=2 * step + 1,
                metric="train/loss",
                value=1.0 / (step + 1),
                step=step,
                split="train",
            )
            _append_event(
                run_dir,
                sequence=2 * step + 2,
                metric="val/loss",
                value=2.0 / (step + 1),
                step=step,
                split="validation",
            )

    index = MetricIndex(tmp_path)
    try:
        index.refresh()
        first = live_dashboard(
            index,
            allowed_run_ids=["run-0", "run-1", "run-2"],
            spec=LiveMetricSpec(),
        )
        assert first["summary"]["runs"] == 2
        assert set(first["selected_metrics"]) == {"train/loss", "val/loss"}
        assert {panel["metric"] for panel in first["panels"]} == {
            "train/loss",
            "val/loss",
        }
        assert all(run["total_steps"] == 10 for run in first["runs"])

        unchanged = live_dashboard(
            index,
            allowed_run_ids=["run-0", "run-1", "run-2"],
            spec=LiveMetricSpec(
                metrics=first["selected_metrics"],
                cursor=first["cursor"],
            ),
        )
        assert unchanged["changed"] is False
        assert unchanged["panels"] == []

        _append_event(
            run0,
            sequence=7,
            metric="train/loss",
            value=0.2,
            step=3,
            split="train",
        )
        assert index.refresh()["events_indexed"] == 1
        changed = live_dashboard(
            index,
            allowed_run_ids=["run-0", "run-1", "run-2"],
            spec=LiveMetricSpec(
                metrics=first["selected_metrics"],
                cursor=first["cursor"],
            ),
        )
        assert changed["changed_metrics"] == ["train/loss"]
        assert [panel["metric"] for panel in changed["panels"]] == ["train/loss"]
    finally:
        index.close()


def test_live_dashboard_supports_search_and_completed_scope(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        run_id="completed-run",
        trial_id="wide-model",
        seed=3,
        state="completed",
        model="example/wide-model",
    )
    index = MetricIndex(tmp_path)
    try:
        index.refresh()
        result = live_dashboard(
            index,
            allowed_run_ids=["completed-run"],
            spec=LiveMetricSpec(active_only=False, search="width"),
        )
        assert [run["run_id"] for run in result["runs"]] == ["completed-run"]
    finally:
        index.close()


def test_desktop_api_registers_live_metric_route(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from research_assistant.desktop_server import create_desktop_app

    app = create_desktop_app(tmp_path, token="secret")
    paths = {route.path for route in app.routes}
    assert "/api/jobs/{job_id}/live-metrics" in paths
