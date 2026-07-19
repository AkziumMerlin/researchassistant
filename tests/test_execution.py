import json
from pathlib import Path

from research_assistant.config import parse_config
from research_assistant.execution import execute_run
from research_assistant.planning import compile_plan
from research_assistant.plugins import load_registry


def test_execute_and_resume(tmp_path: Path) -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "execute"},
            "seed": 0,
            "matrix": {"seed": [0, 1]},
            "stages": [
                {
                    "name": "fit",
                    "type": "core/noop",
                    "params": {"metrics": {"val/loss": 0.5}},
                },
                {"name": "test", "type": "core/noop", "needs": ["fit"]},
            ],
        }
    )
    registry = load_registry()
    plan = compile_plan(config, registry)

    for manifest in plan.runs:
        first = execute_run(manifest, registry, artifact_root=tmp_path)
        second = execute_run(manifest, registry, artifact_root=tmp_path)
        assert first["state"] == "completed"
        assert second["state"] == "completed"

        run_dir = tmp_path / "execute" / manifest.run_id
        metrics = [
            json.loads(line)
            for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert len(metrics) == 1
        assert metrics[0]["metrics"] == {"val/loss": 0.5}
