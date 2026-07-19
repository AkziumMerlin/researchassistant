from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_assistant.errors import ExecutionError
from research_assistant.planning import RunManifest


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
        self.status_path = self.run_dir / "status.json"
        self.metrics_path = self.run_dir / "metrics.jsonl"
        self.manifest = manifest

    def prepare(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        expected = self.manifest.model_dump(mode="json")
        if self.manifest_path.exists():
            actual = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if actual != expected:
                raise ExecutionError(f"manifest mismatch for existing run directory {self.run_dir}")
        else:
            atomic_write_json(self.manifest_path, expected)

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

    def log_metrics(self, stage: str, metrics: dict[str, float]) -> None:
        if not metrics:
            return
        event = {
            "timestamp": utc_now(),
            "run_id": self.manifest.run_id,
            "stage": stage,
            "metrics": metrics,
        }
        with self.metrics_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
