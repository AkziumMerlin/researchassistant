# Publication bundle

A publication spec selects completed runs, report bundles and registry-managed assets:

```yaml
name: paper-results
title: Research results
artifact_root: runs
run_ids: []
trial_ids: []
study_ids: [benchmark]
reports:
  - reports/main-table
  - reports/resolution-transfer
asset_statuses: [selected, released]
include_checkpoints: true
include_environment: true
template: aaai
copy_mode: hardlink
```

```bash
ra publication preview publication.yaml
ra publication build publication.yaml --output publications/paper-results
```

The output contains resolved one-run configurations, manifests, status, resources, diagnostics,
environments, selected reports, figures, tables, content-addressed assets/checkpoints, generated
LaTeX method/results/compute/dataset fragments, `reproduction.sh`, `publication.json` and a complete
SHA-256 checksum manifest. Building occurs in a temporary directory followed by atomic replacement.
The same preview and build operations are available in `Pipeline+`.
