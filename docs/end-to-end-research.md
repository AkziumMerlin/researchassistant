# End-to-end research workflow

# Adaptive HPO

ResearchAssistant searches ordinary experiment configurations rather than introducing a second
execution format. A search specification defines a base config, conditional parameter domains,
validation-only objectives, budgets and an optional ASHA policy.

```yaml
name: kno-search
base_config: configs/kno.yaml
artifact_root: runs
search_space:
  components.model.params.width:
    type: categorical
    choices: [32, 64, 96]
  stages.0.params.lr:
    type: float
    low: 0.0001
    high: 0.003
    log: true
objectives:
  - metric: val/loss
    split: validation
    direction: minimize
sampler: tpe
max_trials: 50
parallelism: 4
max_gpu_hours: 200
asha:
  enabled: true
  resource_steps: [25, 50, 100, 200]
  reduction_factor: 3
  grace_step: 25
```

```bash
ra hpo propose search.yaml --count 4
ra hpo step search.yaml
ra hpo status search.yaml
ra hpo best search.yaml
```

`step` refreshes indexed metrics, applies ASHA pruning, checks compute/failure budgets and fills
free parallel slots. Objective splits containing `test` or `ood` are rejected. State and generated
configs live under `.ra/hpo/SEARCH/`, so the controller can resume after process restarts.

# Dataset lifecycle

Dataset specifications create immutable, checksum-addressed snapshots with explicit split manifests,
preprocessing lineage and optional parent versions.

```yaml
name: rpb
version: 2026-07
source: data/rpb
files:
  include: ["**/*.hdf5"]
  min_files: 1
splits:
  train: ["train/**"]
  validation: ["validation/**"]
  test: ["test/**"]
preprocessing:
  - type: normalize
    source: id-training-statistics
snapshot: true
```

```bash
ra dataset register dataset.yaml
ra dataset list
ra dataset validate DATASET_ID
ra dataset lineage DATASET_ID
ra dataset materialize DATASET_ID data/snapshots/rpb
```

Every file receives a SHA-256 digest. Split overlap is a hard error. Manifests are stored under
`.ra/datasets/manifests`, immutable objects under `.ra/datasets/objects/sha256`, and catalog metadata
under `.ra/datasets.sqlite3`.

# Validation-only selection protocol

Selection specifications separate architecture/checkpoint selection from final test evaluation.

```yaml
name: final-models
artifact_root: runs
selection_metric: loss
selection_split: validation
target_metrics: [loss]
test_splits: [test, ood]
direction: minimize
group_by: [study_id, dataset]
required_seeds: [0, 1, 2]
min_seeds: 3
promote_checkpoints: true
strict_test_lock: true
```

```bash
ra selection preview selection.yaml
ra selection lock selection.yaml
ra selection evaluate final-models --output reports/final-models
```

The lock records selected trials, runs, validation steps and checkpoint assets. Incomplete seed groups
are rejected. Test/OOD values cannot enter selection. `evaluate` reads only locked runs and, by
default, requires target metrics at the validation-selected checkpoint step.

# Statistical analysis

Statistical reports use run-level scalar values and preserve pair identities such as seed and dataset.

```yaml
name: main-comparison
artifact_root: runs
metric: loss
split: test
group_by: model
paired_by: [seed, dataset]
baseline: KNO
direction: minimize
confidence: 0.95
bootstrap_samples: 5000
permutation_samples: 20000
correction: holm
missing_pair_policy: drop
```

```bash
ra statistics run statistics.yaml --output reports/main-comparison
```

The bundle contains raw selected values, group summaries, bootstrap confidence intervals, paired
mean differences, Cohen's \(d_z\), paired sign-permutation \(p\)-values, corrected \(p\)-values,
win/tie counts and missing-cell diagnostics in JSON, CSV and LaTeX.

# Hypotheses and decisions

ResearchAssistant stores scientific intent separately from execution metadata.

```bash
ra research hypothesis create \
  --title "Spherical updates improve transfer" \
  --statement "KNO reduces OOD error at fixed validation protocol." \
  --criteria "Support if paired OOD error improves on at least two tasks."

ra research hypothesis evidence HYPOTHESIS_ID selection final-models \
  --supports support --summary "Validation-only lock selected KNO."

ra research hypothesis conclude HYPOTHESIS_ID supported \
  --conclusion "Criterion satisfied."

ra research decision record \
  --title "Use selected KNO configuration" \
  --choice "trial-abc" \
  --rationale "Best validation mean with complete seeds."
```

Hypotheses, evidence links and decisions are stored in `.ra/research.sqlite3`. Evidence can reference
runs, reports, selection locks, publications, datasets or free-form notes. Full exports are included
in enhanced publication bundles.

# Full publication bundle

`publication build-full` extends the basic bundle with dataset manifests, immutable selection locks,
statistical reports, research decisions, claims, a paper entrypoint and cross-report consistency
checks.

```yaml
name: paper-results
title: Research results
artifact_root: runs
run_ids: []
reports: [reports/main-table]
dataset_ids: [rpb:2026-07:...]
selection_locks: [final-models]
statistical_reports: [reports/main-comparison]
include_research_log: true
strict_consistency: true
template: aaai
compile_pdf: false
```

```bash
ra publication preview-full publication.yaml
ra publication build-full publication.yaml --output publications/paper-results
```

The output adds `paper.tex`, `datasets/`, `selections/`, `statistics/`, `research/`,
`claims.json`, `bundle-lock.json` and a rebuilt checksum manifest. Strict mode rejects report bundles
that reference runs outside the publication selection. Optional `pdflatex` compilation is performed
only when explicitly enabled.
