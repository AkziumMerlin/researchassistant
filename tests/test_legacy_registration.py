from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from research_assistant.config import load_config
from research_assistant.errors import ConfigError, RegistryError
from research_assistant.legacy import (
    LegacyConfigStageParams,
    ProjectRegistrationCatalog,
    discover_python_symbols,
    run_legacy_config,
)
from research_assistant.models import ComponentRef
from research_assistant.plugins import load_registry


def test_python_discovery_does_not_execute_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    source = tmp_path / "component.py"
    source.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "class Model:\n"
        "    \"\"\"A discoverable model.\"\"\"\n"
        "    pass\n",
        encoding="utf-8",
    )

    symbols = discover_python_symbols(source)

    assert symbols == [
        {
            "name": "Model",
            "kind": "class",
            "line": 3,
            "description": "A discoverable model.",
        }
    ]
    assert not marker.exists()


def test_registered_class_uses_signature_schema_and_relative_imports(tmp_path: Path) -> None:
    package = tmp_path / "models"
    package.mkdir()
    (package / "__init__.py").write_text(
        "raise RuntimeError('package init must not execute')\n",
        encoding="utf-8",
    )
    (package / "helper.py").write_text("OFFSET = 3\n", encoding="utf-8")
    (package / "custom.py").write_text(
        "from .helper import OFFSET\n"
        "class CustomModel:\n"
        "    def __init__(self, width: int = 16, enabled: bool = True):\n"
        "        self.width = width + OFFSET\n"
        "        self.enabled = enabled\n",
        encoding="utf-8",
    )
    ProjectRegistrationCatalog(tmp_path).add_python(
        kind="model",
        name="local/custom-model",
        path="models/custom.py",
        symbol="CustomModel",
    )

    registry = load_registry([], project_root=tmp_path)
    spec = registry.get("model", "local/custom-model")
    instance = registry.invoke(
        "model",
        ComponentRef(type="local/custom-model", params={"width": 9}),
        None,
    )

    assert spec.schema.model_json_schema()["properties"]["width"]["default"] == 16
    assert instance.width == 12
    assert instance.enabled is True
    assert spec.provider == "file:models/custom.py#CustomModel"


def test_python_plugin_file_can_be_used_without_import_module_name(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text(
        "from pydantic import BaseModel, ConfigDict\n"
        "class Params(BaseModel):\n"
        "    model_config = ConfigDict(extra='forbid')\n"
        "def build(params, context):\n"
        "    return 'ok'\n"
        "def register(registry):\n"
        "    registry.add('value', 'local/from-file', factory=build, schema=Params)\n",
        encoding="utf-8",
    )

    registry = load_registry(["plugin.py"], project_root=tmp_path)

    assert registry.invoke(
        "value",
        ComponentRef(type="local/from-file", params={}),
        None,
    ) == "ok"


def test_legacy_config_registration_writes_current_wrapper(tmp_path: Path) -> None:
    (tmp_path / "examples").mkdir()
    (tmp_path / "configs").mkdir()
    (tmp_path / "examples/train_from_yaml.py").write_text("print('runner')\n")
    legacy = {
        "experiment": {
            "exp_name": "rpb64_baseline_sweep_smoke",
            "device": "cuda:0",
        },
        "rpb": {"datasets": ["poisson"]},
        "models": {"variants": [{"tag": "fno", "names": ["fno"]}]},
        "train": {"epochs": 2},
        "sweep": {"name": "smoke"},
        "run": {"mode": "grid", "seed": 0},
    }
    source = tmp_path / "configs/old.yaml"
    source.write_text(yaml.safe_dump(legacy, sort_keys=False), encoding="utf-8")

    registration, _content = ProjectRegistrationCatalog(tmp_path).add_legacy_config(
        path="configs/old.yaml",
        entrypoint="examples/train_from_yaml.py",
        output="configs/registered/old.yaml",
    )
    wrapper = load_config(tmp_path / registration.output)

    assert registration.name == "rpb64_baseline_sweep_smoke"
    assert wrapper.resources.accelerator == "cuda"
    assert wrapper.stages[0].type == "core/legacy-config"
    assert wrapper.stages[0].params["config_path"] == "configs/old.yaml"
    assert wrapper.stages[0].params["entrypoint"] == "examples/train_from_yaml.py"
    catalog = yaml.safe_load(
        (tmp_path / ".research-assistant/registrations.yaml").read_text(encoding="utf-8")
    )
    assert catalog["legacy_configs"][0]["output"] == "configs/registered/old.yaml"


def test_current_config_is_not_registered_as_legacy(tmp_path: Path) -> None:
    (tmp_path / "examples").mkdir()
    (tmp_path / "configs").mkdir()
    (tmp_path / "examples/train_from_yaml.py").write_text("print('runner')\n")
    current = {
        "version": 1,
        "experiment": {"name": "current"},
        "stages": [{"name": "noop", "type": "core/noop"}],
    }
    (tmp_path / "configs/current.yaml").write_text(
        yaml.safe_dump(current),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="already looks like a current config"):
        ProjectRegistrationCatalog(tmp_path).add_legacy_config(
            path="configs/current.yaml",
            entrypoint="examples/train_from_yaml.py",
            output="configs/registered/current.yaml",
        )

    assert not (tmp_path / ".research-assistant/registrations.yaml").exists()
    assert not (tmp_path / "configs/registered/current.yaml").exists()


def test_legacy_runner_uses_argument_vector_and_resume_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".research-assistant").mkdir()
    (tmp_path / ".research-assistant/registrations.yaml").write_text(
        "version: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text("experiment: {}\ntrain: {}\n")
    (tmp_path / "runner.py").write_text("print('runner')\n")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("RA_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("research_assistant.legacy.subprocess.run", fake_run)
    context = SimpleNamespace(resume=False)

    run_legacy_config(
        LegacyConfigStageParams(
            config_path="config.yaml",
            entrypoint="runner.py",
            arguments=["--extra", "value"],
        ),
        context,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1:] == [
        str(tmp_path / "runner.py"),
        "--no-resume",
        "--extra",
        "value",
        str(tmp_path / "config.yaml"),
    ]
    assert captured["cwd"] == tmp_path
    assert captured["check"] is False


def test_registration_rejects_paths_outside_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-component.py"
    outside.write_text("class Outside: pass\n")

    with pytest.raises(RegistryError, match="escapes project root"):
        ProjectRegistrationCatalog(tmp_path).add_python(
            kind="model",
            name="local/outside",
            path=outside,
            symbol="Outside",
        )
