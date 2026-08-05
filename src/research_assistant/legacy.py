from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, get_type_hints

import yaml
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from research_assistant.config import dump_config, parse_config
from research_assistant.errors import ConfigError, ExecutionError, RegistryError
from research_assistant.execution import StageContext, StageResult
from research_assistant.models import COMPONENT_NAME_PATTERN
from research_assistant.registry import Registry

CATALOG_PATH = Path(".research-assistant/registrations.yaml")


class PythonRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1)
    name: str = Field(pattern=COMPONENT_NAME_PATTERN)
    path: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    description: str = ""
    catalog: str = "component"
    editor: str | None = None

    @field_validator("symbol")
    @classmethod
    def symbol_is_identifier(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("symbol must be a top-level Python identifier")
        return value


class LegacyConfigRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    path: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    output: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)
    working_directory: str = "."
    description: str = ""


class RegistrationCatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    python: list[PythonRegistration] = Field(default_factory=list)
    legacy_configs: list[LegacyConfigRegistration] = Field(default_factory=list)


class LegacyConfigStageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config_path: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)
    working_directory: str = "."
    python: str | None = None
    resume_flag: str | None = "--resume"
    no_resume_flag: str | None = "--no-resume"
    environment: dict[str, str] = Field(default_factory=dict)


def _root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise RegistryError(f"project root is not a directory: {root}")
    return root


def _bounded(root: Path, value: str | Path, *, exists: bool = False) -> Path:
    path = Path(value).expanduser()
    path = path if path.is_absolute() else root / path
    path = path.resolve(strict=False)
    if not path.is_relative_to(root):
        raise RegistryError(f"path escapes project root {root}: {value}")
    if exists and not path.exists():
        raise RegistryError(f"path does not exist: {path}")
    return path


def find_project_root(start: str | Path | None = None) -> Path | None:
    raw = start or os.environ.get("RA_PROJECT_ROOT") or Path.cwd()
    path = Path(raw).expanduser().resolve()
    path = path.parent if path.is_file() else path
    for candidate in (path, *path.parents):
        if (candidate / CATALOG_PATH).is_file():
            return candidate
    return None


def suggest_legacy_entrypoint(root: str | Path) -> Path | None:
    project = _root(root)
    for relative in (
        "examples/train_from_yaml.py",
        "scripts/train_from_yaml.py",
        "train_from_yaml.py",
    ):
        candidate = project / relative
        if candidate.is_file():
            return candidate
    return None


def discover_python_symbols(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path).expanduser().resolve()
    if source.suffix != ".py" or not source.is_file():
        raise RegistryError(f"Python source is not a .py file: {source}")
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError) as exc:
        raise RegistryError(f"cannot inspect Python source {source}: {exc}") from exc
    result = []
    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        result.append(
            {
                "name": node.name,
                "kind": "class"
                if isinstance(node, ast.ClassDef)
                else "async-function"
                if isinstance(node, ast.AsyncFunctionDef)
                else "function",
                "line": node.lineno,
                "description": (ast.get_docstring(node) or "").strip(),
            }
        )
    return result


def _yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read YAML config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"YAML config root must be a mapping: {path}")
    return value


def is_legacy_config(document: Mapping[str, Any]) -> bool:
    if "version" in document or "stages" in document:
        return False
    sections = {"experiment", "models", "train", "run", "sweep", "rpb"}
    return len(sections.intersection(document)) >= 2


def _safe_name(value: str) -> str:
    result = "".join(
        char if char.isalnum() or char in "_.-" else "-" for char in value.strip()
    ).strip("-")
    return result or "legacy-experiment"


def _experiment_name(document: Mapping[str, Any], fallback: str) -> str:
    experiment = document.get("experiment")
    if isinstance(experiment, Mapping):
        for key in ("exp_name", "name"):
            value = experiment.get(key)
            if isinstance(value, str) and value.strip():
                return _safe_name(value)
    return _safe_name(fallback)


