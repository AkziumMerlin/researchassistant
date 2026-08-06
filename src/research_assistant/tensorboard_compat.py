from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from research_assistant.errors import ResearchAssistantError

EVENT_PREFIX = "events.out.tfevents."
MAX_EVENT_FILES = 20_000
MAX_RUNS = 2_000
MAX_SOURCE_POINTS = 100_000
MAX_ERRORS = 100
IGNORED_SCAN_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


class TensorBoardCompatibilityError(ResearchAssistantError):
    pass


@dataclass(frozen=True, slots=True)
class ScalarPoint:
    step: float
    wall_time: float
    value: float


@dataclass(frozen=True, slots=True)
class TensorBoardRun:
    name: str
    path: str
    event_files: tuple[str, ...]
    tags: dict[str, tuple[ScalarPoint, ...]]
    unsupported: dict[str, int]


@dataclass(frozen=True, slots=True)
class TensorBoardSnapshot:
    root: Path
    fingerprint: tuple[tuple[str, int, int], ...]
    event_file_count: int
    runs: tuple[TensorBoardRun, ...]
    errors: tuple[str, ...]
    unsupported: dict[str, int]
    truncated: bool


def _tensorboard_modules():
    try:
        from tensorboard.backend.event_processing import event_accumulator
        from tensorboard.util import tensor_util
    except ImportError as exc:
        raise TensorBoardCompatibilityError(
            "TensorBoard support is not installed in the Python environment running the "
            "ResearchAssistant sidecar. Install it with: "
            "python -m pip install 'research-assistant[tensorboard]'"
        ) from exc
    return event_accumulator, tensor_util


def _scan_event_files(root: Path) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in IGNORED_SCAN_DIRECTORIES
            and not (current_path / name).is_symlink()
        )
        for name in sorted(names):
            if not name.startswith(EVENT_PREFIX):
                continue
            path = current_path / name
            if path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            if not resolved.is_file() or not resolved.is_relative_to(root):
                continue
            files.append(resolved)
            if len(files) >= MAX_EVENT_FILES:
                truncated = True
                break
        if truncated:
            break
    return files, truncated


def _fingerprint(root: Path, files: list[Path]) -> tuple[tuple[str, int, int], ...]:
    rows: list[tuple[str, int, int]] = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(rows)


def _unsupported_count(value: Any) -> int:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return int(bool(value))


def _simple_scalar_events(accumulator: Any, tag: str) -> tuple[ScalarPoint, ...]:
    points: list[ScalarPoint] = []
    for event in accumulator.Scalars(tag):
        value = float(event.value)
        if math.isfinite(value):
            points.append(
                ScalarPoint(
                    step=float(event.step),
                    wall_time=float(event.wall_time),
                    value=value,
                )
            )
    return tuple(points)


def _tensor_scalar_events(
    accumulator: Any,
    tensor_util: Any,
    tag: str,
) -> tuple[ScalarPoint, ...]:
    points: list[ScalarPoint] = []
    for event in accumulator.Tensors(tag):
        try:
            array = tensor_util.make_ndarray(event.tensor_proto)
            if int(array.size) != 1:
                return ()
            value = float(array.reshape(-1)[0])
        except (TypeError, ValueError, OverflowError):
            return ()
        if math.isfinite(value):
            points.append(
                ScalarPoint(
                    step=float(event.step),
                    wall_time=float(event.wall_time),
                    value=value,
                )
            )
    return tuple(points)


def _load_run(root: Path, directory: Path, event_files: list[Path]) -> TensorBoardRun:
    event_accumulator, tensor_util = _tensorboard_modules()
    accumulator = event_accumulator.EventAccumulator(
        str(directory),
        size_guidance={
            event_accumulator.SCALARS: MAX_SOURCE_POINTS,
            event_accumulator.TENSORS: MAX_SOURCE_POINTS,
        },
        purge_orphaned_data=True,
    )
    accumulator.Reload()
    raw_tags = accumulator.Tags()
    tags: dict[str, tuple[ScalarPoint, ...]] = {}
    for tag in sorted(raw_tags.get("scalars", [])):
        points = _simple_scalar_events(accumulator, str(tag))
        if points:
            tags[str(tag)] = points
    for tag in sorted(raw_tags.get("tensors", [])):
        normalized = str(tag)
        if normalized in tags:
            continue
        points = _tensor_scalar_events(accumulator, tensor_util, normalized)
        if points:
            tags[normalized] = points

    unsupported: dict[str, int] = {}
    for kind, value in raw_tags.items():
        if kind in {"scalars", "tensors"}:
            continue
        count = _unsupported_count(value)
        if count:
            unsupported[str(kind)] = count
    tensor_count = len(raw_tags.get("tensors", [])) - len(
        [tag for tag in raw_tags.get("tensors", []) if str(tag) in tags]
    )
    if tensor_count > 0:
        unsupported["non_scalar_tensors"] = tensor_count

    relative = directory.relative_to(root).as_posix()
    name = relative if relative != "." else root.name
    return TensorBoardRun(
        name=name,
        path=relative,
        event_files=tuple(path.relative_to(root).as_posix() for path in event_files),
        tags=tags,
        unsupported=unsupported,
    )


