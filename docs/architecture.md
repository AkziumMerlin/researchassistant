# Architecture

## Goal

ResearchAssistant is an orchestration layer, not a replacement for every training framework. It
compiles declarative experiment intent into reproducible jobs and delegates domain behavior to
plugins.

```text
CLI / future UI
      |
application services
      |
config -> registry -> plan -> executor -> artifact store
```

The CLI contains presentation logic only. A future TUI or web UI should call the same application
services and consume the same manifests and events.

The base browser workbench follows that boundary. Its FastAPI layer exposes bounded workspace,
registry, config assembly, and planning operations; the bundled Monaco frontend never reimplements
component validation or run identity. Both terminal and web creators assemble the same
`ExperimentConfig` model before invoking the same planner.

## Stable concepts

### Component

A component is addressed by `(kind, namespace/name)`. Its Pydantic schema validates `params`
before any job starts. The factory receives the validated schema instance and a runtime context.

The core does not impose a closed enumeration of component kinds. Conventional kinds are
`model`, `data`, `recipe`, `metric`, `callback`, `stage`, `launcher`, and `reporter`.

The interactive config creator consumes these same registry specifications and Pydantic schemas.
It is a presentation layer over Registry and planning, not a second component database. A future UI
can reuse the same schema metadata and validation service.

### Plan

A plan is the immutable product of config composition, overrides, validation, and matrix
expansion. It contains one manifest per run. Planning is pure: `ra plan` never creates run
artifacts.

### Trial and run

A trial represents one resolved configuration with the seed removed. A run is a trial with a
specific seed. Their identifiers are content hashes, so rerunning the same configuration resumes
the same work.

Output paths are excluded from those hashes. Execution semantics and resource requirements are
included.

### Stage

Stages form a directed acyclic graph. A stage may build registered components through its context
and produces structured metrics and artifacts. This represents specialized protocols without
adding benchmark flags to the core:

```text
fit -> test
    -> OOD
    -> resolution transfer
    -> rollout
```

### Artifact store

Each run directory is self-describing. The filesystem is the durable source of truth; a future
SQLite database will be a rebuildable index rather than the only copy of experiment state.

Stages may override global components. This lets a test, OOD, or resolution stage reuse the fit
recipe and checkpoint while constructing a different data provider. Completed stages expose
named artifacts and final metrics to their dependants; no consumer reconstructs paths from model
names.

### Launcher and resource history

Launcher policy is operational input and is deliberately separate from experiment configuration,
so changing a utilization threshold does not change run identity. The local launcher executes one
manifest per subprocess and assigns physical GPUs through `CUDA_VISIBLE_DEVICES`.

Resource profiles join back to the immutable manifest by `run_id`. Historical placement uses the
seed-independent `trial_id`: an explicit memory request wins, otherwise the maximum placement peak
of the exact prior configuration is multiplied by a safety factor. That peak combines external
process samples with framework-native high-water marks when available.

On shared GPUs, per-process wall time and memory are kept separate from device-wide utilization,
power, and total used memory. Foreign processes are observed and recorded but allowed by default.

### Local UI and workspace

`ra ui` serves packaged static assets on localhost. The browser sees relative POSIX paths only.
The backend resolves every path under the selected project root, excludes generated/heavy
directories, rejects symlink escapes, limits editable files to UTF-8 text, and performs atomic
writes guarded by a SHA-256 revision.

The UI intentionally has no terminal, arbitrary command endpoint, delete action, or run-launch
button in this milestone. Experiment execution remains an explicit CLI action while the UI focuses
on authoring and planning.

## KNO migration map

| Existing responsibility | ResearchAssistant destination |
|---|---|
| `rpb/yaml_config.py` parsing | generic config compiler plus RPB plugin schemas |
| hard-coded model creation | namespaced `model` components |
| RPB loaders and splits | an `rpb/data` component |
| training and rollout branches | separate recipe/stage components |
| seed and variant loops | matrix compiler |
| shell pipeline and retries | local launcher |
| `checkpoint_best.pt` selection | fit callback/stage policy |
| OOD and resolution scripts | dependent evaluation stages |
| directory-name report parsing | manifest and metric event queries |

The RPB and KNO names must not appear in the core package. They belong in a project plugin or a
separately installable adapter.

## Deliberate MVP limitations

- execution is local; the subprocess launcher parallelizes independent runs on one host;
- the reusable PyTorch stages are single-device and intentionally leave task semantics in recipes;
- metric JSONL files remain authoritative while a rebuildable SQLite/WAL index incrementally
  consumes only appended tails for interactive queries;
- interrupted Python processes are recognized on the next invocation only through persisted
  stage state;
- config inheritance intentionally supports a small `extends` mechanism instead of adopting
  Hydra's job lifecycle;
- the first UI milestone edits text and creates/validates configs, but does not yet stream run
  events or expose experiment execution.

## Next milestones

1. Add worker adoption after scheduler restart and MIG-aware placement.
2. Add background filesystem notifications on top of the existing incremental event index.
3. Migrate one KNO protocol as an external acceptance-test plugin.
4. Add Slurm and tracking sinks behind plugin contracts.

The detailed source audit that motivated these boundaries is in
[kno-source-audit.md](kno-source-audit.md).
