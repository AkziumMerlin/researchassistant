from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_assistant.desktop_server import create_desktop_app
from research_assistant.errors import ConfigError
from research_assistant.legacy import ProjectRegistrationCatalog
from research_assistant.models import ComponentRef
from research_assistant.plugins import load_registry
from research_assistant.registry import Registry


def test_changed_python_source_is_reloaded_in_same_process(tmp_path: Path) -> None:
    source = tmp_path / "component.py"
    source.write_text(
        "class Model:\n"
        "    def __init__(self):\n"
        "        self.revision = 1\n",
        encoding="utf-8",
    )
    ProjectRegistrationCatalog(tmp_path).add_python(
        kind="model",
        name="local/model",
        path="component.py",
        symbol="Model",
    )

    first = load_registry([], project_root=tmp_path).invoke(
        "model",
        ComponentRef(type="local/model", params={}),
        None,
    )
    source.write_text(
        "class Model:\n"
        "    def __init__(self):\n"
        "        self.revision = 2\n",
        encoding="utf-8",
    )
    second = load_registry([], project_root=tmp_path).invoke(
        "model",
        ComponentRef(type="local/model", params={}),
        None,
    )

    assert first.revision == 1
    assert second.revision == 2
    assert type(first).__module__ != type(second).__module__


def test_file_plugin_uses_environment_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    (project / "plugin.py").write_text(
        "from pydantic import BaseModel, ConfigDict\n"
        "class Params(BaseModel):\n"
        "    model_config = ConfigDict(extra='forbid')\n"
        "def build(params, context):\n"
        "    return 'project-root'\n"
        "def register(registry):\n"
        "    registry.add('value', 'local/env-root', factory=build, schema=Params)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RA_PROJECT_ROOT", str(project))
    monkeypatch.chdir(elsewhere)

    registry = load_registry(["plugin.py"])

    assert registry.invoke(
        "value",
        ComponentRef(type="local/env-root", params={}),
        None,
    ) == "project-root"


def test_legacy_wrapper_cannot_replace_source_or_use_non_yaml_output(tmp_path: Path) -> None:
    (tmp_path / "runner.py").write_text("print('runner')\n", encoding="utf-8")
    source = tmp_path / "old.yaml"
    source.write_text(
        yaml.safe_dump({"experiment": {}, "train": {}}),
        encoding="utf-8",
    )
    catalog = ProjectRegistrationCatalog(tmp_path)

    with pytest.raises(ConfigError, match="must not overwrite"):
        catalog.add_legacy_config(
            path="old.yaml",
            entrypoint="runner.py",
            output="old.yaml",
        )
    with pytest.raises(ConfigError, match="yaml or .yml"):
        catalog.add_legacy_config(
            path="old.yaml",
            entrypoint="runner.py",
            output="registered.json",
        )

    assert yaml.safe_load(source.read_text(encoding="utf-8")) == {
        "experiment": {},
        "train": {},
    }
    assert not catalog.path.exists()


def test_registry_replace_with_keeps_object_identity() -> None:
    current = Registry()
    replacement = load_registry([])
    identity = id(current)

    current.replace_with(replacement)

    assert id(current) == identity
    assert current.get("stage", "core/noop").provider == "research-assistant"
    assert current.plugin_diagnostics == replacement.plugin_diagnostics


def test_desktop_registration_rolls_back_failure_and_refreshes_bootstrap(
    tmp_path: Path,
) -> None:
    fastapi = pytest.importorskip("fastapi")
    del fastapi
    from fastapi.testclient import TestClient

    bad = tmp_path / "bad.py"
    bad.write_text("raise RuntimeError('broken import')\nclass Bad: pass\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text(
        "class Good:\n"
        "    def __init__(self, width: int = 4):\n"
        "        self.width = width\n",
        encoding="utf-8",
    )
    app = create_desktop_app(tmp_path, token="secret")
    headers = {"Authorization": "Bearer secret"}

    with TestClient(app, headers=headers) as client:
        failed = client.post(
            "/api/legacy/python/register",
            json={
                "path": "bad.py",
                "symbol": "Bad",
                "kind": "model",
                "name": "local/bad",
            },
        )
        assert failed.status_code == 400
        assert not (tmp_path / ".research-assistant/registrations.yaml").exists()

        created = client.post(
            "/api/legacy/python/register",
            json={
                "path": "good.py",
                "symbol": "Good",
                "kind": "model",
                "name": "local/good",
            },
        )
        assert created.status_code == 200
        assert created.json()["restart_required"] is False
        bootstrap = client.get("/api/bootstrap").json()

    component = next(
        row
        for row in bootstrap["components"]
        if row["kind"] == "model" and row["name"] == "local/good"
    )
    assert component["provider"] == "file:good.py#Good"
    assert component["schema"]["properties"]["width"]["default"] == 4