def _deduplicate(points: tuple[ScalarPoint, ...]) -> list[ScalarPoint]:
    latest: dict[float, ScalarPoint] = {}
    for point in points:
        previous = latest.get(point.step)
        if previous is None or point.wall_time >= previous.wall_time:
            latest[point.step] = point
    return sorted(latest.values(), key=lambda point: (point.step, point.wall_time))


def _smooth(values: list[float], weight: float) -> list[float]:
    if weight <= 0 or len(values) < 2:
        return list(values)
    result: list[float] = []
    weighted = 0.0
    normalization = 0.0
    for value in values:
        weighted = weighted * weight + value
        normalization = normalization * weight + 1.0
        result.append(weighted / normalization)
    return result


def _largest_triangle_three_buckets(
    points: list[tuple[float, float]],
    threshold: int,
) -> list[tuple[float, float]]:
    if threshold >= len(points) or threshold <= 0:
        return points
    if threshold == 1:
        return [points[0]]
    if threshold == 2:
        return [points[0], points[-1]]

    sampled = [points[0]]
    bucket_size = (len(points) - 2) / (threshold - 2)
    selected_index = 0
    for bucket in range(threshold - 2):
        average_start = int(math.floor((bucket + 1) * bucket_size)) + 1
        average_end = int(math.floor((bucket + 2) * bucket_size)) + 1
        average_end = min(average_end, len(points))
        average_bucket = points[average_start:average_end]
        if average_bucket:
            average_x = sum(point[0] for point in average_bucket) / len(average_bucket)
            average_y = sum(point[1] for point in average_bucket) / len(average_bucket)
        else:
            average_x, average_y = points[-1]

        range_start = int(math.floor(bucket * bucket_size)) + 1
        range_end = int(math.floor((bucket + 1) * bucket_size)) + 1
        range_end = min(max(range_end, range_start + 1), len(points) - 1)
        anchor_x, anchor_y = points[selected_index]
        best_area = -1.0
        best_index = range_start
        for candidate_index in range(range_start, range_end):
            candidate_x, candidate_y = points[candidate_index]
            area = abs(
                (anchor_x - average_x) * (candidate_y - anchor_y)
                - (anchor_x - candidate_x) * (average_y - anchor_y)
            )
            if area > best_area:
                best_area = area
                best_index = candidate_index
        sampled.append(points[best_index])
        selected_index = best_index
    sampled.append(points[-1])
    return sampled


