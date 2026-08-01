from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError


ArtifactKind = Literal[
    "array",
    "prediction",
    "target",
    "error",
    "mask",
    "latent",
    "gradient",
    "jacobian",
    "image",
    "table",
    "video",
    "other",
]


class ScientificArtifactError(ResearchAssistantError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _shape(value: Any) -> list[int]:
    shape: list[int] = []
    node = value
    while isinstance(node, list):
        shape.append(len(node))
        if not node:
            break
        node = node[0]
    return shape


def _flatten(value: Any) -> list[float]:
    if isinstance(value, list):
        result: list[float] = []
        for item in value:
            result.extend(_flatten(item))
        return result
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)]
    raise ScientificArtifactError("artifact contains non-numeric array values")


def _parse_slice(raw: str | int) -> int | slice:
    if isinstance(raw, int):
        return raw
    value = str(raw).strip()
    if ":" not in value:
        try:
            return int(value)
        except ValueError as exc:
            raise ScientificArtifactError(f"invalid array index {value!r}") from exc
    fields = value.split(":")
    if len(fields) > 3:
        raise ScientificArtifactError(f"invalid array slice {value!r}")
    parsed: list[int | None] = []
    for field in fields:
        try:
            parsed.append(None if field == "" else int(field))
        except ValueError as exc:
            raise ScientificArtifactError(f"invalid array slice {value!r}") from exc
    while len(parsed) < 3:
        parsed.append(None)
    return slice(parsed[0], parsed[1], parsed[2])


def _slice_nested(value: Any, selectors: list[int | slice], depth: int = 0) -> Any:
    if depth >= len(selectors):
        return value
    if not isinstance(value, list):
        raise ScientificArtifactError("slice rank exceeds artifact rank")
    selector = selectors[depth]
    if isinstance(selector, int):
        try:
            return _slice_nested(value[selector], selectors, depth + 1)
        except IndexError as exc:
            raise ScientificArtifactError(f"array index {selector} is out of bounds") from exc
    return [_slice_nested(item, selectors, depth + 1) for item in value[selector]]


def _infer_kind(path: Path) -> ArtifactKind:
    lower = path.name.lower()
    for kind in ("prediction", "target", "error", "mask", "latent", "gradient", "jacobian"):
        if kind in lower:
            return kind  # type: ignore[return-value]
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf"}:
        return "image"
    if path.suffix.lower() in {".csv", ".tsv"}:
        return "table"
    if path.suffix.lower() in {".mp4", ".webm", ".gif"}:
        return "video"
    if path.suffix.lower() in {".json", ".npy", ".npz"}:
        return "array"
    return "other"


