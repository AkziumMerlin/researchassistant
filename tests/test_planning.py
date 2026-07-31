from pydantic import BaseModel, ConfigDict

from research_assistant.builtin import register as register_builtin
from research_assistant.config import parse_config
from research_assistant.planning import compile_plan
from research_assistant.registry import Registry


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int


def build_model(config: ModelParams, _context):
    return config.width


def make_registry() -> Registry:
    registry = Registry()
    register_builtin(registry)
    registry.add(
        "model",
        "test/model",
        factory=build_model,
        schema=ModelParams,
        provider="tests",
    )
    return registry


def test_matrix_expansion_and_ids() -> None:
    config = parse_config(
        {
            "version": 1,
            "experiment": {"name": "matrix"},
            "seed": 0,
            "components": {"model": {"type": "test/model", "params": {"width": 16}}},
            "matrix": {
                "seed": [0, 1, 2],
                "components.model.params.width": [16, 32],
            },
            "stages": [{"name": "fit", "type": "core/noop"}],
        }
    )

    first = compile_plan(config, make_registry())
    second = compile_plan(config, make_registry())

    assert len(first.runs) == 6
    assert [run.run_id for run in first.runs] == [run.run_id for run in second.runs]
    assert len({run.run_id for run in first.runs}) == 6
    assert len({run.trial_id for run in first.runs}) == 2


def test_artifact_root_does_not_change_run_identity() -> None:
    base = {
        "version": 1,
        "experiment": {"name": "identity"},
        "seed": 4,
        "stages": [{"name": "fit", "type": "core/noop"}],
    }
    left = parse_config({**base, "artifacts": {"root": "left"}})
    right = parse_config({**base, "artifacts": {"root": "right"}})

    left_run = compile_plan(left, make_registry()).runs[0]
    right_run = compile_plan(right, make_registry()).runs[0]

    assert left_run.run_id == right_run.run_id
    assert left_run.trial_id == right_run.trial_id


def test_logging_sink_does_not_change_run_identity() -> None:
    base = {
        "version": 1,
        "experiment": {"name": "identity"},
        "seed": 4,
        "stages": [{"name": "fit", "type": "core/noop"}],
    }
    plain = parse_config(base)
    tensorboard = parse_config(
        {
            **base,
            "logging": {
                "tensorboard": {
                    "enabled": True,
                    "directory": "tensorboard",
                    "flush_seconds": 10,
                }
            },
        }
    )

    plain_run = compile_plan(plain, make_registry()).runs[0]
    tensorboard_run = compile_plan(tensorboard, make_registry()).runs[0]

    assert plain_run.run_id == tensorboard_run.run_id
    assert plain_run.trial_id == tensorboard_run.trial_id
