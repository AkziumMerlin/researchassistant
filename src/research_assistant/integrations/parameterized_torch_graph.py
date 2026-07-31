from __future__ import annotations

import ast
import copy
import re
from collections import deque
from importlib import import_module
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_assistant.errors import ExecutionError, RegistryError
from research_assistant.integrations.torch_graph import (
    GraphNode,
    GraphPosition,
    TorchGraphParams,
    build_graph_model,
    validate_graph,
)
from research_assistant.models import COMPONENT_NAME_PATTERN
from research_assistant.registry import Registry

_VARIABLE_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_SOURCE_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
_PYTHON_TARGET = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_.]*(?::|\.)[a-zA-Z_][a-zA-Z0-9_.]*$"
)
_VARIABLE_REF_KEY = "$var"
_EXPRESSION_KEY = "$expr"
_CONDITIONAL_KEY = "$if"
_MAX_REPEAT_COUNT = 4096

VariableType = Literal["int", "float", "bool", "string", "enum", "shape", "json"]
NodeKind = Literal["module", "python", "composite", "repeat", "switch"]
CallStyle = Literal["auto", "positional", "keyword"]
WeightMode = Literal["independent", "shared"]


class ArchitectureVariableSpec(BaseModel):
    """UI and validation metadata for a concrete architecture variable value."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: VariableType = "json"
    description: str = ""
    choices: list[Any] | None = None
    minimum: float | None = Field(default=None, alias="min")
    maximum: float | None = Field(default=None, alias="max")
    enabled_if: str | None = None

    @model_validator(mode="after")
    def validate_definition(self) -> ArchitectureVariableSpec:
        if self.type == "enum" and not self.choices:
            raise ValueError("enum architecture variables require non-empty choices")
        if self.type != "enum" and self.choices is not None:
            raise ValueError("choices are supported only for enum variables")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("variable minimum cannot exceed maximum")
        if self.enabled_if is not None:
            _parse_expression(self.enabled_if)
        return self


class ParameterizedGraphNode(BaseModel):
    """One executable module or one compile-time architecture control node."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    kind: NodeKind = "module"
    type: str | None = Field(default=None, pattern=COMPONENT_NAME_PATTERN)
    target: str | None = None
    template: str | None = None
    inputs: list[str] | dict[str, str] = Field(default_factory=lambda: ["input"])
    params: dict[str, Any] = Field(default_factory=dict)
    output_ports: list[str] = Field(default_factory=lambda: ["output"], min_length=1)
    call_style: CallStyle = "auto"
    count: Any | None = None
    weights: WeightMode = "independent"
    index_name: str = "index"
    carry: dict[str, str] = Field(default_factory=dict)
    selector: Any | None = None
    branches: dict[str, str] = Field(default_factory=dict)
    default_branch: str | None = None
    label: str | None = None
    position: GraphPosition = Field(default_factory=GraphPosition)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> ParameterizedGraphNode:
        if len(self.output_ports) != len(set(self.output_ports)):
            raise ValueError(f"node {self.id!r} output ports must be unique")
        for port in self.output_ports:
            _validate_identifier(port, "output port")
        for source in _input_sources(self.inputs):
            if _SOURCE_NAME.fullmatch(source) is None:
                raise ValueError(f"node {self.id!r} has invalid input source {source!r}")
        if isinstance(self.inputs, dict):
            for port in self.inputs:
                _validate_identifier(port, "input port")
        if self.kind == "module":
            if self.type is None:
                raise ValueError(f"module node {self.id!r} requires type")
        elif self.kind == "python":
            if self.target is None or _PYTHON_TARGET.fullmatch(self.target) is None:
                raise ValueError(
                    f"python node {self.id!r} requires target like package.module:Class"
                )
        elif self.kind == "composite":
            if not self.template:
                raise ValueError(f"composite node {self.id!r} requires template")
        elif self.kind == "repeat":
            if not self.template:
                raise ValueError(f"repeat node {self.id!r} requires template")
            if self.count is None:
                raise ValueError(f"repeat node {self.id!r} requires count")
            _validate_identifier(self.index_name, "repeat index")
        elif self.kind == "switch":
            if self.selector is None:
                raise ValueError(f"switch node {self.id!r} requires selector")
            if not self.branches and self.default_branch is None:
                raise ValueError(f"switch node {self.id!r} requires branches")
        return self


