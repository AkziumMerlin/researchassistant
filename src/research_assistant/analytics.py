from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import statistics
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_assistant.errors import ResearchAssistantError

GROUP_FIELDS = {
    "study_id": "r.study_id",
    "trial_id": "r.trial_id",
    "run_id": "e.run_id",
    "stage": "e.stage",
    "metric": "e.metric",
    "seed": "CAST(r.seed AS TEXT)",
    "model": "COALESCE(r.model, r.trial_id)",
    "dataset": "COALESCE(e.dataset, r.dataset, 'unknown')",
    "split": "COALESCE(e.split, 'unknown')",
}


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricFilter(AnalyticsModel):
    study_ids: list[str] = Field(default_factory=list)
    trial_ids: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    kinds: list[Literal["progress", "final", "resource"]] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    splits: list[str] = Field(default_factory=list)


class ChartSpec(AnalyticsModel):
    name: str = "chart"
    artifact_root: str = "runs"
    filters: MetricFilter = Field(default_factory=MetricFilter)
    chart_type: Literal["line", "bar"] = "line"
    group_by: Literal[
        "study_id", "trial_id", "run_id", "stage", "metric", "seed", "model", "dataset", "split"
    ] = "trial_id"
    aggregate: Literal["mean", "min", "max"] = "mean"
    uncertainty: Literal["none", "std", "sem", "range"] = "std"
    max_points: int = Field(default=1000, ge=20, le=10000)
    max_series: int = Field(default=50, ge=1, le=500)
    y_scale: Literal["linear", "log"] = "linear"
    title: str | None = None
    x_label: str = "step"
    y_label: str | None = None


class TableSpec(AnalyticsModel):
    name: str = "table"
    artifact_root: str = "runs"
    filters: MetricFilter = Field(default_factory=lambda: MetricFilter(kinds=["final"]))
    row: Literal["study_id", "trial_id", "stage", "metric", "model", "dataset", "split"] = (
        "dataset"
    )
    column: Literal["study_id", "trial_id", "stage", "metric", "model", "dataset", "split"] = (
        "model"
    )
    aggregate: Literal["mean_std", "mean", "min", "max"] = "mean_std"
    precision: int = Field(default=4, ge=1, le=10)
    direction: Literal["minimize", "maximize", "none"] = "minimize"
    bold_best: bool = True
    underline_second: bool = False
    caption: str | None = None
    label: str | None = None
    missing: str = "--"
    max_rows: int = Field(default=100, ge=1, le=1000)
    max_columns: int = Field(default=50, ge=1, le=500)


EvaluationGroupField = Literal[
    "study_id", "trial_id", "stage", "model", "dataset", "split"
]


class EvaluationSpec(AnalyticsModel):
    """Select a checkpoint step per run, then aggregate a target metric across runs."""

    name: str = "evaluation"
    artifact_root: str = "runs"
    filters: MetricFilter = Field(default_factory=lambda: MetricFilter(states=["completed"]))
    selection_metric: str
    target_metric: str
    stage: str | None = None
    selection_split: str | None = None
    target_split: str | None = None
    selection_kind: Literal["progress", "final"] = "progress"
    target_kind: Literal["progress", "final"] = "progress"
    direction: Literal["minimize", "maximize"] = "minimize"
    alignment: Literal["same_step", "latest"] = "same_step"
    group_by: list[EvaluationGroupField] = Field(
        default_factory=lambda: ["dataset", "model"],
        min_length=1,
        max_length=3,
    )
    precision: int = Field(default=4, ge=1, le=10)
    table_direction: Literal["minimize", "maximize", "none"] = "minimize"
    bold_best: bool = True
    underline_second: bool = False
    caption: str | None = None
    label: str | None = None
    max_runs: int = Field(default=2000, ge=1, le=10000)

    @field_validator("group_by")
    @classmethod
    def unique_group_fields(
        cls,
        value: list[EvaluationGroupField],
    ) -> list[EvaluationGroupField]:
        if len(value) != len(set(value)):
            raise ValueError("evaluation group_by fields must be unique")
        return value


