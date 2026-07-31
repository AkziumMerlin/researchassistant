# Metrics, indexing, and reproducible reports

ResearchAssistant stores metric history as versioned, append-only events in each run directory.
The local event file is authoritative; SQLite and TensorBoard are derived views that can be removed
without losing a run.

## Metric events

The public stage API accepts a batch of values and optional typed dimensions:

```python
context.log_metrics(
    {"train/loss": loss, "val/rel_l2": relative_l2},
    step=epoch,
    step_kind="epoch",
    dimensions={"dataset": "wave", "split": "validation", "horizon": 4},
)
```

One long-form JSONL event is written per scalar. Events contain `study_id`, `trial_id`, `run_id`,
`attempt`, a monotone per-run `sequence`, `event_id`, stage, kind, metric, value, step semantics,
and dimensions. A resume starts a new attempt and recovers the last sequence by reading only the
tail of the JSONL file. Non-finite metric values are rejected before they can poison summaries.

Final stage outputs are written with `kind: final`; report code never guesses that the last
progress point is the final result.

## Large artifact roots

`ra report index runs` creates `runs/.ra-index.sqlite3`. Its WAL-mode schema indexes run identity,
state, model/data component types, metric events, and common dimensions. Each source file has a
persisted byte offset. Refresh therefore performs these operations:

1. scan the two-level run directory catalog with `scandir`;
2. stat manifests/status files and parse only changed metadata;
3. seek directly to the last indexed byte of each changed `metrics.jsonl`;
4. insert new events in configurable batches;
5. leave an incomplete final JSONL line for the next refresh.

Worker processes never write the shared database. They append to their own run-local files, while
the UI/index command is the single SQLite writer. The index can be rebuilt with:

```bash
ra report index runs --rebuild
```

Chart queries aggregate in SQL before returning data. If a curve has more than `max_points`
distinct steps, numeric steps are bucketed on the server. `max_series` keeps high-cardinality
groupings bounded and the response reports when series were omitted. Catalog dimension values are
also capped. Increasing the number of runs therefore does not make the UI download every
seed-level observation or every trial identifier.

## Chart specifications

```yaml
name: validation-curves
artifact_root: runs
chart_type: line
filters:
  metrics: [val/rel_l2]
  stages: [fit]
  kinds: [progress]
group_by: model
aggregate: mean
uncertainty: std
max_points: 1000
max_series: 50
y_scale: log
title: Validation error
x_label: epoch
y_label: Relative L2
```

The UI renders the bounded response directly. `ra report chart` uses the same query and optionally
exports Matplotlib SVG/PDF/PNG files when `research-assistant[reports]` is installed.
Use `chart_type: bar` for final-metric comparisons; one bounded aggregate is rendered per selected
series with the configured uncertainty.

## Validation-selected evaluation

The results workbench can reproduce the common protocol “choose the best validation step for each
seed, then read the test metric at that exact step.” Selection happens independently per run in
SQLite; runs without a target observation at the selected step remain visible but are excluded
from the seed aggregate.

```yaml
name: validation-selected-results
artifact_root: runs
filters:
  states: [completed]
selection_metric: val/rel_l2
target_metric: test/rel_l2
stage: fit
selection_split: validation
target_split: test
selection_kind: progress
target_kind: progress
direction: minimize
alignment: same_step
group_by: [dataset, model]
precision: 4
table_direction: minimize
caption: Validation-selected test results
label: tab:validation-selected
max_runs: 2000
```

`alignment: latest` is available for protocols that intentionally read the latest target event,
but it is not silently substituted when a same-step target is missing. The UI shows selected,
eligible, and excluded run counts plus the exact selected step and both metric values for every
run.

An evaluation export contains `spec.yaml`, grouped `data.csv`, complete bounded `data.json`,
`table.tex`, and `provenance.json`. Provenance records eligible and excluded run IDs separately,
so a missing or failed seed cannot disappear from a paper table without an audit trail.

## LaTeX table specifications

```yaml
name: benchmark-main
artifact_root: runs
filters:
  metrics: [test/rel_l2]
  kinds: [final]
row: dataset
column: model
aggregate: mean_std
precision: 4
direction: minimize
bold_best: true
underline_second: false
caption: Benchmark results
label: tab:benchmark
missing: "--"
max_rows: 100
max_columns: 50
```

Ranking uses unrounded means. Bold formatting denotes the best configured aggregate, not a claim
of statistical significance. Row and column limits make accidental trial-by-run tables bounded;
the returned data records total cardinalities and whether it was truncated.

Each export directory contains the saved spec, aggregated JSON, source CSV (tables), rendered
LaTeX or figures, and `provenance.json` with the exact selected run IDs.

## TensorBoard

TensorBoard is an optional compatibility sink:

```yaml
logging:
  tensorboard:
    enabled: true
    directory: tensorboard
    flush_seconds: 30
```

Install it with `pip install -e '.[tensorboard]'`. The same typed events are mirrored through
`SummaryWriter`; TensorBoard event files are never read by the report engine. Logging and artifact
root settings are excluded from run/trial identity, so enabling a presentation sink does not create
a different scientific configuration.
