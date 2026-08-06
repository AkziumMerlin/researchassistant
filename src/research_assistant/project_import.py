from __future__ import annotations

import ast
import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from research_assistant.errors import ResearchAssistantError
from research_assistant.legacy import (
    ProjectRegistrationCatalog,
    RegistrationCatalogDocument,
    is_legacy_config,
    suggest_legacy_entrypoint,
)
from research_assistant.plugins import load_registry

IMPORT_MANIFEST_PATH = Path(".research-assistant/import.yaml")
_MAX_SOURCE_SIZE = 2 * 1024 * 1024
_MAX_FILES = 20000
_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".research-assistant",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "checkpoints",
    "dist",
    "node_modules",
    "outputs",
    "results",
    "runs",
    "venv",
}


class ProjectImportCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Literal["python", "legacy-config"]
    path: str = Field(min_length=1)
    selected: bool = False
    confidence: Literal["high", "medium", "low"] = "low"
    reason: str = ""
    symbol: str | None = None
    kind: str | None = None
    name: str = Field(min_length=1)
    description: str = ""
    entrypoint: str | None = None
    output: str | None = None
    already_registered: bool = False


class ProjectImportPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    project_root: str
    entrypoint: str | None = None
    candidates: list[ProjectImportCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        available = [candidate for candidate in self.candidates if not candidate.already_registered]
        return {
            "python": sum(candidate.category == "python" for candidate in self.candidates),
            "legacy_configs": sum(
                candidate.category == "legacy-config" for candidate in self.candidates
            ),
            "recommended": sum(candidate.selected for candidate in available),
            "already_registered": sum(
                candidate.already_registered for candidate in self.candidates
            ),
            "warnings": len(self.warnings),
        }


class ProjectImportStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: Literal["python", "legacy-config"]
    path: str
    name: str
    state: Literal["imported", "skipped", "failed"]
    message: str = ""
    output: str | None = None


class ProjectImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    manifest_path: str
    plan: ProjectImportPlan
    items: list[ProjectImportStatus]

    def summary(self) -> dict[str, int]:
        return {
            "imported": sum(item.state == "imported" for item in self.items),
            "skipped": sum(item.state == "skipped" for item in self.items),
            "failed": sum(item.state == "failed" for item in self.items),
        }


def _root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ResearchAssistantError(f"project root is not a directory: {root}")
    return root


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _candidate_id(category: str, path: str, symbol: str | None = None) -> str:
    digest = hashlib.sha256(f"{category}:{path}:{symbol or ''}".encode()).hexdigest()[:16]
    prefix = "py" if category == "python" else "cfg"
    return f"{prefix}-{digest}"


def _slug(value: str) -> str:
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", value)
    result = "-".join(word.lower() for word in words if word)
    if not result:
        result = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return result or "component"


def _safe_experiment_name(document: dict[str, Any], fallback: str) -> str:
    experiment = document.get("experiment")
    if isinstance(experiment, dict):
        for key in ("exp_name", "name"):
            value = experiment.get(key)
            if isinstance(value, str) and value.strip():
                fallback = value
                break
    result = "".join(
        char if char.isalnum() or char in "_.-" else "-" for char in fallback.strip()
    ).strip("-")
    return result or "legacy-experiment"


def _is_excluded(relative: Path) -> bool:
    parts = relative.parts
    if any(part in _EXCLUDED_DIRS for part in parts):
        return True
    if any(part.startswith(".") for part in parts):
        return True
    pairs = zip(parts, parts[1:], strict=False)
    return any(left == "configs" and right == "registered" for left, right in pairs)


def _project_files(root: Path) -> tuple[list[Path], bool]:
    result: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative_directory = current_path.relative_to(root)
        directories[:] = sorted(
            directory
            for directory in directories
            if not _is_excluded(relative_directory / directory)
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.suffix.lower() not in {".py", ".yaml", ".yml"}:
                continue
            try:
                if path.stat().st_size > _MAX_SOURCE_SIZE:
                    continue
            except OSError:
                continue
            result.append(path)
            if len(result) >= _MAX_FILES:
                return result, True
    return result, False


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _dotted_name(node.value)
    return ""


def _path_tokens(path: Path) -> set[str]:
    tokens: set[str] = set()
    for part in path.parts:
        tokens.update(token for token in re.split(r"[^a-z0-9]+", part.lower()) if token)
    return tokens


def _classify_symbol(
    relative: Path,
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, Literal["high", "medium", "low"], str] | None:
    if isinstance(node, ast.AsyncFunctionDef):
        return None
    symbol = node.name
    lower = symbol.lower()
    stem = relative.stem.lower().replace("_", "").replace("-", "")
    normalized = lower.replace("_", "").replace("-", "")
    tokens = _path_tokens(relative.parent)
    bases = (
        {_dotted_name(base).split(".")[-1].lower() for base in node.bases}
        if isinstance(node, ast.ClassDef)
        else set()
    )
    is_class = isinstance(node, ast.ClassDef)

    if (
        "dataset" in tokens
        or "datasets" in tokens
        or lower.endswith(("dataset", "datamodule"))
        or any(base in {"dataset", "iterabledataset", "datamodule"} for base in bases)
        or "rpb" in lower
    ):
        high = (
            lower.endswith(("dataset", "datamodule"))
            or "rpb" in lower
            or normalized == stem
            or any(base in {"dataset", "iterabledataset", "datamodule"} for base in bases)
        )
        if not is_class:
            high = high or any(word in lower for word in ("build", "create", "load", "make"))
        return "dataset", "high" if high else "medium", "dataset naming or source path"

    if "loss" in tokens or lower.endswith("loss"):
        confidence = "high" if lower.endswith("loss") else "medium"
        return "loss", confidence, "loss naming or source path"
    if "optimizer" in tokens or "optimizers" in tokens or lower.endswith("optimizer"):
        confidence = "high" if lower.endswith("optimizer") else "medium"
        return "optimizer", confidence, "optimizer naming or source path"
    if "scheduler" in tokens or "schedulers" in tokens or lower.endswith("scheduler"):
        confidence = "high" if lower.endswith("scheduler") else "medium"
        return "scheduler", confidence, "scheduler naming or source path"
    if "transform" in tokens or "transforms" in tokens or lower.endswith("transform"):
        confidence = "high" if lower.endswith("transform") else "medium"
        return "transform", confidence, "transform naming or source path"

    model_tokens = {
        "architecture",
        "architectures",
        "model",
        "models",
        "network",
        "networks",
        "operator",
        "operators",
    }
    model_name = any(
        marker in lower
        for marker in ("deeponet", "fno", "kno", "operator", "unet", "cno", "rno")
    )
    module_base = "module" in bases
    scoped_base_model = "basemodel" in bases and bool(tokens.intersection(model_tokens))
    if tokens.intersection(model_tokens) or model_name or module_base or scoped_base_model:
        high = is_class and (normalized == stem or model_name)
        if not is_class:
            high = any(word in lower for word in ("build_model", "create_model", "make_model"))
        return "model", "high" if high else "medium", "model naming, base class, or source path"

    stage_tokens = {"stage", "stages", "trainer", "trainers"}
    if tokens.intersection(stage_tokens) or lower.endswith(("stage", "trainer")):
        high = lower.endswith(("stage", "trainer")) or lower in {"train", "evaluate", "infer"}
        return "stage", "high" if high else "medium", "stage naming or source path"

    if relative.name in {"registry.py", "registries.py", "components.py"}:
        kinds = ("model", "dataset", "loss", "optimizer", "scheduler", "transform")
        for kind in kinds:
            if kind in lower:
                factories = ("build", "create", "get", "load", "make")
                high = any(word in lower for word in factories)
                reason = "factory exposed by a registry module"
                return kind, "high" if high else "medium", reason
    return None


def _unique_component_name(
    kind: str,
    symbol: str,
    relative: Path,
    used_names: set[tuple[str, str]],
) -> str:
    name = f"local/{_slug(symbol)}"
    if (kind, name) in used_names:
        name = f"local/{_slug(symbol)}-{_slug(relative.stem)}"
    if (kind, name) in used_names:
        suffix = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:6]
        name = f"local/{_slug(symbol)}-{suffix}"
    return name


def _python_candidates(
    root: Path,
    files: list[Path],
    existing: RegistrationCatalogDocument,
    warnings: list[str],
) -> list[ProjectImportCandidate]:
    exact_existing = {
        (row.kind, row.path, row.symbol): row
        for row in existing.python
    }
    used_names = {(row.kind, row.name) for row in existing.python}
    candidates: list[ProjectImportCandidate] = []
    for source in files:
        if source.suffix.lower() != ".py" or source.name == "__init__.py":
            continue
        relative = source.relative_to(root)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, UnicodeError, SyntaxError) as exc:
            watched = {"models", "datasets", "experiments"}
            if watched.intersection(relative.parts):
                warnings.append(f"could not inspect {relative.as_posix()}: {exc}")
            continue
        for node in tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            classified = _classify_symbol(relative, node)
            if classified is None:
                continue
            kind, confidence, reason = classified
            exact = exact_existing.get((kind, relative.as_posix(), node.name))
            name = (
                exact.name
                if exact is not None
                else _unique_component_name(kind, node.name, relative, used_names)
            )
            used_names.add((kind, name))
            description = (ast.get_docstring(node) or "").strip()
            already_registered = exact is not None
            candidates.append(
                ProjectImportCandidate(
                    id=_candidate_id("python", relative.as_posix(), node.name),
                    category="python",
                    path=relative.as_posix(),
                    symbol=node.name,
                    kind=kind,
                    name=name,
                    description=description,
                    confidence=confidence,
                    reason=reason,
                    selected=confidence == "high" and not already_registered,
                    already_registered=already_registered,
                )
            )
    return candidates


