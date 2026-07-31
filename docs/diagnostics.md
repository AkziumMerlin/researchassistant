# Diagnostics and automatic interventions

The resilient launcher reads `.ra/diagnostics.yaml` and checks active workers while it samples GPU
telemetry. The default policy detects missing metric progress, sustained low GPU utilization,
large loss/error divergence and GPU out-of-memory signatures.

```bash
ra diagnostics init
ra diagnostics policy
ra diagnostics show runs
```

Each rule chooses `warn`, `terminate` or `retry`. Retries preserve the immutable manifest, mark the
interrupted stage explicitly and restart it with normal resume semantics. `max_automatic_retries`
bounds loops. Findings are appended to `diagnostics.jsonl`, summarized in `diagnostics.json`, and any
process intervention is written to `intervention.json` before the worker process group is signalled.
Only the PID recorded for the active ResearchAssistant worker is affected.
