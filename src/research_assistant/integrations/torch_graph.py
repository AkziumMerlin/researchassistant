from __future__ import annotations

from collections import deque
from collections.abc import Callable
from functools import reduce
from importlib import import_module
from operator import add, mul
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from research_assistant.errors import ExecutionError, RegistryError
from research_assistant.models import COMPONENT_NAME_PATTERN
from research_assistant.registry import Registry

Size = int | list[int]
Padding = int | list[int] | Literal["same", "valid"]


class TorchModuleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LinearParams(TorchModuleParams):
    in_features: PositiveInt
    out_features: PositiveInt
    bias: bool = True


class LazyLinearParams(TorchModuleParams):
    out_features: PositiveInt
    bias: bool = True


class BilinearParams(TorchModuleParams):
    in1_features: PositiveInt
    in2_features: PositiveInt
    out_features: PositiveInt
    bias: bool = True


class ConvParams(TorchModuleParams):
    in_channels: PositiveInt
    out_channels: PositiveInt
    kernel_size: Size
    stride: Size = 1
    padding: Padding = 0
    dilation: Size = 1
    groups: PositiveInt = 1
    bias: bool = True
    padding_mode: Literal["zeros", "reflect", "replicate", "circular"] = "zeros"


class LazyConvParams(TorchModuleParams):
    out_channels: PositiveInt
    kernel_size: Size
    stride: Size = 1
    padding: Padding = 0
    dilation: Size = 1
    groups: PositiveInt = 1
    bias: bool = True
    padding_mode: Literal["zeros", "reflect", "replicate", "circular"] = "zeros"


class ConvTransposeParams(TorchModuleParams):
    in_channels: PositiveInt
    out_channels: PositiveInt
    kernel_size: Size
    stride: Size = 1
    padding: Size = 0
    output_padding: Size = 0
    groups: PositiveInt = 1
    bias: bool = True
    dilation: Size = 1


class BatchNormParams(TorchModuleParams):
    num_features: PositiveInt
    eps: float = Field(default=1e-5, gt=0)
    momentum: float | None = Field(default=0.1, ge=0)
    affine: bool = True
    track_running_stats: bool = True


class LayerNormParams(TorchModuleParams):
    normalized_shape: Size
    eps: float = Field(default=1e-5, gt=0)
    elementwise_affine: bool = True
    bias: bool = True


class GroupNormParams(TorchModuleParams):
    num_groups: PositiveInt
    num_channels: PositiveInt
    eps: float = Field(default=1e-5, gt=0)
    affine: bool = True


class DropoutParams(TorchModuleParams):
    p: float = Field(default=0.5, ge=0, le=1)
    inplace: bool = False


class InplaceParams(TorchModuleParams):
    inplace: bool = False


class LeakyReLUParams(InplaceParams):
    negative_slope: float = 0.01


class ELUParams(InplaceParams):
    alpha: float = 1.0


class SoftmaxParams(TorchModuleParams):
    dim: int = -1


class PoolParams(TorchModuleParams):
    kernel_size: Size
    stride: Size | None = None
    padding: Size = 0
    ceil_mode: bool = False


class MaxPoolParams(PoolParams):
    dilation: Size = 1
    return_indices: bool = False


class AdaptivePoolParams(TorchModuleParams):
    output_size: Size


class FlattenParams(TorchModuleParams):
    start_dim: int = 1
    end_dim: int = -1


class UnflattenParams(TorchModuleParams):
    dim: int
    unflattened_size: list[PositiveInt] = Field(min_length=1)


class UpsampleParams(TorchModuleParams):
    size: Size | None = None
    scale_factor: float | list[float] | None = Field(default=None)
    mode: Literal[
        "nearest",
        "nearest-exact",
        "linear",
        "bilinear",
        "bicubic",
        "trilinear",
        "area",
    ] = "nearest"
    align_corners: bool | None = None

    @model_validator(mode="after")
    def validate_size(self) -> UpsampleParams:
        if (self.size is None) == (self.scale_factor is None):
            raise ValueError("exactly one of size and scale_factor must be configured")
        return self


class EmbeddingParams(TorchModuleParams):
    num_embeddings: PositiveInt
    embedding_dim: PositiveInt
    padding_idx: int | None = None
    max_norm: float | None = Field(default=None, gt=0)
    norm_type: float = Field(default=2.0, gt=0)
    scale_grad_by_freq: bool = False
    sparse: bool = False


class ConcatParams(TorchModuleParams):
    dim: int = 1


class ReshapeParams(TorchModuleParams):
    shape: list[int] = Field(min_length=1)


class PermuteParams(TorchModuleParams):
    dims: list[int] = Field(min_length=1)


class GraphPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = 0
    y: float = 0


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    type: str = Field(pattern=COMPONENT_NAME_PATTERN)
    inputs: list[str] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None
    position: GraphPosition = Field(default_factory=GraphPosition)


class TorchGraphParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_names: list[str] = Field(default_factory=lambda: ["input"], min_length=1)
    nodes: list[GraphNode] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_names_and_topology(self) -> TorchGraphParams:
        if len(self.input_names) != len(set(self.input_names)):
            raise ValueError("graph input names must be unique")
        for name in self.input_names:
            if not name or not name[0].isalpha() or not name.replace("_", "").isalnum():
                raise ValueError(f"invalid graph input name {name!r}")
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("graph node ids must be unique")
        overlap = sorted(set(self.input_names) & set(node_ids))
        if overlap:
            raise ValueError(f"graph inputs and nodes share names: {', '.join(overlap)}")
        _topological_order(self)
        return self


def _torch() -> Any:
    try:
        return import_module("torch")
    except ModuleNotFoundError as exc:
        raise ExecutionError(
            "PyTorch is required to build torch/graph; install ResearchAssistant "
            "with the 'torch' extra"
        ) from exc


def _module_factory(class_name: str) -> Callable[[BaseModel, Any], Any]:
    def build(params: BaseModel, _context: Any) -> Any:
        torch = _torch()
        module_class = getattr(torch.nn, class_name)
        return module_class(**params.model_dump())

    return build


def _custom_module_factory(operation: str) -> Callable[[BaseModel, Any], Any]:
    def build(params: BaseModel, _context: Any) -> Any:
        torch = _torch()

        if operation == "concat":

            class Concat(torch.nn.Module):
                def __init__(self, dim: int) -> None:
                    super().__init__()
                    self.dim = dim

                def forward(self, *values: Any) -> Any:
                    return torch.cat(values, dim=self.dim)

            return Concat(params.dim)

        if operation in {"add", "multiply"}:
            operator = add if operation == "add" else mul

            class Elementwise(torch.nn.Module):
                def forward(self, *values: Any) -> Any:
                    return reduce(operator, values)

            return Elementwise()

        if operation == "reshape":

            class Reshape(torch.nn.Module):
                def __init__(self, shape: list[int]) -> None:
                    super().__init__()
                    self.shape = tuple(shape)

                def forward(self, value: Any) -> Any:
                    return value.reshape(*self.shape)

            return Reshape(params.shape)

        if operation == "permute":

            class Permute(torch.nn.Module):
                def __init__(self, dims: list[int]) -> None:
                    super().__init__()
                    self.dims = tuple(dims)

                def forward(self, value: Any) -> Any:
                    return value.permute(*self.dims)

            return Permute(params.dims)

        raise AssertionError(f"unknown graph operation {operation}")

    return build


def _topological_order(params: TorchGraphParams) -> list[str]:
    node_ids = {node.id for node in params.nodes}
    known = node_ids | set(params.input_names)
    dependencies: dict[str, set[str]] = {}
    followers: dict[str, list[str]] = {node_id: [] for node_id in node_ids}

    for node in params.nodes:
        missing = sorted(set(node.inputs) - known)
        if missing:
            raise ValueError(f"node {node.id!r} has unknown inputs: {', '.join(missing)}")
        if node.id in node.inputs:
            raise ValueError(f"node {node.id!r} cannot consume itself")
        node_dependencies = {source for source in node.inputs if source in node_ids}
        dependencies[node.id] = node_dependencies
        for source in node_dependencies:
            followers[source].append(node.id)

    unknown_outputs = sorted(set(params.outputs) - node_ids)
    if unknown_outputs:
        raise ValueError(f"graph has unknown outputs: {', '.join(unknown_outputs)}")
    if len(params.outputs) != len(set(params.outputs)):
        raise ValueError("graph outputs must be unique")

    ready = deque(node.id for node in params.nodes if not dependencies[node.id])
    order: list[str] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for follower in followers[current]:
            dependencies[follower].discard(current)
            if not dependencies[follower]:
                ready.append(follower)
    if len(order) != len(params.nodes):
        blocked = sorted(node_id for node_id, value in dependencies.items() if value)
        raise ValueError(f"graph contains a cycle involving: {', '.join(blocked)}")
    return order


def validate_graph(params: BaseModel, registry: Registry) -> None:
    if not isinstance(params, TorchGraphParams):
        raise TypeError("torch/graph validator received the wrong parameter schema")
    for node in params.nodes:
        spec = registry.get("torch_module", node.type)
        registry.validate("torch_module", {"type": node.type, "params": node.params})
        metadata = dict(spec.metadata or {})
        exact_inputs = metadata.get("inputs")
        minimum_inputs = metadata.get("min_inputs")
        if isinstance(exact_inputs, int) and len(node.inputs) != exact_inputs:
            raise RegistryError(
                f"graph node {node.id!r} ({node.type}) requires {exact_inputs} input(s), "
                f"got {len(node.inputs)}"
            )
        if isinstance(minimum_inputs, int) and len(node.inputs) < minimum_inputs:
            raise RegistryError(
                f"graph node {node.id!r} ({node.type}) requires at least "
                f"{minimum_inputs} inputs, got {len(node.inputs)}"
            )


