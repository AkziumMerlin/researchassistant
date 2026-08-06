from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from research_assistant.cli_workbench import app
from research_assistant.legacy import ProjectRegistrationCatalog
from research_assistant.project_import import import_project, scan_project


def _write_project(root: Path, *, broken_model: bool = False) -> None:
    (root / "models").mkdir(parents=True)
    (root / "experiments").mkdir()
    (root / "examples").mkdir()
    (root / "configs").mkdir()

    model_import = "import definitely_missing_project_dependency\n" if broken_model else ""
    (root / "models" / "kno.py").write_text(
        model_import
        + "from pathlib import Path\n"
        + "Path('python-imported.txt').write_text('executed')\n\n"
        + "class KNO:\n"
        + "    \"\"\"Test neural operator.\"\"\"\n"
        + "    def __init__(self, width: int = 64):\n"
        + "        self.width = width\n",
        encoding="utf-8",
    )
    (root / "experiments" / "registries.py").write_text(
        "def build_rpb_dataset(task: str = 'poisson', split: str = 'train'):\n"
        "    return {'task': task, 'split': split}\n\n"
        "def helper(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (root / "examples" / "train_from_yaml.py").write_text(
        "print('runner')\n",
        encoding="utf-8",
    )
    (root / "configs" / "rpb.yaml").write_text(
        yaml.safe_dump(
            {
                "experiment": {"name": "rpb-smoke"},
                "rpb": {"task": "poisson"},
                "models": {"kno": {}},
                "train": {"epochs": 1},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "configs" / "current.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "experiment": {"name": "current"},
                "stages": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_scan_project_is_non_executing_and_classifies_kno_project(tmp_path: Path) -> None:
    _write_project(tmp_path)

    plan = scan_project(tmp_path)

    assert not (tmp_path / "python-imported.txt").exists()
    by_symbol = {
        candidate.symbol: candidate
        for candidate in plan.candidates
        if candidate.category == "python"
    }
    assert by_symbol["KNO"].kind == "model"
    assert by_symbol["KNO"].selected is True
    assert by_symbol["build_rpb_dataset"].kind == "dataset"
    assert by_symbol["build_rpb_dataset"].selected is True
    assert "helper" not in by_symbol
    configs = [
        candidate for candidate in plan.candidates if candidate.category == "legacy-config"
    ]
    assert [candidate.path for candidate in configs] == ["configs/rpb.yaml"]
    assert configs[0].output == "configs/registered/rpb.yaml"
    assert plan.entrypoint == "examples/train_from_yaml.py"


def test_import_project_registers_recommended_items_and_is_idempotent(tmp_path: Path) -> None:
    _write_project(tmp_path)

    result = import_project(tmp_path)

    assert result.summary() == {"imported": 3, "skipped": 0, "failed": 0}
    catalog = ProjectRegistrationCatalog(tmp_path).load()
    assert {(item.kind, item.name) for item in catalog.python} == {
        ("dataset", "local/build-rpb-dataset"),
        ("model", "local/kno"),
    }
    assert [item.path for item in catalog.legacy_configs] == ["configs/rpb.yaml"]
    wrapper = tmp_path / "configs" / "registered" / "rpb.yaml"
    assert wrapper.is_file()
    wrapper_document = yaml.safe_load(wrapper.read_text(encoding="utf-8"))
    assert wrapper_document["stages"][0]["type"] == "core/legacy-config"
    manifest = yaml.safe_load(
        (tmp_path / ".research-assistant" / "import.yaml").read_text(encoding="utf-8")
    )
    assert manifest["summary"]["imported"] == 3

    repeated = import_project(tmp_path)
    assert repeated.items == []
    assert repeated.plan.summary()["already_registered"] == 3


def test_failed_python_component_does_not_block_legacy_config_import(tmp_path: Path) -> None:
    _write_project(tmp_path, broken_model=True)

    result = import_project(tmp_path)

    failed = [item for item in result.items if item.state == "failed"]
    imported = [item for item in result.items if item.state == "imported"]
    assert any(item.path == "models/kno.py" for item in failed)
    assert any(item.category == "legacy-config" for item in imported)
    catalog = ProjectRegistrationCatalog(tmp_path).load()
    assert all(item.path != "models/kno.py" for item in catalog.python)
    assert [item.path for item in catalog.legacy_configs] == ["configs/rpb.yaml"]


def test_project_cli_supports_scan_and_confirmed_import(tmp_path: Path) -> None:
    _write_project(tmp_path)
    runner = CliRunner()

    scan = runner.invoke(app, ["project", "scan", str(tmp_path), "--json"])
    assert scan.exit_code == 0, scan.output
    payload = json.loads(scan.stdout)
    assert payload["entrypoint"] == "examples/train_from_yaml.py"

    imported = runner.invoke(
        app,
        ["project", "import", str(tmp_path), "--yes", "--json"],
    )
    assert imported.exit_code == 0, imported.output
    result = json.loads(imported.stdout)
    assert result["manifest_path"] == ".research-assistant/import.yaml"
    assert sum(item["state"] == "imported" for item in result["items"]) == 3
