from __future__ import annotations

import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

import research_assistant


def test_runtime_version_matches_project_metadata() -> None:
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with project_path.open("rb") as source:
        project_version = tomllib.load(source)["project"]["version"]

    assert distribution_version("research-assistant") == project_version
    assert research_assistant.__version__ == project_version