def _wrapper_path(relative: Path) -> Path:
    parts = relative.parts
    if "configs" in parts:
        index = parts.index("configs")
        tail = Path(*parts[index + 1 :])
        return Path(*parts[: index + 1]) / "registered" / tail
    return IMPORT_MANIFEST_PATH.parent / "registered-configs" / relative


def _unique_experiment_name(
    initial: str,
    relative: Path,
    used_names: set[str],
) -> str:
    name = initial
    if name in used_names:
        name = f"{name}-{_slug(relative.parent.name or relative.stem)}"
    if name in used_names:
        suffix = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:6]
        name = f"{name}-{suffix}"
    return name


def _legacy_candidates(
    root: Path,
    files: list[Path],
    existing: RegistrationCatalogDocument,
    entrypoint: Path | None,
    warnings: list[str],
) -> list[ProjectImportCandidate]:
    exact_existing = {row.path: row for row in existing.legacy_configs}
    used_names = {row.name for row in existing.legacy_configs}
    candidates: list[ProjectImportCandidate] = []
    for source in files:
        if source.suffix.lower() not in {".yaml", ".yml"}:
            continue
        relative = source.relative_to(root)
        try:
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            if "configs" in relative.parts:
                warnings.append(f"could not inspect {relative.as_posix()}: {exc}")
            continue
        if not isinstance(document, dict) or not is_legacy_config(document):
            continue
        exact = exact_existing.get(relative.as_posix())
        initial_name = _safe_experiment_name(document, source.stem)
        name = (
            exact.name
            if exact is not None
            else _unique_experiment_name(initial_name, relative, used_names)
        )
        used_names.add(name)
        output = exact.output if exact is not None else _wrapper_path(relative).as_posix()
        runner = (
            exact.entrypoint
            if exact is not None
            else (_relative(root, entrypoint) if entrypoint is not None else None)
        )
        already_registered = exact is not None
        candidates.append(
            ProjectImportCandidate(
                id=_candidate_id("legacy-config", relative.as_posix()),
                category="legacy-config",
                path=relative.as_posix(),
                name=name,
                description=f"Compatibility wrapper for {relative.as_posix()}",
                entrypoint=runner,
                output=output,
                confidence="high" if runner else "low",
                reason="legacy experiment YAML with the project runner",
                selected=runner is not None and not already_registered,
                already_registered=already_registered,
            )
        )
    return candidates


