from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_assistant.artifacts import RunStore, atomic_write_json, utc_now
from research_assistant.config import apply_overrides
from research_assistant.errors import ConfigError, LaunchError
from research_assistant.models import ComponentRef
from research_assistant.planning import Plan, RunManifest
from research_assistant.registry import Registry


class GpuPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    devices: list[int] | None = None
    min_free_memory_gb: float = Field(default=0.0, ge=0)
    reserve_memory_gb: float = Field(default=0.5, ge=0)
    default_required_memory_gb: float = Field(default=1.0, ge=0)
    max_utilization_percent: float = Field(default=90.0, ge=0, le=100)
    foreign_processes: Literal["allow", "block"] = "allow"
    max_our_jobs_per_gpu: int = Field(default=1, ge=1)
    historical_memory_safety_factor: float = Field(default=1.2, ge=1)


class LocalLauncherParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_parallel: int = Field(default=1, ge=1)
    poll_interval_seconds: float = Field(default=2.0, ge=0.05)
    sample_interval_seconds: float = Field(default=2.0, ge=0.05)
    fail_fast: bool = False
    gpu: GpuPolicy = Field(default_factory=GpuPolicy)


class LauncherDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    type: str = "core/local-subprocess"
    params: dict[str, Any] = Field(default_factory=dict)

    def reference(self) -> ComponentRef:
        return ComponentRef(type=self.type, params=self.params)


@dataclass(frozen=True, slots=True)
class GpuSnapshot:
    index: int
    uuid: str
    name: str
    memory_total_mb: float
    memory_used_mb: float
    memory_free_mb: float
    utilization_percent: float
    power_watts: float | None = None
    process_memory_mb: Mapping[int, float] = field(default_factory=dict)

    @property
    def compute_pids(self) -> frozenset[int]:
        return frozenset(self.process_memory_mb)


class GpuProbe(Protocol):
    def snapshots(self) -> list[GpuSnapshot]: ...


def _optional_float(value: str) -> float | None:
    normalized = value.strip()
    if not normalized or normalized.lower() in {"n/a", "[n/a]", "not supported"}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


