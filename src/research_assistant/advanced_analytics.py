from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_assistant.analytics import ChartSpec, MetricFilter, MetricIndex
from research_assistant.errors import ResearchAssistantError

Dimension = Literal[
    "study_id",
    "trial_id",
    "run_id",
    "stage",
    "metric",
    "seed",
    "model",
    "dataset",
    "split",
]


class AdvancedAnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdvancedChartSpec(AdvancedAnalyticsModel):
    name: str = "advanced-chart"
    artifact_root: str = "runs"
    chart_type: Literal["scatter", "histogram", "heatmap", "composite"]
    filters: MetricFilter = Field(default_factory=MetricFilter)
    metric: str | None = None
    x_metric: str | None = None
    y_metric: str | None = None
    group_by: Dimension = "trial_id"
    x_group: Dimension = "dataset"
    y_group: Dimension = "model"
    aggregate: Literal["mean", "min", "max"] = "mean"
    bins: int = Field(default=30, ge=2, le=200)
    max_points: int = Field(default=5000, ge=10, le=50000)
    max_cells: int = Field(default=2500, ge=4, le=10000)
    panels: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    title: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    y_scale: Literal["linear", "log"] = "linear"

    @model_validator(mode="after")
    def validate_chart_inputs(self) -> AdvancedChartSpec:
        if self.chart_type == "scatter" and not (self.x_metric and self.y_metric):
            raise ValueError("scatter charts require x_metric and y_metric")
        if self.chart_type in {"histogram", "heatmap"} and not self.metric:
            raise ValueError(f"{self.chart_type} charts require metric")
        if self.chart_type == "composite" and not self.panels:
            raise ValueError("composite charts require at least one panel")
        return self


def _filtered_cte(index: MetricIndex, filters: MetricFilter) -> tuple[str, list[Any]]:
    where, parameters = index._where(filters)  # noqa: SLF001 - extension over the same index
    query = f"""
        WITH filtered AS (
            SELECT e.*, r.study_id, r.trial_id, r.seed, r.state, r.model,
                   COALESCE(e.dataset, r.dataset, 'unknown') AS resolved_dataset,
                   COALESCE(e.split, 'unknown') AS resolved_split
            FROM metric_events e JOIN runs r ON r.run_id=e.run_id
            WHERE {where}
        )
    """
    return query, parameters


def _dimension(field: Dimension, alias: str = "f") -> str:
    mapping = {
        "study_id": f"{alias}.study_id",
        "trial_id": f"{alias}.trial_id",
        "run_id": f"{alias}.run_id",
        "stage": f"{alias}.stage",
        "metric": f"{alias}.metric",
        "seed": f"CAST({alias}.seed AS TEXT)",
        "model": f"COALESCE({alias}.model, {alias}.trial_id)",
        "dataset": f"COALESCE({alias}.resolved_dataset, 'unknown')",
        "split": f"COALESCE({alias}.resolved_split, 'unknown')",
    }
    return mapping[field]


def _base_filters(spec: AdvancedChartSpec) -> MetricFilter:
    return spec.filters.model_copy(update={"metrics": []})


def _scatter(index: MetricIndex, spec: AdvancedChartSpec) -> dict[str, Any]:
    cte, parameters = _filtered_cte(index, _base_filters(spec))
    group = _dimension(spec.group_by, "x")
    query = f"""
        {cte}
        SELECT {group} AS series, x.run_id, x.stage, x.step, x.value AS x, y.value AS y
        FROM filtered x JOIN filtered y
          ON y.run_id=x.run_id AND y.attempt=x.attempt
         AND y.stage=x.stage AND y.step IS x.step
         AND y.dimensions_json=x.dimensions_json
        WHERE x.metric=? AND y.metric=?
        ORDER BY series, x.run_id, x.step
        LIMIT ?
    """
    with index._lock:  # noqa: SLF001
        rows = index._connection.execute(  # noqa: SLF001
            query,
            [*parameters, spec.x_metric, spec.y_metric, spec.max_points + 1],
        ).fetchall()
    truncated = len(rows) > spec.max_points
    rows = rows[: spec.max_points]
    series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        x_value, y_value = float(row["x"]), float(row["y"])
        if spec.y_scale == "log" and y_value <= 0:
            continue
        series.setdefault(str(row["series"]), []).append(
            {
                "x": x_value,
                "y": y_value,
                "run_id": str(row["run_id"]),
                "stage": str(row["stage"]),
                "step": row["step"],
            }
        )
    return {
        "spec": spec.model_dump(mode="json"),
        "series": [{"name": name, "points": points} for name, points in series.items()],
        "points": sum(len(points) for points in series.values()),
        "truncated": truncated,
    }