def scan_project(
    project_root: str | Path = ".",
    *,
    include_python: bool = True,
    include_configs: bool = True,
) -> ProjectImportPlan:
    root = _root(project_root)
    existing = ProjectRegistrationCatalog(root).load()
    files, truncated = _project_files(root)
    warnings: list[str] = []
    if truncated:
        warnings.append(f"project scan stopped after {_MAX_FILES} source/config files")
    entrypoint = suggest_legacy_entrypoint(root)
    candidates: list[ProjectImportCandidate] = []
    if include_python:
        candidates.extend(_python_candidates(root, files, existing, warnings))
    if include_configs:
        candidates.extend(_legacy_candidates(root, files, existing, entrypoint, warnings))
        has_legacy = any(row.category == "legacy-config" for row in candidates)
        if entrypoint is None and has_legacy:
            warnings.append(
                "legacy YAML files were found, but no train_from_yaml.py runner was detected"
            )
    candidates.sort(key=lambda row: (row.category, row.kind or "", row.path, row.symbol or ""))
    return ProjectImportPlan(
        project_root=str(root),
        entrypoint=_relative(root, entrypoint) if entrypoint is not None else None,
        candidates=candidates,
        warnings=warnings,
    )


def _restore_catalog(
    catalog: ProjectRegistrationCatalog,
    previous: RegistrationCatalogDocument,
    existed: bool,
) -> None:
    if existed:
        catalog.save(previous)
        return
    catalog.path.unlink(missing_ok=True)
    try:
        catalog.path.parent.rmdir()
    except OSError:
        pass


