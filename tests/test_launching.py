import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from research_assistant.artifacts import RunStore
from research_assistant.config import parse_config
from research_assistant.launching import (
    GpuLeaseStore,
    GpuPolicy,
    GpuSnapshot,
    LocalLauncherParams,
    LocalSubprocessLauncher,
    MemoryEstimate,
    NvidiaSmiProbe,
    ResourceRecorder,
    capture_worker_resources,
    eligible_gpu,
    estimate_memory,
    load_launcher_reference,
)
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry
from research_assistant.reporting import collect_resource_summary


def snapshot(*, utilization: float = 40.0) -> GpuSnapshot:
    return GpuSnapshot(
        index=2,
        uuid="GPU-shared",
        name="Shared GPU",
        memory_total_mb=24_576,
        memory_used_mb=12_000,
        memory_free_mb=12_576,
        utilization_percent=utilization,
        power_watts=150.0,
        process_memory_mb={99_999: 8_000},
    )


def test_shared_gpu_is_allowed_when_thresholds_pass() -> None:
    estimate = MemoryEstimate(required_mb=4_096, source="default")
    allow = GpuPolicy(
        min_free_memory_gb=8,
        reserve_memory_gb=1,
        max_utilization_percent=50,
    )

    selected = eligible_gpu(
        [snapshot()],
        estimate=estimate,
        policy=allow,
        our_pids=set(),
        our_jobs_per_gpu={},
    )

    assert selected is not None
    assert selected.index == 2
    blocked = eligible_gpu(
        [snapshot()],
        estimate=estimate,
        policy=allow.model_copy(update={"foreign_processes": "block"}),
        our_pids=set(),
        our_jobs_per_gpu={},
    )
    assert blocked is None
    overloaded = eligible_gpu(
        [snapshot(utilization=51)],
        estimate=estimate,
        policy=allow,
        our_pids=set(),
        our_jobs_per_gpu={},
    )
    assert overloaded is None


def test_nvidia_smi_probe_parses_foreign_processes() -> None:
    class FakeProbe(NvidiaSmiProbe):
        def _run(self, *arguments: str, allow_failure: bool = False) -> str:
            del allow_failure
            if arguments[0].startswith("--query-gpu"):
                return '2, GPU-shared, "Shared, GPU", 24576, 12000, 12576, 40, 150\n'
            return "99999, GPU-shared, 8000\n"

    observed = FakeProbe().snapshots()

    assert len(observed) == 1
    assert observed[0].name == "Shared, GPU"
    assert observed[0].process_memory_mb == {99_999: 8_000}


def test_default_launcher_accepts_cli_overrides() -> None:
    reference = load_launcher_reference(None, ["params.max_parallel=3"])

    assert reference.type == "core/local-subprocess"
    assert reference.params == {"max_parallel": 3}


def test_worker_captures_framework_native_memory_peak(tmp_path: Path, monkeypatch) -> None:
    cuda = SimpleNamespace(
        is_available=lambda: True,
        max_memory_allocated=lambda: 128 * 1024**2,
        max_memory_reserved=lambda: 192 * 1024**2,
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))

    capture_worker_resources(tmp_path)

    payload = json.loads((tmp_path / "worker-resources.json").read_text(encoding="utf-8"))
    assert payload["cuda_peak_allocated_mb"] == 128
    assert payload["cuda_peak_reserved_mb"] == 192


def make_manifest(name: str = "launch-test"):
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": name},
            "seed": 3,
            "stages": [{"name": "fit", "type": "core/noop"}],
            "resources": {"accelerator": "cpu"},
        }
    )
    registry = load_registry()
    return compile_plan(config, registry).runs[0], registry


def test_resource_profile_drives_historical_memory_estimate(tmp_path: Path) -> None:
    manifest, _registry = make_manifest("history")
    store = RunStore(manifest, root=tmp_path)
    store.prepare()
    status = store.load_status()
    status["state"] = "completed"
    store.save_status(status)
    recorder = ResourceRecorder(
        store.run_dir,
        run_id=manifest.run_id,
        attempt_id="attempt-1",
        worker_pid=123,
        started_epoch=100.0,
        gpu=snapshot(),
        estimate=MemoryEstimate(required_mb=1_024, source="default"),
        expected_interval=1.0,
    )
    recorder.sample(
        replace(snapshot(), process_memory_mb={123: 2_048, 99_999: 8_000}),
        100.0,
    )
    recorder.sample(
        replace(snapshot(), process_memory_mb={123: 3_072, 99_999: 8_000}),
        101.0,
    )
    (store.run_dir / "worker-resources.json").write_text(
        json.dumps(
            {
                "framework": "pytorch",
                "cuda_peak_allocated_mb": 3_200,
                "cuda_peak_reserved_mb": 3_500,
            }
        ),
        encoding="utf-8",
    )
    recorder.finalize(exit_code=0, state="completed", finished_epoch=102.0)

    estimate = estimate_memory(
        manifest,
        tmp_path,
        GpuPolicy(historical_memory_safety_factor=1.25),
    )
    rows = collect_resource_summary(tmp_path)

    assert estimate.source == "history"
    assert estimate.observed_peak_mb == 3_500
    assert estimate.required_mb == 4_375
    assert rows[0]["trial_id"] == manifest.trial_id
    assert rows[0]["process_memory_peak_mb_max"] == 3_072
    assert rows[0]["placement_memory_peak_mb_max"] == 3_500
    resources = json.loads((store.run_dir / "resources.json").read_text(encoding="utf-8"))
    assert resources["attribution"]["exact"][-2:] == [
        "framework_memory_allocated_peak_mb",
        "framework_memory_reserved_peak_mb",
    ]
    assert resources["attribution"]["sampled_process"] == ["process_memory_peak_mb"]
    assert resources["attempts"][0]["foreign_compute_pids"] == [99_999]


def test_local_launcher_executes_cpu_run_in_subprocess(tmp_path: Path) -> None:
    manifest, registry = make_manifest("subprocess")
    plan = compile_plan(manifest.config, registry)
    launcher = LocalSubprocessLauncher(
        LocalLauncherParams(
            max_parallel=1,
            poll_interval_seconds=0.05,
            sample_interval_seconds=0.05,
        ),
        lease_store=GpuLeaseStore(tmp_path / "leases"),
    )

    result = launcher.launch(plan, artifact_root=tmp_path)

    run_dir = tmp_path / manifest.study_id / manifest.run_id
    assert result == {manifest.run_id: 0}
    assert json.loads((run_dir / "status.json").read_text(encoding="utf-8"))["state"] == "completed"
    resources = json.loads((run_dir / "resources.json").read_text(encoding="utf-8"))
    assert resources["total"]["gpu_wall_seconds"] == 0.0
    assert resources["total"]["wall_seconds"] > 0