def _histogram(index: MetricIndex, spec: AdvancedChartSpec) -> dict[str, Any]:
    cte, parameters = _filtered_cte(index, _base_filters(spec))
    group = _dimension(spec.group_by)
    query = f"""
        {cte}
        SELECT {group} AS series, f.value
        FROM filtered f WHERE f.metric=?
        ORDER BY series, f.value LIMIT ?
    """
    with index._lock:  # noqa: SLF001
        rows = index._connection.execute(  # noqa: SLF001
            query,
            [*parameters, spec.metric, spec.max_points + 1],
        ).fetchall()
    truncated = len(rows) > spec.max_points
    rows = rows[: spec.max_points]
    grouped: dict[str, list[float]] = {}
    for row in rows:
        value = float(row["value"])
        grouped.setdefault(str(row["series"]), []).append(value)
    result: list[dict[str, Any]] = []
    for name, values in sorted(grouped.items()):
        minimum, maximum = min(values), max(values)
        width = (maximum - minimum) / spec.bins if maximum > minimum else 1.0
        counts = [0] * spec.bins
        for value in values:
            index_value = min(spec.bins - 1, max(0, int((value - minimum) / width)))
            counts[index_value] += 1
        result.append(
            {
                "name": name,
                "n": len(values),
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "bins": [
                    {
                        "lower": minimum + position * width,
                        "upper": minimum + (position + 1) * width,
                        "count": count,
                    }
                    for position, count in enumerate(counts)
                ],
            }
        )
    return {
        "spec": spec.model_dump(mode="json"),
        "series": result,
        "points": sum(item["n"] for item in result),
        "truncated": truncated,
    }


def _heatmap(index: MetricIndex, spec: AdvancedChartSpec) -> dict[str, Any]:
    cte, parameters = _filtered_cte(index, _base_filters(spec))
    x_group = _dimension(spec.x_group)
    y_group = _dimension(spec.y_group)
    aggregate = {"mean": "AVG(f.value)", "min": "MIN(f.value)", "max": "MAX(f.value)"}[
        spec.aggregate
    ]
    query = f"""
        {cte}
        SELECT {x_group} AS x, {y_group} AS y, {aggregate} AS value,
               COUNT(*) AS n,
               CASE WHEN COUNT(*) > 1 THEN
                 SQRT(MAX((SUM(f.value*f.value)-SUM(f.value)*SUM(f.value)/COUNT(*))
                          /(COUNT(*)-1), 0))
               ELSE 0 END AS std
        FROM filtered f WHERE f.metric=?
        GROUP BY x, y ORDER BY y, x LIMIT ?
    """
    with index._lock:  # noqa: SLF001
        rows = index._connection.execute(  # noqa: SLF001
            query,
            [*parameters, spec.metric, spec.max_cells + 1],
        ).fetchall()
    truncated = len(rows) > spec.max_cells
    rows = rows[: spec.max_cells]
    cells = [
        {
            "x": str(row["x"]),
            "y": str(row["y"]),
            "value": float(row["value"]),
            "std": float(row["std"] or 0.0),
            "n": int(row["n"]),
        }
        for row in rows
        if not (spec.y_scale == "log" and float(row["value"]) <= 0)
    ]
    return {
        "spec": spec.model_dump(mode="json"),
        "x": sorted({cell["x"] for cell in cells}),
        "y": sorted({cell["y"] for cell in cells}),
        "cells": cells,
        "truncated": truncated,
    }


def advanced_chart(
    index: MetricIndex,
    spec: AdvancedChartSpec,
    *,
    _depth: int = 0,
) -> dict[str, Any]:
    if _depth > 1:
        raise ResearchAssistantError("nested composite charts are not supported")
    if spec.chart_type == "scatter":
        return _scatter(index, spec)
    if spec.chart_type == "histogram":
        return _histogram(index, spec)
    if spec.chart_type == "heatmap":
        return _heatmap(index, spec)

    panels: list[dict[str, Any]] = []
    for position, raw_panel in enumerate(spec.panels):
        chart_type = raw_panel.get("chart_type", "line")
        merged = {
            "name": f"{spec.name}-panel-{position + 1}",
            "artifact_root": spec.artifact_root,
            "filters": spec.filters.model_dump(mode="json"),
            **raw_panel,
        }
        if chart_type in {"line", "bar"}:
            panel_spec = ChartSpec.model_validate(merged)
            panels.append({"chart_type": chart_type, "chart": index.chart(panel_spec)})
        else:
            panel_spec = AdvancedChartSpec.model_validate(merged)
            if panel_spec.chart_type == "composite":
                raise ResearchAssistantError("composite panels cannot contain another composite")
            panels.append(
                {
                    "chart_type": panel_spec.chart_type,
                    "chart": advanced_chart(index, panel_spec, _depth=_depth + 1),
                }
            )
    return {"spec": spec.model_dump(mode="json"), "panels": panels, "points": _count_points(panels)}


def _count_points(panels: list[dict[str, Any]]) -> int:
    total = 0
    for panel in panels:
        chart = panel.get("chart") or {}
        if isinstance(chart.get("points"), int):
            total += chart["points"]
        elif isinstance(chart.get("cells"), list):
            total += len(chart["cells"])
    return total


