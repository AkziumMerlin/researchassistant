# Browser-to-Theia UI parity

The retired Vite/browser workbench is no longer shipped. Its workflows are either native Theia
facilities or ordinary tabs in the dockable ResearchAssistant view.

| Retired browser workflow | Theia replacement |
| --- | --- |
| custom file tree/editor/search | Navigator, Monaco and Search in Workspace |
| browser terminal dialog | native Theia terminal; SSH workspaces use the generated SSH/tmux profile |
| modal layout manager | native dockable/persisted Theia workbench layout |
| PyTorch graph dialog and component palette | Models visual parameterized-graph editor with weighted search and category/provider filters |
| project init, config creator and config inspector | Project tab |
| persistent jobs, recovery, logs, rendered live dashboards, saved views and job artifacts | Jobs tab |
| analytics overview, rendered charts/tables and selected-checkpoint evaluation | Runs and Reports tabs |
| advanced plots and saved report specs | Reports / Advanced plots and Saved specs |
| notebook file/cell editor, dirty-state handling, keyboard execution and persistent kernels | Notebooks / Notebook editor |
| artifact discovery, registration, slicing and lifecycle | Artifacts tab |
| cache, asset registry, diagnostics and publication bundles | Pipeline tab |
| workspace/environment catalog, detached analysis and developer tools | Workbench tab |
| system/process/GPU monitor | Monitor tab |
| protocols, hypotheses, evidence and publication journal | Research tab |
| cross-study run aggregation, lineage, context snapshots and typed planner | Runs, Artifacts, Notebooks and Assistant |

Two old endpoints are intentionally not reproduced as custom panels: `/api/terminals` is superseded
by Theia terminal services, and `/api/torch/graph/validate` is superseded by the richer
`/api/torch/parameterized-graph/validate` contract used by Models. Everything else remains backed by
the existing Python routes, so local and SSH workspaces use the same behavior.
