# Model architectures

The browser workbench exposes **Models** as a top-level section. Architectures are saved as
workspace files under `architectures/*.json` and can be reused by multiple experiment configs.

## Architecture variables

A parameterized graph declares concrete defaults in `graph.variables` and references them from
module parameters with an object containing only `$var`:

```json
{
  "variables": {"in_channels": 3, "width": 64},
  "nodes": [
    {
      "id": "stem",
      "type": "torch.nn/Conv2d",
      "inputs": ["input"],
      "params": {
        "in_channels": {"$var": "in_channels"},
        "out_channels": {"$var": "width"},
        "kernel_size": 3,
        "padding": 1
      }
    }
  ]
}
```

References are resolved recursively before the registered PyTorch module schemas are validated.
The resolved values therefore retain the same strict type and range checks as literal parameters.

When an architecture is selected in the config creator, its variables can be overridden for that
experiment. They are also regular matrix/override paths, for example:

```yaml
matrix:
  components.model.params.variables.width: [32, 64, 96]
```

Saved architecture files are design-time artifacts. The selected graph is embedded into the
experiment config, so runs do not depend on a mutable external architecture file.
