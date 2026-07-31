# Persistent jobs and live inspection

ResearchAssistant exposes one detached job store to both the CLI and browser. Jobs are persisted
under `.ra/ui-launches/`; closing a terminal, browser, or SSH tunnel does not remove their request,
state, scheduler log, or association with run artifacts.

```bash
ra job start configs/experiment.yaml --workspace . --output runs
ra job list --workspace .
ra job show JOB_ID --workspace .
ra job log JOB_ID --follow --workspace .
ra job log JOB_ID --source worker --run RUN_ID --follow --workspace .
ra job metrics JOB_ID --run RUN_ID --workspace .
ra job artifacts JOB_ID --run RUN_ID --workspace .
```

`ra job cancel` sends signals only to the scheduler and worker process IDs recorded for that job.
It never scans for or terminates unrelated processes. `ra job recover` reuses the immutable persisted
request, enables resume, and starts a new detached scheduler for an orphaned, failed, interrupted, or
cancelled job.

Logs use byte cursors rather than returning an unbounded tail. The browser can page backward and
forward through scheduler or worker logs. Live metrics are read from the authoritative run-local
`metrics.jsonl`; artifacts are listed inside the selected run and classified for image or text
preview. Common prediction, sample, target, residual, and error-map filenames receive semantic
labels in the gallery.

The browser adds a **Jobs+** workbench with the same start, cancel, recover, log, metric, and artifact
operations. Its **Live metrics** view monitors all active runs of a job in one bounded dashboard,
with filters, saved views, incremental cursors, automatic chart refresh, status/ETA cards, and direct
links to each run's logs and artifacts. See [live-metrics.md](live-metrics.md) for scaling and query
semantics. The existing launch API remains available for compatibility; both interfaces use the same
persistent store.
