from __future__ import annotations

import importlib
from collections.abc import Callable
from importlib.metadata import entry_points

from research_assistant.builtin import register as register_builtin
from research_assistant.errors import RegistryError
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


def load_registry(modules: list[str] | None = None) -> Registry:
    registry = Registry()
    register_builtin(registry)

    for point in entry_points(group=PLUGIN_GROUP):
        try:
            register = point.load()
        except Exception as exc:
            raise RegistryError(f"cannot load plugin entry point {point.name!r}: {exc}") from exc
        _register_callable(register, registry, f"entry-point:{point.name}")

    for module_name in modules or []:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RegistryError(f"cannot import plugin module {module_name!r}: {exc}") from exc
        _register_callable(getattr(module, "register", None), registry, module_name)

    return registry
