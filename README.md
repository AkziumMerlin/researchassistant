# ResearchAssistant

ResearchAssistant is a local-first, plugin-driven experiment orchestrator. It turns a typed
YAML configuration into immutable run manifests, executes a dependency graph of stages, and
stores enough structured state to resume and inspect every run.

The core deliberately knows nothing about a particular dataset, model family, benchmark, or
training framework. Projects add those concepts as namespaced components.

> Status: early MVP. The current release provides the orchestration core, plugin API, optional
> single-device PyTorch integration, a shared-GPU local subprocess launcher, and a local browser
> workbench.

## What works now

- strict Pydantic-validated YAML;
- relative `extends` and typed `--set KEY=VALUE` overrides;
- namespaced component registry;
- installed plugins through Python entry points;
- explicit local plugin modules during development;
- Cartesian matrices, including multiple random seeds;
- validated stage DAGs;
- deterministic trial and run identifiers;
- atomic manifests and status updates;
- streaming and final structured metrics;
- named artifacts passed between dependent stages;
- stage-local component overrides for test/OOD protocols;
- safe resume with distinct failed/interrupted states;
- optional recipe-based PyTorch fit/evaluate stages with atomic checkpoints;
- shared-GPU subprocess scheduling with configurable memory/utilization gates;
- per-attempt compute telemetry and trial-aware historical memory estimates;
- an interactive schema-driven config creator built from registered components;
- a bundled Monaco workbench for editing files and visually creating/validating configs;
- detached experiment launch and run-status monitoring from the browser;
- an incremental SQLite metric index with UI chart and LaTeX-table builders;
- reproducible chart/table bundles with data and run provenance;
- seed-aware mean and standard-deviation reports;
- a compact Linux CLI.

## Install

ResearchAssistant requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ra doctor
```

For the built-in PyTorch stages:

```bash
pip install -e '.[dev,torch]'
```

For the local browser UI:

```bash
pip install -e '.[dev,ui]'
```

For server-side PDF/SVG/PNG figure export:

```bash
pip install -e '.[dev,ui,reports]'
```

## Five-minute example

Create a tiny project:

```bash
ra init demo
cd demo
ra config validate configs/smoke.yaml
ra plan configs/smoke.yaml
ra run configs/smoke.yaml
ra status runs
ra report summary runs
```

The generated example contains one component, one custom stage, three seeds, and a dependent
evaluation stage. Running the same command again resumes the already completed runs instead of
duplicating them.

## Local browser workbench

Open the current project in the bundled UI:

```bash
ra ui . --plugin my_project.plugin
```

The workbench provides a project explorer, Monaco file editor with tabs and `Ctrl+S`, the live
component registry, a visual schema-driven config creator, composed-config and run-plan inspection,
detached experiment launch with config/launcher overrides, persistent run monitoring, aggregate
metric/resource summaries, and indexed chart/LaTeX-table builders with saved-spec loading. Chart
queries are aggregated on the server rather than transferring complete metric histories to the
browser.

On an SSH server, use SSH mode and optionally provide the address used from your local machine:

```bash
ra ui . --plugin my_project.plugin --ssh --ssh-target user@server --port 8765
```

The command keeps the service on the server loopback interface and prints the corresponding
`ssh -L` command. Browser launches run in detached scheduler processes with immutable request
snapshots under `.ra/ui-launches/`; closing the browser or reconnecting the SSH tunnel does not
stop them, and reopening the UI restores their status and bounded scheduler-log tail.

The editor uses optimistic revisions and atomic replacement: an external file change produces a
conflict instead of being overwritten. See [docs/ui.md](docs/ui.md) for the security boundary,
frontend build, and current limitations.

## Create configurations from the registry

Build a validated YAML interactively from built-in and project components:

```bash
ra config create configs/experiment.yaml --plugin my_project.plugin
```

Frequently used components can be preselected while their typed parameters are still prompted:

```bash
ra config create configs/experiment.yaml \
  --plugin my_project.plugin \
  --component model=my_project/mlp \
  --component data=my_project/dataset \
  --component recipe=my_project/mse \
  --stage fit=torch/fit \
  --stage test=torch/evaluate
```

The creator shows required fields, defaults, enums, and descriptions from each registered Pydantic
schema, then compiles the plan before writing. See
[docs/config-creator.md](docs/config-creator.md) for the full flow.

## Configuration

```yaml
version: 1

experiment:
  name: example
  tags: [baseline]

plugins:
  - my_project.plugin

seed: 0

components:
  model:
    type: my_project/mlp
    params:
      in_features: 16
      width: 64
      out_features: 2

matrix:
  seed: [0, 1, 2]
  components.model.params.width: [64, 128]

stages:
  - name: fit
    type: my_project/fit

  - name: test
    type: my_project/evaluate
    needs: [fit]
    components:
      data:
        type: my_project/dataset
        params:
          split: test
    params:
      split: test

resources:
  accelerator: cuda
  devices: 1

artifacts:
  root: runs
```

Inspect the fully composed configuration without executing it:

```bash
ra config render configs/experiment.yaml \
  --set components.model.params.width=256 \
  --set 'matrix.seed=[3,4,5]'
