from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from research_assistant.system_monitor import NvidiaSystemProbe, SystemMonitor
from research_assistant.ui.server import create_app


class NoGpuProbe:
    def snapshot(self) -> dict[str, Any]:
        return {
            "available": False,
            "error": "test host has no GPU",
            "devices": [],
            "processes": {},
        }


class CurrentProcessGpuProbe:
    def snapshot(self) -> dict[str, Any]:
        return {
            "available": True,
            "error": None,
            "devices": [
                {
                    "index": 0,
                    "uuid": "GPU-test",
                    "name": "Test GPU",
                    "pci_bus_id": "00000000:01:00.0",
                    "memory_total_mb": 40960.0,
                    "memory_used_mb": 2048.0,
                    "memory_free_mb": 38912.0,
                    "memory_percent": 5.0,
                    "utilization_percent": 25.0,
                    "memory_utilization_percent": 10.0,
                    "temperature_c": 42.0,
                    "power_watts": 100.0,
                    "power_limit_watts": 250.0,
                    "power_percent": 40.0,
                    "process_count": 1,
                }
            ],
            "processes": {
                os.getpid(): [
                    {
                        "gpu_uuid": "GPU-test",
                        "gpu_index": 0,
                        "memory_mb": 512.0,
                        "process_name": "pytest",
                    }
                ]
            },
        }


def test_system_monitor_samples_host_and_current_process(tmp_path: Path) -> None:
    monitor = SystemMonitor(tmp_path, gpu_probe=NoGpuProbe())
    snapshot = monitor.snapshot(
        process_scope="user",
        process_sort="pid",
        process_limit=2000,
        search=str(os.getpid()),
    )

    assert snapshot["host"]["cpu_count"] >= 1
    assert snapshot["host"]["memory"]["total_bytes"] > 0
    assert snapshot["host"]["disk"]["total_bytes"] > 0
    assert snapshot["gpus"]["available"] is False
    current = next(row for row in snapshot["processes"] if row["pid"] == os.getpid())
    assert current["same_user"] is True
    assert current["command"]
    assert current["memory_rss_bytes"] > 0


def test_system_monitor_correlates_gpu_and_researchassistant_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "study-a" / "run-a"
    run_dir.mkdir(parents=True)
    (run_dir / "launcher.json").write_text(
        '{"worker_pid": %d, "gpu": {"index": 0, "uuid": "GPU-test"}}\n' % os.getpid(),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        '{"run_id": "run-a", "state": "running", "attempt": 2, '
        '"stages": {"fit": {"state": "running"}}}\n',
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        '{"run_id": "run-a", "study_id": "study-a", "trial_id": "trial-a"}\n',
        encoding="utf-8",
    )
    (run_dir / "worker.log").write_text("training step 17\n", encoding="utf-8")

    monitor = SystemMonitor(tmp_path, gpu_probe=CurrentProcessGpuProbe())
    snapshot = monitor.snapshot(
        process_scope="ra",
        process_sort="gpu",
        process_limit=100,
    )
    current = next(row for row in snapshot["processes"] if row["pid"] == os.getpid())

    assert current["gpu_memory_mb"] == 512.0
    assert current["gpus"][0]["gpu_index"] == 0
    assert current["ra"]["run_id"] == "run-a"
    assert current["ra"]["study_id"] == "study-a"
    assert current["ra"]["trial_id"] == "trial-a"
    assert current["ra"]["stage"] == "fit"

    context = monitor.process_context(os.getpid())
    assert context["process"]["ra"]["run_id"] == "run-a"
    worker_log = next(log for log in context["logs"] if log["kind"] == "worker_log")
    assert worker_log["path"] == "runs/study-a/run-a/worker.log"
    assert "training step 17" in worker_log["tail"]


def test_nvidia_probe_parses_devices_and_processes(monkeypatch) -> None:
    probe = NvidiaSystemProbe()
    gpu_output = (
        "0, GPU-one, NVIDIA A100, 00000000:01:00.0, 40960, 1024, 39936, "
        "45, 12, 51, 132.5, 250\n"
    )
    process_output = "1234, python, GPU-one, 768\n"

    def fake_run(*arguments: str):
        if arguments[0].startswith("--query-gpu="):
            return gpu_output, None
        return process_output, None

    monkeypatch.setattr(probe, "_run", fake_run)
    snapshot = probe.snapshot()

    assert snapshot["available"] is True
    assert snapshot["devices"][0]["memory_percent"] == 2.5
    assert snapshot["devices"][0]["power_percent"] == 53.0
    assert snapshot["devices"][0]["process_count"] == 1
    assert snapshot["processes"][1234][0]["memory_mb"] == 768.0


def test_system_monitor_ui_routes_and_extension(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    assert hasattr(app.state, "system_monitor")
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/system-monitor/snapshot" in paths
    assert "/api/system-monitor/processes/{pid}" in paths

    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "/api/extensions/system-monitor.js" in index.text

        extension = client.get("/api/extensions/system-monitor.js")
        assert extension.status_code == 200
        assert "installSystemMonitor" in extension.text

        snapshot = client.get(
            "/api/system-monitor/snapshot",
            params={"scope": "user", "sort": "pid", "search": str(os.getpid())},
        )
        assert snapshot.status_code == 200
        assert snapshot.json()["host"]["process_count"] >= 1

        protected = client.post(
            f"/api/system-monitor/processes/{os.getpid()}/signal",
            json={"signal": "TERM"},
        )
        assert protected.status_code == 400