class GraphTemplate(BaseModel):
    """Reusable named subgraph with named tensor inputs and outputs."""

    model_config = ConfigDict(extra="forbid")

    input_names: list[str] = Field(default_factory=lambda: ["input"], min_length=1)
    nodes: list[ParameterizedGraphNode] = Field(default_factory=list)
    outputs: list[str] | dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_names_and_topology(self) -> GraphTemplate:
        _validate_template_topology(self)
        return self


class ParameterizedTorchGraphParams(BaseModel):
    """A typed visual PyTorch architecture language.

    The legacy static DAG remains valid. Advanced graphs may additionally use typed variables,
    safe expressions, named tensor ports, reusable subgraphs, compile-time switches, repeated
    blocks with independent or shared weights, and workspace Python ``nn.Module`` classes.
    Matrix axes continue to override concrete values through paths such as
    ``components.model.params.variables.width``.
    """

    model_config = ConfigDict(extra="forbid")

    variables: dict[str, Any] = Field(default_factory=dict)
    variable_specs: dict[str, ArchitectureVariableSpec] = Field(default_factory=dict)
    input_names: list[str] = Field(default_factory=lambda: ["input"], min_length=1)
    nodes: list[ParameterizedGraphNode] = Field(min_length=1)
    outputs: list[str] | dict[str, str] = Field(min_length=1)
    subgraphs: dict[str, GraphTemplate] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_architecture(self) -> ParameterizedTorchGraphParams:
        names = set(self.variables) | set(self.variable_specs)
        invalid = sorted(name for name in names if _VARIABLE_NAME.fullmatch(name) is None)
        if invalid:
            raise ValueError(
                "invalid architecture variable names: "
                + ", ".join(invalid)
                + "; use letters, digits and underscore, beginning with a letter"
            )
        unknown_specs = sorted(set(self.variable_specs) - set(self.variables))
        if unknown_specs:
            raise ValueError(
                "variable specs require concrete values in variables: "
                + ", ".join(unknown_specs)
            )
        _validate_variable_values(self.variables, self.variable_specs)
        for name in self.subgraphs:
            _validate_identifier(name, "subgraph name")
        _validate_template_topology(self.root_template())
        references: set[str] = set()
        loop_names: set[str] = set()
        _collect_graph_variable_references(self.root_template(), references)
        _collect_repeat_index_names(self.root_template(), loop_names)
        for template in self.subgraphs.values():
            _collect_graph_variable_references(template, references)
            _collect_repeat_index_names(template, loop_names)
        missing = sorted(references - set(self.variables) - loop_names)
        if missing:
            raise ValueError(f"unknown architecture variables: {', '.join(missing)}")
        return self

    def root_template(self) -> GraphTemplate:
        return GraphTemplate(
            input_names=self.input_names,
            nodes=self.nodes,
            outputs=self.outputs,
        )


def variable_reference(name: str) -> dict[str, str]:
    if _VARIABLE_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid architecture variable name {name!r}")
    return {_VARIABLE_REF_KEY: name}


def expression_reference(expression: str) -> dict[str, str]:
    _parse_expression(expression)
    return {_EXPRESSION_KEY: expression}


def _validate_identifier(value: str, description: str) -> None:
    if _VARIABLE_NAME.fullmatch(value) is None:
        raise ValueError(f"invalid {description} {value!r}")


def _input_sources(inputs: list[str] | dict[str, str]) -> list[str]:
    return list(inputs.values()) if isinstance(inputs, dict) else list(inputs)


def _output_mapping(outputs: list[str] | dict[str, str]) -> dict[str, str]:
    if isinstance(outputs, dict):
        return dict(outputs)
    if len(outputs) == 1:
        return {"output": outputs[0]}
    return {f"output_{index}": source for index, source in enumerate(outputs)}


def _source_owner(source: str) -> str:
    return source.split(".", 1)[0]


def _node_references(node: ParameterizedGraphNode) -> set[str]:
    return {_source_owner(source) for source in _input_sources(node.inputs)}


