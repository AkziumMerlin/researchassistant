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

## Stable concepts

### Component

A component is addressed by `(kind, namespace/name)`. Its Pydantic schema validates `params`
before any job starts. The factory receives the validated schema instance and a runtime context.

The core does not impose a closed enumeration of component kinds. Conventional kinds are
`model`, `data`, `recipe`, `metric`, `callback`, `stage`, `launcher`, and `reporter`.

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

- execution is local and sequential;
- there is no reusable PyTorch fit/evaluate stage yet;
- there is no SQLite index yet; the current report command scans self-describing run directories;
- interrupted Python processes are recognized on the next invocation only through persisted
  stage state;
- config inheritance intentionally supports a small `extends` mechanism instead of adopting
  Hydra's job lifecycle.

## Next milestones

1. Add a lazy, optional PyTorch integration with `data`, `model`, and `recipe` protocols.
2. Add subprocess workers and a local CUDA lease scheduler.
3. Add an event index and seed-aware reports based on manifests, never path parsing.
4. Migrate one KNO protocol as an external acceptance-test plugin.
5. Add Slurm and tracking sinks behind plugin contracts.

The detailed source audit that motivated these boundaries is in
[kno-source-audit.md](kno-source-audit.md).