def _iter_run_directories(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    try:
        studies = os.scandir(root)
    except OSError:
        return
    with studies:
        for study in studies:
            if not study.is_dir(follow_symlinks=False) or study.name.startswith("."):
                continue
            try:
                runs = os.scandir(study.path)
            except OSError:
                continue
            with runs:
                for run in runs:
                    if run.is_dir(follow_symlinks=False) and not run.name.startswith("."):
                        yield Path(run.path)


def _component_type(config: dict[str, Any], kind: str) -> str | None:
    reference = (config.get("components") or {}).get(kind) or {}
    value = reference.get("type")
    return str(value) if value else None


class MetricIndex:
    """Rebuildable, incremental index over self-contained run directories."""

    def __init__(self, artifact_root: str | Path, database: str | Path | None = None) -> None:
        self.root = Path(artifact_root).expanduser().resolve()
        self.database = Path(database or self.root / ".ra-index.sqlite3")
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.create_function("SQRT", 1, math.sqrt)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA temp_store=MEMORY")
        self._connection.execute("PRAGMA cache_size=-65536")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL,
                trial_id TEXT NOT NULL,
                seed INTEGER,
                state TEXT NOT NULL,
                model TEXT,
                dataset TEXT,
                manifest_path TEXT NOT NULL UNIQUE,
                config_json TEXT NOT NULL,
                assignments_json TEXT NOT NULL,
                manifest_mtime_ns INTEGER NOT NULL,
                status_mtime_ns INTEGER NOT NULL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS metric_events (
                event_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_offset INTEGER NOT NULL,
                schema_version INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                run_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                stage TEXT NOT NULL,
                kind TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                step REAL,
                step_kind TEXT,
                dataset TEXT,
                split TEXT,
                horizon TEXT,
                resolution TEXT,
                dimensions_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS index_files (
                path TEXT PRIMARY KEY,
                offset INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS metric_run_idx
                ON metric_events(run_id, stage, metric, kind, step);
            CREATE INDEX IF NOT EXISTS metric_query_idx
                ON metric_events(metric, kind, stage, step);
            CREATE INDEX IF NOT EXISTS metric_dimensions_idx
                ON metric_events(dataset, split, metric);
            CREATE INDEX IF NOT EXISTS runs_trial_idx
                ON runs(study_id, trial_id, state);
            """
        )
        self._connection.commit()

    def rebuild(self) -> dict[str, int]:
        with self._lock:
            self._connection.executescript(
                "DELETE FROM metric_events; DELETE FROM index_files; DELETE FROM runs;"
            )
            self._connection.commit()
        return self.refresh()

    def refresh(self, *, batch_size: int = 5000) -> dict[str, int]:
        stats = {"runs_scanned": 0, "runs_updated": 0, "events_indexed": 0, "skipped": 0}
        with self._lock:
            for run_dir in _iter_run_directories(self.root):
                manifest_path = run_dir / "manifest.json"
                status_path = run_dir / "status.json"
                if not manifest_path.is_file():
                    continue
                stats["runs_scanned"] += 1
                if self._upsert_run(manifest_path, status_path):
                    stats["runs_updated"] += 1
                metrics_path = run_dir / "metrics.jsonl"
                if metrics_path.is_file():
                    indexed, skipped = self._ingest_metrics(metrics_path, batch_size=batch_size)
                    stats["events_indexed"] += indexed
                    stats["skipped"] += skipped
            self._connection.commit()
        return stats

    def _upsert_run(self, manifest_path: Path, status_path: Path) -> bool:
        manifest_stat = manifest_path.stat()
        status_mtime = status_path.stat().st_mtime_ns if status_path.is_file() else 0
        existing = self._connection.execute(
            "SELECT manifest_mtime_ns, status_mtime_ns FROM runs WHERE manifest_path = ?",
            (str(manifest_path),),
        ).fetchone()
        if existing and tuple(existing) == (manifest_stat.st_mtime_ns, status_mtime):
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = (
                json.loads(status_path.read_text(encoding="utf-8"))
                if status_path.is_file()
                else {}
            )
        except (OSError, ValueError, TypeError):
            return False
        config = manifest.get("config") or {}
        run_id = str(manifest.get("run_id") or manifest_path.parent.name)
        self._connection.execute(
            """
            INSERT INTO runs (
                run_id, study_id, trial_id, seed, state, model, dataset, manifest_path,
                config_json, assignments_json, manifest_mtime_ns, status_mtime_ns, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                state=excluded.state, model=excluded.model, dataset=excluded.dataset,
                config_json=excluded.config_json, assignments_json=excluded.assignments_json,
                manifest_mtime_ns=excluded.manifest_mtime_ns,
                status_mtime_ns=excluded.status_mtime_ns, updated_at=excluded.updated_at
            """,
            (
                run_id,
                str(manifest.get("study_id", "unknown")),
                str(manifest.get("trial_id", "unknown")),
                config.get("seed"),
                str(status.get("state", "pending")),
                _component_type(config, "model"),
                _component_type(config, "data"),
                str(manifest_path),
                json.dumps(config, sort_keys=True),
                json.dumps(manifest.get("assignments") or {}, sort_keys=True),
                manifest_stat.st_mtime_ns,
                status_mtime,
                status.get("updated_at"),
            ),
        )
        return True

    def _ingest_metrics(self, path: Path, *, batch_size: int) -> tuple[int, int]:
        stat = path.stat()
        state = self._connection.execute(
            "SELECT offset, size FROM index_files WHERE path = ?", (str(path),)
        ).fetchone()
        offset = int(state["offset"]) if state else 0
        if stat.st_size < offset:
            self._connection.execute(
                "DELETE FROM metric_events WHERE source_path = ?", (str(path),)
            )
            offset = 0
        if stat.st_size == offset and state and int(state["size"]) == stat.st_size:
            return 0, 0

        pending: list[tuple[Any, ...]] = []
        indexed = 0
        skipped = 0
        consumed = offset
        with path.open("rb") as stream:
            stream.seek(offset)
            while True:
                line_offset = stream.tell()
                raw = stream.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    break
                consumed = stream.tell()
                try:
                    payload = json.loads(raw)
                    rows = self._event_rows(payload, path, line_offset)
                except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
                    skipped += 1
                    continue
                pending.extend(rows)
                if len(pending) >= batch_size:
                    indexed += self._insert_events(pending)
                    pending.clear()
        if pending:
            indexed += self._insert_events(pending)
        self._connection.execute(
            """
            INSERT INTO index_files(path, offset, size, mtime_ns) VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                offset=excluded.offset, size=excluded.size, mtime_ns=excluded.mtime_ns
            """,
            (str(path), consumed, stat.st_size, stat.st_mtime_ns),
        )
        return indexed, skipped

    def _event_rows(
        self, payload: dict[str, Any], path: Path, line_offset: int
    ) -> list[tuple[Any, ...]]:
        if "metric" in payload and "value" in payload:
            values = [(str(payload["metric"]), float(payload["value"]))]
        else:
            values = [
                (str(name), float(value)) for name, value in (payload.get("metrics") or {}).items()
            ]
        dimensions = payload.get("dimensions") or {}
        rows: list[tuple[Any, ...]] = []
        for metric, value in values:
            if not math.isfinite(value):
                continue
            event_id = payload.get("event_id")
            if not event_id or len(values) > 1:
                identity = f"{path}:{line_offset}:{metric}".encode()
                event_id = hashlib.sha256(identity).hexdigest()
            rows.append(
                (
                    str(event_id),
                    str(path),
                    line_offset,
                    int(payload.get("schema_version", 0)),
                    str(payload.get("timestamp", "")),
                    str(payload.get("run_id", path.parent.name)),
                    int(payload.get("attempt", 1)),
                    int(payload.get("sequence", line_offset)),
                    str(payload.get("stage", "unknown")),
                    str(payload.get("kind", "progress")),
                    metric,
                    value,
                    float(payload["step"]) if payload.get("step") is not None else None,
                    str(payload.get("step_kind", "epoch")),
                    self._dimension(dimensions, "dataset"),
                    self._dimension(dimensions, "split"),
                    self._dimension(dimensions, "horizon"),
                    self._dimension(dimensions, "resolution"),
                    json.dumps(dimensions, sort_keys=True, ensure_ascii=False),
                )
            )
        return rows

    @staticmethod
    def _dimension(dimensions: dict[str, Any], name: str) -> str | None:
        value = dimensions.get(name)
        return None if value is None else str(value)

    def _insert_events(self, rows: Sequence[tuple[Any, ...]]) -> int:
        before = self._connection.total_changes
        self._connection.executemany(
            """
            INSERT OR IGNORE INTO metric_events (
                event_id, source_path, source_offset, schema_version, timestamp, run_id,
                attempt, sequence, stage, kind, metric, value, step, step_kind,
                dataset, split, horizon, resolution, dimensions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return self._connection.total_changes - before

    @staticmethod
    def _where(filters: MetricFilter) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        fields = {
            "study_ids": "r.study_id",
            "trial_ids": "r.trial_id",
            "run_ids": "e.run_id",
            "stages": "e.stage",
            "metrics": "e.metric",
            "kinds": "e.kind",
            "states": "r.state",
            "models": "COALESCE(r.model, r.trial_id)",
            "datasets": "COALESCE(e.dataset, r.dataset)",
            "splits": "e.split",
        }
        document = filters.model_dump()
        for name, field in fields.items():
            values = document[name]
            if values:
                clauses.append(f"{field} IN ({','.join('?' for _ in values)})")
                parameters.extend(values)
        return (" AND ".join(clauses) if clauses else "1=1"), parameters

    def catalog(self, *, limit: int = 500) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("catalog limit must be positive")
        with self._lock:
            result: dict[str, Any] = {}
            cardinality: dict[str, int] = {}
            truncated: dict[str, bool] = {}
            tables = {
                "runs": {
                    "studies": "study_id",
                    "trials": "trial_id",
                    "states": "state",
                    "models": "COALESCE(model, trial_id)",
                },
                "metric_events": {
                    "stages": "stage",
                    "metrics": "metric",
                    "kinds": "kind",
                    "datasets": "dataset",
                    "splits": "split",
                },
            }
            for table, dimensions in tables.items():
                for key, expression in dimensions.items():
                    rows = self._connection.execute(
                        f"SELECT DISTINCT {expression} value "
                        f"FROM {table} ORDER BY value LIMIT ?",
                        (limit,),
                    )
                    values = [row["value"] for row in rows if row["value"] is not None]
                    result[key] = values
                    cardinality[key] = int(
                        self._connection.execute(
                            f"SELECT COUNT(DISTINCT {expression}) FROM {table}"
                        ).fetchone()[0]
                    )
                    truncated[key] = cardinality[key] > len(values)
            result["run_count"] = self._connection.execute(
                "SELECT COUNT(*) FROM runs"
            ).fetchone()[0]
            result["event_count"] = self._connection.execute(
                "SELECT COUNT(*) FROM metric_events"
            ).fetchone()[0]
            result["cardinality"] = cardinality
            result["truncated"] = truncated
            return result

    def selected_run_ids(self, filters: MetricFilter) -> list[str]:
        where, parameters = self._where(filters)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT DISTINCT e.run_id FROM metric_events e
                JOIN runs r ON r.run_id=e.run_id WHERE {where} ORDER BY e.run_id
                """,
                parameters,
            )
            return [str(row[0]) for row in rows]

    def chart(self, spec: ChartSpec) -> dict[str, Any]:
        where, parameters = self._where(spec.filters)
        group = GROUP_FIELDS[spec.group_by]
        with self._lock:
            bounds = self._connection.execute(
                f"""
                SELECT MIN(COALESCE(e.step, 0)), MAX(COALESCE(e.step, 0)),
                       COUNT(DISTINCT COALESCE(e.step, 0)), COUNT(DISTINCT {group})
                FROM metric_events e JOIN runs r ON r.run_id=e.run_id WHERE {where}
                """,
                parameters,
            ).fetchone()
            minimum, maximum, distinct, series_total = bounds
            if minimum is None:
                return {
                    "spec": spec.model_dump(mode="json"),
                    "series": [],
                    "points": 0,
                    "series_count": 0,
                    "series_total": 0,
                    "truncated": False,
                }
            width = 0.0
            if distinct > spec.max_points and maximum > minimum:
                width = (maximum - minimum) / (spec.max_points - 1)
            if width:
                x_expression = "(? + CAST((COALESCE(e.step, 0) - ?) / ? AS INTEGER) * ?)"
                x_parameters = [minimum, minimum, width, width]
            else:
                x_expression = "COALESCE(e.step, 0)"
                x_parameters = []
            query_parameters = [
                *parameters,
                spec.max_series,
                *x_parameters,
                *parameters,
            ]
            aggregate = {"mean": "AVG(e.value)", "min": "MIN(e.value)", "max": "MAX(e.value)"}[
                spec.aggregate
            ]
            rows = self._connection.execute(
                f"""
                WITH selected_series AS (
                    SELECT {group} AS series
                    FROM metric_events e JOIN runs r ON r.run_id=e.run_id
                    WHERE {where}
                    GROUP BY series ORDER BY COUNT(*) DESC, series LIMIT ?
                )
                SELECT {group} AS series, {x_expression} AS x,
                       {aggregate} AS y, COUNT(*) AS n,
                       CASE WHEN COUNT(*) > 1 THEN
                         SQRT(MAX((SUM(e.value * e.value) - SUM(e.value) * SUM(e.value) / COUNT(*))
                                  / (COUNT(*) - 1), 0))
                       ELSE 0 END AS std,
                       MIN(e.value) AS minimum, MAX(e.value) AS maximum
                FROM metric_events e JOIN runs r ON r.run_id=e.run_id
                JOIN selected_series selected ON selected.series={group}
                WHERE {where}
                GROUP BY series, x ORDER BY series, x
                """,
                query_parameters,
            ).fetchall()
        series: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            std = float(row["std"] or 0.0)
            n = int(row["n"])
            if spec.uncertainty == "std":
                lower, upper = row["y"] - std, row["y"] + std
            elif spec.uncertainty == "sem":
                sem = std / math.sqrt(n) if n else 0.0
                lower, upper = row["y"] - sem, row["y"] + sem
            elif spec.uncertainty == "range":
                lower, upper = row["minimum"], row["maximum"]
            else:
                lower = upper = row["y"]
            series.setdefault(str(row["series"]), []).append(
                {"x": row["x"], "y": row["y"], "lower": lower, "upper": upper, "n": n}
            )
        return {
            "spec": spec.model_dump(mode="json"),
            "series": [{"name": name, "points": points} for name, points in series.items()],
            "points": sum(len(points) for points in series.values()),
            "series_count": len(series),
            "series_total": int(series_total),
            "truncated": int(series_total) > len(series),
        }

    def table(self, spec: TableSpec) -> dict[str, Any]:
        where, parameters = self._where(spec.filters)
        row_expr, column_expr = GROUP_FIELDS[spec.row], GROUP_FIELDS[spec.column]
        with self._lock:
            totals = self._connection.execute(
                f"""
                SELECT COUNT(DISTINCT {row_expr}), COUNT(DISTINCT {column_expr})
                FROM metric_events e JOIN runs r ON r.run_id=e.run_id WHERE {where}
                """,
                parameters,
            ).fetchone()
            rows = self._connection.execute(
                f"""
                WITH selected_rows AS (
                    SELECT {row_expr} AS dimension_value
                    FROM metric_events e JOIN runs r ON r.run_id=e.run_id
                    WHERE {where}
                    GROUP BY {row_expr} ORDER BY COUNT(*) DESC, {row_expr} LIMIT ?
                ), selected_columns AS (
                    SELECT {column_expr} AS dimension_value
                    FROM metric_events e JOIN runs r ON r.run_id=e.run_id
                    WHERE {where}
                    GROUP BY {column_expr} ORDER BY COUNT(*) DESC, {column_expr} LIMIT ?
                )
                SELECT {row_expr} AS row_name, {column_expr} AS column_name,
                       COUNT(*) AS n, AVG(e.value) AS mean,
                       CASE WHEN COUNT(*) > 1 THEN
                         SQRT(MAX((SUM(e.value * e.value) - SUM(e.value) * SUM(e.value) / COUNT(*))
                                  / (COUNT(*) - 1), 0))
                       ELSE 0 END AS std,
                       MIN(e.value) AS minimum, MAX(e.value) AS maximum
                FROM metric_events e JOIN runs r ON r.run_id=e.run_id
                JOIN selected_rows selected_row ON selected_row.dimension_value={row_expr}
                JOIN selected_columns selected_col ON selected_col.dimension_value={column_expr}
                WHERE {where}
                GROUP BY row_name, column_name ORDER BY row_name, column_name
                """,
                [
                    *parameters,
                    spec.max_rows,
                    *parameters,
                    spec.max_columns,
                    *parameters,
                ],
            ).fetchall()
        cells = [dict(row) for row in rows]
        row_total, column_total = int(totals[0]), int(totals[1])
        row_names = sorted({str(cell["row_name"]) for cell in cells})
        column_names = sorted({str(cell["column_name"]) for cell in cells})
        return {
            "spec": spec.model_dump(mode="json"),
            "rows": row_names,
            "columns": column_names,
            "cells": cells,
            "row_total": row_total,
            "column_total": column_total,
            "truncated": row_total > len(row_names) or column_total > len(column_names),
        }

    def evaluate(self, spec: EvaluationSpec) -> dict[str, Any]:
        """Apply validation-selected evaluation without loading run histories into the browser."""
        base_filters = spec.filters.model_copy(
            update={"metrics": [], "kinds": [], "stages": [], "splits": []}
        )
        where, parameters = self._where(base_filters)
        selection_clauses = ["e.metric = ?", "e.kind = ?"]
        selection_parameters: list[Any] = [spec.selection_metric, spec.selection_kind]
        if spec.stage is not None:
            selection_clauses.append("e.stage = ?")
            selection_parameters.append(spec.stage)
        if spec.selection_split is not None:
            selection_clauses.append("COALESCE(e.split, 'unknown') = ?")
            selection_parameters.append(spec.selection_split)

        target_clauses = ["t.metric = ?", "t.kind = ?", "t.stage = s.stage"]
        target_parameters: list[Any] = [spec.target_metric, spec.target_kind]
        if spec.target_split is not None:
            target_clauses.append("COALESCE(t.split, 'unknown') = ?")
            target_parameters.append(spec.target_split)
        if spec.alignment == "same_step":
            target_clauses.append("t.step IS s.step")
            target_order = "t.sequence DESC"
        else:
            target_order = "COALESCE(t.step, -1) DESC, t.sequence DESC"

        direction = "ASC" if spec.direction == "minimize" else "DESC"
        query = f"""
            WITH ranked_selection AS (
                SELECT e.run_id, e.stage, e.step, e.step_kind, e.value,
                       e.dataset, e.split,
                       ROW_NUMBER() OVER (
                           PARTITION BY e.run_id
                           ORDER BY e.value {direction}, COALESCE(e.step, -1) DESC,
                                    e.sequence DESC
                       ) AS selection_rank
                FROM metric_events e JOIN runs r ON r.run_id=e.run_id
                WHERE {where} AND {" AND ".join(selection_clauses)}
            ), selected AS (
                SELECT * FROM ranked_selection WHERE selection_rank = 1
            )
            SELECT r.study_id, r.trial_id, r.run_id, r.seed, r.state,
                   COALESCE(r.model, r.trial_id) AS model,
                   COALESCE(s.dataset, r.dataset, 'unknown') AS dataset,
                   COALESCE(s.split, 'unknown') AS split,
                   s.stage, s.step AS selected_step, s.step_kind,
                   s.value AS selection_value,
                   (
                       SELECT t.value FROM metric_events t
                       WHERE t.run_id=s.run_id AND {" AND ".join(target_clauses)}
                       ORDER BY {target_order} LIMIT 1
                   ) AS target_value
            FROM selected s JOIN runs r ON r.run_id=s.run_id
            ORDER BY r.study_id, r.trial_id, r.seed, r.run_id
            LIMIT ?
        """
        with self._lock:
            rows = self._connection.execute(
                query,
                [
                    *parameters,
                    *selection_parameters,
                    *target_parameters,
                    spec.max_runs + 1,
                ],
            ).fetchall()

        truncated = len(rows) > spec.max_runs
        rows = rows[: spec.max_runs]
        run_rows: list[dict[str, Any]] = []
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for raw in rows:
            row = dict(raw)
            row["eligible"] = row["target_value"] is not None
            row["reason"] = None if row["eligible"] else "target metric missing at selected step"
            run_rows.append(row)
            if not row["eligible"]:
                continue
            key = tuple(str(row[field]) for field in spec.group_by)
            grouped.setdefault(key, []).append(row)

        groups: list[dict[str, Any]] = []
        for key, observations in sorted(grouped.items()):
            values = [float(row["target_value"]) for row in observations]
            dimensions = dict(zip(spec.group_by, key, strict=True))
            groups.append(
                {
                    "label": " · ".join(key),
                    "dimensions": dimensions,
                    "n": len(values),
                    "mean": statistics.fmean(values),
                    "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "minimum": min(values),
                    "maximum": max(values),
                    "seeds": sorted(
                        row["seed"] for row in observations if row["seed"] is not None
                    ),
                    "run_ids": [str(row["run_id"]) for row in observations],
                }
            )

        eligible = sum(bool(row["eligible"]) for row in run_rows)
        return {
            "spec": spec.model_dump(mode="json"),
            "runs": run_rows,
            "groups": groups,
            "selected_runs": len(run_rows),
            "eligible_runs": eligible,
            "excluded_runs": len(run_rows) - eligible,
            "truncated": truncated,
        }


def bounded_artifact_root(workspace: Path, relative: str) -> Path:
    candidate = (workspace / relative).resolve()
    if Path(relative).is_absolute() or not candidate.is_relative_to(workspace.resolve()):
        raise ResearchAssistantError("artifact root must stay inside the workspace")
    return candidate
