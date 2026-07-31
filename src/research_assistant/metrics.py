from __future__ import annotations

import json
import math
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from research_assistant.errors import ExecutionError

MetricKind = Literal["progress", "final", "resource"]
StepKind = Literal["epoch", "batch", "optimizer_step", "wall_seconds", "custom"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class MetricEvent:
    study_id: str
    trial_id: str
    run_id: str
    attempt: int
    sequence: int
    stage: str
    kind: MetricKind
    metric: str
    value: float
    step: int | float | None = None
    step_kind: StepKind = "epoch"
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "study_id": self.study_id,
            "trial_id": self.trial_id,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "sequence": self.sequence,
            "stage": self.stage,
            "kind": self.kind,
            "metric": self.metric,
            "value": self.value,
            # Retained for readers of the original batched event format.
            "metrics": {self.metric: self.value},
            "step_kind": self.step_kind,
            "dimensions": dict(self.dimensions),
        }
        if self.step is not None:
            payload["step"] = self.step
        return payload


class MetricSink(Protocol):
    def write(self, events: Sequence[MetricEvent]) -> None: ...

    def close(self) -> None: ...


class JsonlMetricSink:
    """Append complete batches with one OS-level append operation."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, events: Sequence[MetricEvent]) -> None:
        if not events:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = "".join(
            json.dumps(event.as_dict(), sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
            for event in events
        ).encode("utf-8")
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
        finally:
            os.close(descriptor)

    def close(self) -> None:
        return


class TensorBoardMetricSink:
    """Optional compatibility sink; JSONL remains authoritative."""

    def __init__(self, directory: Path, *, flush_seconds: int = 30) -> None:
        self.directory = directory
        self.flush_seconds = flush_seconds
        self._writer: Any | None = None

    def _get_writer(self):
        if self._writer is None:
            try:
                from torch.utils.tensorboard import SummaryWriter
            except ImportError as exc:
                raise ExecutionError(
                    "TensorBoard logging is enabled but unavailable; "
                    "install research-assistant[tensorboard]"
                ) from exc
            self._writer = SummaryWriter(
                log_dir=str(self.directory),
                flush_secs=self.flush_seconds,
            )
        return self._writer

    def write(self, events: Sequence[MetricEvent]) -> None:
        if not events:
            return
        writer = self._get_writer()
        for event in events:
            step = event.step if event.step is not None else event.sequence
            writer.add_scalar(
                f"{event.stage}/{event.metric}",
                event.value,
                global_step=int(step),
            )

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()


def validate_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_name, raw_value in metrics.items():
        name = str(raw_name).strip()
        if not name:
            raise ExecutionError("metric names cannot be empty")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ExecutionError(f"metric {name!r} must be finite, got {value!r}")
        normalized[name] = value
    return normalized


def last_sequence(path: Path) -> int:
    """Read only the tail of an event file so resume stays O(1)."""
    if not path.is_file() or path.stat().st_size == 0:
        return 0
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        block = 4096
        data = b""
        position = end
        while position > 0 and data.count(b"\n") < 2:
            size = min(block, position)
            position -= size
            stream.seek(position)
            data = stream.read(size) + data
        for line in reversed(data.splitlines()):
            try:
                payload = json.loads(line)
                return int(payload.get("sequence", 0))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    return 0
