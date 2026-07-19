# KNO experiment infrastructure audit

This audit covers the supplied KNO project snapshot dated 2026-07-19. Its purpose is to preserve
useful behavior without moving RPB or neural-operator assumptions into ResearchAssistant core.

## Existing layers

The code is already partially separated:

- `experiments/specs.py` defines model, task, component, and training specifications;
- `experiments/experiment.py` owns model/task grids, run directories, seeds, resume, and artifacts;
- `experiments/trainer.py` owns PyTorch fit/evaluate/checkpoint logic;
- `rpb/data.py` and `rpb/adjacent_rollout.py` implement benchmark-specific data contracts;
- `rpb/yaml_config.py` combines RPB loading, baseline construction, sweeps, and execution;
- `scripts/final_v4/gpu_queue.py` and `gpu_job_worker.py` implement the restartable GPU queue;
- reporting scripts recover experiment identity largely from paths and historical JSON files.

The main issue is therefore not an absence of modules. It is that the orchestration boundary cuts
through domain-specific objects: `Experiment` knows models, tasks, PyTorch devices, loaders,
optimizers, TensorBoard, model parameter counts, and checkpoint naming simultaneously.

## Behavior worth preserving

### Reproducible independent runs

Each model/task/seed combination can rebuild the model from its specification. ResearchAssistant
represents this as one resolved run manifest per matrix combination, with seed included in the run
identity and excluded from the trial identity.

### Scientifically correct checkpoint resume

KNO checkpoints preserve model, optimizer, scheduler, AMP scaler, epoch, best metric, history, and
random-number-generator state. Writes use a temporary file followed by an atomic replacement.
This belongs in the optional PyTorch fit integration, not in the generic executor.

The generic executor is responsible for stage lifecycle only: immutable manifest checks,
completed-stage skipping, and distinct pending/running/completed/failed/interrupted states.

### Explicit model selection

KNO selects checkpoints by a named validation metric such as `val/l2` or
`val/l2_rollout@1`. Test and OOD metrics must remain downstream evaluation outputs and must not be
eligible for checkpoint selection. A future PyTorch fit schema should encode `monitor` and `mode`
explicitly.

### Long-running metric history

The old trainer writes epoch histories and can recover some legacy histories from logs. Stages now
have a structured `context.log_metrics(..., step=...)` event API, so progress is durable without
parsing human-readable logs.

### Restartable GPU workers

The final KNO queue has several useful operational properties:

- one seed/config per subprocess;
- physical GPU selection through `CUDA_VISIBLE_DEVICES`;
- workers survive a scheduler or SSH disconnect;
- atomic job state files allow adoption after restart;
- foreign GPU processes and free-memory requirements are checked;
- retries are isolated to failed jobs.

These requirements should guide the ResearchAssistant local CUDA launcher. They should not be
implemented inside a PyTorch trainer.

## Behavior that remains plugin-specific

The following KNO concepts must not enter core configuration models:

- RPB dataset names, HDF5 layout, normalization, coordinates, and Fourier features;
- the `x`/`y` batch convention;
- rollout target time dimensions and horizon metrics;
- relative Lp and H1 losses;
- KNO synchronization, energy, UMAP, and activation diagnostics;
- FNO/RNO/CNO/DeepONet/KNO constructor registries;
- TensorBoard-specific visualization settings.

They belong to an RPB data plugin, reusable PyTorch recipes, or KNO analysis stages.

## Changes made after the audit

The orchestration MVP was extended with:

- stage-local component overrides;
- structured progress metrics with numeric steps;
- named and validated artifacts between stages;
- dependency metric access;
- environment snapshots;
- interrupted-state persistence;
- seed-aware final metric aggregation.

## Remaining acceptance work

The next implementation milestone is an optional `research-assistant[torch]` integration. Its
acceptance test should reproduce one small KNO-style protocol:

1. build fresh model/data/recipe components for each seed;
2. fit with validation checkpoint selection;
3. interrupt and resume with optimizer/scheduler/RNG state intact;
4. evaluate the published best checkpoint on a downstream split;
5. aggregate the downstream metric across three seeds.

Only after this passes should the CUDA subprocess scheduler be moved into the core launcher API.