class ScientificArtifactCatalog:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.catalog_path = self.workspace / ".ra" / "scientific-artifacts.json"

    def _safe_path(self, raw: str | Path) -> Path:
        path = Path(raw)
        resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise ScientificArtifactError(f"path escapes workspace: {raw}")
        return resolved

    def _load(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            return {"version": 1, "artifacts": {}}
        try:
            value = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScientificArtifactError(f"cannot read artifact catalog: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("artifacts"), dict):
            raise ScientificArtifactError("invalid artifact catalog")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.catalog_path, value)

    def _describe(self, path: Path) -> dict[str, Any]:
        description: dict[str, Any] = {"format": path.suffix.lower().lstrip(".") or "file"}
        if path.suffix.lower() == ".json" and path.stat().st_size <= 32 * 1024 * 1024:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return description
            if isinstance(value, dict) and "data" in value:
                value = value["data"]
            if isinstance(value, list):
                description.update({"shape": _shape(value), "numeric": True})
        elif path.suffix.lower() in {".csv", ".tsv"}:
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle, delimiter=delimiter))
            description.update(
                {
                    "shape": [max(0, len(rows) - 1), len(rows[0]) if rows else 0],
                    "columns": rows[0] if rows else [],
                }
            )
        elif path.suffix.lower() in {".npy", ".npz"}:
            try:
                import numpy as np
            except ImportError:
                description["requires"] = "numpy"
            else:
                loaded = np.load(path, mmap_mode="r", allow_pickle=False)
                if hasattr(loaded, "files"):
                    description["keys"] = list(loaded.files)
                    description["shape"] = {
                        key: list(loaded[key].shape) for key in loaded.files
                    }
                else:
                    description["shape"] = list(loaded.shape)
                    description["dtype"] = str(loaded.dtype)
        return description

    def register(
        self,
        path: str | Path,
        *,
        kind: ArtifactKind | None = None,
        name: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        sample_id: str | None = None,
        role: str | None = None,
        dimensions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved = self._safe_path(path)
        if not resolved.is_file():
            raise ScientificArtifactError(f"artifact does not exist: {resolved}")
        relative = resolved.relative_to(self.workspace).as_posix()
        digest = _sha256(resolved)
        artifact_id = hashlib.sha256(f"{relative}\0{digest}".encode()).hexdigest()[:20]
        now = utc_now()
        item = {
            "artifact_id": artifact_id,
            "path": relative,
            "name": name or resolved.name,
            "kind": kind or _infer_kind(resolved),
            "run_id": run_id,
            "stage": stage,
            "sample_id": sample_id,
            "role": role,
            "dimensions": dimensions or [],
            "metadata": metadata or {},
            "tags": sorted(set(tags or [])),
            "size": resolved.stat().st_size,
            "sha256": digest,
            "modified_at": resolved.stat().st_mtime,
            "registered_at": now,
            "description": self._describe(resolved),
        }
        catalog = self._load()
        catalog["artifacts"][artifact_id] = item
        self._save(catalog)
        return item

    def discover(self, roots: list[str] | None = None, *, limit: int = 10000) -> dict[str, Any]:
        accepted = {".json", ".csv", ".tsv", ".npy", ".npz", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf", ".mp4", ".webm", ".gif"}
        added: list[dict[str, Any]] = []
        scanned = 0
        for raw_root in roots or ["runs", "reports"]:
            root = self._safe_path(raw_root)
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if scanned >= limit:
                    return {"scanned": scanned, "added": added, "truncated": True}
                if not path.is_file() or path.suffix.lower() not in accepted:
                    continue
                if ".ra" in path.parts:
                    continue
                scanned += 1
                try:
                    added.append(self.register(path))
                except ScientificArtifactError:
                    continue
        return {"scanned": scanned, "added": added, "truncated": False}

    def list(
        self,
        *,
        kind: str | None = None,
        run_id: str | None = None,
        sample_id: str | None = None,
        search: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        query = (search or "").lower().strip()
        rows: list[dict[str, Any]] = []
        for item in self._load()["artifacts"].values():
            if kind and item.get("kind") != kind:
                continue
            if run_id and item.get("run_id") != run_id:
                continue
            if sample_id and item.get("sample_id") != sample_id:
                continue
            haystack = " ".join(
                str(item.get(key) or "") for key in ("name", "path", "kind", "run_id", "sample_id")
            ).lower()
            if query and query not in haystack:
                continue
            row = dict(item)
            row["exists"] = (self.workspace / row["path"]).is_file()
            rows.append(row)
        rows.sort(key=lambda row: float(row.get("modified_at") or 0), reverse=True)
        return rows[:limit]

    def require(self, artifact_id: str, *, refresh: bool = False) -> dict[str, Any]:
        catalog = self._load()
        if artifact_id not in catalog["artifacts"]:
            raise ScientificArtifactError(f"unknown artifact {artifact_id!r}")
        item = dict(catalog["artifacts"][artifact_id])
        path = self._safe_path(item["path"])
        if not path.is_file():
            item["exists"] = False
            return item
        if refresh:
            item.update(
                {
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                    "modified_at": path.stat().st_mtime,
                    "description": self._describe(path),
                }
            )
            catalog["artifacts"][artifact_id] = item
            self._save(catalog)
        item["exists"] = True
        return item

    def _load_array(self, item: dict[str, Any], key: str | None = None) -> Any:
        path = self._safe_path(item["path"])
        suffix = path.suffix.lower()
        if suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                selected_key = key or ("data" if "data" in value else None)
                if selected_key is None or selected_key not in value:
                    raise ScientificArtifactError("JSON array artifact requires --key")
                value = value[selected_key]
            if not isinstance(value, list):
                raise ScientificArtifactError("JSON artifact does not contain an array")
            return value
        if suffix in {".npy", ".npz"}:
            try:
                import numpy as np
            except ImportError as exc:
                raise ScientificArtifactError("NumPy is required for .npy/.npz artifacts") from exc
            loaded = np.load(path, allow_pickle=False)
            if hasattr(loaded, "files"):
                selected_key = key or (loaded.files[0] if len(loaded.files) == 1 else None)
                if selected_key is None or selected_key not in loaded.files:
                    raise ScientificArtifactError("NPZ artifact requires a valid key")
                loaded = loaded[selected_key]
            return loaded.tolist()
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle, delimiter=delimiter))
            start = 1 if rows and any(not _is_number(value) for value in rows[0]) else 0
            return [[float(value) for value in row] for row in rows[start:] if row]
        raise ScientificArtifactError(f"unsupported array format: {suffix or path.name}")

    def slice(
        self,
        artifact_id: str,
        *,
        selection: list[str | int] | None = None,
        key: str | None = None,
        max_elements: int = 100000,
    ) -> dict[str, Any]:
        item = self.require(artifact_id)
        value = self._load_array(item, key=key)
        selectors = [_parse_slice(raw) for raw in selection or []]
        sliced = _slice_nested(value, selectors) if selectors else value
        flat = _flatten(sliced)
        if len(flat) > max_elements:
            raise ScientificArtifactError(
                f"slice contains {len(flat)} values; limit is {max_elements}"
            )
        finite = [number for number in flat if math.isfinite(number)]
        return {
            "artifact_id": artifact_id,
            "selection": selection or [],
            "shape": _shape(sliced),
            "count": len(flat),
            "finite_count": len(finite),
            "minimum": min(finite) if finite else None,
            "maximum": max(finite) if finite else None,
            "mean": sum(finite) / len(finite) if finite else None,
            "data": sliced,
        }

    def compare(self, left_id: str, right_id: str, *, key: str | None = None) -> dict[str, Any]:
        left = self._load_array(self.require(left_id), key=key)
        right = self._load_array(self.require(right_id), key=key)
        left_shape = _shape(left)
        right_shape = _shape(right)
        if left_shape != right_shape:
            return {
                "compatible": False,
                "left_shape": left_shape,
                "right_shape": right_shape,
            }
        left_values = _flatten(left)
        right_values = _flatten(right)
        differences = [a - b for a, b in zip(left_values, right_values, strict=True)]
        absolute = [abs(value) for value in differences]
        squared = [value * value for value in differences]
        return {
            "compatible": True,
            "left_shape": left_shape,
            "right_shape": right_shape,
            "count": len(differences),
            "mae": sum(absolute) / len(absolute) if absolute else 0.0,
            "rmse": math.sqrt(sum(squared) / len(squared)) if squared else 0.0,
            "maximum_absolute_error": max(absolute) if absolute else 0.0,
        }


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
