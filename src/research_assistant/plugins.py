from __future__ import annotations

import importlib
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

from research_assistant.builtin import register as register_builtin
from research_assistant.errors import RegistryError
from research_assistant.legacy import register_file_plugin, register_project_catalog
from research_assistant.plugin_sdk import (
    contract_from_module,
    inspect_provider,
    require_compatible,
)
from research_assistant.registry import Registry

PLUGIN_GROUP = "research_assistant.plugins"
RegisterFunction = Callable[[Registry], None]


def _register_callable(register: object, registry: Registry, provider: str) -> None:
    if not callable(register):
        raise RegistryError(f"plugin {provider!r} does not expose a callable register function")
    try:
        register(registry)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError(f"plugin {provider!r} failed to register: {exc}") from exc


def _file_plugin_path(value: str) -> str | None:
    if value.startswith("file:"):
        return value.removeprefix("file:")
    if value.endswith(".py") or "/" in value or "\\" in value:
        return value
    return None


def load_registry(
    modules: list[str] | None = None,
    *,
    project_root: str | Path | None = None,
) -> Registry:
    registry = Registry()
    register_builtin(registry)
    diagnostics: list[dict[str, object]] = [
        {
            "provider": "research_assistant.builtin",
            "state": "compatible",
            "contract": {
                "name": "research-assistant-builtins",
                "version": "1.0.0",
                "config_schema_versions": [1],
                "architecture_schema_versions": [2],
            },
            "message": "built-in components use the installed core contract",
        }
    ]

    for point in entry_points(group=PLUGIN_GROUP):
        provider = f"entry-point:{point.name}"
        try:
            register = point.load()
        except Exception as exc:
            raise RegistryError(f"cannot load plugin entry point {point.name!r}: {exc}") from exc
        diagnostic = inspect_provider(provider, register)
        require_compatible(diagnostic)
        diagnostics.append(diagnostic.as_dict())
        _register_callable(register, registry, provider)

    root = Path(project_root or Path.cwd()).expanduser().resolve()
    for module_name in modules or []:
        file_path = _file_plugin_path(module_name)
        if file_path is not None:
            provider = f"file:{file_path}"
            module = register_file_plugin(registry, file_path, project_root=root)
            diagnostic = contract_from_module(module, provider)
            require_compatible(diagnostic)
            diagnostics.append(diagnostic.as_dict())
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RegistryError(f"cannot import plugin module {module_name!r}: {exc}") from exc
        register = getattr(module, "register", None)
        diagnostic = inspect_provider(module_name, register)
        require_compatible(diagnostic)
        diagnostics.append(diagnostic.as_dict())
        _register_callable(register, registry, module_name)

    catalog_root = register_project_catalog(registry, project_root)
    if catalog_root is not None:
        diagnostics.append(
            {
                "provider": str(catalog_root / ".research-assistant" / "registrations.yaml"),
                "state": "compatible",
                "contract": None,
                "message": "project-local Python component registrations loaded",
            }
        )

    registry.plugin_diagnostics = diagnostics
    return registry
