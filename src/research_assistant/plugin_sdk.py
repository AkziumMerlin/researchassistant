from __future__ import annotations

import importlib
import re
from dataclasses import asdict, dataclass
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant import __version__
from research_assistant.errors import RegistryError

ContractState = Literal["compatible", "legacy", "incompatible"]
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[+.-].*)?$")


class PluginContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[+.-].*)?$")
    minimum_research_assistant: str = "0.3.0"
    maximum_research_assistant_exclusive: str | None = None
    config_schema_versions: list[int] = Field(default_factory=lambda: [1])
    architecture_schema_versions: list[int] = Field(default_factory=lambda: [2])
    capabilities: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PluginDiagnostic:
    provider: str
    state: ContractState
    contract: dict[str, Any] | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise RegistryError(f"invalid semantic version {value!r}")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def validate_plugin_contract(contract: PluginContract) -> None:
    current = _version_tuple(__version__.split("+", 1)[0])
    minimum = _version_tuple(contract.minimum_research_assistant)
    if current < minimum:
        raise RegistryError(
            f"plugin {contract.name!r} requires ResearchAssistant >= "
            f"{contract.minimum_research_assistant}; installed version is {__version__}"
        )
    if contract.maximum_research_assistant_exclusive is not None:
        maximum = _version_tuple(contract.maximum_research_assistant_exclusive)
        if current >= maximum:
            raise RegistryError(
                f"plugin {contract.name!r} requires ResearchAssistant < "
                f"{contract.maximum_research_assistant_exclusive}; installed version is {__version__}"
            )
    if 1 not in contract.config_schema_versions:
        raise RegistryError(
            f"plugin {contract.name!r} does not declare support for config schema version 1"
        )


def contract_from_module(module: ModuleType, provider: str) -> PluginDiagnostic:
    raw = getattr(module, "RESEARCH_ASSISTANT_PLUGIN", None)
    if raw is None:
        return PluginDiagnostic(
            provider=provider,
            state="legacy",
            contract=None,
            message=(
                "plugin does not declare RESEARCH_ASSISTANT_PLUGIN; it remains compatible "
                "during the pre-1.0 transition"
            ),
        )
    try:
        contract = PluginContract.model_validate(raw)
        validate_plugin_contract(contract)
    except Exception as exc:
        return PluginDiagnostic(
            provider=provider,
            state="incompatible",
            contract=raw if isinstance(raw, dict) else None,
            message=str(exc),
        )
    return PluginDiagnostic(
        provider=provider,
        state="compatible",
        contract=contract.model_dump(mode="json"),
        message="plugin compatibility contract is valid",
    )


def inspect_provider(provider: str, register: object | None = None) -> PluginDiagnostic:
    module_name = getattr(register, "__module__", None) if register is not None else provider
    try:
        module = importlib.import_module(str(module_name))
    except Exception as exc:
        return PluginDiagnostic(
            provider=provider,
            state="legacy",
            contract=None,
            message=f"cannot inspect plugin module contract: {exc}",
        )
    return contract_from_module(module, provider)


def require_compatible(diagnostic: PluginDiagnostic) -> None:
    if diagnostic.state == "incompatible":
        raise RegistryError(f"incompatible plugin {diagnostic.provider!r}: {diagnostic.message}")