def _validate_template_topology(template: GraphTemplate) -> list[str]:
    if len(template.input_names) != len(set(template.input_names)):
        raise ValueError("graph input names must be unique")
    for name in template.input_names:
        _validate_identifier(name, "graph input")
    node_ids = [node.id for node in template.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("graph node ids must be unique")
    overlap = sorted(set(template.input_names) & set(node_ids))
    if overlap:
        raise ValueError(f"graph inputs and nodes share names: {', '.join(overlap)}")

    node_by_id = {node.id: node for node in template.nodes}
    known_sources = set(template.input_names)
    for node in template.nodes:
        for port in node.output_ports:
            known_sources.add(f"{node.id}.{port}")
        if len(node.output_ports) == 1:
            known_sources.add(node.id)

    dependencies: dict[str, set[str]] = {}
    followers: dict[str, list[str]] = {node_id: [] for node_id in node_by_id}
    known_owners = set(node_by_id) | set(template.input_names)
    for node in template.nodes:
        missing_sources = sorted(set(_input_sources(node.inputs)) - known_sources)
        if missing_sources:
            raise ValueError(
                f"node {node.id!r} has unknown inputs: {', '.join(missing_sources)}"
            )
        owners = _node_references(node)
        missing_owners = sorted(owners - known_owners)
        if missing_owners:
            raise ValueError(
                f"node {node.id!r} has unknown input owners: {', '.join(missing_owners)}"
            )
        if node.id in owners:
            raise ValueError(f"node {node.id!r} cannot consume itself")
        node_dependencies = owners & set(node_by_id)
        dependencies[node.id] = set(node_dependencies)
        for source in node_dependencies:
            followers[source].append(node.id)

    outputs = _output_mapping(template.outputs)
    if len(outputs) != len(set(outputs)):
        raise ValueError("graph output names must be unique")
    for name in outputs:
        _validate_identifier(name, "graph output")
    unknown_outputs = sorted(set(outputs.values()) - known_sources)
    if unknown_outputs:
        raise ValueError(f"graph has unknown outputs: {', '.join(unknown_outputs)}")

    ready = deque(node.id for node in template.nodes if not dependencies[node.id])
    order: list[str] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for follower in followers[current]:
            dependencies[follower].discard(current)
            if not dependencies[follower]:
                ready.append(follower)
    if len(order) != len(template.nodes):
        blocked = sorted(node_id for node_id, value in dependencies.items() if value)
        raise ValueError(f"graph contains a cycle involving: {', '.join(blocked)}")
    return order


def _is_marker(value: Any, key: str) -> bool:
    return isinstance(value, dict) and set(value) == {key}


def _collect_binding_references(value: Any, result: set[str]) -> None:
    if _is_marker(value, _VARIABLE_REF_KEY):
        name = value[_VARIABLE_REF_KEY]
        if isinstance(name, str):
            result.add(name)
        return
    if _is_marker(value, _EXPRESSION_KEY):
        expression = value[_EXPRESSION_KEY]
        if isinstance(expression, str):
            result.update(_expression_names(expression))
        return
    if _is_marker(value, _CONDITIONAL_KEY):
        payload = value[_CONDITIONAL_KEY]
        if isinstance(payload, dict):
            for nested in payload.values():
                _collect_binding_references(nested, result)
        return
    if isinstance(value, dict):
        for nested in value.values():
            _collect_binding_references(nested, result)
    elif isinstance(value, list):
        for nested in value:
            _collect_binding_references(nested, result)


def _collect_graph_variable_references(template: GraphTemplate, result: set[str]) -> None:
    for node in template.nodes:
        _collect_binding_references(node.params, result)
        _collect_binding_references(node.count, result)
        _collect_binding_references(node.selector, result)


def _collect_repeat_index_names(template: GraphTemplate, result: set[str]) -> None:
    for node in template.nodes:
        if node.kind == "repeat":
            result.add(node.index_name)


_ALLOWED_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "bool": bool,
    "float": float,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "sum": sum,
}
_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)


