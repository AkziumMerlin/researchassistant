from __future__ import annotations

import json
import math
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from research_assistant.artifacts import atomic_write_json, utc_now

DiagnosticAction = Literal["warn", "terminate", "retry"]


class DiagnosticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    check_interval_seconds: float = Field(default=20.0, ge=1.0)
    warmup_seconds: float = Field(default=120.0, ge=0.0)
    metric_stall_seconds: float = Field(default=900.0, ge=10.0)
    gpu_idle_seconds: float = Field(default=300.0, ge=10.0)
    gpu_utilization_floor_percent: float = Field(default=1.0, ge=0.0, le=100.0)
    divergence_window: int = Field(default=5, ge=3, le=100)
    divergence_factor: float = Field(default=50.0, ge=1.1)
    max_automatic_retries: int = Field(default=1, ge=0, le=20)
    on_metric_stall: DiagnosticAction = "warn"
    on_gpu_idle: DiagnosticAction = "warn"
    on_divergence: DiagnosticAction = "terminate"
    on_oom: DiagnosticAction = "retry"
    metric_names: list[str] = Field(
        default_factory=lambda: ["loss", "error", "rel_l2"],
        max_length=50,
    )


def load_diagnostic_policy(workspace: Path) -> DiagnosticPolicy:
    configured = os.environ.get("RA_DIAGNOSTICS_CONFIG")
    path = Path(configured).expanduser() if configured else workspace / ".ra" / "diagnostics.yaml"
    if not path.is_file():
        return DiagnosticPolicy()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return DiagnosticPolicy()
    if not isinstance(payload, dict):
        return DiagnosticPolicy()
    try:
        return DiagnosticPolicy.model_validate(payload)
    except ValueError:
        return DiagnosticPolicy()


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    code: str
    severity: Literal["warning", "error"]
    message: str
    action: DiagnosticAction
    observed: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, run_id: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "timestamp": utc_now(),
            "run_id": run_id,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "action": self.action,
            "observed": self.observed,
        }


@dataclass(slots=True)
class RunDiagnosticState:
    last_check: float = 0.0
    idle_since: float | None = None
    emitted: dict[str, float] = field(default_factory=dict)
    retry_count: int = 0


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _tail(path: Path, limit: int = 512 * 1024) -> bytes:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read()
    except OSError:
        return b""


def _metric_events(path: Path, limit: int = 256) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in _tail(path).splitlines()[-limit:]:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _metric_age(run_dir: Path, now: float) -> float | None:
    path = run_dir / "metrics.jsonl"
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return None


