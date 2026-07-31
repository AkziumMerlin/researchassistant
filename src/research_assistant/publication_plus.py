from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import Field, field_validator

from research_assistant.artifacts import utc_now
from research_assistant.dataset_registry import DatasetRegistry
from research_assistant.errors import ResearchAssistantError
from research_assistant.publication import (
    PublicationSpec,
    build_publication_bundle as build_base_bundle,
    preview_publication as preview_base_publication,
)
from research_assistant.research_log import ResearchLog
from research_assistant.selection import load_selection_lock


class EnhancedPublicationError(ResearchAssistantError):
    pass


class EnhancedPublicationSpec(PublicationSpec):
    dataset_ids: list[str] = Field(default_factory=list, max_length=1000)
    selection_locks: list[str] = Field(default_factory=list, max_length=1000)
    statistical_reports: list[str] = Field(default_factory=list, max_length=1000)
    bibliography: list[str] = Field(default_factory=list, max_length=100)
    include_research_log: bool = True
    strict_consistency: bool = True
    compile_pdf: bool = False
    paper_title: str | None = None
    abstract: str | None = None
    claims: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)

    @field_validator(
        "dataset_ids",
        "selection_locks",
        "statistical_reports",
        "bibliography",
    )
    @classmethod
    def unique_extended(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))


