from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from research_assistant.errors import RegistryError
from research_assistant.models import COMPONENT_NAME_PATTERN, ComponentRef

Factory = Callable[[BaseModel, Any], Any]


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    kind: str
    name: str
    factory: Factory
    schema: type[BaseModel]
    description: str = ""
    provider: str = "local"


class Registry:
    def __init__(self) -> None:
        self._components: dict[tuple[str, str], ComponentSpec] = {}

    def add(
        self,
        kind: str,
        name: str,
        *,
        factory: Factory,
        schema: type[BaseModel],
        description: str = "",
        provider: str = "local",
    ) -> None:
        import re

        if not re.fullmatch(COMPONENT_NAME_PATTERN, name):
            raise RegistryError(f"component name {name!r} must use the namespace/name form")
        key = (kind, name)
        if key in self._components:
            previous = self._components[key]
            raise RegistryError(
                f"duplicate {kind} component {name!r}; already provided by {previous.provider}"
            )
        self._components[key] = ComponentSpec(
            kind=kind,
            name=name,
            factory=factory,
            schema=schema,
            description=description,
            provider=provider,
        )

    def get(self, kind: str, name: str) -> ComponentSpec:
        try:
            return self._components[(kind, name)]
        except KeyError as exc:
            available = ", ".join(spec.name for spec in self.list(kind)) or "none"
            raise RegistryError(
                f"unknown {kind} component {name!r}; available: {available}"
            ) from exc

    def list(self, kind: str | None = None) -> list[ComponentSpec]:
        specs = self._components.values()
        if kind is not None:
            specs = (spec for spec in specs if spec.kind == kind)
        return sorted(specs, key=lambda item: (item.kind, item.name))

    def validate(self, kind: str, reference: ComponentRef | dict[str, Any]) -> BaseModel:
        if not isinstance(reference, ComponentRef):
            reference = ComponentRef.model_validate(reference)
        spec = self.get(kind, reference.type)
        try:
            return spec.schema.model_validate(reference.params)
        except ValidationError as exc:
            raise RegistryError(f"invalid parameters for {kind} {reference.type}: {exc}") from exc

    def invoke(self, kind: str, reference: ComponentRef | dict[str, Any], context: Any) -> Any:
        if not isinstance(reference, ComponentRef):
            reference = ComponentRef.model_validate(reference)
        spec = self.get(kind, reference.type)
        params = self.validate(kind, reference)
        return spec.factory(params, context)

    def schema(self, kind: str, name: str) -> dict[str, Any]:
        return self.get(kind, name).schema.model_json_schema()
