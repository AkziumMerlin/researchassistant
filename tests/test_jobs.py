import json
import os
from pathlib import Path
from types import SimpleNamespace

from research_assistant.artifacts import atomic_write_json
from research_assistant.jobs import JobService


def _job_fixture(root: Path) -> tuple[JobService, str, str, Path]:
    service = JobService(root)
    job_id = "20260731T010000Z-deadbeef00"
    run_id = "run-0001"
    job_dir = root / ".ra" / "ui-launches" / job_id
    run_dir = root / "runs" / "study" / run_id
    job_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    atomic_write_json(
        job_dir / "request.json",
        {
            "schema_version": 1,
            "launch_id": job_id,
            "created_at": "2026-07-31T01:00:00+00:00",
            "workspace_root": str(root),
            "config_path": "configs/smoke.yaml",
            "launcher_path": None,
            "artifact_root": str(root / "runs"),
            "artifact_root_relative": "runs",
            "resume": True,
            "overrides": [],
            "launcher_overrides": [],
            "plan": {
                "study_id": "study",
                "runs": 1,
                "trials": 1,
                "run_ids": [run_id],
                "trial_ids": ["trial"],
                "run_details": [],
            },
        },
    )
    atomic_write_json(
        job_dir / "state.json",
        {
            "schema_version": 1,
            "launch_id": job_id,
            "state": "failed",
            "created_at": "2026-07-31T01:00:00+00:00",
            "finished_at": "2026-07-31T01:00:01+00:00",
            "exit_code": 1,
        },
    )
    atomic_write_json(job_dir / "process.json", {"scheduler_pid": 99999999})
    atomic_write_json(
        run_dir / "status.json",
        {
            "run_id": run_id,
            "state": "failed",
            "attempt": 1,
            "updated_at": "2026-07-31T01:00:01+00:00",
            "stages": {},
        },
    )
    atomic_write_json(
        run_dir / "launcher.json",
        {"state": "failed", "run_id": run_id, "worker_pid": 99999998},
    )
    return service, job_id, run_id, run_dir


def test_job_logs_metrics_artifacts_and_cancel(tmp_path: Path) -> None:
    service, job_id, run_id, run_dir = _job_fixture(tmp_path)
    job_dir = tmp_path / ".ra" / "ui-launches" / job_id
    (job_dir / "scheduler.log").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (run_dir / "worker.log").write_text("worker output\n", encoding="utf-8")
    events = [
        {
            "schema_version": 1,
            "event_id": f"event-{sequence}",
            "timestamp": "2026-07-31T01:00:00+00:00",
            "run_id": run_id,
            "attempt": 1,
            "sequence": sequence,
            "stage": "fit",
            "kind": "progress",
            "metric": "loss",
            "value": 1.0 / sequence,
            "step": sequence,
            "step_kind": "epoch",
            "dimensions": {"split": "train"},
        }
        for sequence in range(1, 4)
    ]
    (run_dir / "metrics.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    prediction = run_dir / "artifacts" / "prediction_sample.png"
    prediction.parent.mkdir()
    prediction.write_bytes(b"not-a-real-png")
    report = run_dir / "artifacts" / "summary.json"
    report.write_text('{"ok": true}\n', encoding="utf-8")

    first = service.log_page(job_id, cursor=0, limit=6)
    second = service.log_page(job_id, cursor=first["next_cursor"], limit=1024)
    assert first["text"] == "alpha\n"
    assert second["text"] == "beta\ngamma\n"
    assert second["eof"] is True
    assert service.log_page(job_id, source="worker", run_id=run_id, tail=True)["text"] == (
        "worker output\n"
    )

    metrics = service.metrics(job_id, run_id, since_sequence=1)
    assert [event["sequence"] for event in metrics["events"]] == [2, 3]
    assert metrics["latest"]["fit · loss · train"]["value"] == 1 / 3

    artifacts = service.artifacts(job_id, run_id)
    by_path = {item["path"]: item for item in artifacts["artifacts"]}
    assert by_path["artifacts/prediction_sample.png"]["semantic_kind"] == "prediction"
    assert by_path["artifacts/summary.json"]["preview"] == "text"
    preview = service.artifact_preview(job_id, run_id, "artifacts/summary.json")
    assert '"ok": true' in preview["text"]

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    status["state"] = "running"
    atomic_write_json(run_dir / "status.json", status)
    cancelled = service.cancel(job_id, grace_seconds=0)
    assert cancelled["state"] == "cancelled"
    assert json.loads((run_dir / "status.json").read_text())["state"] == "interrupted"


def test_job_recovery_persists_queued_state_before_spawn(tmp_path: Path, monkeypatch) -> None:
    service, job_id, _run_id, _run_dir = _job_fixture(tmp_path)
    job_dir = tmp_path / ".ra" / "ui-launches" / job_id
    observed: dict[str, str] = {}

    def fake_popen(*_args, **_kwargs):
        observed.update(json.loads((job_dir / "state.json").read_text(encoding="utf-8")))
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr("research_assistant.jobs.subprocess.Popen", fake_popen)
    recovered = service.recover(job_id)

    assert observed["state"] == "queued"
    assert recovered["state"] == "queued"
    assert recovered["scheduler_alive"] is True
    process = json.loads((job_dir / "process.json").read_text(encoding="utf-8"))
    assert process["recovery"] is True
