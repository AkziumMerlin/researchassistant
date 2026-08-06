from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tensorboard.compat.proto import event_pb2, summary_pb2
from tensorboard.summary.writer.event_file_writer import EventFileWriter

from research_assistant.tensorboard_compat import TensorBoardStore
from research_assistant.ui.server import create_app


def _write_scalars(logdir: Path, values: dict[str, list[float]], *, start: float = 1000.0) -> None:
    logdir.mkdir(parents=True, exist_ok=True)
    writer = EventFileWriter(str(logdir))
    steps = max((len(series) for series in values.values()), default=0)
    for step in range(steps):
        summaries = [
            summary_pb2.Summary.Value(tag=tag, simple_value=series[step])
            for tag, series in values.items()
            if step < len(series)
        ]
        writer.add_event(
            event_pb2.Event(
                wall_time=start + step * 2.0,
                step=step,
                summary=summary_pb2.Summary(value=summaries),
            )
        )
    writer.flush()
    writer.close()


def test_tensorboard_store_catalogs_and_charts_existing_runs(tmp_path: Path) -> None:
    root = tmp_path / "tensorboard"
    _write_scalars(
        root / "model-a" / "seed0",
        {
            "train/loss": [1.0 / (step + 1) for step in range(80)],
            "validation/loss": [1.2 / (step + 1) for step in range(80)],
        },
    )
    _write_scalars(
        root / "model-b" / "seed1",
        {"train/loss": [1.5 / (step + 1) for step in range(60)]},
        start=2000.0,
    )
    bad = root / "broken"
    bad.mkdir(parents=True)
    (bad / "events.out.tfevents.corrupt").write_bytes(b"not a tensorboard event file")

    store = TensorBoardStore(tmp_path)
    catalog = store.catalog(root)

    assert catalog["event_files"] == 3
    assert catalog["run_count"] == 2
    assert {run["name"] for run in catalog["runs"]} == {
        "model-a/seed0",
        "model-b/seed1",
    }
    tags = {row["name"]: row for row in catalog["tags"]}
    assert tags["train/loss"]["runs"] == 2
    assert tags["train/loss"]["points"] == 140
    assert tags["validation/loss"]["runs"] == 1
    assert catalog["errors"]

    cached = store.catalog(root)
    assert cached["cache_hit"] is True

    result = store.chart(
        root,
        runs=[],
        tags=["train/loss"],
        x_axis="relative_time",
        smoothing=0.6,
        max_points=20,
        max_series=10,
        y_scale="linear",
    )
    chart = result["chart"]
    assert chart["series_count"] == 2
    assert chart["series_total"] == 2
    assert chart["spec"]["x_label"] == "relative time (hours)"
    assert all(len(series["points"]) <= 20 for series in chart["series"])
    assert all(series["points"][0]["x"] == 0.0 for series in chart["series"])


def test_tensorboard_catalog_cache_invalidates_when_events_change(tmp_path: Path) -> None:
    root = tmp_path / "logs"
    run = root / "run"
    _write_scalars(run, {"loss": [3.0, 2.0]})
    store = TensorBoardStore(tmp_path)
    first = store.catalog(root)
    assert first["cache_hit"] is False
    assert first["tags"][0]["points"] == 2

    _write_scalars(run, {"loss": [1.0, 0.5]}, start=3000.0)
    second = store.catalog(root)
    assert second["cache_hit"] is False
    assert second["tags"][0]["points"] == 4


def test_tensorboard_routes_read_workspace_logs_and_reject_escapes(tmp_path: Path) -> None:
    _write_scalars(tmp_path / "old-runs" / "run-a", {"train/loss": [3.0, 2.0, 1.0]})

    with TestClient(create_app(tmp_path)) as client:
        catalog_response = client.post(
            "/api/tensorboard/catalog",
            json={"logdir": "old-runs", "reload": False, "max_runs": 100},
        )
        assert catalog_response.status_code == 200
        catalog = catalog_response.json()
        assert catalog["run_count"] == 1
        assert catalog["tags"][0]["name"] == "train/loss"

        chart_response = client.post(
            "/api/tensorboard/chart",
            json={
                "logdir": "old-runs",
                "runs": ["run-a"],
                "tags": ["train/loss"],
                "x_axis": "step",
                "smoothing": 0.0,
                "max_points": 100,
                "max_series": 10,
                "y_scale": "linear",
            },
        )
        assert chart_response.status_code == 200
        assert chart_response.json()["chart"]["series"][0]["name"] == "run-a"

        escape = client.post(
            "/api/tensorboard/catalog",
            json={"logdir": "../outside", "reload": False},
        )
        assert escape.status_code == 400

        missing = client.post(
            "/api/tensorboard/catalog",
            json={"logdir": "missing", "reload": False},
        )
        assert missing.status_code == 400
