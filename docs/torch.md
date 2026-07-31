# Optional PyTorch integration

The integration is intentionally smaller than a general training framework. It standardizes the
reproducible lifecycle around a task-specific recipe without assuming `(x, y)` batches, a forward
signature, or a metric family.

Install it with `pip install -e '.[torch]'`. The rest of ResearchAssistant imports and plans
experiments without importing PyTorch.

## Component contract

| Kind | Factory result | Responsibility |
|---|---|---|
| `model` | `torch.nn.Module` | architecture and initialized parameters |
| `data` | `TorchDataLoaders` | re-iterable training and named evaluation loaders |
| `recipe` | `TorchRecipe` | optimizer plus train/evaluation/prediction semantics |
| `stage` | built in | lifecycle, reduction, checkpointing, and artifact publication |

`TorchStep` carries an optional differentiable loss, scalar metrics, and a positive weight. The
stage computes weighted means. For the usual sample mean, set `weight` to the batch size. For a
sequence or masked task, the recipe can use the number of valid elements instead.

The recipe receives the model, untouched batch, and resolved `torch.device`. It therefore decides
how to unpack and move a batch, how to call the model, and whether evaluation means one-step
prediction, autoregressive rollout, sampling, or another protocol.

## Registry graph models

ResearchAssistant registers `model: torch/graph` together with a catalog of standard
`torch_module` components. The catalog covers linear, convolutional and transposed-convolutional
layers; normalization; common activations; dropout; pooling; shape operations; embeddings; and
multi-input add, multiply, and concatenate nodes. PyTorch is still imported only when the model is
constructed for execution.

A graph model is stored entirely in the normal experiment config:

```yaml
components:
  model:
    type: torch/graph
    params:
      input_names: [input]
      nodes:
        - id: hidden
          type: torch.nn/Linear
          inputs: [input]
          params: {in_features: 16, out_features: 64}
          position: {x: 280, y: 80}
        - id: activation
          type: torch.nn/GELU
          inputs: [hidden]
          position: {x: 510, y: 80}
        - id: output
          type: torch.nn/Linear
          inputs: [activation]
          params: {in_features: 64, out_features: 4}
          position: {x: 740, y: 80}
      outputs: [output]
```

Node order is not semantically significant. Validation resolves a topological order and rejects
unknown references, cycles, duplicate names, invalid nested module parameters, and incorrect input
arity. One graph input can be passed positionally; multiple inputs can be passed positionally in
`input_names` order or as exactly matching keyword arguments. A single configured output is
returned directly, while multiple outputs are returned as a tuple.

The browser config creator exposes the same representation through a graph canvas. Modules are
added from the registered palette, dragged into place, connected through ports, and edited through
their Pydantic-derived parameter forms. Applying the graph calls the server-side registry
validator before it can enter the generated YAML.

## Fit lifecycle

`torch/fit` performs the following operations:

1. resolve `cpu` or `cuda` from the stage and run resource settings;
2. seed Python, PyTorch, CUDA, and NumPy when installed;
3. construct model, data, and recipe components;
4. train and evaluate every epoch;
5. select `best.pt` using an explicitly named non-training metric;
6. atomically update `last.pt` after every complete epoch;
7. publish both files as named stage artifacts.

The checkpoint contains the model, optimizer, optional scheduler, AMP scaler, epoch, selection
state, metric history, and RNG state. If an interrupted stage is run again with resume enabled,
training continues after the last fully completed epoch.

Model state dictionaries are used instead of serializing whole Python model objects. This keeps
checkpoints less coupled to module paths and follows the flexible save/load pattern recommended by
PyTorch. Checkpoints still use Python serialization internally and should only be loaded from a
trusted run directory.

## Evaluation lifecycle

`torch/evaluate` reconstructs the same registered components, resolves a named checkpoint from a
completed dependency stage or a direct `checkpoint_path`, loads the model state, and evaluates
selected named splits. Stage-local component overrides can replace the data component for OOD,
resolution-transfer, or rollout tests while reusing the fitted architecture and recipe.

```yaml
stages:
  - name: fit
    type: torch/fit
    params:
      epochs: 100
      monitor: val/relative_l2
      mode: min

  - name: rollout
    type: torch/evaluate
    needs: [fit]
    components:
      data:
        type: my_project/long_horizon_data
    params:
      checkpoint_stage: fit
      checkpoint: best
      splits: [rollout]
```

## Reusing trained checkpoints

Managed checkpoints are discovered from run manifests and completed-stage artifact records:

```bash
ra checkpoint list runs
ra checkpoint show runs/<study>/<run>/checkpoints/fit/best.pt
```

`ra infer` restores the resolved source config and its plugins, verifies that the registered model
component matches exactly, and creates a new inference study containing only `torch/evaluate`.
The source study/trial/run and checkpoint path are retained in the new run manifest's provenance.

```bash
ra infer runs/<study>/<run>/checkpoints/fit/best.pt --split test --device cuda
```

An external `.pt`, `.pth`, or `.ckpt` has no ResearchAssistant manifest, so its reconstruction
config must be explicit:

```bash
ra infer weights/model.pt --config configs/inference.yaml --split ood
```

Use `--predict` when the recipe defines `predict_step`. `torch/predict` writes one PyTorch file per
batch and a compact JSON index instead of retaining the complete prediction set in memory:

```bash
ra infer runs/<study>/<run>/checkpoints/fit/best.pt --split test --predict
```

As with resume, only load checkpoints produced by a trusted source. PyTorch checkpoint loading can
deserialize Python-owned state.

## Deliberate limits

- one process and one device per run;
- no distributed wrappers or gradient accumulation yet;
- data-loader/sampler construction and worker seeding remain in the data component;
- callbacks and external tracking are not embedded in the recipe contract;
- `torch/predict` requires the project recipe to define how a batch becomes a prediction;
- AMP is currently CUDA-only.

The next execution layer will launch one run per subprocess and assign CUDA devices outside the
training code. Distributed training can later be an alternative stage/plugin rather than new
branches inside `torch/fit`.