def build_graph_model(params: TorchGraphParams, context: Any) -> Any:
    validate_graph(params, context.registry)
    order = _topological_order(params)
    nodes = {node.id: node for node in params.nodes}
    torch = _torch()
    modules = {
        node.id: context.registry.invoke(
            "torch_module",
            {"type": node.type, "params": node.params},
            context,
        )
        for node in params.nodes
    }

    class RegistryGraph(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.graph_modules = torch.nn.ModuleDict(modules)
            self.input_names = tuple(params.input_names)
            self.execution_order = tuple(order)
            self.output_names = tuple(params.outputs)

        def forward(self, *args: Any, **kwargs: Any) -> Any:
            if args and kwargs:
                raise TypeError("torch/graph accepts positional or named inputs, not both")
            if kwargs:
                missing = sorted(set(self.input_names) - set(kwargs))
                extra = sorted(set(kwargs) - set(self.input_names))
                if missing or extra:
                    raise TypeError(
                        f"torch/graph input mismatch; missing={missing or 'none'}, "
                        f"extra={extra or 'none'}"
                    )
                values = {name: kwargs[name] for name in self.input_names}
            else:
                if len(args) != len(self.input_names):
                    raise TypeError(
                        f"torch/graph expects {len(self.input_names)} positional input(s), "
                        f"got {len(args)}"
                    )
                values = dict(zip(self.input_names, args, strict=True))

            for node_id in self.execution_order:
                node = nodes[node_id]
                incoming = [values[source] for source in node.inputs]
                values[node_id] = self.graph_modules[node_id](*incoming)
            outputs = tuple(values[name] for name in self.output_names)
            return outputs[0] if len(outputs) == 1 else outputs

    return RegistryGraph()


def _register_module(
    registry: Registry,
    name: str,
    class_name: str,
    schema: type[BaseModel],
    *,
    category: str,
    description: str,
    inputs: int | None = 1,
    min_inputs: int | None = None,
) -> None:
    metadata: dict[str, Any] = {"category": category}
    if inputs is not None:
        metadata["inputs"] = inputs
    if min_inputs is not None:
        metadata["min_inputs"] = min_inputs
    registry.add(
        "torch_module",
        name,
        factory=_module_factory(class_name),
        schema=schema,
        description=description,
        provider="research-assistant[torch]",
        catalog="graph-node",
        metadata=metadata,
    )


def _register_operation(
    registry: Registry,
    name: str,
    operation: str,
    schema: type[BaseModel],
    *,
    description: str,
    inputs: int | None = 1,
    min_inputs: int | None = None,
) -> None:
    metadata: dict[str, Any] = {"category": "Graph operations"}
    if inputs is not None:
        metadata["inputs"] = inputs
    if min_inputs is not None:
        metadata["min_inputs"] = min_inputs
    registry.add(
        "torch_module",
        name,
        factory=_custom_module_factory(operation),
        schema=schema,
        description=description,
        provider="research-assistant[torch]",
        catalog="graph-node",
        metadata=metadata,
    )


def register(registry: Registry) -> None:
    registry.add(
        "model",
        "torch/graph",
        factory=build_graph_model,
        schema=TorchGraphParams,
        description="Build an executable PyTorch module from a validated directed acyclic graph.",
        provider="research-assistant[torch]",
        editor="torch-graph",
        validator=validate_graph,
    )

    _register_module(
        registry,
        "torch.nn/Linear",
        "Linear",
        LinearParams,
        category="Linear",
        description="Applies an affine linear transformation.",
    )
    _register_module(
        registry,
        "torch.nn/LazyLinear",
        "LazyLinear",
        LazyLinearParams,
        category="Linear",
        description="Linear layer whose input width is inferred on first use.",
    )
    _register_module(
        registry,
        "torch.nn/Bilinear",
        "Bilinear",
        BilinearParams,
        category="Linear",
        description="Applies a bilinear transformation to two inputs.",
        inputs=2,
    )

    for dimension in (1, 2, 3):
        _register_module(
            registry,
            f"torch.nn/Conv{dimension}d",
            f"Conv{dimension}d",
            ConvParams,
            category="Convolution",
            description=f"Standard {dimension}D convolution.",
        )
        _register_module(
            registry,
            f"torch.nn/LazyConv{dimension}d",
            f"LazyConv{dimension}d",
            LazyConvParams,
            category="Convolution",
            description=f"{dimension}D convolution with inferred input channels.",
        )
        _register_module(
            registry,
            f"torch.nn/ConvTranspose{dimension}d",
            f"ConvTranspose{dimension}d",
            ConvTransposeParams,
            category="Convolution",
            description=f"Standard {dimension}D transposed convolution.",
        )
        _register_module(
            registry,
            f"torch.nn/BatchNorm{dimension}d",
            f"BatchNorm{dimension}d",
            BatchNormParams,
            category="Normalization",
            description=f"Batch normalization for {dimension}D inputs.",
        )

    _register_module(
        registry,
        "torch.nn/LayerNorm",
        "LayerNorm",
        LayerNormParams,
        category="Normalization",
        description="Normalizes over the configured trailing dimensions.",
    )
    _register_module(
        registry,
        "torch.nn/GroupNorm",
        "GroupNorm",
        GroupNormParams,
        category="Normalization",
        description="Separates channels into groups and normalizes each group.",
    )

    for name, schema in (
        ("ReLU", InplaceParams),
        ("GELU", TorchModuleParams),
        ("SiLU", InplaceParams),
        ("Tanh", TorchModuleParams),
        ("Sigmoid", TorchModuleParams),
        ("Mish", InplaceParams),
    ):
        _register_module(
            registry,
            f"torch.nn/{name}",
            name,
            schema,
            category="Activation",
            description=f"PyTorch {name} activation.",
        )
    _register_module(
        registry,
        "torch.nn/LeakyReLU",
        "LeakyReLU",
        LeakyReLUParams,
        category="Activation",
        description="Leaky rectified linear activation.",
    )
    _register_module(
        registry,
        "torch.nn/ELU",
        "ELU",
        ELUParams,
        category="Activation",
        description="Exponential linear activation.",
    )
    _register_module(
        registry,
        "torch.nn/Softmax",
        "Softmax",
        SoftmaxParams,
        category="Activation",
        description="Normalizes values with softmax along one dimension.",
    )

    for name in ("Dropout", "Dropout1d", "Dropout2d", "Dropout3d"):
        _register_module(
            registry,
            f"torch.nn/{name}",
            name,
            DropoutParams,
            category="Regularization",
            description=f"PyTorch {name} regularization.",
        )

    for dimension in (1, 2, 3):
        _register_module(
            registry,
            f"torch.nn/MaxPool{dimension}d",
            f"MaxPool{dimension}d",
            MaxPoolParams,
            category="Pooling",
            description=f"Maximum pooling over {dimension}D windows.",
        )
        _register_module(
            registry,
            f"torch.nn/AvgPool{dimension}d",
            f"AvgPool{dimension}d",
            PoolParams,
            category="Pooling",
            description=f"Average pooling over {dimension}D windows.",
        )
        _register_module(
            registry,
            f"torch.nn/AdaptiveAvgPool{dimension}d",
            f"AdaptiveAvgPool{dimension}d",
            AdaptivePoolParams,
            category="Pooling",
            description=f"Adaptive average pooling to a fixed {dimension}D output size.",
        )

    _register_module(
        registry,
        "torch.nn/Flatten",
        "Flatten",
        FlattenParams,
        category="Shape",
        description="Flattens a contiguous range of dimensions.",
    )
    _register_module(
        registry,
        "torch.nn/Unflatten",
        "Unflatten",
        UnflattenParams,
        category="Shape",
        description="Expands one dimension into a configured shape.",
    )
    _register_module(
        registry,
        "torch.nn/Upsample",
        "Upsample",
        UpsampleParams,
        category="Shape",
        description="Resizes tensors by an output size or scale factor.",
    )
    _register_module(
        registry,
        "torch.nn/Identity",
        "Identity",
        TorchModuleParams,
        category="Shape",
        description="Returns its input unchanged.",
    )
    _register_module(
        registry,
        "torch.nn/Embedding",
        "Embedding",
        EmbeddingParams,
        category="Embedding",
        description="Trainable lookup table for discrete indices.",
    )

    _register_operation(
        registry,
        "torch.graph/Add",
        "add",
        TorchModuleParams,
        description="Elementwise sum of two or more graph values.",
        inputs=None,
        min_inputs=2,
    )
    _register_operation(
        registry,
        "torch.graph/Multiply",
        "multiply",
        TorchModuleParams,
        description="Elementwise product of two or more graph values.",
        inputs=None,
        min_inputs=2,
    )
    _register_operation(
        registry,
        "torch.graph/Concat",
        "concat",
        ConcatParams,
        description="Concatenates two or more graph values along a dimension.",
        inputs=None,
        min_inputs=2,
    )
    _register_operation(
        registry,
        "torch.graph/Reshape",
        "reshape",
        ReshapeParams,
        description="Reshapes one graph value.",
    )
    _register_operation(
        registry,
        "torch.graph/Permute",
        "permute",
        PermuteParams,
        description="Permutes dimensions of one graph value.",
    )
