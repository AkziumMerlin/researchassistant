# Resilient scheduler and stage cache

The local subprocess launcher can attach a replacement scheduler to workers that survived a UI,
SSH session or scheduler-process failure. Opening the persistent job catalog performs safe automatic
adoption when the recorded scheduler is dead but one or more recorded worker PIDs still match the
expected `_worker MANIFEST` command. Manual adoption is also available:

```bash
ra job adopt JOB_ID --workspace .
```

Adoption uses an atomic per-job lock, never scans unrelated processes and reuses the existing worker
PID, GPU lease, attempt identifier, logs and run directory. The replacement scheduler resumes GPU
telemetry and diagnostics and schedules only runs that are neither completed nor already alive.

Completed stages are stored in `.ra/stage-cache` by default. Keys include the resolved stage,
effective component references, provider source hashes, dependencies and artifact digests, seed,
assignments, plugin set and manifest provenance. Providers can opt out with
`metadata={"cacheable": False}`. Control it with:

```bash
RA_STAGE_CACHE=off|read|write|readwrite
RA_STAGE_CACHE_ROOT=/path/to/cache
RA_STAGE_CACHE_NAMESPACE=experiment-family
ra cache stats
ra cache prune --keep 10000
```

A cache hit is recorded in `status.json` with `cache_hit` and `cache_key`; final metrics are mirrored
into the new run and artifacts are materialized inside that run, so downstream stages do not depend
on the cache directory remaining mounted.