class ProjectRegistrationCatalog:
    def __init__(self, root: str | Path) -> None:
        self.root = _root(root)
        self.path = self.root / CATALOG_PATH

    def load(self) -> RegistrationCatalogDocument:
        if not self.path.is_file():
            return RegistrationCatalogDocument()
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            return RegistrationCatalogDocument.model_validate(raw)
        except Exception as exc:
            raise RegistryError(f"invalid registration catalog {self.path}: {exc}") from exc

    def save(self, document: RegistrationCatalogDocument) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                yaml.safe_dump(
                    document.model_dump(mode="json", exclude_none=True),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise RegistryError(f"cannot write registration catalog {self.path}: {exc}") from exc

    def add_python(
        self,
        *,
        kind: str,
        name: str,
        path: str | Path,
        symbol: str,
        description: str = "",
        catalog: str = "component",
        editor: str | None = None,
        replace: bool = False,
    ) -> PythonRegistration:
        source = _bounded(self.root, path, exists=True)
        if source.suffix != ".py" or not source.is_file():
            raise RegistryError(f"registered source must be a .py file: {source}")
        item = PythonRegistration(
            kind=kind,
            name=name,
            path=source.relative_to(self.root).as_posix(),
            symbol=symbol,
            description=description,
            catalog=catalog,
            editor=editor,
        )
        document = self.load()
        key = (kind, name)
        if any((row.kind, row.name) == key for row in document.python) and not replace:
            raise RegistryError(f"{kind} component {name!r} is already registered")
        document.python = [row for row in document.python if (row.kind, row.name) != key]
        document.python.append(item)
        document.python.sort(key=lambda row: (row.kind, row.name))
        self.save(document)
        return item

    def add_legacy_config(
        self,
        *,
        path: str | Path,
        entrypoint: str | Path,
        output: str | Path,
        name: str | None = None,
        arguments: list[str] | None = None,
        working_directory: str | Path = ".",
        description: str = "",
        replace: bool = False,
    ) -> tuple[LegacyConfigRegistration, str]:
        source = _bounded(self.root, path, exists=True)
        runner = _bounded(self.root, entrypoint, exists=True)
        workdir = _bounded(self.root, working_directory, exists=True)
        destination = _bounded(self.root, output)
        if source.suffix.lower() not in {".yaml", ".yml"} or not source.is_file():
            raise ConfigError(f"legacy config must be a YAML file: {source}")
        if runner.suffix != ".py" or not runner.is_file():
            raise ConfigError(f"legacy entrypoint must be a Python file: {runner}")
        if not workdir.is_dir():
            raise ConfigError(f"legacy working directory is not a directory: {workdir}")
        old = _yaml_mapping(source)
        item = LegacyConfigRegistration(
            name=name or _experiment_name(old, source.stem),
            path=source.relative_to(self.root).as_posix(),
            entrypoint=runner.relative_to(self.root).as_posix(),
            output=destination.relative_to(self.root).as_posix(),
            arguments=list(arguments or []),
            working_directory=workdir.relative_to(self.root).as_posix(),
            description=description,
        )
        document = self.load()
        if any(row.name == item.name for row in document.legacy_configs) and not replace:
            raise RegistryError(f"legacy config {item.name!r} is already registered")
        document.legacy_configs = [
            row for row in document.legacy_configs if row.name != item.name
        ]
        document.legacy_configs.append(item)
        document.legacy_configs.sort(key=lambda row: row.name)
        self.save(document)
        content = legacy_wrapper_config(self.root, item, old)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return item, content

    def remove_python(self, kind: str, name: str) -> bool:
        document = self.load()
        remaining = [
            row for row in document.python if (row.kind, row.name) != (kind, name)
        ]
        if len(remaining) == len(document.python):
            return False
        document.python = remaining
        self.save(document)
        return True

    def remove_legacy_config(self, name: str) -> bool:
        document = self.load()
        remaining = [row for row in document.legacy_configs if row.name != name]
        if len(remaining) == len(document.legacy_configs):
            return False
        document.legacy_configs = remaining
        self.save(document)
        return True


def legacy_wrapper_config(
    root: Path,
    registration: LegacyConfigRegistration,
    document: Mapping[str, Any] | None = None,
) -> str:
    old = dict(document or _yaml_mapping(root / registration.path))
    if not is_legacy_config(old):
        raise ConfigError(f"{registration.path} already looks like a current config")
    accelerator = "auto"
    experiment = old.get("experiment")
    if isinstance(experiment, Mapping):
        device = str(experiment.get("device") or "auto").lower()
        if device == "cpu":
            accelerator = "cpu"
        elif device.startswith("cuda"):
            accelerator = "cuda"
    config = parse_config(
        {
            "version": 1,
            "experiment": {
                "name": registration.name,
                "description": registration.description
                or f"Compatibility wrapper for {registration.path}",
                "tags": ["legacy", "compatibility"],
            },
            "stages": [
                {
                    "name": "legacy",
                    "type": "core/legacy-config",
                    "params": {
                        "config_path": registration.path,
                        "entrypoint": registration.entrypoint,
                        "arguments": registration.arguments,
                        "working_directory": registration.working_directory,
                    },
                }
            ],
            "resources": {"accelerator": accelerator, "devices": 1},
            "artifacts": {"root": "runs"},
        }
    )
    return dump_config(config, compact=True)


def _identifier(value: str) -> str:
    result = "".join(char if char.isalnum() or char == "_" else "_" for char in value)
    return f"_{result}" if not result or result[0].isdigit() else result


def _namespace(name: str, path: Path) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    module = ModuleType(name)
    module.__package__ = name
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    module.__file__ = None
    sys.modules[name] = module
    return module


def load_python_file(path: str | Path, *, project_root: str | Path) -> ModuleType:
    root = _root(project_root)
    source = _bounded(root, path, exists=True)
    if source.suffix != ".py" or not source.is_file():
        raise RegistryError(f"Python source is not a .py file: {source}")
    package = "_research_assistant_project_" + hashlib.sha256(
        str(root).encode()
    ).hexdigest()[:16]
    _namespace(package, root)
    package_path = root
    for part in source.relative_to(root).parent.parts:
        package_path /= part
        package = f"{package}.{_identifier(part)}"
        _namespace(package, package_path)
    module_name = (
        package
        if source.name == "__init__.py"
        else f"{package}.{_identifier(source.stem)}"
    )
    cached = sys.modules.get(module_name)
    if cached is not None and getattr(cached, "__file__", None) == str(source):
        return cached
    spec = importlib.util.spec_from_file_location(
        module_name,
        source,
        submodule_search_locations=[str(source.parent)] if source.name == "__init__.py" else None,
    )
    if spec is None or spec.loader is None:
        raise RegistryError(f"cannot import Python file {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous = list(sys.path)
    sys.path[:0] = [str(root), str(source.parent)]
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise RegistryError(f"cannot import Python file {source}: {exc}") from exc
    finally:
        sys.path[:] = previous
    return module


def _component_schema(target: Any, name: str) -> tuple[type[BaseModel], bool]:
    inspected = target.__init__ if inspect.isclass(target) else target
    signature = inspect.signature(target)
    try:
        hints = get_type_hints(inspected)
    except Exception:
        hints = {}
    fields: dict[str, tuple[Any, Any]] = {}
    context_parameter = False
    allow_extra = False
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            if parameter.default is inspect.Parameter.empty:
                raise RegistryError(
                    f"{target!r} has required positional-only parameter {parameter.name!r}"
                )
            continue
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            allow_extra = True
            continue
        if parameter.name in {"context", "stage_context"}:
            context_parameter = True
            continue
        annotation = hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Parameter.empty or isinstance(annotation, str):
            annotation = Any
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotation, default)
    model_config = ConfigDict(
        extra="allow" if allow_extra else "forbid",
        arbitrary_types_allowed=True,
    )
    try:
        model = create_model(name, __config__=model_config, **fields)
        model.model_json_schema()
    except Exception:
        model = create_model(
            name,
            __config__=model_config,
            **{key: (Any, default) for key, (_, default) in fields.items()},
        )
    return model, context_parameter


def register_python_component(
    registry: Registry,
    root: Path,
    registration: PythonRegistration,
) -> None:
    module = load_python_file(registration.path, project_root=root)
    target = getattr(module, registration.symbol, None)
    if not callable(target):
        raise RegistryError(
            f"{registration.path} does not expose callable {registration.symbol!r}"
        )
    if inspect.iscoroutinefunction(target):
        raise RegistryError("async component factories are not supported")
    model_name = "Registered" + "".join(
        part.title() for part in registration.name.replace("/", "_").split("_")
    )
    schema, with_context = _component_schema(target, f"{model_name}Params")

    def factory(params: BaseModel, context: Any) -> Any:
        values = params.model_dump(exclude_unset=True)
        if with_context:
            values["context"] = context
        return target(**values)

    registry.add(
        registration.kind,
        registration.name,
        factory=factory,
        schema=schema,
        description=registration.description,
        provider=f"file:{registration.path}#{registration.symbol}",
        catalog=registration.catalog,
        editor=registration.editor,
        metadata={
            "source": registration.path,
            "symbol": registration.symbol,
            "registration": "project-python",
        },
    )


def register_project_catalog(
    registry: Registry,
    project_root: str | Path | None = None,
) -> Path | None:
    root = find_project_root(project_root)
    if root is None:
        return None
    os.environ["RA_PROJECT_ROOT"] = str(root)
    for registration in ProjectRegistrationCatalog(root).load().python:
        register_python_component(registry, root, registration)
    return root


def register_file_plugin(
    registry: Registry,
    path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> ModuleType:
    root = _root(project_root or Path.cwd())
    module = load_python_file(path, project_root=root)
    register = getattr(module, "register", None)
    if not callable(register):
        raise RegistryError(f"{path} does not expose register(registry)")
    try:
        register(registry)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError(f"Python plugin {path} failed to register: {exc}") from exc
    return module


def _stage_path(root: Path, value: str, *, directory: bool = False) -> Path:
    try:
        path = _bounded(root, value, exists=True)
    except RegistryError as exc:
        raise ExecutionError(str(exc)) from exc
    if directory and not path.is_dir():
        raise ExecutionError(f"expected a directory: {path}")
    if not directory and not path.is_file():
        raise ExecutionError(f"expected a file: {path}")
    return path


def run_legacy_config(params: LegacyConfigStageParams, context: StageContext) -> StageResult:
    root = find_project_root() or _root(os.environ.get("RA_PROJECT_ROOT", Path.cwd()))
    config = _stage_path(root, params.config_path)
    entrypoint = _stage_path(root, params.entrypoint)
    workdir = _stage_path(root, params.working_directory, directory=True)
    command = [params.python or sys.executable, str(entrypoint)]
    flag = params.resume_flag if context.resume else params.no_resume_flag
    if flag:
        command.append(flag)
    command.extend(params.arguments)
    command.append(str(config))
    environment = os.environ.copy()
    environment.update(params.environment)
    completed = subprocess.run(command, cwd=workdir, env=environment, check=False)
    if completed.returncode:
        raise ExecutionError(
            f"legacy runner exited with status {completed.returncode}: {' '.join(command)}"
        )
    return StageResult()


def register_legacy_stage(registry: Registry) -> None:
    registry.add(
        "stage",
        "core/legacy-config",
        factory=run_legacy_config,
        schema=LegacyConfigStageParams,
        description="Run an existing YAML through its original Python entrypoint.",
        provider="research-assistant",
        metadata={"compatibility": "legacy-yaml"},
    )
