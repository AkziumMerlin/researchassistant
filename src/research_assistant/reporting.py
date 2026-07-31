from __future__ import annotations

import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from research_assistant.analytics import ChartSpec, EvaluationSpec, MetricIndex, TableSpec
from research_assistant.artifacts import atomic_write_json
from research_assistant.errors import ResearchAssistantError


def collect_summary(
    root: str | Path,
    *,
    stage: str | None = None,
    metric: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate final stage metrics by study and trial across seeds."""
    groups: dict[tuple[str, str, str, str], list[tuple[int | None, float]]] = defaultdict(list)
    root = Path(root)

    for status_path in sorted(root.glob("*/*/status.json")):
        run_dir = status_path.parent
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            status_data = json.loads(status_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if status_data.get("state") != "completed":
            continue

        study_id = str(manifest.get("study_id", "unknown"))
        trial_id = str(manifest.get("trial_id", "unknown"))
        seed = (manifest.get("config") or {}).get("seed")
        for stage_name, stage_status in (status_data.get("stages") or {}).items():
            if stage is not None and stage_name != stage:
                continue
            if stage_status.get("state") != "completed":
                continue
            for metric_name, raw_value in (stage_status.get("metrics") or {}).items():
                if metric is not None and metric_name != metric:
                    continue
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                groups[(study_id, trial_id, str(stage_name), str(metric_name))].append(
                    (seed, value)
                )

    rows: list[dict[str, Any]] = []
    for (study_id, trial_id, stage_name, metric_name), observations in sorted(groups.items()):
        values = [value for _, value in observations]
        rows.append(
            {
                "study_id": study_id,
                "trial_id": trial_id,
                "stage": stage_name,
                "metric": metric_name,
                "n": len(values),
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
                "seeds": sorted(seed for seed, _ in observations if seed is not None),
            }
        )
    return rows


def collect_resource_summary(
    root: str | Path,
    *,
    trial_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate completed resource profiles by exact seed-independent trial identity."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    root = Path(root)
    for resources_path in sorted(root.glob("*/*/resources.json")):
        run_dir = resources_path.parent
        try:
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if status.get("state") != "completed":
            continue
        study_id = str(manifest.get("study_id", "unknown"))
        trial_id = str(manifest.get("trial_id", "unknown"))
        if trial_ids is not None and trial_id not in trial_ids:
            continue
        total = resources.get("total") or {}
        try:
            observation = {
                "wall_seconds": float(total.get("wall_seconds", 0)),
                "gpu_wall_seconds": float(total.get("gpu_wall_seconds", 0)),
                "process_memory_peak_mb": float(total.get("process_memory_peak_mb", 0)),
                "placement_memory_peak_mb": float(
                    total.get("placement_memory_peak_mb", total.get("process_memory_peak_mb", 0))
                ),
                "device_active_seconds": float(total.get("device_active_seconds", 0)),
                "device_energy_joules": float(total.get("device_energy_joules", 0)),
                "attempts": int(total.get("attempts", 0)),
                "seed": (manifest.get("config") or {}).get("seed"),
            }
        except (TypeError, ValueError):
            continue
        groups[(study_id, trial_id)].append(observation)

    rows: list[dict[str, Any]] = []
    for (study_id, trial_id), observations in sorted(groups.items()):
        wall = [item["wall_seconds"] for item in observations]
        gpu_wall = [item["gpu_wall_seconds"] for item in observations]
        memory = [item["process_memory_peak_mb"] for item in observations]
        placement_memory = [item["placement_memory_peak_mb"] for item in observations]
        active = [item["device_active_seconds"] for item in observations]
        energy = [item["device_energy_joules"] for item in observations]
        rows.append(
            {
                "study_id": study_id,
                "trial_id": trial_id,
                "n": len(observations),
                "wall_seconds_mean": statistics.fmean(wall),
                "wall_seconds_std": statistics.stdev(wall) if len(wall) > 1 else 0.0,
                "gpu_hours_mean": statistics.fmean(gpu_wall) / 3600,
                "gpu_hours_total": sum(gpu_wall) / 3600,
                "process_memory_peak_mb_mean": statistics.fmean(memory),
                "process_memory_peak_mb_max": max(memory),
                "placement_memory_peak_mb_mean": statistics.fmean(placement_memory),
                "placement_memory_peak_mb_max": max(placement_memory),
                "device_active_seconds_mean": statistics.fmean(active),
                "device_energy_kwh_mean": statistics.fmean(energy) / 3_600_000,
                "attempts_total": sum(item["attempts"] for item in observations),
                "seeds": sorted(
                    item["seed"] for item in observations if item["seed"] is not None
                ),
            }
        )
    return rows


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _number(value: float, precision: int) -> str:
    return f"{float(value):.{precision}g}"


def render_latex_table(data: dict[str, Any], spec: TableSpec) -> str:
    cells = {
        (str(cell["row_name"]), str(cell["column_name"])): cell for cell in data["cells"]
    }
    ranks: dict[tuple[str, str], int] = {}
    if spec.direction != "none":
        for row_name in data["rows"]:
            observations = [
                (column, float(cells[(row_name, column)]["mean"]))
                for column in data["columns"]
                if (row_name, column) in cells
            ]
            observations.sort(key=lambda item: item[1], reverse=spec.direction == "maximize")
            distinct: list[float] = []
            for _, value in observations:
                if value not in distinct:
                    distinct.append(value)
            for column, value in observations:
                ranks[(row_name, column)] = distinct.index(value) + 1

    alignment = "l" + "c" * len(data["columns"])
    lines: list[str] = []
    if spec.caption or spec.label:
        lines.append(r"\begin{table}[!ht]")
        lines.append(r"\centering")
    if spec.caption:
        lines.append(rf"\caption{{{_latex_escape(spec.caption)}}}")
    if spec.label:
        if not re.fullmatch(r"[A-Za-z0-9:._-]+", spec.label):
            raise ResearchAssistantError("LaTeX labels may contain only letters, digits, : . _ -")
        lines.append(rf"\label{{{spec.label}}}")
    lines.extend([rf"\begin{{tabular}}{{{alignment}}}", r"\toprule"])
    header = [spec.row, *[_latex_escape(column) for column in data["columns"]]]
    lines.append(" & ".join(header) + r" \\")
    lines.append(r"\midrule")
    for row_name in data["rows"]:
        rendered = [_latex_escape(row_name)]
        for column in data["columns"]:
            cell = cells.get((row_name, column))
            if cell is None:
                rendered.append(_latex_escape(spec.missing))
                continue
            primary = {
                "mean_std": cell["mean"],
                "mean": cell["mean"],
                "min": cell["minimum"],
                "max": cell["maximum"],
            }[spec.aggregate]
            if spec.aggregate == "mean_std":
                content = (
                    rf"{_number(primary, spec.precision)} \pm "
                    rf"{_number(cell['std'], spec.precision)}"
                )
            else:
                content = _number(primary, spec.precision)
            rank = ranks.get((row_name, column))
            if spec.bold_best and rank == 1:
                content = rf"\mathbf{{{content}}}"
            math_cell = f"${content}$"
            if spec.underline_second and rank == 2:
                math_cell = rf"\underline{{{math_cell}}}"
            rendered.append(math_cell)
        lines.append(" & ".join(rendered) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    if spec.caption or spec.label:
        lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def render_evaluation_latex(data: dict[str, Any], spec: EvaluationSpec) -> str:
    row_field = spec.group_by[0]
    column_fields = spec.group_by[1:]
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    row_names: set[str] = set()
    column_names: set[str] = set()
    for group in data["groups"]:
        dimensions = group["dimensions"]
        row_name = str(dimensions[row_field])
        column_name = (
            " · ".join(str(dimensions[field]) for field in column_fields)
            if column_fields
            else spec.target_metric
        )
        row_names.add(row_name)
        column_names.add(column_name)
        cells[(row_name, column_name)] = group
    rows = sorted(row_names)
    columns = sorted(column_names)

    ranks: dict[tuple[str, str], int] = {}
    if spec.table_direction != "none":
        for row_name in rows:
            observations = [
                (column, float(cells[(row_name, column)]["mean"]))
                for column in columns
                if (row_name, column) in cells
            ]
            observations.sort(
                key=lambda item: item[1],
                reverse=spec.table_direction == "maximize",
            )
            distinct = list(dict.fromkeys(value for _, value in observations))
            for column, value in observations:
                ranks[(row_name, column)] = distinct.index(value) + 1

    lines: list[str] = []
    if spec.caption or spec.label:
        lines.extend([r"\begin{table}[!ht]", r"\centering"])
    if spec.caption:
        lines.append(rf"\caption{{{_latex_escape(spec.caption)}}}")
    if spec.label:
        if not re.fullmatch(r"[A-Za-z0-9:._-]+", spec.label):
            raise ResearchAssistantError("LaTeX labels may contain only letters, digits, : . _ -")
        lines.append(rf"\label{{{spec.label}}}")
    lines.extend(
        [
            rf"\begin{{tabular}}{{l{'c' * len(columns)}}}",
            r"\toprule",
            " & ".join([_latex_escape(row_field), *map(_latex_escape, columns)]) + r" \\",
            r"\midrule",
        ]
    )
    for row_name in rows:
        rendered = [_latex_escape(row_name)]
        for column in columns:
            cell = cells.get((row_name, column))
            if cell is None:
                rendered.append("--")
                continue
            content = (
                rf"{_number(cell['mean'], spec.precision)} \pm "
                rf"{_number(cell['std'], spec.precision)}"
            )
            rank = ranks.get((row_name, column))
            if spec.bold_best and rank == 1:
                content = rf"\mathbf{{{content}}}"
            math_cell = f"${content}$"
            if spec.underline_second and rank == 2:
                math_cell = rf"\underline{{{math_cell}}}"
            rendered.append(math_cell)
        lines.append(" & ".join(rendered) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    if spec.caption or spec.label:
        lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def _provenance(index: MetricIndex, filters, *, kind: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "artifact_root": str(index.root),
        "database": str(index.database),
        "run_ids": index.selected_run_ids(filters),
    }


def write_table_bundle(index: MetricIndex, spec: TableSpec, output: str | Path) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = index.table(spec)
    (output / "spec.yaml").write_text(
        yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    atomic_write_json(output / "data.json", data)
    atomic_write_json(output / "provenance.json", _provenance(index, spec.filters, kind="table"))
    (output / "table.tex").write_text(render_latex_table(data, spec), encoding="utf-8")
    with (output / "data.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["row_name", "column_name", "n", "mean", "std", "minimum", "maximum"],
        )
        writer.writeheader()
        writer.writerows(data["cells"])
    return output


def write_evaluation_bundle(
    index: MetricIndex,
    spec: EvaluationSpec,
    output: str | Path,
) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = index.evaluate(spec)
    (output / "spec.yaml").write_text(
        yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    atomic_write_json(output / "data.json", data)
    provenance = _provenance(index, spec.filters, kind="validation-selected-evaluation")
    provenance["eligible_run_ids"] = [
        row["run_id"] for row in data["runs"] if row["eligible"]
    ]
    provenance["excluded_run_ids"] = [
        row["run_id"] for row in data["runs"] if not row["eligible"]
    ]
    atomic_write_json(output / "provenance.json", provenance)
    (output / "table.tex").write_text(
        render_evaluation_latex(data, spec),
        encoding="utf-8",
    )
    fieldnames = [
        *spec.group_by,
        "n",
        "mean",
        "std",
        "minimum",
        "maximum",
        "seeds",
        "run_ids",
    ]
    with (output / "data.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for group in data["groups"]:
            writer.writerow(
                {
                    **group["dimensions"],
                    "n": group["n"],
                    "mean": group["mean"],
                    "std": group["std"],
                    "minimum": group["minimum"],
                    "maximum": group["maximum"],
                    "seeds": ",".join(map(str, group["seeds"])),
                    "run_ids": ",".join(group["run_ids"]),
                }
            )
    return output


def write_chart_bundle(
    index: MetricIndex,
    spec: ChartSpec,
    output: str | Path,
    *,
    formats: tuple[str, ...] = ("svg", "pdf", "png"),
) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = index.chart(spec)
    (output / "spec.yaml").write_text(
        yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    atomic_write_json(output / "data.json", data)
    atomic_write_json(output / "provenance.json", _provenance(index, spec.filters, kind="chart"))
    if formats:
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ResearchAssistantError(
                "figure export requires research-assistant[reports]"
            ) from exc
        figure, axes = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
        if spec.chart_type == "bar":
            observations = [
                (series["name"], series["points"][-1])
                for series in data["series"]
                if series["points"]
            ]
            names = [name for name, _ in observations]
            values = [point["y"] for _, point in observations]
            lower = [point["y"] - point["lower"] for _, point in observations]
            upper = [point["upper"] - point["y"] for _, point in observations]
            axes.bar(
                names,
                values,
                yerr=[lower, upper] if spec.uncertainty != "none" else None,
                capsize=3,
            )
            axes.tick_params(axis="x", rotation=25)
            axes.set_xlabel(spec.group_by.replace("_", " "))
        else:
            for series in data["series"]:
                x = [point["x"] for point in series["points"]]
                y = [point["y"] for point in series["points"]]
                lower = [point["lower"] for point in series["points"]]
                upper = [point["upper"] for point in series["points"]]
                line = axes.plot(x, y, label=series["name"])[0]
                if spec.uncertainty != "none":
                    axes.fill_between(
                        x, lower, upper, color=line.get_color(), alpha=0.18, linewidth=0
                    )
            axes.set_xlabel(spec.x_label)
        axes.set_ylabel(spec.y_label or ", ".join(spec.filters.metrics) or "value")
        axes.set_yscale(spec.y_scale)
        if spec.title:
            axes.set_title(spec.title)
        if data["series"] and spec.chart_type == "line":
            axes.legend(frameon=False)
        axes.grid(alpha=0.2)
        for file_format in formats:
            if file_format not in {"svg", "pdf", "png"}:
                raise ResearchAssistantError(f"unsupported chart format: {file_format}")
            figure.savefig(output / f"chart.{file_format}", dpi=180)
        plt.close(figure)
    return output