def write_advanced_chart_bundle(
    index: MetricIndex,
    spec: AdvancedChartSpec,
    output: str | Path,
    *,
    formats: tuple[str, ...] = ("svg", "pdf", "png"),
) -> Path:
    """Persist a reproducible advanced-chart query, data, provenance, and figures."""
    from datetime import UTC, datetime

    import yaml

    from research_assistant.artifacts import atomic_write_json

    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    data = advanced_chart(index, spec)
    (destination / "spec.yaml").write_text(
        yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    atomic_write_json(destination / "data.json", data)
    atomic_write_json(
        destination / "provenance.json",
        {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "kind": "advanced-chart",
            "artifact_root": str(index.root),
            "database": str(index.database),
            "run_ids": index.selected_run_ids(spec.filters),
        },
    )
    if not formats:
        return destination
    unsupported = sorted(set(formats) - {"svg", "pdf", "png"})
    if unsupported:
        raise ResearchAssistantError(
            f"unsupported advanced chart format(s): {', '.join(unsupported)}"
        )
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ResearchAssistantError(
            "figure export requires research-assistant[reports]"
        ) from exc

    panels = data.get("panels") if spec.chart_type == "composite" else None
    if panels:
        columns = 2 if len(panels) > 1 else 1
        rows = (len(panels) + columns - 1) // columns
        figure, axes = plt.subplots(
            rows,
            columns,
            figsize=(6.4 * columns, 4.0 * rows),
            constrained_layout=True,
            squeeze=False,
        )
        flat_axes = list(axes.flat)
        for axis, panel in zip(flat_axes, panels, strict=False):
            _render_matplotlib_chart(axis, panel["chart"])
        for axis in flat_axes[len(panels) :]:
            axis.set_visible(False)
    else:
        figure, axis = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
        _render_matplotlib_chart(axis, data)
    for file_format in formats:
        figure.savefig(destination / f"chart.{file_format}", dpi=180)
    plt.close(figure)
    return destination


def _render_matplotlib_chart(axis: Any, chart: dict[str, Any]) -> None:
    chart_type = str((chart.get("spec") or {}).get("chart_type", "line"))
    if chart_type == "scatter":
        for series in chart.get("series", []):
            points = series.get("points", [])
            axis.scatter(
                [point["x"] for point in points],
                [point["y"] for point in points],
                label=series.get("name"),
                s=18,
            )
    elif chart_type == "histogram":
        for series in chart.get("series", []):
            bins = series.get("bins", [])
            if not bins:
                continue
            edges = [bins[0]["lower"], *[bin_["upper"] for bin_ in bins]]
            axis.stairs(
                [bin_["count"] for bin_ in bins],
                edges,
                label=series.get("name"),
            )
    elif chart_type == "heatmap":
        x_names = chart.get("x", [])
        y_names = chart.get("y", [])
        values = {(cell["y"], cell["x"]): cell["value"] for cell in chart.get("cells", [])}
        if not x_names or not y_names:
            axis.text(0.5, 0.5, "No heatmap cells", ha="center", va="center")
            return
        matrix = [
            [values.get((y_name, x_name), float("nan")) for x_name in x_names]
            for y_name in y_names
        ]
        image = axis.imshow(matrix, aspect="auto")
        axis.set_xticks(range(len(x_names)), labels=x_names, rotation=30, ha="right")
        axis.set_yticks(range(len(y_names)), labels=y_names)
        axis.figure.colorbar(image, ax=axis, shrink=0.8)
    elif chart_type == "bar":
        observations = [
            (series.get("name"), series["points"][-1])
            for series in chart.get("series", [])
            if series.get("points")
        ]
        names = [name for name, _point in observations]
        values = [point["y"] for _name, point in observations]
        lower = [point["y"] - point.get("lower", point["y"]) for _name, point in observations]
        upper = [point.get("upper", point["y"]) - point["y"] for _name, point in observations]
        axis.bar(names, values, yerr=[lower, upper], capsize=3)
        axis.tick_params(axis="x", rotation=25)
    else:
        for series in chart.get("series", []):
            points = series.get("points", [])
            x_values = [point["x"] for point in points]
            y_values = [point["y"] for point in points]
            line = axis.plot(x_values, y_values, label=series.get("name"))[0]
            if any("lower" in point or "upper" in point for point in points):
                axis.fill_between(
                    x_values,
                    [point.get("lower", point["y"]) for point in points],
                    [point.get("upper", point["y"]) for point in points],
                    color=line.get_color(),
                    alpha=0.18,
                    linewidth=0,
                )
    spec = chart.get("spec") or {}
    if spec.get("title"):
        axis.set_title(spec["title"])
    if spec.get("x_label"):
        axis.set_xlabel(spec["x_label"])
    if spec.get("y_label"):
        axis.set_ylabel(spec["y_label"])
    if spec.get("y_scale") and chart_type != "heatmap":
        axis.set_yscale(spec["y_scale"])
    if chart.get("series"):
        axis.legend(frameon=False)
    axis.grid(alpha=0.2)
