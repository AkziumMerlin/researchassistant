from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_assistant.artifacts import RunStore, atomic_write_json, utc_now
from research_assistant.diagnostics import DiagnosticEngine
from research_assistant.errors import LaunchError
from research_assistant.launching import (
    ActiveJob,
    GpuLease,
    GpuSnapshot,
    LocalSubprocessLauncher,
    MemoryEstimate,
    ResourceRecorder,
    _pid_alive,
    eligible_gpu,
    estimate_memory,
)
from research_assistant.planning import Plan, RunManifest


class _NullStream:
    def close(self) -> None:
        return None


@dataclass(slots=True)
class _AdoptedProcess:
    pid: int
    run_dir: Path

    def poll(self) -> int | None:
        if _pid_alive(self.pid):
            return None
        try:
            status = json.loads((self.run_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            status = {}
        return 0 if status.get("state") == "completed" else 1

    def terminate(self) -> None:
        try:
            os.kill(self.pid, 15)
        except (OSError, ProcessLookupError, PermissionError):
            return


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_epoch(value: Any, fallback: float) -> float:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def _process_matches_worker(pid: int, manifest_path: Path) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    arguments = {part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part}
    return "_worker" in arguments and str(manifest_path.resolve()) in arguments


def _gpu_from_launcher(
    launcher: dict[str, Any],
    snapshots: list[GpuSnapshot],
) -> GpuSnapshot | None:
    raw = launcher.get("gpu")
    if not isinstance(raw, dict):
        return None
    uuid = str(raw.get("uuid", ""))
    for snapshot in snapshots:
        if snapshot.uuid == uuid:
            return snapshot
    try:
        index = int(raw.get("index", 0))
    except (TypeError, ValueError):
        index = 0
    return GpuSnapshot(
        index=index,
        uuid=uuid or f"unknown-{index}",
        name=str(raw.get("name", "unknown")),
        memory_total_mb=0.0,
        memory_used_mb=0.0,
        memory_free_mb=0.0,
        utilization_percent=0.0,
    )


def _estimate_from_launcher(launcher: dict[str, Any]) -> MemoryEstimate | None:
    raw = launcher.get("memory_estimate")
    if not isinstance(raw, dict):
        return None
    try:
        required = float(raw.get("required_mb"))
    except (TypeError, ValueError):
        return None
    source = str(raw.get("source", "default"))
    if source not in {"explicit", "history", "default"}:
        source = "default"
    return MemoryEstimate(required_mb=required, source=source)  # type: ignore[arg-type]


def _adopt(
    launcher: LocalSubprocessLauncher,
    manifest: RunManifest,
    store: RunStore,
    snapshots: list[GpuSnapshot],
    now: float,
) -> ActiveJob | None:
    record = _read_mapping(store.run_dir / "launcher.json")
    try:
        pid = int(record.get("worker_pid"))
    except (TypeError, ValueError):
        return None
    if record.get("state") != "running" or not _process_matches_worker(pid, store.manifest_path):
        return None
    gpu = _gpu_from_launcher(record, snapshots)
    estimate = _estimate_from_launcher(record)
    lease: GpuLease | None = None
    if gpu is not None:
        for slot in range(launcher.params.gpu.max_our_jobs_per_gpu):
            lease = launcher.lease_store.acquire(gpu.uuid, slot, manifest.run_id, pid)
            if lease is not None:
                break
    started = _parse_epoch(record.get("started_at"), now)
    attempt_id = str(record.get("attempt_id") or f"adopted-{pid}")
    recorder = ResourceRecorder(
        store.run_dir,
        run_id=manifest.run_id,
        attempt_id=attempt_id,
        worker_pid=pid,
        started_epoch=started,
        gpu=gpu,
        estimate=estimate,
        expected_interval=launcher.params.sample_interval_seconds,
    )
    return ActiveJob(
        manifest=manifest,
        process=_AdoptedProcess(pid, store.run_dir),  # type: ignore[arg-type]
        log_stream=_NullStream(),
        gpu=gpu,
        estimate=estimate,
        recorder=recorder,
        lease=lease,
    )


def _mark_interrupted(root: Path, manifest: RunManifest, reason: str) -> None:
    store = RunStore(manifest, root=root)
    status = store.load_status()
    for stage in status.get("stages", {}).values():
        if isinstance(stage, dict) and stage.get("state") == "running":
            stage.update({"state": "interrupted", "finished_at": utc_now(), "error": reason})
    status.update({"state": "interrupted", "error": reason})
    store.save_status(status)
    store.close()


def _launcher_record(
    root: Path,
    job: ActiveJob,
    *,
    state: str,
    exit_code: int,
    now: float,
) -> None:
    atomic_write_json(
        root / job.manifest.study_id / job.manifest.run_id / "launcher.json",
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


def launch_resilient(
    self: LocalSubprocessLauncher,
    plan: Plan,
    *,
    artifact_root: Path | None = None,
    resume: bool = True,
    on_event: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Launch, adopt, diagnose and optionally retry local workers."""
    emit = on_event or (lambda _message: None)
    root = Path(artifact_root or (plan.runs[0].config.artifacts.root if plan.runs else "runs"))
    root = root.resolve()
    workspace = root.parent
    diagnostics = DiagnosticEngine(workspace)

    try:
        initial_snapshots = self.probe.snapshots() if any(
            run.config.resources.accelerator != "cpu" for run in plan.runs
        ) else []
    except LaunchError:
        initial_snapshots = []

    pending: list[tuple[RunManifest, RunStore]] = []
    active: list[ActiveJob] = []
    for manifest in plan.runs:
        store = RunStore(manifest, root=root)
        store.prepare()
        status = store.load_status()
        if resume and status.get("state") == "completed":
            emit(f"skip completed run {manifest.run_id}")
            store.close()
            continue
        adopted = _adopt(self, manifest, store, initial_snapshots, self.clock())
        if adopted is not None:
            active.append(adopted)
            store.close()
            emit(f"adopt run {manifest.run_id} pid={adopted.process.pid}")
        else:
            pending.append((manifest, store))

    results: dict[str, int] = {}
    requested_actions: dict[str, str] = {}
    stop_scheduling = False
    next_sample = 0.0
    snapshots = initial_snapshots
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
                snapshot = snapshot_by_uuid.get(job.gpu.uuid) if job.gpu is not None else None
                if snapshot is not None:
                    job.recorder.sample(snapshot, now)
                findings = diagnostics.check(
                    run_id=job.manifest.run_id,
                    run_dir=root / job.manifest.study_id / job.manifest.run_id,
                    worker_pid=job.process.pid,
                    now=now,
                    gpu_utilization_percent=(snapshot.utilization_percent if snapshot else None),
                )
                chosen: str | None = None
                for finding in findings:
                    action = diagnostics.apply(
                        finding,
                        run_id=job.manifest.run_id,
                        run_dir=root / job.manifest.study_id / job.manifest.run_id,
                        worker_pid=job.process.pid,
                    )
                    emit(
                        f"diagnostic run {job.manifest.run_id} code={finding.code} action={action}"
                    )
                    if action == "retry":
                        chosen = "retry"
                    elif action == "terminate" and chosen is None:
                        chosen = "terminate"
                if chosen:
                    requested_actions[job.manifest.run_id] = chosen
            next_sample = now + min(
                self.params.sample_interval_seconds,
                diagnostics.policy.check_interval_seconds,
            )

        for job in list(active):
            exit_code = job.process.poll()
            if exit_code is None:
                continue
            active.remove(job)
            job.log_stream.close()
            if job.lease is not None:
                job.lease.release()
            run_dir = root / job.manifest.study_id / job.manifest.run_id
            action = requested_actions.pop(job.manifest.run_id, None)
            oom = diagnostics.classify_exit(
                run_id=job.manifest.run_id,
                run_dir=run_dir,
                exit_code=exit_code,
            )
            if oom is not None:
                diagnostics.record(run_dir, oom, run_id=job.manifest.run_id)
                action = oom.action
            status = _read_mapping(run_dir / "status.json")
            state = str(status.get("state", "failed"))
            diagnostics.state(job.manifest.run_id).retry_count = max(
                diagnostics.state(job.manifest.run_id).retry_count,
                max(0, int(status.get("attempt", 1)) - 1),
            )
            retry = action == "retry" and diagnostics.can_retry(job.manifest.run_id)
            if retry:
                count = diagnostics.mark_retry(job.manifest.run_id)
                reason_code = oom.code if oom else "diagnostic intervention"
                reason = f"automatic retry {count}: {reason_code}"
                _mark_interrupted(root, job.manifest, reason)
                state = "interrupted"
            elif action == "terminate" and state not in {"completed", "failed", "interrupted"}:
                _mark_interrupted(root, job.manifest, "terminated by diagnostic policy")
                state = "interrupted"
            job.recorder.finalize(exit_code=exit_code, state=state, finished_epoch=now)
            _launcher_record(root, job, state=state, exit_code=exit_code, now=now)
            if retry:
                replacement = RunStore(job.manifest, root=root)
                replacement.prepare()
                pending.append((job.manifest, replacement))
                emit(f"retry run {job.manifest.run_id} after diagnostic intervention")
                continue
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
                if job.gpu is None:
                    continue
                jobs_per_gpu[job.gpu.uuid] = jobs_per_gpu.get(job.gpu.uuid, 0) + 1
                current = next(
                    (snapshot for snapshot in snapshots if snapshot.uuid == job.gpu.uuid), None
                )
                if current is None or job.process.pid not in current.compute_pids:
                    reserved[job.gpu.uuid] = reserved.get(job.gpu.uuid, 0.0) + (
                        job.estimate.required_mb if job.estimate else 0.0
                    )
            selected_index: int | None = None
            selected_gpu: GpuSnapshot | None = None
            selected_estimate: MemoryEstimate | None = None
            for index, (manifest, _store) in enumerate(pending):
                accelerator = manifest.config.resources.accelerator
                if accelerator == "cpu" or (accelerator == "auto" and not snapshots):
                    selected_index = index
                    break
                if manifest.config.resources.devices != 1:
                    raise LaunchError("the local GPU launcher currently supports one GPU per run")
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

    for manifest, store in pending:
        results[manifest.run_id] = 1
        store.close()
    return results
