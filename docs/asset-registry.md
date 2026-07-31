# Artifact and checkpoint registry

`ra asset refresh runs` scans named stage artifacts and managed checkpoints, computes content hashes,
and stores immutable objects under `.ra/objects/sha256`. Metadata and lifecycle state live in
`.ra/assets.sqlite3`.

```bash
ra asset list --kind checkpoint
ra asset promote ASSET_ID selected
ra asset promote ASSET_ID released
ra asset pin ASSET_ID
ra asset materialize ASSET_ID exports/model.pt
ra asset retention --keep-candidates-per-trial 3
ra asset gc
```

Lifecycle states are `candidate`, `selected`, `released` and `archived`. Pinned and released assets
cannot be deleted. Content objects are deduplicated by SHA-256 across runs; source paths remain
independent references and may be pruned only through an explicit retention or delete operation.
The `Pipeline+` UI exposes refresh, search, promotion, pinning and archive actions.