def _parse_expression(expression: str) -> ast.Expression:
    if len(expression) > 1000:
        raise ValueError("architecture expressions cannot exceed 1000 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid architecture expression {expression!r}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 128:
        raise ValueError("architecture expressions cannot exceed 128 syntax nodes")
    for node in nodes:
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(
                f"unsupported expression construct {type(node).__name__} in {expression!r}"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
                raise ValueError(f"unsupported function call in expression {expression!r}")
            if node.keywords:
                raise ValueError("architecture expression calls do not accept keyword arguments")
    return tree


def _expression_names(expression: str) -> set[str]:
    tree = _parse_expression(expression)
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCTIONS
    }


def _evaluate_expression(expression: str, scope: dict[str, Any]) -> Any:
    tree = _parse_expression(expression)
    missing = sorted(_expression_names(expression) - set(scope))
    if missing:
        raise RegistryError(
            f"unknown names in architecture expression {expression!r}: {', '.join(missing)}"
        )
    environment = {**_ALLOWED_FUNCTIONS, **scope}
    code = compile(tree, "<architecture-expression>", "eval")
    return eval(code, {"__builtins__": {}}, environment)


def _resolve_value(value: Any, scope: dict[str, Any]) -> Any:
    if _is_marker(value, _VARIABLE_REF_KEY):
        name = value[_VARIABLE_REF_KEY]
        if not isinstance(name, str) or name not in scope:
            raise RegistryError(f"unknown architecture variable {name!r}")
        return copy.deepcopy(scope[name])
    if _is_marker(value, _EXPRESSION_KEY):
        expression = value[_EXPRESSION_KEY]
        if not isinstance(expression, str):
            raise RegistryError("$expr requires a string expression")
        return copy.deepcopy(_evaluate_expression(expression, scope))
    if _is_marker(value, _CONDITIONAL_KEY):
        payload = value[_CONDITIONAL_KEY]
        if not isinstance(payload, dict) or "condition" not in payload:
            raise RegistryError("$if requires condition, then and optional else values")
        condition = bool(_resolve_value(payload["condition"], scope))
        branch = payload.get("then") if condition else payload.get("else")
        return _resolve_value(branch, scope)
    if isinstance(value, dict):
        return {key: _resolve_value(nested, scope) for key, nested in value.items()}
    if isinstance(value, list):
        return [_resolve_value(nested, scope) for nested in value]
    return copy.deepcopy(value)


def _validate_variable_values(
    variables: dict[str, Any], specs: dict[str, ArchitectureVariableSpec]
) -> None:
    for name, spec in specs.items():
        value = variables[name]
        if spec.type == "bool":
            valid = isinstance(value, bool)
        elif spec.type == "int":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif spec.type == "float":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif spec.type == "string":
            valid = isinstance(value, str)
        elif spec.type == "enum":
            valid = value in (spec.choices or [])
        elif spec.type == "shape":
            valid = (
                isinstance(value, (list, tuple))
                and bool(value)
                and all(isinstance(item, int) and item > 0 for item in value)
            )
        else:
            valid = True
        if not valid:
            raise ValueError(
                f"architecture variable {name!r} does not match declared type {spec.type!r}"
            )
        if spec.minimum is not None and isinstance(value, (int, float)):
            if value < spec.minimum:
                raise ValueError(
                    f"architecture variable {name!r} is below minimum {spec.minimum}"
                )
        if spec.maximum is not None and isinstance(value, (int, float)):
            if value > spec.maximum:
                raise ValueError(
                    f"architecture variable {name!r} exceeds maximum {spec.maximum}"
                )
    for name, spec in specs.items():
        if spec.enabled_if is not None:
            result = _evaluate_expression(spec.enabled_if, variables)
            if not isinstance(result, bool):
                raise ValueError(f"enabled_if for {name!r} must evaluate to bool")


def _selector_key(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _template_for_name(
    name: str,
    subgraphs: dict[str, GraphTemplate],
    stack: tuple[str, ...],
) -> GraphTemplate:
    if name not in subgraphs:
        raise RegistryError(f"unknown architecture subgraph {name!r}")
    if name in stack:
        chain = " -> ".join((*stack, name))
        raise RegistryError(f"recursive architecture subgraphs are not supported: {chain}")
    return subgraphs[name]


def _validate_control_interface(
    node: ParameterizedGraphNode, template: GraphTemplate
) -> None:
    if isinstance(node.inputs, dict):
        missing = sorted(set(template.input_names) - set(node.inputs))
        extra = sorted(set(node.inputs) - set(template.input_names))
        if missing or extra:
            raise RegistryError(
                f"node {node.id!r} subgraph input mismatch; "
                f"missing={missing or 'none'}, extra={extra or 'none'}"
            )
    elif len(node.inputs) != len(template.input_names):
        raise RegistryError(
            f"node {node.id!r} passes {len(node.inputs)} inputs to a subgraph "
            f"expecting {len(template.input_names)}"
        )
    expected_outputs = set(_output_mapping(template.outputs))
    actual_outputs = set(node.output_ports)
    if actual_outputs != expected_outputs:
        raise RegistryError(
            f"node {node.id!r} output ports must match subgraph outputs; "
            f"expected={sorted(expected_outputs)}, got={sorted(actual_outputs)}"
        )


def _validate_template(
    template: GraphTemplate,
    registry: Registry,
    scope: dict[str, Any],
    subgraphs: dict[str, GraphTemplate],
    stack: tuple[str, ...],
) -> None:
    order = _validate_template_topology(template)
    node_by_id = {node.id: node for node in template.nodes}
    for node_id in order:
        node = node_by_id[node_id]
        if node.kind == "module":
            resolved = _resolve_value(node.params, scope)
            registry.validate("torch_module", {"type": node.type, "params": resolved})
            spec = registry.get("torch_module", node.type or "")
            metadata = dict(spec.metadata or {})
            exact = metadata.get("inputs")
            minimum = metadata.get("min_inputs")
            input_count = len(_input_sources(node.inputs))
            if isinstance(exact, int) and input_count != exact:
                raise RegistryError(
                    f"graph node {node.id!r} ({node.type}) requires {exact} input(s), "
                    f"got {input_count}"
                )
            if isinstance(minimum, int) and input_count < minimum:
                raise RegistryError(
                    f"graph node {node.id!r} ({node.type}) requires at least {minimum} "
                    f"inputs, got {input_count}"
                )
        elif node.kind == "python":
            _resolve_value(node.params, scope)
        elif node.kind == "composite":
            nested = _template_for_name(node.template or "", subgraphs, stack)
            _validate_control_interface(node, nested)
            _validate_template(
                nested,
                registry,
                scope,
                subgraphs,
                (*stack, node.template or ""),
            )
        elif node.kind == "repeat":
            count = _resolve_value(node.count, scope)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise RegistryError(f"repeat node {node.id!r} count must resolve to a positive int")
            if count > _MAX_REPEAT_COUNT:
                raise RegistryError(
                    f"repeat node {node.id!r} count exceeds {_MAX_REPEAT_COUNT}"
                )
            nested = _template_for_name(node.template or "", subgraphs, stack)
            _validate_control_interface(node, nested)
            nested_outputs = set(_output_mapping(nested.outputs))
            unknown_carry_inputs = sorted(set(node.carry) - set(nested.input_names))
            unknown_carry_outputs = sorted(set(node.carry.values()) - nested_outputs)
            if unknown_carry_inputs or unknown_carry_outputs:
                raise RegistryError(
                    f"repeat node {node.id!r} has invalid carry mapping; "
                    f"inputs={unknown_carry_inputs or 'none'}, "
                    f"outputs={unknown_carry_outputs or 'none'}"
                )
            if node.weights == "shared":
                names: set[str] = set()
                _collect_graph_variable_references(nested, names)
                if node.index_name in names:
                    raise RegistryError(
                        f"shared repeat node {node.id!r} cannot use index {node.index_name!r} "
                        "inside module parameters"
                    )
                nested_scope = {**scope, node.index_name: 0}
                _validate_template(
                    nested,
                    registry,
                    nested_scope,
                    subgraphs,
                    (*stack, node.template or ""),
                )
            else:
                for index in range(count):
                    nested_scope = {**scope, node.index_name: index}
                    _validate_template(
                        nested,
                        registry,
                        nested_scope,
                        subgraphs,
                        (*stack, node.template or ""),
                    )
        elif node.kind == "switch":
            selected = _selector_key(_resolve_value(node.selector, scope))
            template_name = node.branches.get(selected, node.default_branch)
            if template_name is None:
                raise RegistryError(
                    f"switch node {node.id!r} has no branch for selector {selected!r}"
                )
            nested = _template_for_name(template_name, subgraphs, stack)
            _validate_control_interface(node, nested)
            _validate_template(
                nested,
                registry,
                scope,
                subgraphs,
                (*stack, template_name),
            )


def _legacy_graph_supported(params: ParameterizedTorchGraphParams) -> bool:
    return (
        not params.subgraphs
        and isinstance(params.outputs, list)
        and all(
            node.kind == "module"
            and isinstance(node.inputs, list)
            and node.output_ports == ["output"]
            for node in params.nodes
        )
    )


def resolve_parameterized_graph(params: ParameterizedTorchGraphParams) -> TorchGraphParams:
    """Resolve a legacy-compatible parameterized DAG into the original graph schema."""

    if not _legacy_graph_supported(params):
        raise RegistryError(
            "advanced parameterized graphs cannot be flattened to TorchGraphParams; "
            "build them with build_parameterized_graph"
        )
    nodes = [
        GraphNode(
            id=node.id,
            type=node.type or "",
            inputs=list(node.inputs),
            params=_resolve_value(node.params, params.variables),
            label=node.label,
            position=node.position,
        )
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
    if _legacy_graph_supported(params):
        validate_graph(resolve_parameterized_graph(params), registry)
        return
    _validate_template(
        params.root_template(),
        registry,
        dict(params.variables),
        params.subgraphs,
        ("root",),
    )


def _torch() -> Any:
    try:
        return import_module("torch")
    except ModuleNotFoundError as exc:
        raise ExecutionError(
            "PyTorch is required to build torch/parameterized-graph; install "
            "ResearchAssistant with the 'torch' extra"
        ) from exc


def _load_python_class(target: str) -> Any:
    module_name, separator, attribute_path = target.partition(":")
    if not separator:
        module_name, _, attribute_path = target.rpartition(".")
    if not module_name or not attribute_path:
        raise RegistryError(f"invalid Python module target {target!r}")
    try:
        value: Any = import_module(module_name)
        for attribute in attribute_path.split("."):
            value = getattr(value, attribute)
    except (ImportError, AttributeError) as exc:
        raise RegistryError(f"cannot import Python module target {target!r}") from exc
    return value


def _inputs_for_template(
    node: ParameterizedGraphNode,
    template: GraphTemplate,
    values: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(node.inputs, dict):
        missing = sorted(set(template.input_names) - set(node.inputs))
        extra = sorted(set(node.inputs) - set(template.input_names))
        if missing or extra:
            raise TypeError(
                f"node {node.id!r} subgraph input mismatch; missing={missing or 'none'}, "
                f"extra={extra or 'none'}"
            )
        return {name: values[source] for name, source in node.inputs.items()}
    if len(node.inputs) != len(template.input_names):
        raise TypeError(
            f"node {node.id!r} passes {len(node.inputs)} values to a subgraph expecting "
            f"{len(template.input_names)}"
        )
    return {
        name: values[source]
        for name, source in zip(template.input_names, node.inputs, strict=True)
    }


def _unpack_result(result: Any, ports: list[str]) -> dict[str, Any]:
    if isinstance(result, dict):
        missing = sorted(set(ports) - set(result))
        if missing:
            raise TypeError(f"module result is missing named outputs: {', '.join(missing)}")
        return {port: result[port] for port in ports}
    if len(ports) == 1:
        return {ports[0]: result}
    if not isinstance(result, (tuple, list)) or len(result) != len(ports):
        raise TypeError(f"module must return {len(ports)} outputs for ports {ports}")
    return dict(zip(ports, result, strict=True))


def _pack_public_outputs(
    output_definition: list[str] | dict[str, str], output_values: dict[str, Any]
) -> Any:
    if isinstance(output_definition, dict):
        if len(output_values) == 1 and "output" in output_values:
            return output_values["output"]
        return output_values
    values = tuple(output_values.values())
    return values[0] if len(values) == 1 else values


def _store_node_outputs(
    values: dict[str, Any], node: ParameterizedGraphNode, result: dict[str, Any]
) -> None:
    for port, value in result.items():
        values[f"{node.id}.{port}"] = value
    if len(result) == 1:
        values[node.id] = next(iter(result.values()))


def _compile_template(
    template: GraphTemplate,
    scope: dict[str, Any],
    subgraphs: dict[str, GraphTemplate],
    context: Any,
    stack: tuple[str, ...],
) -> Any:
    torch = _torch()
    order = _validate_template_topology(template)
    nodes = {node.id: node for node in template.nodes}
    modules: dict[str, Any] = {}
    runtime: dict[str, tuple[str, Any]] = {}

    for node_id in order:
        node = nodes[node_id]
        if node.kind == "module":
            resolved = _resolve_value(node.params, scope)
            module = context.registry.invoke(
                "torch_module",
                {"type": node.type, "params": resolved},
                context,
            )
            modules[node.id] = module
            runtime[node.id] = ("module", None)
        elif node.kind == "python":
            params = _resolve_value(node.params, scope)
            module_class = _load_python_class(node.target or "")
            module = module_class(**params)
            if not isinstance(module, torch.nn.Module):
                raise RegistryError(f"Python target {node.target!r} did not create nn.Module")
            modules[node.id] = module
            runtime[node.id] = ("module", None)
        elif node.kind == "composite":
            nested = _template_for_name(node.template or "", subgraphs, stack)
            module = _compile_template(
                nested,
                scope,
                subgraphs,
                context,
                (*stack, node.template or ""),
            )
            modules[node.id] = module
            runtime[node.id] = ("composite", nested)
        elif node.kind == "repeat":
            count = _resolve_value(node.count, scope)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise RegistryError(f"repeat node {node.id!r} count must resolve to a positive int")
            nested = _template_for_name(node.template or "", subgraphs, stack)
            if node.weights == "shared":
                module = _compile_template(
                    nested,
                    {**scope, node.index_name: 0},
                    subgraphs,
                    context,
                    (*stack, node.template or ""),
                )
                modules[node.id] = module
            else:
                module = torch.nn.ModuleList(
                    [
                        _compile_template(
                            nested,
                            {**scope, node.index_name: index},
                            subgraphs,
                            context,
                            (*stack, node.template or ""),
                        )
                        for index in range(count)
                    ]
                )
                modules[node.id] = module
            runtime[node.id] = ("repeat", (nested, count))
        elif node.kind == "switch":
            selected = _selector_key(_resolve_value(node.selector, scope))
            template_name = node.branches.get(selected, node.default_branch)
            if template_name is None:
                raise RegistryError(
                    f"switch node {node.id!r} has no branch for selector {selected!r}"
                )
            nested = _template_for_name(template_name, subgraphs, stack)
            module = _compile_template(
                nested,
                scope,
                subgraphs,
                context,
                (*stack, template_name),
            )
            modules[node.id] = module
            runtime[node.id] = ("switch", nested)

    class ExecutableTemplate(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.graph_modules = torch.nn.ModuleDict(modules)
            self.input_names = tuple(template.input_names)
            self.execution_order = tuple(order)
            self.output_definition = copy.deepcopy(template.outputs)
            self.output_mapping = _output_mapping(template.outputs)

        def run_mapping(self, inputs: dict[str, Any]) -> dict[str, Any]:
            missing = sorted(set(self.input_names) - set(inputs))
            extra = sorted(set(inputs) - set(self.input_names))
            if missing or extra:
                raise TypeError(
                    f"subgraph input mismatch; missing={missing or 'none'}, "
                    f"extra={extra or 'none'}"
                )
            values = {name: inputs[name] for name in self.input_names}
            for current_id in self.execution_order:
                current = nodes[current_id]
                mode, metadata = runtime[current_id]
                module = self.graph_modules[current_id]
                if mode == "module":
                    if isinstance(current.inputs, dict):
                        named = {
                            name: values[source] for name, source in current.inputs.items()
                        }
                        if current.call_style == "positional":
                            result = module(*named.values())
                        else:
                            result = module(**named)
                    else:
                        incoming = [values[source] for source in current.inputs]
                        if current.call_style == "keyword":
                            raise TypeError(
                                f"node {current.id!r} uses keyword call style with unnamed inputs"
                            )
                        result = module(*incoming)
                    unpacked = _unpack_result(result, current.output_ports)
                elif mode in {"composite", "switch"}:
                    nested = metadata
                    nested_inputs = _inputs_for_template(current, nested, values)
                    unpacked = module.run_mapping(nested_inputs)
                elif mode == "repeat":
                    nested, count = metadata
                    repeated_inputs = _inputs_for_template(current, nested, values)
                    current_inputs = dict(repeated_inputs)
                    unpacked: dict[str, Any] = {}
                    for index in range(count):
                        repeated_module = (
                            module if current.weights == "shared" else module[index]
                        )
                        unpacked = repeated_module.run_mapping(current_inputs)
                        if index + 1 < count:
                            next_inputs = dict(repeated_inputs)
                            if current.carry:
                                for input_name, output_name in current.carry.items():
                                    if output_name not in unpacked:
                                        raise TypeError(
                                            f"repeat node {current.id!r} carry references unknown "
                                            f"output {output_name!r}"
                                        )
                                    next_inputs[input_name] = unpacked[output_name]
                            elif (
                                len(nested.input_names) == 1
                                and len(unpacked) == 1
                            ):
                                next_inputs[nested.input_names[0]] = next(iter(unpacked.values()))
                            else:
                                common = set(nested.input_names) & set(unpacked)
                                if not common:
                                    raise TypeError(
                                        f"repeat node {current.id!r} needs an explicit "
                                        "carry mapping"
                                    )
                                for input_name in common:
                                    next_inputs[input_name] = unpacked[input_name]
                            current_inputs = next_inputs
                else:  # pragma: no cover
                    raise AssertionError(mode)
                selected = {
                    port: unpacked[port]
                    for port in current.output_ports
                    if port in unpacked
                }
                if len(selected) != len(current.output_ports):
                    missing_ports = sorted(set(current.output_ports) - set(unpacked))
                    raise TypeError(
                        f"node {current.id!r} is missing outputs: {', '.join(missing_ports)}"
                    )
                _store_node_outputs(values, current, selected)
            return {name: values[source] for name, source in self.output_mapping.items()}

        def forward(self, *args: Any, **kwargs: Any) -> Any:
            if args and kwargs:
                raise TypeError("graph accepts positional or named inputs, not both")
            if kwargs:
                inputs = dict(kwargs)
            else:
                if len(args) != len(self.input_names):
                    raise TypeError(
                        f"graph expects {len(self.input_names)} positional input(s), "
                        f"got {len(args)}"
                    )
                inputs = dict(zip(self.input_names, args, strict=True))
            output_values = self.run_mapping(inputs)
            return _pack_public_outputs(self.output_definition, output_values)

    return ExecutableTemplate()


def build_parameterized_graph(params: ParameterizedTorchGraphParams, context: Any) -> Any:
    validate_parameterized_graph(params, context.registry)
    if _legacy_graph_supported(params):
        return build_graph_model(resolve_parameterized_graph(params), context)
    return _compile_template(
        params.root_template(),
        dict(params.variables),
        params.subgraphs,
        context,
        ("root",),
    )


def register(registry: Registry) -> None:
    registry.add(
        "model",
        "torch/parameterized-graph",
        factory=build_parameterized_graph,
        schema=ParameterizedTorchGraphParams,
        description=(
            "Build a typed visual PyTorch architecture with variables, expressions, named ports, "
            "subgraphs, repeats, switches and workspace Python modules."
        ),
        provider="research-assistant[torch]",
        editor="torch-graph",
        validator=validate_parameterized_graph,
        metadata={
            "architecture_variables": True,
            "typed_variables": True,
            "expressions": True,
            "named_ports": True,
            "subgraphs": True,
            "control_flow": ["repeat", "switch", "composite", "python"],
        },
    )
