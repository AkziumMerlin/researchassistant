# Model architectures

The browser workbench exposes **Models** as a top-level section. Architectures are saved under
`architectures/*.json` and can be reused by multiple experiment configs. Architecture files use
language version 2 while remaining backward-compatible with version-1 static DAGs.

## Typed architecture variables

Concrete values remain in `graph.variables`, so matrix axes and CLI overrides keep stable paths.
Optional declarations in `graph.variable_specs` describe the editor and validate values:

```json
{
  "variables": {
    "backend": "kuramoto",
    "use_omega": true,
    "width": 64,
    "canonical_size": [32, 32]
  },
  "variable_specs": {
    "backend": {
      "type": "enum",
      "choices": ["kuramoto", "cnn", "iter_cnn"]
    },
    "use_omega": {
      "type": "bool",
      "enabled_if": "backend == 'kuramoto'"
    },
    "width": {"type": "int", "min": 1},
    "canonical_size": {"type": "shape"}
  }
}
```

Supported variable types are `int`, `float`, `bool`, `string`, `enum`, `shape`, and `json`.
The config creator renders checkboxes and enum selectors and disables variables whose simple
`enabled_if` condition is false.

Variables remain ordinary matrix paths:

```yaml
matrix:
  components.model.params.variables.backend: [kuramoto, cnn]
  components.model.params.variables.width: [32, 64, 96]
```

## Bindings and expressions

Any constructor parameter, repeat count, or switch selector may use a literal, a variable, or a
safe expression:

```json
{"$var": "width"}
```

```json
{"$expr": "layer_steps[layer_index]"}
```

Expressions support arithmetic, comparisons, indexing, boolean operations, conditional
expressions, and a small allow-list of pure functions: `abs`, `bool`, `float`, `int`, `len`, `max`,
`min`, `round`, and `sum`. Attribute access, imports, comprehensions, lambdas, and arbitrary calls
are rejected.

## Named tensor ports

Nodes can use a mapping instead of an input list:

```json
{
  "inputs": {
    "feature": "previous.feature",
    "oscillator": "previous.oscillator",
    "stimulus": "previous.stimulus"
  },
  "output_ports": ["feature", "oscillator", "stimulus"]
}
```

Sources use `node.port`; a node with one output can also be referenced by `node`.
A module returning a mapping is matched by key, while a tuple is matched by port order.

## Reusable subgraphs

`subgraphs` contains named graph templates with their own inputs, nodes, and named outputs.
A `composite` node invokes one template:

```json
{
  "id": "block",
  "kind": "composite",
  "template": "conformer_block",
  "inputs": {"input": "stem"},
  "output_ports": ["output"]
}
```

The Models UI edits the root model and each subgraph on separate canvases.
Recursive subgraph references are rejected.

## Repeated blocks and weight tying

A `repeat` node applies a subgraph multiple times:

```json
{
  "id": "layers",
  "kind": "repeat",
  "template": "kno_layer",
  "count": {"$var": "n_layers"},
  "weights": "independent",
  "index_name": "layer_index",
  "inputs": {
    "feature": "initial.feature",
    "oscillator": "initial.oscillator",
    "stimulus": "initial.stimulus"
  },
  "carry": {
    "feature": "feature",
    "oscillator": "oscillator",
    "stimulus": "stimulus"
  },
  "output_ports": ["feature", "oscillator", "stimulus"]
}
```

`weights: independent` builds one submodule per iteration and exposes the loop index to
expressions. `weights: shared` builds one submodule and reuses it at every iteration. Shared repeats
reject module-construction expressions that depend on the loop index.

This represents both independently parameterized Conformer blocks and weight-tied inner
integration steps.

## Compile-time switches

A `switch` selects one subgraph from a boolean or categorical architecture variable:

```json
{
  "id": "backend_layer",
  "kind": "switch",
  "selector": {"$var": "backend"},
  "branches": {
    "kuramoto": "kuramoto_layer",
    "cnn": "canonical_cnn_layer",
    "iter_cnn": "iterative_cnn_layer"
  },
  "inputs": {
    "feature": "feature",
    "oscillator": "oscillator",
    "stimulus": "stimulus"
  },
  "output_ports": ["feature", "oscillator", "stimulus"]
}
```

Switches are resolved while the model is built; they are architecture choices, not data-dependent
runtime branches.

## Workspace Python modules

A `python` node imports an `nn.Module` class by `package.module:Class` and resolves its constructor
parameters through the same variable/expression system:

```json
{
  "id": "local_coupling",
  "kind": "python",
  "target": "project.models.kno:LocalCoupling",
  "inputs": {
    "oscillator_field": "state.oscillator",
    "canonical_feature_field": "state.feature"
  },
  "call_style": "keyword",
  "params": {
    "field_channels": {"$var": "width"},
    "oscillator_channels": {"$expr": "n_osc * osc_dim"},
    "ndim": {"$expr": "len(canonical_size)"}
  },
  "output_ports": ["output"]
}
```

The target must construct a `torch.nn.Module`. This is the escape hatch for domain-specific
operations such as spectral resampling, tangent projection, oscillator normalization, relative
attention, or convolution modules that are not part of the built-in palette.

## KNO and Conformer decomposition

A KNO can be represented with:

- typed `backend`, `geometry`, `use_local`, `use_stimulus`, and `use_omega` variables;
- a backend `switch`;
- an independent outer repeat over KNO layers;
- a stage repeat whose count is `layer_steps[layer_index]`;
- a shared repeat for weight-tied integration steps;
- named `feature`, `oscillator`, and `stimulus` state ports;
- Python nodes for KNO-specific mathematical operations.

A Conformer can be represented as a reusable `conformer_block` subgraph, an independent repeat over
blocks, residual graph edges, and optional switch branches for convolution, macaron feed-forward,
or attention variants.

Saved architecture files are design-time artifacts. The selected graph is embedded into the
experiment config, so runs do not depend on a mutable external architecture file.