```

`extends` is resolved relative to the child configuration:

```yaml
extends:
  - ../base/training.yaml

experiment:
  name: larger-model

components:
  model:
    params:
      width: 256
```

Mappings are merged recursively; lists and scalar values are replaced.

## Register a component

Every component has a kind, a namespaced name, a typed parameter model, and a factory. For a
PyTorch architecture, the project plugin can contain:

```python
from typing import Any

from pydantic import BaseModel, ConfigDict
from torch import nn

from research_assistant.registry import Registry


class MLPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_features: int
    width: int = 128
    out_features: int


def build_mlp(config: MLPConfig, _context: Any) -> nn.Module:
    return nn.Sequential(
        nn.Linear(config.in_features, config.width),
        nn.GELU(),
        nn.Linear(config.width, config.out_features),
    )


def register(registry: Registry) -> None:
    registry.add(
        "model",
        "my_project/mlp",
        factory=build_mlp,
        schema=MLPConfig,
        description="A compact two-layer MLP.",
        provider=__name__,
    )
```

During development, put the module in `plugins`. For an installed package, expose the same
function through `pyproject.toml`:

```toml
[project.entry-points."research_assistant.plugins"]
my-project = "my_project.plugin:register"
```

Then inspect the generated parameter schema:

```bash
ra component describe model my_project/mlp --plugin my_project.plugin
```

## PyTorch without a universal Trainer

The optional integration supplies `torch/fit` and `torch/evaluate`. A project registers three
ordinary components:

- `model` returns an `nn.Module`;
- `data` returns `TorchDataLoaders`;
- `recipe` returns `TorchRecipe`, whose two steps own batch unpacking, device transfer, forward
  semantics, loss, and task metrics.

```python
from research_assistant.integrations.torch import TorchRecipe, TorchStep


def build_recipe(config, _context):
    def step(model, batch, device, _split=None):
        inputs, target = (value.to(device) for value in batch)
        prediction = model(inputs)
        loss = loss_fn(prediction, target)
        return TorchStep(loss=loss, metrics={"mae": mae(prediction, target)}, weight=len(inputs))

    return TorchRecipe(
        optimizer=lambda model: torch.optim.AdamW(model.parameters(), lr=config.lr),
        train_step=lambda model, batch, device: step(model, batch, device),
        eval_step=lambda model, batch, device, split: step(model, batch, device, split),
    )
```

ResearchAssistant owns epochs, train/eval mode, optional CUDA AMP, metric reduction, validation
selection, and resume. The recipe owns the scientific meaning of a step, so rollouts and unusual
batch structures do not require flags in the core.

Run the complete regression example:

```bash
PYTHONPATH=examples/torch ra run examples/torch/configs/regression.yaml
```

See [docs/torch.md](docs/torch.md) for the complete contract and checkpoint behavior.

## Shared-GPU scheduling

Use `ra launch` to isolate every run in its own process and assign physical NVIDIA GPUs dynamically:

```bash
PYTHONPATH=examples/torch ra launch examples/torch/configs/regression.yaml \
  --launcher examples/torch/configs/shared-gpu-launcher.yaml
```

The default shared-server policy permits foreign CUDA processes. Eligibility is controlled by
current free memory, device utilization, an optional device allow-list, and the number of
ResearchAssistant workers already assigned to a GPU. `resources.memory_gb` is an explicit per-run
request; otherwise the scheduler uses the historical placement-memory peak of the exact trial with
a configurable safety factor. PyTorch workers add allocator-native memory high-water marks so short
peaks are not dependent on the external sampling interval.

Inspect previous costs for the configurations in a plan:

```bash
ra report resources runs --config examples/torch/configs/regression.yaml
```

See [docs/launcher.md](docs/launcher.md) for the policy schema, telemetry guarantees, and shared-GPU
attribution rules.

## Artifact layout

```text
runs/<study>/<run-id>/
├── manifest.json
├── environment.json
├── status.json
├── metrics.jsonl
├── resources.json          # launcher-managed runs
├── resource-events.jsonl   # sampled GPU context
└── ... project artifacts ...
```

`manifest.json` is immutable. `status.json` is written atomically. A resume refuses to reuse a
directory if its manifest does not match the compiled run.

Long-running stages can call `context.log_metrics(metrics, step=epoch)`. A fit stage publishes
checkpoints through `StageResult.artifacts`; dependent stages resolve them with
`context.artifact("fit", "best")`. Artifact paths must remain inside the run directory.

Metric events are versioned and append-only. Index them incrementally and generate reports with:

```bash
ra report index runs
ra report chart reports/specs/learning-curves.yaml
ra report table reports/specs/benchmark-table.yaml
```

See [docs/reporting.md](docs/reporting.md) for event dimensions, scalable indexing, report specs,
TensorBoard compatibility, and report-bundle provenance.

## Design boundaries

- A `model` only constructs a model; it does not own an experiment.
- A `data` component owns splits and loading, not the train loop.
- A `recipe` defines task-specific optimization semantics.
- A `stage` is an executable unit such as fit, test, OOD evaluation, or report generation.
- A `launcher` decides where stages run; it must not leak scheduling into training code.

See [docs/architecture.md](docs/architecture.md) for the architecture and KNO migration map.
