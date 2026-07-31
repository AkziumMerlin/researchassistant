from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_assistant.artifacts import utc_now
from research_assistant.asset_registry import AssetRegistry
from research_assistant.errors import ResearchAssistantError


class PublicationError(ResearchAssistantError):
    pass


class PublicationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="publication", min_length=1, max_length=120)
    title: str | None = None
    authors: list[str] = Field(default_factory=list, max_length=100)
    artifact_root: str = "runs"
    study_ids: list[str] = Field(default_factory=list, max_length=100)
    trial_ids: list[str] = Field(default_factory=list, max_length=1000)
    run_ids: list[str] = Field(default_factory=list, max_length=10000)
    reports: list[str] = Field(default_factory=list, max_length=1000)
    asset_statuses: list[Literal["selected", "released"]] = Field(
        default_factory=lambda: ["selected", "released"]
    )
    include_all_artifacts: bool = False
    include_checkpoints: bool = True
    include_environment: bool = True
    template: Literal["generic", "aaai", "neurips"] = "generic"
    copy_mode: Literal["copy", "hardlink"] = "hardlink"

    @field_validator("study_ids", "trial_ids", "run_ids", "reports", "asset_statuses")
    @classmethod
    def unique(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))


def load_publication_spec(path: str | Path) -> PublicationSpec:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PublicationError(f"cannot read publication spec {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PublicationError(f"invalid publication YAML {source}: {exc}") from exc
    try:
        return PublicationSpec.model_validate(payload)
    except ValueError as exc:
        raise PublicationError(str(exc)) from exc


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _copy_file(source: Path, destination: Path, mode: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "hardlink":
        try:
            os.link(source, destination)
            return
        except OSError:
            pass
    shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path, mode: str) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    copy_function = lambda src, dst: _copy_file(Path(src), Path(dst), mode)
    shutil.copytree(source, destination, copy_function=copy_function)


def _selected_runs(workspace: Path, spec: PublicationSpec) -> list[dict[str, Any]]:
    root = (workspace / spec.artifact_root).resolve()
    if not root.is_relative_to(workspace):
        raise PublicationError("artifact root escapes workspace")
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        manifest = _read_mapping(manifest_path)
        status = _read_mapping(manifest_path.parent / "status.json")
        study_id = str(manifest.get("study_id", manifest_path.parent.parent.name))
        trial_id = str(manifest.get("trial_id", "unknown"))
        run_id = str(manifest.get("run_id", manifest_path.parent.name))
        if spec.study_ids and study_id not in spec.study_ids:
            continue
        if spec.trial_ids and trial_id not in spec.trial_ids:
            continue
        if spec.run_ids and run_id not in spec.run_ids:
            continue
        if status.get("state") != "completed" and run_id not in spec.run_ids:
            continue
        rows.append(
            {
                "study_id": study_id,
                "trial_id": trial_id,
                "run_id": run_id,
                "run_dir": manifest_path.parent,
                "manifest": manifest,
                "status": status,
                "resources": _read_mapping(manifest_path.parent / "resources.json"),
            }
        )
    if not rows:
        raise PublicationError("publication selection contains no runs")
    return rows


def _component_types(run: dict[str, Any], kind: str) -> set[str]:
    config = run["manifest"].get("config") or {}
    reference = (config.get("components") or {}).get(kind) or {}
    value = reference.get("type")
    return {str(value)} if value else set()


def _tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _methods_tex(spec: PublicationSpec, runs: list[dict[str, Any]]) -> str:
    studies = sorted({run["study_id"] for run in runs})
    trials = sorted({run["trial_id"] for run in runs})
    seeds = sorted(
        {
            (run["manifest"].get("config") or {}).get("seed")
            for run in runs
            if (run["manifest"].get("config") or {}).get("seed") is not None
        }
    )
    models = sorted(set().union(*(_component_types(run, "model") for run in runs)))
    datasets = sorted(set().union(*(_component_types(run, "data") for run in runs)))
    return (
        "\\section{Experimental protocol}\n"
        f"This bundle contains {len(runs)} completed runs from {len(studies)} studies and "
        f"{len(trials)} resolved trials. "
        "The included random seeds are "
        f"{_tex_escape(', '.join(map(str, seeds)) or 'unspecified')}.\n\n"
        f"Model components: {_tex_escape(', '.join(models) or 'unspecified')}.\\\\\n"
        f"Data components: {_tex_escape(', '.join(datasets) or 'unspecified')}.\n"
    )


def _compute_tex(runs: list[dict[str, Any]]) -> str:
    totals = [run["resources"].get("total") or {} for run in runs]
    wall = sum(float(item.get("wall_seconds", 0.0)) for item in totals)
    gpu = sum(float(item.get("gpu_wall_seconds", 0.0)) for item in totals)
    energy = sum(float(item.get("device_energy_joules", 0.0)) for item in totals)
    peak = max((float(item.get("placement_memory_peak_mb", 0.0)) for item in totals), default=0.0)
    return (
        "\\section{Compute statement}\n"
        f"The included runs account for {wall / 3600:.3f} wall-clock hours and "
        f"{gpu / 3600:.3f} assigned GPU-hours. The maximum recorded placement memory was "
        f"{peak / 1024:.3f}~GiB. Device-wide sampled energy totals {energy / 3.6e6:.3f}~kWh; "
        "this quantity may include activity from foreign processes on shared accelerators.\n"
    )


def _dataset_tex(runs: list[dict[str, Any]]) -> str:
    datasets = sorted(set().union(*(_component_types(run, "data") for run in runs)))
    return (
        "\\section{Dataset statement}\n"
        "The exact resolved data-component references and parameters are preserved in the "
        "per-run configuration files and manifests included with this bundle. "
        f"Data component types: {_tex_escape(', '.join(datasets) or 'unspecified')}.\n"
    )


def _results_tex(report_files: list[Path]) -> str:
    tables = [path for path in report_files if path.suffix.lower() == ".tex"]
    figures = [path for path in report_files if path.suffix.lower() in {".pdf", ".png", ".svg"}]
    lines = ["\\section{Generated results}"]
    if tables:
        lines.append("Generated tables included in this bundle:")
        lines.append("\\begin{itemize}")
        lines.extend(f"\\item {_tex_escape(path.name)}" for path in tables)
        lines.append("\\end{itemize}")
    if figures:
        lines.append("Generated figures included in this bundle:")
        lines.append("\\begin{itemize}")
        lines.extend(f"\\item {_tex_escape(path.name)}" for path in figures)
        lines.append("\\end{itemize}")
    if not tables and not figures:
        lines.append("No report tables or figures were explicitly selected.")
    return "\n".join(lines) + "\n"


def _checksums(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "checksums.sha256":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def preview_publication(workspace: str | Path, spec: PublicationSpec) -> dict[str, Any]:
    root = Path(workspace).resolve()
    runs = _selected_runs(root, spec)
    registry = AssetRegistry(root)
    try:
        registry.refresh(spec.artifact_root)
        statuses = set(spec.asset_statuses)
        assets = [
            asset
            for asset in registry.list(limit=10000)
            if asset["run_id"] in {run["run_id"] for run in runs}
            and (
                spec.include_all_artifacts
                or asset["status"] in statuses
                or (
                    spec.include_checkpoints
                    and asset["kind"] == "checkpoint"
                    and asset["status"] in statuses
                )
            )
        ]
    finally:
        registry.close()
    return {
        "name": spec.name,
        "runs": len(runs),
        "studies": sorted({run["study_id"] for run in runs}),
        "trials": len({run["trial_id"] for run in runs}),
        "assets": len(assets),
        "reports": len(spec.reports),
    }


def build_publication_bundle(
    workspace: str | Path,
    spec: PublicationSpec,
    destination: str | Path,
) -> Path:
    workspace_path = Path(workspace).resolve()
    target = Path(destination)
    target = target.resolve() if target.is_absolute() else (workspace_path / target).resolve()
    if not target.is_relative_to(workspace_path):
        raise PublicationError("publication destination escapes workspace")
    runs = _selected_runs(workspace_path, spec)
    temporary = target.with_name(target.name + f".tmp-{uuid4().hex}")
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)

    configs_dir = temporary / "configs"
    provenance_dir = temporary / "provenance"
    reports_dir = temporary / "reports"
    figures_dir = temporary / "figures"
    tables_dir = temporary / "tables"
    assets_dir = temporary / "assets"
    checkpoints_dir = temporary / "checkpoints"
    for directory in (
        configs_dir,
        provenance_dir,
        reports_dir,
        figures_dir,
        tables_dir,
        assets_dir,
        checkpoints_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    for run in runs:
        run_id = run["run_id"]
        config = run["manifest"].get("config") or {}
        (configs_dir / f"{run_id}.yaml").write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        run_provenance = provenance_dir / run_id
        run_provenance.mkdir()
        for name in (
            "manifest.json",
            "status.json",
            "resources.json",
            "diagnostics.json",
            "diagnostics.jsonl",
            "environment.json",
        ):
            if name == "environment.json" and not spec.include_environment:
                continue
            source = run["run_dir"] / name
            if source.is_file():
                _copy_file(source, run_provenance / name, spec.copy_mode)

    report_files: list[Path] = []
    for raw in spec.reports:
        source = (workspace_path / raw).resolve()
        if not source.is_relative_to(workspace_path) or not source.exists():
            raise PublicationError(f"report path does not exist inside workspace: {raw}")
        destination_path = reports_dir / source.name
        if source.is_dir():
            _copy_tree(source, destination_path, spec.copy_mode)
            copied = [path for path in destination_path.rglob("*") if path.is_file()]
        else:
            _copy_file(source, destination_path, spec.copy_mode)
            copied = [destination_path]
        report_files.extend(copied)
        for path in copied:
            suffix = path.suffix.lower()
            if suffix in {".pdf", ".png", ".svg"}:
                _copy_file(path, figures_dir / path.name, spec.copy_mode)
            elif suffix in {".tex", ".csv"}:
                _copy_file(path, tables_dir / path.name, spec.copy_mode)

    registry = AssetRegistry(workspace_path)
    try:
        registry.refresh(spec.artifact_root)
        selected_ids = {run["run_id"] for run in runs}
        statuses = set(spec.asset_statuses)
        included_assets: list[dict[str, Any]] = []
        for asset in registry.list(limit=10000):
            if asset["run_id"] not in selected_ids:
                continue
            include = spec.include_all_artifacts or asset["status"] in statuses
            if asset["kind"] == "checkpoint" and not spec.include_checkpoints:
                include = False
            if not include:
                continue
            destination_root = checkpoints_dir if asset["kind"] == "checkpoint" else assets_dir
            destination_path = destination_root / f"{asset['asset_id']}-{asset['name']}"
            registry.materialize(asset["asset_id"], destination_path)
            included_assets.append(asset)
    finally:
        registry.close()

    (temporary / "methods.tex").write_text(_methods_tex(spec, runs), encoding="utf-8")
    (temporary / "results.tex").write_text(_results_tex(report_files), encoding="utf-8")
    (temporary / "compute_statement.tex").write_text(_compute_tex(runs), encoding="utf-8")
    (temporary / "dataset_statement.tex").write_text(_dataset_tex(runs), encoding="utf-8")
    reproduction = "#!/usr/bin/env bash\nset -euo pipefail\n"
    reproduction += 'ROOT="$(cd "$(dirname "$0")" && pwd)"\n'
    reproduction += 'for config in "$ROOT"/configs/*.yaml; do ra run "$config"; done\n'
    reproduction_path = temporary / "reproduction.sh"
    reproduction_path.write_text(reproduction, encoding="utf-8")
    reproduction_path.chmod(0o755)
    readme = (
        f"# {spec.title or spec.name}\n\n"
        f"Generated by ResearchAssistant at {utc_now()}.\n\n"
        "- `configs/`: resolved one-run experiment configurations\n"
        "- `provenance/`: manifests, status, resources, diagnostics and environments\n"
        "- `reports/`, `figures/`, `tables/`: selected report outputs\n"
        "- `assets/`, `checkpoints/`: registry-selected content-addressed assets\n"
        "- `reproduction.sh`: rerun all resolved configurations\n"
    )
    (temporary / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "name": spec.name,
        "title": spec.title,
        "authors": spec.authors,
        "template": spec.template,
        "created_at": utc_now(),
        "spec": spec.model_dump(mode="json"),
        "run_ids": [run["run_id"] for run in runs],
        "asset_ids": [asset["asset_id"] for asset in included_assets],
    }
    (temporary / "publication.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = _checksums(temporary)
    (temporary / "checksums.sha256").write_text(
        "".join(f"{digest}  {path}\n" for path, digest in sorted(checksums.items())),
        encoding="utf-8",
    )
    if target.exists():
        shutil.rmtree(target)
    temporary.replace(target)
    return target