def load_enhanced_publication_spec(path: str | Path) -> EnhancedPublicationSpec:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EnhancedPublicationError(f"cannot read publication spec {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise EnhancedPublicationError(f"invalid publication YAML {source}: {exc}") from exc
    try:
        return EnhancedPublicationSpec.model_validate(payload)
    except ValueError as exc:
        raise EnhancedPublicationError(str(exc)) from exc


def _safe_path(workspace: Path, raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise EnhancedPublicationError(f"path escapes workspace: {raw}")
    if must_exist and not resolved.exists():
        raise EnhancedPublicationError(f"path does not exist: {raw}")
    return resolved


def _copy(source: Path, destination: Path, mode: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, copy_function=shutil.copy2)
        return
    if mode == "hardlink":
        try:
            os.link(source, destination)
            return
        except OSError:
            pass
    shutil.copy2(source, destination)


def _selected_run_ids(bundle: Path) -> set[str]:
    configs = bundle / "configs"
    return {path.stem for path in configs.glob("*.yaml")} if configs.is_dir() else set()


def _report_run_ids(path: Path) -> set[str]:
    result: set[str] = set()
    candidates = [path] if path.is_file() else list(path.rglob("*.json"))
    for candidate in candidates:
        if candidate.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        stack: list[Any] = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "run_id" and isinstance(child, str):
                        result.add(child)
                    elif key in {"run_ids", "selected_run_ids"} and isinstance(child, list):
                        result.update(str(item) for item in child)
                    else:
                        stack.append(child)
            elif isinstance(value, list):
                stack.extend(value)
    return result


def _consistency(
    workspace: Path,
    selected_runs: set[str],
    report_paths: list[str],
) -> dict[str, Any]:
    stale: list[dict[str, Any]] = []
    for raw in report_paths:
        path = _safe_path(workspace, raw)
        referenced = _report_run_ids(path)
        outside = sorted(referenced - selected_runs)
        if outside:
            stale.append({"path": raw, "outside_selection": outside})
    return {
        "selected_runs": len(selected_runs),
        "reports_checked": len(report_paths),
        "stale_reports": stale,
        "valid": not stale,
    }


def preview_enhanced_publication(
    workspace: str | Path, spec: EnhancedPublicationSpec
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    base = preview_base_publication(workspace_path, PublicationSpec.model_validate(
        spec.model_dump(mode="python", exclude={
            "dataset_ids",
            "selection_locks",
            "statistical_reports",
            "bibliography",
            "include_research_log",
            "strict_consistency",
            "compile_pdf",
            "paper_title",
            "abstract",
            "claims",
        })
    ))
    datasets = DatasetRegistry(workspace_path)
    try:
        dataset_rows = [datasets.require(dataset_id) for dataset_id in spec.dataset_ids]
    finally:
        datasets.close()
    locks = [load_selection_lock(workspace_path, name) for name in spec.selection_locks]
    report_paths = [*spec.reports, *spec.statistical_reports]
    selected_runs = set()
    for lock in locks:
        selected_runs.update(str(value) for value in lock.get("selected_run_ids") or [])
    base.update(
        {
            "datasets": len(dataset_rows),
            "selection_locks": len(locks),
            "statistical_reports": len(spec.statistical_reports),
            "research_log": spec.include_research_log,
            "compile_pdf": spec.compile_pdf,
            "report_paths": report_paths,
            "locked_run_ids": sorted(selected_runs),
        }
    )
    return base


def _write_paper(bundle: Path, spec: EnhancedPublicationSpec) -> None:
    title = spec.paper_title or spec.title or spec.name
    authors = ", ".join(spec.authors) if spec.authors else "Anonymous"
    abstract = spec.abstract or (
        "This document is generated from an immutable ResearchAssistant publication bundle. "
        "All reported values are linked to selected runs and checksum-verified artifacts."
    )
    if spec.template == "aaai":
        preamble = (
            r"\documentclass[letterpaper]{article}" "\n"
            r"\usepackage{aaai26}" "\n"
        )
    elif spec.template == "neurips":
        preamble = (
            r"\documentclass{article}" "\n"
            r"\usepackage[preprint]{neurips_2026}" "\n"
        )
    else:
        preamble = (
            r"\documentclass[11pt]{article}" "\n"
            r"\usepackage[margin=1in]{geometry}" "\n"
        )
    text = (
        preamble
        + r"\usepackage{graphicx,booktabs,amsmath}" "\n"
        + r"\title{" + title.replace("_", r"\_") + "}\n"
        + r"\author{" + authors.replace("_", r"\_") + "}\n"
        + r"\begin{document}" "\n"
        + r"\maketitle" "\n"
        + r"\begin{abstract}" "\n"
        + abstract
        + "\n"
        + r"\end{abstract}" "\n"
        + r"\input{methods.tex}" "\n"
        + r"\input{results.tex}" "\n"
        + r"\input{statistical_statement.tex}" "\n"
        + r"\input{compute_statement.tex}" "\n"
        + r"\input{dataset_statement.tex}" "\n"
        + r"\input{research_statement.tex}" "\n"
        + (
            r"\bibliographystyle{aaai26}" "\n"
            r"\bibliography{bibliography}" "\n"
            if spec.bibliography
            else ""
        )
        + r"\end{document}" "\n"
    )
    (bundle / "paper.tex").write_text(text, encoding="utf-8")


def _statistical_statement(bundle: Path) -> str:
    reports = list((bundle / "statistics").rglob("analysis.json")) if (bundle / "statistics").is_dir() else []
    if not reports:
        return (
            "\\section{Statistical analysis}\n"
            "No standalone statistical reports were selected for this bundle.\n"
        )
    comparisons = 0
    methods: set[str] = set()
    for path in reports:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        comparisons += len(payload.get("comparisons") or [])
        spec = payload.get("spec") or {}
        methods.add(
            f"paired permutation tests with {spec.get('correction', 'unspecified')} correction"
        )
    return (
        "\\section{Statistical analysis}\n"
        f"The bundle contains {len(reports)} statistical report(s) and {comparisons} "
        f"registered pairwise comparison(s). Methods: {', '.join(sorted(methods))}.\n"
    )


def _research_statement(export: dict[str, Any] | None) -> str:
    if not export:
        return (
            "\\section{Research decisions}\n"
            "No hypothesis or decision journal was included.\n"
        )
    hypotheses = export.get("hypotheses") or []
    decisions = export.get("decisions") or []
    supported = sum(item.get("status") == "supported" for item in hypotheses)
    refuted = sum(item.get("status") == "refuted" for item in hypotheses)
    return (
        "\\section{Research decisions}\n"
        f"The audit log contains {len(hypotheses)} hypotheses and {len(decisions)} decisions. "
        f"{supported} hypotheses are marked supported and {refuted} are marked refuted. "
        "The complete evidence links and rationales are included in "
        "\\texttt{research/research-log.json}.\n"
    )


def _write_checksums(bundle: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name == "checksums.sha256":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(bundle).as_posix()] = digest.hexdigest()
    (bundle / "checksums.sha256").write_text(
        "".join(f"{digest}  {path}\n" for path, digest in result.items()),
        encoding="utf-8",
    )
    return result


def build_enhanced_publication_bundle(
    workspace: str | Path,
    spec: EnhancedPublicationSpec,
    destination: str | Path,
) -> Path:
    workspace_path = Path(workspace).resolve()
    target = _safe_path(workspace_path, destination, must_exist=False)
    staging = target.with_name(target.name + f".plus-{uuid4().hex}")
    shutil.rmtree(staging, ignore_errors=True)
    base_spec = PublicationSpec.model_validate(
        spec.model_dump(mode="python", exclude={
            "dataset_ids",
            "selection_locks",
            "statistical_reports",
            "bibliography",
            "include_research_log",
            "strict_consistency",
            "compile_pdf",
            "paper_title",
            "abstract",
            "claims",
        })
    )
    try:
        build_base_bundle(workspace_path, base_spec, staging)
        selected_runs = _selected_run_ids(staging)
        consistency = _consistency(
            workspace_path,
            selected_runs,
            [*spec.reports, *spec.statistical_reports],
        )
        if spec.strict_consistency and not consistency["valid"]:
            raise EnhancedPublicationError(
                "selected reports reference runs outside the publication selection"
            )

        dataset_dir = staging / "datasets"
        dataset_dir.mkdir(exist_ok=True)
        registry = DatasetRegistry(workspace_path)
        try:
            dataset_rows = []
            for dataset_id in spec.dataset_ids:
                row = registry.require(dataset_id)
                dataset_rows.append(row)
                registry.export_manifest(
                    dataset_id, dataset_dir / f"{dataset_id.replace(':', '-')}.json"
                )
        finally:
            registry.close()

        selection_dir = staging / "selections"
        selection_dir.mkdir(exist_ok=True)
        locks: list[dict[str, Any]] = []
        for name in spec.selection_locks:
            lock = load_selection_lock(workspace_path, name)
            locks.append(lock)
            (selection_dir / f"{lock['name']}.json").write_text(
                json.dumps(lock, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        statistics_dir = staging / "statistics"
        statistics_dir.mkdir(exist_ok=True)
        for raw in spec.statistical_reports:
            source = _safe_path(workspace_path, raw)
            _copy(source, statistics_dir / source.name, spec.copy_mode)

        bibliography_chunks: list[str] = []
        for raw in spec.bibliography:
            source = _safe_path(workspace_path, raw)
            bibliography_chunks.append(source.read_text(encoding="utf-8"))
        if bibliography_chunks:
            (staging / "bibliography.bib").write_text(
                "\n\n".join(bibliography_chunks) + "\n", encoding="utf-8"
            )

        research_export: dict[str, Any] | None = None
        if spec.include_research_log:
            log = ResearchLog(workspace_path)
            try:
                research_export = log.export()
            finally:
                log.close()
            research_dir = staging / "research"
            research_dir.mkdir(exist_ok=True)
            (research_dir / "research-log.json").write_text(
                json.dumps(research_export, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        claims_payload = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "claims": spec.claims,
            "selection_locks": [
                {
                    "name": lock.get("name"),
                    "digest": lock.get("lock_digest"),
                    "run_ids": lock.get("selected_run_ids"),
                }
                for lock in locks
            ],
            "statistical_reports": spec.statistical_reports,
        }
        (staging / "claims.json").write_text(
            json.dumps(claims_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (staging / "statistical_statement.tex").write_text(
            _statistical_statement(staging), encoding="utf-8"
        )
        (staging / "research_statement.tex").write_text(
            _research_statement(research_export), encoding="utf-8"
        )
        _write_paper(staging, spec)

        metadata_path = staging / "publication.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            metadata = {}
        metadata.update(
            {
                "enhanced_schema_version": 1,
                "enhanced_at": utc_now(),
                "datasets": [
                    {
                        "dataset_id": row["dataset_id"],
                        "digest": row["digest"],
                        "manifest_path": row["manifest_path"],
                    }
                    for row in dataset_rows
                ],
                "selection_locks": [
                    {"name": lock["name"], "digest": lock["lock_digest"]} for lock in locks
                ],
                "statistical_reports": spec.statistical_reports,
                "consistency": consistency,
                "claims": len(spec.claims),
            }
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        if spec.compile_pdf:
            try:
                subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "paper.tex"],
                    cwd=staging,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except FileNotFoundError as exc:
                raise EnhancedPublicationError("pdflatex is not installed") from exc
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                output = getattr(exc, "stdout", "") or ""
                raise EnhancedPublicationError(
                    f"publication LaTeX compilation failed: {output[-2000:]}"
                ) from exc

        checksums = _write_checksums(staging)
        lock = {
            "schema_version": 1,
            "created_at": utc_now(),
            "publication": spec.name,
            "selected_run_ids": sorted(selected_runs),
            "dataset_ids": spec.dataset_ids,
            "selection_digests": [lock["lock_digest"] for lock in locks],
            "checksums_count": len(checksums),
        }
        lock["digest"] = hashlib.sha256(
            json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        (staging / "bundle-lock.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _write_checksums(staging)

        if target.exists():
            backup = target.with_name(target.name + f".bak-{uuid4().hex}")
            target.replace(backup)
            try:
                staging.replace(target)
            except BaseException:
                backup.replace(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            staging.replace(target)
        return target
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
