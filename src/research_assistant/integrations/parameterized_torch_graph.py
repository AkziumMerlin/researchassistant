from __future__ import annotations

import copy
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_assistant.errors import RegistryError
from research_assistant.integrations.torch_graph import (
    GraphNode,
    TorchGraphParams,
    build_graph_model,
    validate_graph,
)
from research_assistant.registry import Registry

_VARIABLE_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_VARIABLE_REF_KEY = "$var"


class ParameterizedTorchGraphParams(BaseModel):
    """A torch graph with reusable JSON-valued architecture variables.

    Node parameters reference a variable with ``{"$var": "name"}``. References may appear
    recursively inside lists and mappings. Matrix axes can override concrete values through paths
    such as ``components.model.params.variables.width`` before registry validation.
    """

    model_config = ConfigDict(extra="forbid")

    variables: dict[str, Any] = Field(default_factory=dict)
    input_names: list[str] = Field(default_factory=lambda: ["input"], min_length=1)
    nodes: list[GraphNode] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_variables_and_topology(self) -> ParameterizedTorchGraphParams:
        invalid = sorted(name for name in self.variables if _VARIABLE_NAME.fullmatch(name) is None)
        if invalid:
            raise ValueError(
                "invalid architecture variable names: "
                + ", ".join(invalid)
                + "; use letters, digits and underscore, beginning with a letter"
            )
        references: set[str] = set()
        for node in self.nodes:
            _collect_variable_references(node.params, references)
        missing = sorted(references - set(self.variables))
        if missing:
            raise ValueError(f"unknown architecture variables: {', '.join(missing)}")
        _as_unresolved_graph(self)
        return self


def variable_reference(name: str) -> dict[str, str]:
    if _VARIABLE_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid architecture variable name {name!r}")
    return {_VARIABLE_REF_KEY: name}


def _is_variable_reference(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {_VARIABLE_REF_KEY}
        and isinstance(value[_VARIABLE_REF_KEY], str)
    )


def _collect_variable_references(value: Any, result: set[str]) -> None:
    if _is_variable_reference(value):
        result.add(value[_VARIABLE_REF_KEY])
        return
    if isinstance(value, dict):
        for nested in value.values():
            _collect_variable_references(nested, result)
    elif isinstance(value, list):
        for nested in value:
            _collect_variable_references(nested, result)


def _resolve_value(value: Any, variables: dict[str, Any]) -> Any:
    if _is_variable_reference(value):
        name = value[_VARIABLE_REF_KEY]
        if name not in variables:
            raise RegistryError(f"unknown architecture variable {name!r}")
        return copy.deepcopy(variables[name])
    if isinstance(value, dict):
        return {key: _resolve_value(nested, variables) for key, nested in value.items()}
    if isinstance(value, list):
        return [_resolve_value(nested, variables) for nested in value]
    return copy.deepcopy(value)


def _as_unresolved_graph(params: ParameterizedTorchGraphParams) -> TorchGraphParams:
    """Reuse the base graph's name and DAG validation without resolving node parameters."""

    return TorchGraphParams(
        input_names=params.input_names,
        nodes=params.nodes,
        outputs=params.outputs,
    )


def resolve_parameterized_graph(params: ParameterizedTorchGraphParams) -> TorchGraphParams:
    nodes = [
        node.model_copy(update={"params": _resolve_value(node.params, params.variables)}, deep=True)
        for node in params.nodes
    ]
    return TorchGraphParams(
        input_names=list(params.input_names),
        nodes=nodes,
        outputs=list(params.outputs),
    )


def validate_parameterized_graph(params: BaseModel, registry: Registry) -> None:
    if not isinstance(params, ParameterizedTorchGraphParams):
        raise TypeError("parameterized torch graph validator received the wrong parameter schema")
    validate_graph(resolve_parameterized_graph(params), registry)


def build_parameterized_graph(params: ParameterizedTorchGraphParams, context: Any) -> Any:
    resolved = resolve_parameterized_graph(params)
    return build_graph_model(resolved, context)


def register(registry: Registry) -> None:
    registry.add(
        "model",
        "torch/parameterized-graph",
        factory=build_parameterized_graph,
        schema=ParameterizedTorchGraphParams,
        description=(
            "Build a reusable PyTorch DAG whose module parameters may reference named architecture "
            "variables."
        ),
        provider="research-assistant[torch]",
        editor="torch-graph",
        validator=validate_parameterized_graph,
        metadata={"architecture_variables": True},
    )
