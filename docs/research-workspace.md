# Research workspace

ResearchAssistant 0.3 adds a unified research workspace over the existing orchestration,
artifact, notebook, reporting and lifecycle services. It is available from the browser through
**Research** and from the CLI through the existing `ra workspace` and `ra analysis` groups.

## Studies, trials and runs

A run is selected by its immutable `run_id`; selection never relies on the current sort order or a
path glob. The workspace can therefore aggregate an explicit set of runs even when they belong to
different studies or trials.

```bash
ra workspace runs --artifact-root runs
ra workspace aggregate \
  --run RUN_A \
  --run RUN_B \
  --metric relative_l2 \
  --group-by model
```

Aggregation reads completed stage metrics from each selected run and reports count, mean, standard
deviation, minimum, maximum, median, seeds and contributing run identifiers. Supported grouping
dimensions are `study_id`, `trial_id`, `experiment`, `model`, `dataset`, `recipe`, and `state`.
The browser exposes the same operation in the **Runs** tab.

## Durable launches

Detached launch records now carry a scheduler lease heartbeat. When a UI backend starts, it
reconciles persisted launch state with the scheduler PID and run-local status files.

The durable controls distinguish:

- `running`: the scheduler process is alive;
- `orphaned`: the scheduler disappeared while one or more runs remain non-terminal;
- `completed`: all persisted runs completed, even if the scheduler died before its final write;
- `failed`, `cancelled`, and `interrupted`: recoverable terminal states.

`adopt` waits for any still-running worker process groups, then recompiles the immutable persisted
request and resumes only incomplete runs. It does not start a second copy of a live worker. A reboot
can therefore be recovered by adopting the orphaned launch after the workspace is available again.

```bash
ra job list
ra job adopt JOB_ID
ra job cancel JOB_ID
```

Cancellation targets both the scheduler process group and known worker process groups. The normal
operation sends `SIGTERM`; `--force` uses `SIGKILL`.

## Scientific artifacts and lineage

The **Artifacts** tab uses the existing scientific-artifact catalog rather than treating arrays,
figures, predictions and targets as anonymous files. It exposes format, shape, dtype, run/sample
identity, bounded slicing, numerical comparison and run lineage. Discovery remains explicit and
bounded:

```bash
ra artifact discover --root runs --root reports
```

An artifact associated with a run links back to its immutable manifest, run state, launcher
assignment, resources and related registered artifacts.

## Contextual notebooks

A notebook context is an immutable JSON selection under `.ra/notebook-contexts/`. It records exact
run and artifact identifiers together with resolved metadata. A generated notebook loads that
selection into `RA_CONTEXT`, `RUNS`, and `ARTIFACTS` without scanning the workspace implicitly.

```bash
ra analysis context-create \
  --run RUN_A \
  --artifact ARTIFACT_ID \
  --notebook notebooks/analysis.ipynb
```

The notebook remains an ordinary `.ipynb` file. Reproducible operations discovered interactively
should still be promoted to a registered analysis task or pipeline stage.

## Capability parity

`ra workspace capabilities` and `/api/workspace/capabilities` expose a machine-readable
matrix for CLI, API and UI coverage. Public capabilities must declare every surface as `yes` or
`partial`; accidental CLI-only or UI-only additions fail the capability contract test.

## Plugin contracts and migrations

Plugins may declare a compatibility contract in their module:

```python
RESEARCH_ASSISTANT_PLUGIN = {
    "name": "my-project",
    "version": "0.4.0",
    "minimum_research_assistant": "0.3.0",
    "maximum_research_assistant_exclusive": "1.0.0",
    "config_schema_versions": [1],
    "architecture_schema_versions": [2],
    "capabilities": ["model.graph"],
}
```

Legacy plugins without this declaration remain accepted before ResearchAssistant 1.0 and are shown
as `legacy`. An explicitly incompatible contract prevents plugin loading with a diagnostic instead
of failing later while compiling a run.

Persisted configuration documents pass through the migration registry before Pydantic validation.
Migrations are sequential, auditable and idempotent. Preview or apply them with:

```bash
ra workspace migrate configs/legacy.yaml
ra workspace migrate configs/legacy.yaml --write
```

## Typed assistant

The Assistant tab emits an `AssistantPlan` whose actions refer to declared ResearchAssistant
capabilities. The built-in deterministic provider can inspect and aggregate runs, compare explicit
artifacts, create a contextual notebook, and draft a schema-shaped configuration. It cannot execute
shell commands or launch experiments.

Workspace-mutating actions are blocked unless the user reviews the plan and explicitly enables
writes. A future model-backed provider must implement the same typed plan contract; model output is
never executed directly.

## Layout and browser testing

The shared layout manager persists dialog geometry and exposes import/export/reset of a workspace
layout snapshot. It is the common foundation for replacing independent extension-specific layout
rules. Explorer width continues to use its IDE-style separator and participates in layout reset.

CI runs a real Chromium flow with Playwright in addition to Python API tests and JavaScript syntax
checks. The browser test opens the workbench, loads persisted runs, switches research tabs and
verifies the shared layout control.

## Frontend integration

Browser features are ordinary Vite modules under `ui/frontend/src/extensions/` and are imported by
the main frontend entrypoint after the core workbench is initialized. The server exposes typed API
routes only: it does not rewrite `index.html`, patch the generated bundle, serve JavaScript from
`/api/extensions`, or assemble architecture code through blob URLs at runtime.
