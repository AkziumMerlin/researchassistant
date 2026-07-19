from pathlib import Path

import pytest

from research_assistant.config import load_config
from research_assistant.errors import ConfigError


def test_extends_and_override(tmp_path: Path) -> None:
    (tmp_path / "base.yaml").write_text(
        """version: 1
experiment: {name: inherited}
seed: 0
stages:
  - {name: fit, type: core/noop}
resources: {accelerator: cpu}
""",
        encoding="utf-8",
    )
    (tmp_path / "child.yaml").write_text(
        """extends: base.yaml
experiment: {name: child}
matrix: {seed: [0, 1]}
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path / "child.yaml", ["resources.devices=2"])

    assert config.experiment.name == "child"
    assert config.resources.accelerator == "cpu"
    assert config.resources.devices == 2
    assert config.matrix["seed"] == [0, 1]


def test_extends_cycle_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("extends: b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("extends: a.yaml\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="cyclic config inheritance"):
        load_config(tmp_path / "a.yaml")
