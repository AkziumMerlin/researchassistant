from __future__ import annotations

import json
import os
import platform
import sys
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

from research_assistant.errors import ExecutionError
from research_assistant.metrics import (
    JsonlMetricSink,
    MetricEvent,
    MetricKind,
    MetricSink,
    StepKind,
    TensorBoardMetricSink,
    last_sequence,
    utc_now,
    validate_metrics,
)
from research_assistant.planning import RunManifest


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class RunStore:
    def __init__(self, manifest: RunManifest, root: str | Path | None = None) -> None:
        artifact_root = Path(root or manifest.config.artifacts.root)
        self.run_dir = artifact_root / manifest.study_id / manifest.run_id
        self.manifest_path = self.run_dir / "manifest.json"
        self.environment_path = self.run_dir / "environment.json"
        self.status_path = self.run_dir / "status.json"
        self.metrics_path = self.run_dir / "metrics.jsonl"
        self.manifest = manifest
        self.attempt = 0
        self._sequence = 0
        self._sinks: list[MetricSink] = [JsonlMetricSink(self.metrics_path)]
        tensorboard = manifest.config.logging.tensorboard
        if tensorboard.enabled:
            directory = Path(tensorboard.directory)
            if directory.is_absolute() or ".." in directory.parts:
                raise ExecutionError("TensorBoard directory must stay inside the run directory")
            self._sinks.append(
                TensorBoardMetricSink(
                    self.run_dir / directory,
                    flush_seconds=tensorboard.flush_seconds,
                )
            )

    def prepare(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        expected = self.manifest.model_dump(mode="json")
        if self.manifest_path.exists():
            actual = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if actual != expected:
                raise ExecutionError(f"manifest mismatch for existing run directory {self.run_dir}")
        else:
            atomic_write_json(self.manifest_path, expected)
        if not self.environment_path.exists():
            packages = {
                str(dist.metadata.get("Name", "unknown")): dist.version
                for dist in distributions()
                if dist.metadata.get("Name")
            }
            atomic_write_json(
                self.environment_path,
                {
                    "captured_at": utc_now(),
                    "python": platform.python_version(),
                    "executable": sys.executable,
                    "platform": platform.platform(),
                    "packages": dict(sorted(packages.items(), key=lambda item: item[0].lower())),
                },
            )
        self._sequence = last_sequence(self.metrics_path)

    def begin_attempt(self, attempt: int) -> None:
        if attempt < 1:
            raise ExecutionError("attempt numbers start at one")
        self.attempt = attempt

    def load_status(self) -> dict[str, Any]:
        if not self.status_path.exists():
            return {
                "run_id": self.manifest.run_id,
                "state": "pending",
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "stages": {},
            }
        return json.loads(self.status_path.read_text(encoding="utf-8"))

    def save_status(self, status: dict[str, Any]) -> None:
        status["updated_at"] = utc_now()
        atomic_write_json(self.status_path, status)

    def log_metrics(
        self,
        stage: str,
        metrics: dict[str, float],
        *,
        step: int | float | None = None,
        kind: MetricKind = "progress",
        step_kind: StepKind = "epoch",
        dimensions: dict[str, Any] | None = None,
    ) -> None:
        normalized = validate_metrics(metrics)
        if not normalized:
            return
        events: list[MetricEvent] = []
        for name, value in normalized.items():
            self._sequence += 1
            events.append(
                MetricEvent(
                    study_id=self.manifest.study_id,
                    trial_id=self.manifest.trial_id,
                    run_id=self.manifest.run_id,
                    attempt=self.attempt,
                    sequence=self._sequence,
                    stage=stage,
                    kind=kind,
                    metric=name,
                    value=value,
                    step=step,
                    step_kind=step_kind,
                    dimensions=dimensions or {},
                )
            )
        for sink in self._sinks:
            sink.write(events)

    def close(self) -> None:
        for sink in reversed(self._sinks):
            sink.close()