def _started_epoch(run_dir: Path) -> float | None:
    try:
        launcher = json.loads((run_dir / "launcher.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return _parse_timestamp(launcher.get("started_at"))


def _divergent_metric(
    events: list[dict[str, Any]],
    policy: DiagnosticPolicy,
) -> tuple[str, float, float] | None:
    grouped: dict[str, list[float]] = {}
    for event in events:
        name = str(event.get("metric", ""))
        if not any(token.lower() in name.lower() for token in policy.metric_names):
            continue
        try:
            value = float(event["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            grouped.setdefault(name, []).append(value)
    for name, values in grouped.items():
        if len(values) < policy.divergence_window:
            continue
        window = values[-policy.divergence_window :]
        reference = min(abs(value) for value in values[:-1] if value != 0) if any(
            value != 0 for value in values[:-1]
        ) else 0.0
        latest = abs(window[-1])
        if reference > 0 and latest > reference * policy.divergence_factor:
            return name, latest, reference
    return None


def _oom_in_log(run_dir: Path) -> bool:
    text = _tail(run_dir / "worker.log", 256 * 1024).decode("utf-8", errors="ignore").lower()
    tokens = (
        "cuda out of memory",
        "outofmemoryerror",
        "cudnn_status_alloc_failed",
        "hip out of memory",
    )
    return any(token in text for token in tokens)


def _terminate_group(pid: int) -> None:
    if pid <= 1 or pid == os.getpid():
        return
    try:
        group = os.getpgid(pid)
    except (OSError, ProcessLookupError):
        group = None
    try:
        if group == pid:
            os.killpg(group, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError, PermissionError):
        return


class DiagnosticEngine:
    """Detect run pathologies and persist auditable interventions."""

    def __init__(self, workspace: Path, policy: DiagnosticPolicy | None = None) -> None:
        self.workspace = workspace.resolve()
        self.policy = policy or load_diagnostic_policy(self.workspace)
        self.states: dict[str, RunDiagnosticState] = {}

    def state(self, run_id: str) -> RunDiagnosticState:
        return self.states.setdefault(run_id, RunDiagnosticState())

    def check(
        self,
        *,
        run_id: str,
        run_dir: Path,
        worker_pid: int,
        now: float,
        gpu_utilization_percent: float | None,
    ) -> list[DiagnosticFinding]:
        if not self.policy.enabled:
            return []
        state = self.state(run_id)
        if now - state.last_check < self.policy.check_interval_seconds:
            return []
        state.last_check = now
        started = _started_epoch(run_dir)
        age = now - started if started is not None else None
        if age is not None and age < self.policy.warmup_seconds:
            return []

        findings: list[DiagnosticFinding] = []
        metric_age = _metric_age(run_dir, now)
        stalled_for = metric_age if metric_age is not None else age
        if stalled_for is not None and stalled_for >= self.policy.metric_stall_seconds:
            findings.append(
                DiagnosticFinding(
                    code="metric-stall",
                    severity="warning",
                    message=(
                        f"no new metric event for {stalled_for:.0f}s"
                        if metric_age is not None
                        else f"worker emitted no metric event for {stalled_for:.0f}s"
                    ),
                    action=self.policy.on_metric_stall,
                    observed={
                        "seconds": stalled_for,
                        "metrics_file_exists": metric_age is not None,
                    },
                )
            )

        if gpu_utilization_percent is not None:
            if gpu_utilization_percent <= self.policy.gpu_utilization_floor_percent:
                state.idle_since = state.idle_since or now
                idle_seconds = now - state.idle_since
                if idle_seconds >= self.policy.gpu_idle_seconds:
                    findings.append(
                        DiagnosticFinding(
                            code="gpu-idle",
                            severity="warning",
                            message=(
                                f"GPU utilization stayed at or below "
                                f"{self.policy.gpu_utilization_floor_percent:g}% for "
                                f"{idle_seconds:.0f}s"
                            ),
                            action=self.policy.on_gpu_idle,
                            observed={
                                "seconds": idle_seconds,
                                "utilization_percent": gpu_utilization_percent,
                            },
                        )
                    )
            else:
                state.idle_since = None

        divergence = _divergent_metric(_metric_events(run_dir / "metrics.jsonl"), self.policy)
        if divergence is not None:
            name, latest, reference = divergence
            findings.append(
                DiagnosticFinding(
                    code="metric-divergence",
                    severity="error",
                    message=f"{name} increased by more than {self.policy.divergence_factor:g}x",
                    action=self.policy.on_divergence,
                    observed={"metric": name, "latest": latest, "reference": reference},
                )
            )
        return self._deduplicate(run_id, findings, now)

    def classify_exit(
        self,
        *,
        run_id: str,
        run_dir: Path,
        exit_code: int,
    ) -> DiagnosticFinding | None:
        if exit_code == 0 or not self.policy.enabled or not _oom_in_log(run_dir):
            return None
        finding = DiagnosticFinding(
            code="out-of-memory",
            severity="error",
            message="worker log contains a GPU out-of-memory signature",
            action=self.policy.on_oom,
            observed={"exit_code": exit_code},
        )
        rows = self._deduplicate(run_id, [finding], time.time(), repeat_after=0.0)
        return rows[0] if rows else None

    def _deduplicate(
        self,
        run_id: str,
        findings: list[DiagnosticFinding],
        now: float,
        *,
        repeat_after: float = 300.0,
    ) -> list[DiagnosticFinding]:
        state = self.state(run_id)
        result: list[DiagnosticFinding] = []
        for finding in findings:
            previous = state.emitted.get(finding.code)
            if previous is not None and now - previous < repeat_after:
                continue
            state.emitted[finding.code] = now
            result.append(finding)
        return result

    def record(self, run_dir: Path, finding: DiagnosticFinding, *, run_id: str) -> None:
        payload = finding.as_dict(run_id=run_id)
        path = run_dir / "diagnostics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        summary_path = run_dir / "diagnostics.json"
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            summary = {"schema_version": 1, "run_id": run_id, "findings": {}}
        findings = summary.setdefault("findings", {})
        findings[finding.code] = payload
        summary["updated_at"] = utc_now()
        atomic_write_json(summary_path, summary)

    def apply(
        self,
        finding: DiagnosticFinding,
        *,
        run_id: str,
        run_dir: Path,
        worker_pid: int,
    ) -> DiagnosticAction:
        self.record(run_dir, finding, run_id=run_id)
        if finding.action in {"terminate", "retry"}:
            atomic_write_json(
                run_dir / "intervention.json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "requested_at": utc_now(),
                    "action": finding.action,
                    "reason": finding.code,
                    "worker_pid": worker_pid,
                },
            )
            _terminate_group(worker_pid)
        return finding.action

    def can_retry(self, run_id: str) -> bool:
        state = self.state(run_id)
        return state.retry_count < self.policy.max_automatic_retries

    def mark_retry(self, run_id: str) -> int:
        state = self.state(run_id)
        state.retry_count += 1
        return state.retry_count


def diagnostic_catalog(root: Path, *, limit: int = 1000) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.glob("*/*/diagnostics.jsonl")):
        for raw in _tail(path, 1024 * 1024).splitlines():
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            total += 1
            if len(rows) < limit:
                payload["path"] = path.relative_to(root).as_posix()
                rows.append(payload)
    rows.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return {"findings": rows[:limit], "total": total, "truncated": total > limit}
