# Advanced chart queries and validation-selected evaluation

Validation-selected evaluation is available from both the browser and CLI:

```bash
ra report evaluate evaluation.yaml --output reports/selected
```

The selection metric is optimized independently for every run. The target metric is then read at
the selected step (or at the latest compatible event when configured), and only the resulting target
values are aggregated across seeds. The report bundle contains the validated spec, JSON and CSV
data, LaTeX, and exact run provenance.

Advanced chart data supports `scatter`, `histogram`, `heatmap`, and bounded `composite` layouts:

```yaml
name: error-vs-gradient
artifact_root: runs
chart_type: scatter
x_metric: gradient_norm
y_metric: relative_l2
group_by: model
filters:
  kinds: [progress]
  splits: [test]
```

```bash
ra report advanced-chart chart.yaml --output reports/error-vs-gradient
```

Scatter points are paired within the same run, attempt, stage, step, and complete metric-dimension
record. Histograms and heatmaps are aggregated in SQLite, with explicit limits on points, cells,
bins, series, and composite panels. The browser **Charts+** workbench renders these query results
without transferring complete metric histories. CLI bundles contain the validated spec, bounded
query data, exact run provenance, and SVG/PDF/PNG figures; `--format none` writes data only.
