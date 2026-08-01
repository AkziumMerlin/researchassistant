from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError


class WorkspaceError(ResearchAssistantError):
    pass


def _catalog_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "research-assistant" / "workspaces.json"


def _run_json(argv: list[str], *, timeout: float = 30.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"cannot execute {argv[0]!r}: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise WorkspaceError(f"{argv[0]!r} failed: {detail or completed.returncode}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"{argv[0]!r} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise WorkspaceError(f"{argv[0]!r} returned an unexpected payload")
    return value


class WorkspaceCatalog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or _catalog_path()).expanduser().resolve()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "workspaces": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"cannot read workspace catalog {self.path}: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("workspaces"), dict):
            raise WorkspaceError("invalid workspace catalog")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, value)

    def list(self) -> list[dict[str, Any]]:
        rows = []
        for record in self._load()["workspaces"].values():
            item = dict(record)
            item["exists"] = Path(item["path"]).is_dir()
            item["python_exists"] = Path(item["python"]).is_file()
            rows.append(item)
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return rows

    def add(
        self,
        name: str,
        path: str | Path,
        *,
        python: str | Path | None = None,
        conda_env: str | None = None,
        ssh_target: str | None = None,
    ) -> dict[str, Any]:
        normalized = name.strip()
        if not normalized or len(normalized) > 160:
            raise WorkspaceError("workspace name must contain 1-160 characters")
        workspace = Path(path).expanduser().resolve()
        if not workspace.is_dir():
            raise WorkspaceError(f"workspace directory does not exist: {workspace}")
        interpreter = Path(python or sys.executable).expanduser().resolve()
        if not interpreter.is_file():
            raise WorkspaceError(f"Python interpreter does not exist: {interpreter}")
        catalog = self._load()
        previous = catalog["workspaces"].get(normalized, {})
        now = utc_now()
        record = {
            "name": normalized,
            "path": str(workspace),
            "python": str(interpreter),
            "conda_env": conda_env,
            "ssh_target": ssh_target,
            "created_at": previous.get("created_at", now),
            "updated_at": now,
        }
        catalog["workspaces"][normalized] = record
        self._save(catalog)
        return record

    def remove(self, name: str) -> None:
        catalog = self._load()
        if name not in catalog["workspaces"]:
            raise WorkspaceError(f"unknown workspace {name!r}")
        del catalog["workspaces"][name]
        self._save(catalog)


def conda_environments() -> list[dict[str, Any]]:
    try:
        payload = _run_json(["conda", "env", "list", "--json"], timeout=20.0)
    except WorkspaceError:
        return []
    active_prefix = os.environ.get("CONDA_PREFIX")
    rows: list[dict[str, Any]] = []
    for raw in payload.get("envs", []):
        prefix = Path(str(raw)).expanduser().resolve()
        python = prefix / ("python.exe" if os.name == "nt" else "bin/python")
        rows.append(
            {
                "name": prefix.name,
                "prefix": str(prefix),
                "python": str(python),
                "python_exists": python.is_file(),
                "active": active_prefix is not None and Path(active_prefix).resolve() == prefix,
            }
        )
    return rows


def inspect_interpreter(python: str | Path) -> dict[str, Any]:
    interpreter = Path(python).expanduser().resolve()
    if not interpreter.is_file():
        raise WorkspaceError(f"Python interpreter does not exist: {interpreter}")
    script = r'''
import importlib.util, json, os, platform, sys
payload = {
    "executable": sys.executable,
    "version": platform.python_version(),
    "implementation": platform.python_implementation(),
    "platform": platform.platform(),
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "conda_prefix": os.environ.get("CONDA_PREFIX"),
    "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV"),
    "packages": {},
}
for name in ("research_assistant", "torch", "numpy", "scipy", "matplotlib", "jupyter_client"):
    payload["packages"][name] = bool(importlib.util.find_spec(name))
if payload["packages"]["torch"]:
    import torch
    payload["torch"] = {
        "version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "devices": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
    }
print(json.dumps(payload))
'''
    payload = _run_json([str(interpreter), "-c", script], timeout=60.0)
    payload["requested_executable"] = str(interpreter)
    return payload


def export_environment(
    destination: str | Path,
    *,
    python: str | Path = sys.executable,
    explicit_conda: bool = True,
) -> Path:
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    interpreter = Path(python).expanduser().resolve()
    if explicit_conda and os.environ.get("CONDA_PREFIX"):
        try:
            completed = subprocess.run(
                ["conda", "list", "--explicit"],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            target.write_text(completed.stdout, encoding="utf-8")
            return target
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    try:
        completed = subprocess.run(
            [str(interpreter), "-m", "pip", "freeze", "--all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"cannot export environment from {interpreter}: {exc}") from exc
    target.write_text(completed.stdout, encoding="utf-8")
    return target
