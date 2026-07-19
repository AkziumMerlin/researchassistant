# Interactive configuration creator

`ra config create` builds an experiment YAML from the same component registry used by validation,
planning, and execution. There is no second architecture catalog or manually maintained template
schema.

Start the wizard with an explicit development plugin:

```bash
ra config create configs/baseline.yaml --plugin my_project.plugin
```

The creator performs these steps:

1. loads built-ins, installed entry-point plugins, and every explicit `--plugin` module;
2. asks for experiment metadata and one or more random seeds;
3. lists registered components by kind and namespaced name;
4. prompts for fields from each component's Pydantic schema;
5. builds ordered stages and validates their dependency names;
6. configures accelerator, device count, optional memory request, and artifact root;
7. compiles the resulting plan before writing the file.

Existing files are never replaced implicitly. Use `--overwrite` only when replacement is intended.

## Preselect common components

Selections can be supplied on the command line while their schema parameters remain interactive:

```bash
ra config create configs/mlp.yaml \
  --plugin my_project.plugin \
  --component model=my_project/mlp \
  --component data=my_project/dataset \
  --component recipe=my_project/classification \
  --stage fit=torch/fit \
  --stage test=torch/evaluate
```

`--component` uses `KIND=REGISTERED_TYPE`. Because the current experiment model has one global
component per kind, the creator rejects duplicate kinds. `--stage` uses
`STAGE_NAME=REGISTERED_TYPE` and preserves command-line order.

Without these flags, the same components are shown in numbered menus with their registry
descriptions.

## Schema-driven values

Simple values, lists, and mappings use YAML syntax:

```text
width:       128
dropout:     0.1
splits:      [val, test]
dimensions:  {x: 128, y: 128}
enabled:     true
```

The prompt shows whether a field is required, its JSON-schema type, enum alternatives, default,
and description. The entire component schema is validated after entry, including custom Pydantic
validators. Invalid parameter groups can be retried without writing a partial config.

Accepted defaults are omitted from component `params`, keeping generated YAML concise and allowing
the registered schema to remain the source of defaults. Required values and user changes are
serialized explicitly.

## Seeds and dependencies

A single seed becomes the top-level `seed`. Multiple seeds produce both a deterministic base seed
and a `matrix.seed` axis:

```yaml
seed: 0
matrix:
  seed: [0, 1, 2]
```

Dependencies can reference only stages already created. This makes the generated ordering
unambiguous and prevents forward references or accidental cycles before plan compilation.

After creation, the normal commands remain available:

```bash
ra config validate configs/baseline.yaml
ra plan configs/baseline.yaml
ra launch configs/baseline.yaml --launcher configs/shared-gpu-launcher.yaml
```