class TensorBoardStore:
    """Cached scalar reader for existing TensorBoard event directories."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self._cache: dict[str, TensorBoardSnapshot] = {}

    def _snapshot(
        self,
        root: Path,
        *,
        force: bool = False,
    ) -> tuple[TensorBoardSnapshot, bool]:
        root = root.resolve()
        files, scan_truncated = _scan_event_files(root)
        fingerprint = _fingerprint(root, files)
        key = str(root)
        cached = self._cache.get(key)
        if not force and cached is not None and cached.fingerprint == fingerprint:
            return cached, True

        grouped: dict[Path, list[Path]] = {}
        for path in files:
            grouped.setdefault(path.parent, []).append(path)
        errors: list[str] = []
        runs: list[TensorBoardRun] = []
        unsupported: dict[str, int] = {}
        run_truncated = len(grouped) > MAX_RUNS
        directories = sorted(
            grouped,
            key=lambda path: path.relative_to(root).as_posix(),
        )[:MAX_RUNS]
        for directory in directories:
            try:
                run = _load_run(root, directory, grouped[directory])
            except Exception as exc:  # TensorBoard exposes several parser-specific exceptions.
                if len(errors) < MAX_ERRORS:
                    relative = directory.relative_to(root).as_posix()
                    errors.append(f"{relative}: {type(exc).__name__}: {exc}")
                continue
            for kind, count in run.unsupported.items():
                unsupported[kind] = unsupported.get(kind, 0) + count
            if not run.tags:
                if len(errors) < MAX_ERRORS:
                    errors.append(f"{run.path}: no readable scalar summaries")
                continue
            runs.append(run)

        snapshot = TensorBoardSnapshot(
            root=root,
            fingerprint=fingerprint,
            event_file_count=len(files),
            runs=tuple(runs),
            errors=tuple(errors),
            unsupported=unsupported,
            truncated=scan_truncated or run_truncated,
        )
        self._cache[key] = snapshot
        return snapshot, False

    def catalog(
        self,
        root: str | Path,
        *,
        force: bool = False,
        max_runs: int = 500,
    ) -> dict[str, Any]:
        snapshot, cache_hit = self._snapshot(Path(root), force=force)
        tag_summary: dict[str, dict[str, int]] = {}
        run_rows: list[dict[str, Any]] = []
        for run in snapshot.runs:
            tag_counts = {tag: len(points) for tag, points in run.tags.items()}
            for tag, count in tag_counts.items():
                summary = tag_summary.setdefault(tag, {"runs": 0, "points": 0})
                summary["runs"] += 1
                summary["points"] += count
            if len(run_rows) < max_runs:
                latest_wall_time = max(
                    (point.wall_time for points in run.tags.values() for point in points),
                    default=None,
                )
                run_rows.append(
                    {
                        "name": run.name,
                        "path": run.path,
                        "event_files": list(run.event_files),
                        "event_file_count": len(run.event_files),
                        "scalar_tags": sorted(run.tags),
                        "tag_counts": tag_counts,
                        "point_count": sum(tag_counts.values()),
                        "latest_wall_time": latest_wall_time,
                        "unsupported": dict(run.unsupported),
                    }
                )
        tags = [
            {"name": tag, **values}
            for tag, values in sorted(
                tag_summary.items(),
                key=lambda item: (-item[1]["runs"], item[0].casefold(), item[0]),
            )
        ]
        return {
            "root": snapshot.root.relative_to(self.workspace_root).as_posix(),
            "event_files": snapshot.event_file_count,
            "run_count": len(snapshot.runs),
            "runs": run_rows,
            "runs_truncated": len(snapshot.runs) > len(run_rows),
            "tags": tags,
            "tag_count": len(tags),
            "unsupported": dict(snapshot.unsupported),
            "errors": list(snapshot.errors),
            "truncated": snapshot.truncated,
            "cache_hit": cache_hit,
            "source_point_limit_per_tag": MAX_SOURCE_POINTS,
        }

    def chart(
        self,
        root: str | Path,
        *,
        runs: list[str],
        tags: list[str],
        x_axis: Literal["step", "relative_time", "wall_time"] = "step",
        smoothing: float = 0.0,
        max_points: int = 1000,
        max_series: int = 50,
        y_scale: Literal["linear", "log"] = "linear",
        title: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        snapshot, cache_hit = self._snapshot(Path(root), force=force)
        selected_runs = set(runs)
        requested_tags = list(dict.fromkeys(tags))
        candidates: list[tuple[str, str, list[tuple[float, float]]]] = []
        for run in snapshot.runs:
            if selected_runs and run.name not in selected_runs and run.path not in selected_runs:
                continue
            for tag in requested_tags:
                raw = run.tags.get(tag)
                if not raw:
                    continue
                deduplicated = _deduplicate(raw)
                if not deduplicated:
                    continue
                first_wall_time = min(point.wall_time for point in deduplicated)
                values = _smooth([point.value for point in deduplicated], smoothing)
                points: list[tuple[float, float]] = []
                for point, value in zip(deduplicated, values, strict=True):
                    if y_scale == "log" and value <= 0:
                        continue
                    if x_axis == "step":
                        x = point.step
                    elif x_axis == "relative_time":
                        x = (point.wall_time - first_wall_time) / 3600.0
                    else:
                        x = point.wall_time
                    if math.isfinite(x) and math.isfinite(value):
                        points.append((x, value))
                if not points:
                    continue
                points.sort(key=lambda item: item[0])
                points = _largest_triangle_three_buckets(points, max_points)
                name = run.name if len(requested_tags) == 1 else f"{run.name} · {tag}"
                candidates.append((name, tag, points))

        total = len(candidates)
        series = [
            {
                "name": name,
                "tag": tag,
                "points": [{"x": x, "y": y, "n": 1} for x, y in points],
            }
            for name, tag, points in candidates[:max_series]
        ]
        missing_runs = sorted(
            selected_runs
            - {run.name for run in snapshot.runs}
            - {run.path for run in snapshot.runs}
        )
        available_tags = {tag for run in snapshot.runs for tag in run.tags}
        missing_tags = sorted(set(requested_tags) - available_tags)
        warnings: list[str] = []
        if missing_runs:
            warnings.append(f"Unknown runs: {', '.join(missing_runs[:20])}")
        if missing_tags:
            warnings.append(f"Unknown scalar tags: {', '.join(missing_tags[:20])}")
        if snapshot.errors:
            warnings.append(f"{len(snapshot.errors)} TensorBoard run(s) could not be parsed")
        x_label = {
            "step": "step",
            "relative_time": "relative time (hours)",
            "wall_time": "wall time (Unix seconds)",
        }[x_axis]
        y_label = requested_tags[0] if len(requested_tags) == 1 else "TensorBoard scalar"
        return {
            "chart": {
                "spec": {
                    "chart_type": "line",
                    "uncertainty": "none",
                    "y_scale": y_scale,
                    "title": title or y_label,
                    "x_label": x_label,
                    "y_label": y_label,
                },
                "series": series,
                "series_count": len(series),
                "series_total": total,
                "truncated": total > len(series),
            },
            "source": {
                "root": snapshot.root.relative_to(self.workspace_root).as_posix(),
                "event_files": snapshot.event_file_count,
                "runs": len(snapshot.runs),
                "cache_hit": cache_hit,
                "x_axis": x_axis,
                "smoothing": smoothing,
            },
            "warnings": warnings,
        }
