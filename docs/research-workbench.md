# Integrated research workbench

ResearchAssistant exposes the same research services through the CLI and the local browser UI. The
workbench is local-first: every path is bounded by the selected workspace, process execution uses
argument vectors rather than a shell, and write-capable developer operations are disabled unless
trusted mode is explicitly enabled.

## Visual research protocols

The **Workbench → Protocols** panel provides structured forms for adaptive HPO, validation-only
selection, paired statistical analysis, and publication bundles. The forms call the existing
research APIs; they do not introduce a second configuration or execution format. Advanced fields
remain available in saved YAML specifications and the corresponding CLI commands.

## Scientific artifacts

Register arrays, predictions, targets, errors, masks, latent fields, gradients, Jacobians, images,
tables, and videos:

```bash
ra artifact discover --root runs --root reports
ra artifact register runs/study/run/prediction.json \
  --kind prediction --dimension sample --dimension y --dimension x
ra artifact list --kind prediction
ra artifact slice ARTIFACT_ID --select 0 --select :
ra artifact compare PREDICTION_ID TARGET_ID
```

The catalog lives at `.ra/scientific-artifacts.json` and records the workspace-relative path,
SHA-256 digest, role, run/stage/sample identity, dimensions, tags, shape, and format metadata. JSON,
CSV, and TSV arrays work without extra dependencies. Install `.[scientific]` for NumPy `.npy` and
`.npz` files. Slices are bounded before being returned to the browser.

## Result lifecycle

Lifecycle operations are soft and provenance-aware:

```bash
ra lifecycle protect runs/STUDY/RUN
ra lifecycle pin runs/STUDY/RUN --reason "selected for the paper"
ra lifecycle archive runs/STUDY/RUN
ra lifecycle trash runs/STUDY/RUN
ra lifecycle restore TRASH_ID
ra lifecycle gc --older-than-days 30       # dry run
ra lifecycle gc --older-than-days 30 --apply
```

Pinned results and paths referenced by selection locks, reports, or publication JSON are protected
from ordinary trash operations. Trashed payloads move atomically to `.ra/trash` and can be restored.
The quota view reports storage used by runs, reports, publications, and trash.

## Detached analysis and tasks

Start an analysis script without tying it to the browser or SSH session:

```bash
ra analysis run scripts/analyze.py --arg runs/study --profile
ra analysis list
ra analysis logs ANALYSIS_ID
ra analysis stop ANALYSIS_ID
```

Project tasks can be declared in `.ra/tasks.yaml`:

```yaml
tasks:
  test:
    description: Run the project test suite
    script: scripts/run_tests.py
    args: []
    cwd: .
  diagnostics:
    script: scripts/analyze_diagnostics.py
    args: [runs/diagnostics]
```

The manager stores immutable argv/cwd metadata and separate stdout/stderr logs under
`.ra/analysis-sessions`. Inline scratchpads are restricted to trusted developer mode.

## Workspaces and Conda

Save frequently used local or SSH workspaces and bind each one to a Python interpreter:

```bash
ra workspace add KNO-paper . --python "$CONDA_PREFIX/bin/python" --conda-env KNO
ra workspace list
ra workspace conda
ra workspace inspect --python "$CONDA_PREFIX/bin/python"
ra workspace export-env environment.lock --python "$CONDA_PREFIX/bin/python"
```

Interpreter inspection reports Python, executable, platform and, when installed, PyTorch/CUDA/device
information. Environment export prefers a Conda explicit specification in an active Conda
environment and falls back to `pip freeze --all`.

## Trusted developer mode

Read-only diagnostics, Git status/diff/log, branch listing, and project text search are available by
default. Write operations require an explicit trusted local session:

```bash
RA_TRUSTED_DEV=1 ra ui . --plugin my_project.plugin
```

Trusted mode enables namespaced branch creation, branch switching, explicit-path commits, pushes
from non-default branches, saved tasks, move, and mkdir operations. It deliberately does not expose
a browser shell. Git commits require explicit paths, and direct pushes to `main` or `master` are
rejected.