def _status(
    candidate: ProjectImportCandidate,
    state: Literal["imported", "skipped", "failed"],
    message: str = "",
) -> ProjectImportStatus:
    return ProjectImportStatus(
        id=candidate.id,
        category=candidate.category,
        path=candidate.path,
        name=candidate.name,
        state=state,
        message=message,
        output=candidate.output,
    )


def _write_manifest(root: Path, result: ProjectImportResult) -> None:
    path = root / IMPORT_MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "project": ".",
        "entrypoint": result.plan.entrypoint,
        "summary": result.summary(),
        "items": [item.model_dump(mode="json", exclude_none=True) for item in result.items],
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ResearchAssistantError(f"cannot write project import manifest {path}: {exc}") from exc


def _selected_candidates(
    plan: ProjectImportPlan,
    candidate_ids: list[str] | None,
    import_all: bool,
) -> list[ProjectImportCandidate]:
    by_id = {candidate.id: candidate for candidate in plan.candidates}
    if candidate_ids is not None:
        unknown = sorted(set(candidate_ids).difference(by_id))
        if unknown:
            raise ResearchAssistantError(
                "unknown project import candidate(s): " + ", ".join(unknown)
            )
        return [by_id[candidate_id] for candidate_id in candidate_ids]
    if import_all:
        return [candidate for candidate in plan.candidates if not candidate.already_registered]
    return [candidate for candidate in plan.candidates if candidate.selected]


def _import_python_candidate(
    root: Path,
    catalog: ProjectRegistrationCatalog,
    candidate: ProjectImportCandidate,
    *,
    replace: bool,
    validate_python: bool,
) -> ProjectImportStatus:
    if not candidate.symbol or not candidate.kind:
        return _status(candidate, "failed", "incomplete Python candidate")
    existed = catalog.path.is_file()
    previous = catalog.load()
    try:
        catalog.add_python(
            kind=candidate.kind,
            name=candidate.name,
            path=candidate.path,
            symbol=candidate.symbol,
            description=candidate.description,
            replace=replace,
        )
        if validate_python:
            load_registry([], project_root=root)
    except Exception as exc:
        _restore_catalog(catalog, previous, existed)
        return _status(candidate, "failed", str(exc))
    return _status(candidate, "imported")


def _import_config_candidate(
    root: Path,
    catalog: ProjectRegistrationCatalog,
    candidate: ProjectImportCandidate,
    *,
    replace: bool,
) -> ProjectImportStatus:
    if not candidate.entrypoint or not candidate.output:
        return _status(candidate, "failed", "legacy runner or wrapper path is missing")
    destination = root / candidate.output
    exact = next(
        (
            row
            for row in catalog.load().legacy_configs
            if row.path == candidate.path and row.name == candidate.name
        ),
        None,
    )
    if exact is not None and not replace:
        return _status(candidate, "skipped", "already registered")
    if destination.exists() and exact is None and not replace:
        return _status(candidate, "failed", f"wrapper already exists: {candidate.output}")
    try:
        catalog.add_legacy_config(
            path=candidate.path,
            entrypoint=candidate.entrypoint,
            output=candidate.output,
            name=candidate.name,
            description=candidate.description,
            replace=replace,
        )
    except Exception as exc:
        return _status(candidate, "failed", str(exc))
    return _status(candidate, "imported")


def import_project(
    project_root: str | Path = ".",
    *,
    candidate_ids: list[str] | None = None,
    import_all: bool = False,
    replace: bool = False,
    validate_python: bool = True,
    include_python: bool = True,
    include_configs: bool = True,
) -> ProjectImportResult:
    root = _root(project_root)
    plan = scan_project(
        root,
        include_python=include_python,
        include_configs=include_configs,
    )
    selected = _selected_candidates(plan, candidate_ids, import_all)
    catalog = ProjectRegistrationCatalog(root)
    items: list[ProjectImportStatus] = []
    for candidate in selected:
        if candidate.already_registered and not replace:
            items.append(_status(candidate, "skipped", "already registered"))
        elif candidate.category == "python":
            items.append(
                _import_python_candidate(
                    root,
                    catalog,
                    candidate,
                    replace=replace,
                    validate_python=validate_python,
                )
            )
        else:
            items.append(
                _import_config_candidate(
                    root,
                    catalog,
                    candidate,
                    replace=replace,
                )
            )

    result = ProjectImportResult(
        manifest_path=IMPORT_MANIFEST_PATH.as_posix(),
        plan=plan,
        items=items,
    )
    _write_manifest(root, result)
    return result
