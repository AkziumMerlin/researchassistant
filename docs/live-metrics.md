# Multi-run live metrics

The **Jobs+ → Live metrics** workbench is the primary online view for large experiments. It reads
ResearchAssistant's run-local `metrics.jsonl` files through the shared SQLite/WAL metric index; it
does not start one TensorBoard instance per directory and does not require navigating to a run
subdirectory.

For the selected persistent job, the dashboard provides:

- all active runs by default, with an option to include completed and failed runs;
- filters by trial, model, dataset, stage, state, run/config search text, and metric;
- line grouping by run, seed, model, or trial;
- linear and logarithmic scales with bounded uncertainty bands for aggregate views;
- current step, inferred total epochs when available, ETA, latest values, and resource metrics;
- direct links from each run row to worker logs and artifacts;
- named views stored in browser local storage.

The browser polls every three seconds while the dialog is open. Each request carries a cursor with
the latest indexed sequence for every visible run. The metric index seeks from persisted byte
offsets and ingests only appended JSONL records. If no selected metric changed, the response omits
all chart panels. When a metric changed, only that bounded panel is recomputed and replaced in the
browser. Status cards and the run table remain current even when no scalar event was emitted.

The server never transfers complete unbounded histories. Every panel has explicit `max_points` and
`max_series` limits and uses the same SQL bucketing as reproducible report charts. Grouped views can
therefore cover many runs without making browser memory proportional to the raw event count.

TensorBoard remains an optional compatibility sink for external plugins and unsupported summary
types. It is not required for scalar monitoring.