class NvidiaSmiProbe:
    """Read scheduling and telemetry data from the driver-provided nvidia-smi CLI."""

    def __init__(self, executable: str = "nvidia-smi", timeout_seconds: float = 5.0) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def _run(self, *arguments: str, allow_failure: bool = False) -> str:
        try:
            completed = subprocess.run(
                [self.executable, *arguments],
                check=not allow_failure,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise LaunchError("nvidia-smi was not found; cannot schedule CUDA runs") from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise LaunchError(f"nvidia-smi query failed: {exc}") from exc
        return completed.stdout if completed.returncode == 0 else ""

    def snapshots(self) -> list[GpuSnapshot]:
        output = self._run(
            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu,power.draw",
            "--format=csv,noheader,nounits",
        )
        rows = list(csv.reader(output.splitlines(), skipinitialspace=True))
        process_output = self._run(
            "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
            "--format=csv,noheader,nounits",
            allow_failure=True,
        )
        processes: dict[str, dict[int, float]] = {}
        for row in csv.reader(process_output.splitlines(), skipinitialspace=True):
            if len(row) < 3:
                continue
            try:
                pid = int(row[0].strip())
            except ValueError:
                continue
            memory = _optional_float(row[2])
            if memory is not None:
                processes.setdefault(row[1].strip(), {})[pid] = memory

        snapshots: list[GpuSnapshot] = []
        for row in rows:
            if len(row) < 8:
                raise LaunchError(f"unexpected nvidia-smi GPU row: {row!r}")
            power = _optional_float(row[7])
            snapshots.append(
                GpuSnapshot(
                    index=int(row[0].strip()),
                    uuid=row[1].strip(),
                    name=row[2].strip(),
                    memory_total_mb=float(row[3]),
                    memory_used_mb=float(row[4]),
                    memory_free_mb=float(row[5]),
                    utilization_percent=float(row[6]),
                    power_watts=power,
                    process_memory_mb=processes.get(row[1].strip(), {}),
                )
            )
        return snapshots


@dataclass(frozen=True, slots=True)
class MemoryEstimate:
    required_mb: float
    source: Literal["explicit", "history", "default"]
    observed_peak_mb: float | None = None


def _completed_historical_peaks(root: Path, trial_id: str) -> list[float]:
    peaks: list[float] = []
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        run_dir = manifest_path.parent
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            resources = json.loads((run_dir / "resources.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if manifest.get("trial_id") != trial_id or status.get("state") != "completed":
            continue
        total = resources.get("total") or {}
        raw_peak = total.get("placement_memory_peak_mb", total.get("process_memory_peak_mb"))
        try:
            peak = float(raw_peak)
        except (TypeError, ValueError):
            continue
        if math.isfinite(peak) and peak > 0:
            peaks.append(peak)
    return peaks


def estimate_memory(manifest: RunManifest, history_root: Path, policy: GpuPolicy) -> MemoryEstimate:
    if manifest.config.resources.memory_gb is not None:
        return MemoryEstimate(
            required_mb=manifest.config.resources.memory_gb * 1024,
            source="explicit",
        )
    historical = _completed_historical_peaks(history_root, manifest.trial_id)
    if historical:
        observed = max(historical)
        return MemoryEstimate(
            required_mb=observed * policy.historical_memory_safety_factor,
            source="history",
            observed_peak_mb=observed,
        )
    return MemoryEstimate(required_mb=policy.default_required_memory_gb * 1024, source="default")


def eligible_gpu(
    snapshots: Sequence[GpuSnapshot],
    *,
    estimate: MemoryEstimate,
    policy: GpuPolicy,
    our_pids: set[int],
    our_jobs_per_gpu: Mapping[str, int],
    reserved_memory_mb: Mapping[str, float] | None = None,
) -> GpuSnapshot | None:
    allowed = set(policy.devices) if policy.devices is not None else None
    reserved_memory_mb = reserved_memory_mb or {}
    minimum_free = max(
        policy.min_free_memory_gb * 1024,
        estimate.required_mb + policy.reserve_memory_gb * 1024,
    )
    candidates: list[GpuSnapshot] = []
    for snapshot in snapshots:
        if allowed is not None and snapshot.index not in allowed:
            continue
        if our_jobs_per_gpu.get(snapshot.uuid, 0) >= policy.max_our_jobs_per_gpu:
            continue
        effective_free = snapshot.memory_free_mb - reserved_memory_mb.get(snapshot.uuid, 0.0)
        if effective_free < minimum_free:
            continue
        if snapshot.utilization_percent > policy.max_utilization_percent:
            continue
        foreign = snapshot.compute_pids - our_pids
        if policy.foreign_processes == "block" and foreign:
            continue
        candidates.append(snapshot)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.utilization_percent,
            item.memory_free_mb - estimate.required_mb,
            item.index,
        ),
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class GpuLease:
    def __init__(self, path: Path, run_id: str, worker_pid: int) -> None:
        self.path = path
        self.run_id = run_id
        self.worker_pid = worker_pid

    def bind_worker(self, worker_pid: int) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise LaunchError(f"cannot update GPU lease {self.path}") from exc
        if payload.get("run_id") != self.run_id or payload.get("worker_pid") != self.worker_pid:
            raise LaunchError(f"GPU lease changed while starting run {self.run_id}")
        payload["worker_pid"] = worker_pid
        payload["bound_at"] = utc_now()
        atomic_write_json(self.path, payload)
        self.worker_pid = worker_pid

    def release(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if payload.get("run_id") == self.run_id and payload.get("worker_pid") == self.worker_pid:
            self.path.unlink(missing_ok=True)


class GpuLeaseStore:
    def __init__(self, root: Path | None = None) -> None:
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
        self.root = root or runtime / "research-assistant" / "gpu-leases"

    def acquire(self, gpu_uuid: str, slot: int, run_id: str, worker_pid: int) -> GpuLease | None:
        self.root.mkdir(parents=True, exist_ok=True)
        safe_uuid = "".join(character if character.isalnum() else "-" for character in gpu_uuid)
        path = self.root / f"{safe_uuid}.{slot}.json"
        payload = {
            "run_id": run_id,
            "worker_pid": worker_pid,
            "scheduler_pid": os.getpid(),
            "created_at": utc_now(),
        }
        for _ in range(2):
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    existing_pid = int(existing["worker_pid"])
                except (OSError, ValueError, TypeError, KeyError):
                    path.unlink(missing_ok=True)
                    continue
                if existing.get("run_id") == run_id and existing_pid == worker_pid:
                    return GpuLease(path, run_id, worker_pid)
                if not _pid_alive(existing_pid):
                    path.unlink(missing_ok=True)
                    continue
                return None
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, sort_keys=True)
                    stream.write("\n")
                return GpuLease(path, run_id, worker_pid)
        return None


class ResourceRecorder:
    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str,
        attempt_id: str,
        worker_pid: int,
        started_epoch: float,
        gpu: GpuSnapshot | None,
        estimate: MemoryEstimate | None,
        expected_interval: float,
    ) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.worker_pid = worker_pid
        self.started_epoch = started_epoch
        self.gpu = gpu
        self.estimate = estimate
        self.expected_interval = expected_interval
        self.samples = 0
        self.process_memory_peak_mb = 0.0
        self.device_memory_peak_mb = 0.0
        self.device_active_seconds = 0.0
        self.device_energy_joules = 0.0
        self.telemetry_gap_seconds = 0.0
        self.foreign_pids: set[int] = set()
        self.last_timestamp: float | None = None
        self.last_utilization = 0.0
        self.last_power: float | None = None

    def sample(self, snapshot: GpuSnapshot, timestamp: float) -> None:
        if self.last_timestamp is not None:
            raw_delta = max(0.0, timestamp - self.last_timestamp)
            measured_delta = min(raw_delta, self.expected_interval * 3)
            self.telemetry_gap_seconds += raw_delta - measured_delta
            self.device_active_seconds += measured_delta * self.last_utilization / 100
            if self.last_power is not None:
                self.device_energy_joules += measured_delta * self.last_power
        process_memory = float(snapshot.process_memory_mb.get(self.worker_pid, 0.0))
        foreign = snapshot.compute_pids - {self.worker_pid}
        self.samples += 1
        self.process_memory_peak_mb = max(self.process_memory_peak_mb, process_memory)
        self.device_memory_peak_mb = max(self.device_memory_peak_mb, snapshot.memory_used_mb)
        self.foreign_pids.update(foreign)
        self.last_timestamp = timestamp
        self.last_utilization = snapshot.utilization_percent
        self.last_power = snapshot.power_watts
        event = {
            "schema_version": 1,
            "timestamp": datetime.fromtimestamp(timestamp, UTC).isoformat(),
            "timestamp_epoch": timestamp,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "worker_pid": self.worker_pid,
            "gpu_uuid": snapshot.uuid,
            "gpu_index": snapshot.index,
            "device_utilization_percent": snapshot.utilization_percent,
            "device_memory_used_mb": snapshot.memory_used_mb,
            "device_memory_free_mb": snapshot.memory_free_mb,
            "process_memory_mb": process_memory,
            "power_watts": snapshot.power_watts,
            "foreign_compute_pids": sorted(foreign),
        }
        with (self.run_dir / "resource-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    def finalize(self, *, exit_code: int, state: str, finished_epoch: float) -> dict[str, Any]:
        gpu_wall_seconds = max(0.0, finished_epoch - self.started_epoch) if self.gpu else 0.0
        try:
            worker_resources = json.loads(
                (self.run_dir / "worker-resources.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            worker_resources = {}
        framework_allocated_peak = float(worker_resources.get("cuda_peak_allocated_mb", 0.0))
        framework_reserved_peak = float(worker_resources.get("cuda_peak_reserved_mb", 0.0))
        placement_memory_peak = max(self.process_memory_peak_mb, framework_reserved_peak)
        attempt = {
            "attempt_id": self.attempt_id,
            "started_at": datetime.fromtimestamp(self.started_epoch, UTC).isoformat(),
            "finished_at": datetime.fromtimestamp(finished_epoch, UTC).isoformat(),
            "state": state,
            "exit_code": exit_code,
            "worker_pid": self.worker_pid,
            "wall_seconds": max(0.0, finished_epoch - self.started_epoch),
            "gpu_wall_seconds": gpu_wall_seconds,
            "samples": self.samples,
            "process_memory_peak_mb": self.process_memory_peak_mb,
            "framework_memory_allocated_peak_mb": framework_allocated_peak,
            "framework_memory_reserved_peak_mb": framework_reserved_peak,
            "placement_memory_peak_mb": placement_memory_peak,
            "device_memory_peak_mb": self.device_memory_peak_mb,
            "device_active_seconds": self.device_active_seconds,
            "device_energy_joules": self.device_energy_joules,
            "telemetry_gap_seconds": self.telemetry_gap_seconds,
            "foreign_compute_pids": sorted(self.foreign_pids),
            "gpu": (
                {
                    "index": self.gpu.index,
                    "uuid": self.gpu.uuid,
                    "name": self.gpu.name,
                    "memory_total_mb": self.gpu.memory_total_mb,
                }
                if self.gpu
                else None
            ),
            "memory_estimate": (
                {
                    "required_mb": self.estimate.required_mb,
                    "source": self.estimate.source,
                    "observed_peak_mb": self.estimate.observed_peak_mb,
                }
                if self.estimate
                else None
            ),
        }
        resources_path = self.run_dir / "resources.json"
        try:
            existing = json.loads(resources_path.read_text(encoding="utf-8"))
            attempts = list(existing.get("attempts") or [])
        except (OSError, ValueError, TypeError):
            attempts = []
        attempts = [item for item in attempts if item.get("attempt_id") != self.attempt_id]
        attempts.append(attempt)
        total = {
            "attempts": len(attempts),
            "wall_seconds": sum(float(item.get("wall_seconds", 0)) for item in attempts),
            "gpu_wall_seconds": sum(float(item.get("gpu_wall_seconds", 0)) for item in attempts),
            "process_memory_peak_mb": max(
                (float(item.get("process_memory_peak_mb", 0)) for item in attempts), default=0.0
            ),
            "framework_memory_allocated_peak_mb": max(
                (
                    float(item.get("framework_memory_allocated_peak_mb", 0))
                    for item in attempts
                ),
                default=0.0,
            ),
            "framework_memory_reserved_peak_mb": max(
                (
                    float(item.get("framework_memory_reserved_peak_mb", 0))
                    for item in attempts
                ),
                default=0.0,
            ),
            "placement_memory_peak_mb": max(
                (float(item.get("placement_memory_peak_mb", 0)) for item in attempts),
                default=0.0,
            ),
            "device_memory_peak_mb": max(
                (float(item.get("device_memory_peak_mb", 0)) for item in attempts), default=0.0
            ),
            "device_active_seconds": sum(
                float(item.get("device_active_seconds", 0)) for item in attempts
            ),
            "device_energy_joules": sum(
                float(item.get("device_energy_joules", 0)) for item in attempts
            ),
            "telemetry_gap_seconds": sum(
                float(item.get("telemetry_gap_seconds", 0)) for item in attempts
            ),
        }
        payload = {
            "schema_version": 1,
            "run_id": self.run_id,
            "updated_at": utc_now(),
            "attribution": {
                "exact": [
                    "wall_seconds",
                    "gpu_wall_seconds",
                    "framework_memory_allocated_peak_mb",
                    "framework_memory_reserved_peak_mb",
                ],
                "sampled_process": ["process_memory_peak_mb"],
                "device_wide": [
                    "device_memory_peak_mb",
                    "device_active_seconds",
                    "device_energy_joules",
                ],
            },
            "attempts": attempts,
            "total": total,
        }
        atomic_write_json(resources_path, payload)
        return payload


def capture_worker_resources(run_dir: Path) -> None:
    """Persist framework-native high-water marks without importing an optional framework."""
    torch = sys.modules.get("torch")
    if torch is None:
        return
    try:
        if not torch.cuda.is_available():
            return
        payload = {
            "schema_version": 1,
            "captured_at": utc_now(),
            "framework": "pytorch",
            "cuda_peak_allocated_mb": torch.cuda.max_memory_allocated() / (1024**2),
            "cuda_peak_reserved_mb": torch.cuda.max_memory_reserved() / (1024**2),
        }
    except (AttributeError, RuntimeError):
        return
    atomic_write_json(run_dir / "worker-resources.json", payload)


@dataclass(slots=True)
class ActiveJob:
    manifest: RunManifest
    process: subprocess.Popen[str]
    log_stream: Any
    gpu: GpuSnapshot | None
    estimate: MemoryEstimate | None
    recorder: ResourceRecorder
    lease: GpuLease | None


class LocalSubprocessLauncher:
    def __init__(
        self,
        params: LocalLauncherParams,
        *,
        probe: GpuProbe | None = None,
        lease_store: GpuLeaseStore | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.params = params
        self.probe = probe or NvidiaSmiProbe()
        self.lease_store = lease_store or GpuLeaseStore()
        self.clock = clock
        self.sleeper = sleeper

    def _start(
        self,
        manifest: RunManifest,
        store: RunStore,
        *,
        gpu: GpuSnapshot | None,
        estimate: MemoryEstimate | None,
        resume: bool,
    ) -> ActiveJob:
        lease = None
        if gpu is not None:
            for slot in range(self.params.gpu.max_our_jobs_per_gpu):
                lease = self.lease_store.acquire(gpu.uuid, slot, manifest.run_id, os.getpid())
                if lease is not None:
                    break
            if lease is None:
                raise LaunchError(
                    f"could not acquire a ResearchAssistant lease for GPU {gpu.index}"
                )
        log_path = store.run_dir / "worker.log"
        log_stream = log_path.open("a", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "research_assistant",
            "_worker",
            str(store.manifest_path.resolve()),
        ]
        if not resume:
            command.append("--no-resume")
        environment = os.environ.copy()
        if gpu is not None:
            environment["CUDA_VISIBLE_DEVICES"] = str(gpu.index)
        else:
            environment.pop("CUDA_VISIBLE_DEVICES", None)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
                env=environment,
                start_new_session=True,
            )
            if lease is not None:
                lease.bind_worker(process.pid)
        except BaseException:
            if process is not None:
                process.terminate()
            log_stream.close()
            if lease is not None:
                lease.release()
            raise
        started_epoch = self.clock()
        attempt_id = uuid4().hex
        atomic_write_json(
            store.run_dir / "launcher.json",
            {
                "schema_version": 1,
                "state": "running",
                "run_id": manifest.run_id,
                "attempt_id": attempt_id,
                "worker_pid": process.pid,
                "started_at": datetime.fromtimestamp(started_epoch, UTC).isoformat(),
                "gpu": (
                    {"index": gpu.index, "uuid": gpu.uuid, "name": gpu.name} if gpu else None
                ),
                "memory_estimate": (
                    {"required_mb": estimate.required_mb, "source": estimate.source}
                    if estimate
                    else None
                ),
            },
        )
        recorder = ResourceRecorder(
            store.run_dir,
            run_id=manifest.run_id,
            attempt_id=attempt_id,
            worker_pid=process.pid,
            started_epoch=started_epoch,
            gpu=gpu,
            estimate=estimate,
            expected_interval=self.params.sample_interval_seconds,
        )
        return ActiveJob(manifest, process, log_stream, gpu, estimate, recorder, lease)

    def launch(
        self,
        plan: Plan,
        *,
        artifact_root: Path | None = None,
        resume: bool = True,
        on_event: Callable[[str], None] | None = None,
    ) -> dict[str, int]:
        emit = on_event or (lambda _message: None)
        root = (
            Path(artifact_root or plan.runs[0].config.artifacts.root)
            if plan.runs
            else Path("runs")
        )
        pending: list[tuple[RunManifest, RunStore]] = []
        for manifest in plan.runs:
            store = RunStore(manifest, root=root)
            store.prepare()
            if resume and store.load_status().get("state") == "completed":
                emit(f"skip completed run {manifest.run_id}")
                continue
            pending.append((manifest, store))

        active: list[ActiveJob] = []
        results: dict[str, int] = {}
        stop_scheduling = False
        next_sample = 0.0
        snapshots: list[GpuSnapshot] = []
        while pending or active:
            now = self.clock()
            needs_gpu = any(
                manifest.config.resources.accelerator != "cpu" for manifest, _store in pending
            ) or any(job.gpu is not None for job in active)
            if needs_gpu and now >= next_sample:
                try:
                    snapshots = self.probe.snapshots()
                except LaunchError:
                    if any(
                        manifest.config.resources.accelerator == "cuda"
                        for manifest, _store in pending
                    ):
                        raise
                    snapshots = []
                snapshot_by_uuid = {snapshot.uuid: snapshot for snapshot in snapshots}
                for job in active:
                    if job.gpu is not None and job.gpu.uuid in snapshot_by_uuid:
                        job.recorder.sample(snapshot_by_uuid[job.gpu.uuid], now)
                next_sample = now + self.params.sample_interval_seconds

            for job in list(active):
                exit_code = job.process.poll()
                if exit_code is None:
                    continue
                active.remove(job)
                job.log_stream.close()
                if job.lease is not None:
                    job.lease.release()
                status = RunStore(job.manifest, root=root).load_status()
                state = str(status.get("state", "failed"))
                job.recorder.finalize(exit_code=exit_code, state=state, finished_epoch=now)
                launcher_path = root / job.manifest.study_id / job.manifest.run_id / "launcher.json"
                atomic_write_json(
                    launcher_path,
                    {
                        "schema_version": 1,
                        "state": state,
                        "run_id": job.manifest.run_id,
                        "attempt_id": job.recorder.attempt_id,
                        "worker_pid": job.process.pid,
                        "finished_at": datetime.fromtimestamp(now, UTC).isoformat(),
                        "exit_code": exit_code,
                    },
                )
                results[job.manifest.run_id] = exit_code
                emit(f"finish run {job.manifest.run_id} state={state} exit={exit_code}")
                if exit_code != 0 and self.params.fail_fast:
                    stop_scheduling = True

            made_progress = False
            while pending and len(active) < self.params.max_parallel and not stop_scheduling:
                our_pids = {job.process.pid for job in active}
                jobs_per_gpu: dict[str, int] = {}
                reserved: dict[str, float] = {}
                for job in active:
                    if job.gpu is not None:
                        jobs_per_gpu[job.gpu.uuid] = jobs_per_gpu.get(job.gpu.uuid, 0) + 1
                        current = next(
                            (
                                snapshot
                                for snapshot in snapshots
                                if snapshot.uuid == job.gpu.uuid
                            ),
                            None,
                        )
                        if current is None or job.process.pid not in current.compute_pids:
                            reserved[job.gpu.uuid] = reserved.get(job.gpu.uuid, 0.0) + (
                                job.estimate.required_mb if job.estimate else 0.0
                            )
                selected_index = None
                selected_gpu = None
                selected_estimate = None
                for index, (manifest, _store) in enumerate(pending):
                    accelerator = manifest.config.resources.accelerator
                    if accelerator == "cpu" or (accelerator == "auto" and not snapshots):
                        selected_index = index
                        break
                    if manifest.config.resources.devices != 1:
                        raise LaunchError(
                            "the local GPU launcher currently supports one GPU per run"
                        )
                    estimate = estimate_memory(manifest, root, self.params.gpu)
                    candidate = eligible_gpu(
                        snapshots,
                        estimate=estimate,
                        policy=self.params.gpu,
                        our_pids=our_pids,
                        our_jobs_per_gpu=jobs_per_gpu,
                        reserved_memory_mb=reserved,
                    )
                    if candidate is not None:
                        selected_index = index
                        selected_gpu = candidate
                        selected_estimate = estimate
                        break
                if selected_index is None:
                    break
                manifest, store = pending.pop(selected_index)
                job = self._start(
                    manifest,
                    store,
                    gpu=selected_gpu,
                    estimate=selected_estimate,
                    resume=resume,
                )
                active.append(job)
                made_progress = True
                if selected_gpu is None:
                    emit(f"start run {manifest.run_id} on cpu pid={job.process.pid}")
                else:
                    emit(
                        f"start run {manifest.run_id} on gpu={selected_gpu.index} "
                        f"pid={job.process.pid} required={selected_estimate.required_mb:.0f}MiB "
                        f"source={selected_estimate.source}"
                    )

            if stop_scheduling and not active:
                break
            if (pending or active) and not made_progress:
                self.sleeper(self.params.poll_interval_seconds)

        for manifest, _store in pending:
            results[manifest.run_id] = 1
        return results


def load_launcher_reference(path: Path | None, overrides: list[str] | None = None) -> ComponentRef:
    if path is None:
        document: Any = {"version": 1, "type": "core/local-subprocess", "params": {}}
    else:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"cannot read launcher config {path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid launcher YAML in {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("launcher config root must be a mapping")
    document = apply_overrides(document, overrides or [])
    try:
        return LauncherDocument.model_validate(document).reference()
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def build_local_launcher(params: LocalLauncherParams, _context: Any) -> LocalSubprocessLauncher:
    return LocalSubprocessLauncher(params)


def register(registry: Registry) -> None:
    registry.add(
        "launcher",
        "core/local-subprocess",
        factory=build_local_launcher,
        schema=LocalLauncherParams,
        description="Schedule isolated local subprocesses across shared NVIDIA GPUs.",
        provider="research-assistant",
    )
