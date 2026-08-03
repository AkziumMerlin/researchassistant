from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError
from research_assistant.run_workspace import RunWorkspace
from research_assistant.scientific_artifacts import ScientificArtifactCatalog
from research_assistant.ui.workspace import Workspace


class NotebookContextError(ResearchAssistantError):
    pass


class NotebookContextStore:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Workspace(workspace)
        self.root = self.workspace.root / ".ra" / "notebook-contexts"
        self.root.mkdir(parents=True, exist_ok=True)

    def _context_path(self, context_id: str) -> Path:
        if not context_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in context_id):
            raise NotebookContextError("invalid notebook context identifier")
        path = (self.root / f"{context_id}.json").resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise NotebookContextError("notebook context escapes state root")
        return path

    def create(
        self,
        *,
        run_ids: list[str] | None = None,
        artifact_ids: list[str] | None = None,
        artifact_root: str = "runs",
        label: str | None = None,
        notebook_path: str | None = None,
        kernel_name: str = "python3",
    ) -> dict[str, Any]:
        selected_runs = list(dict.fromkeys(run_ids or []))
        selected_artifacts = list(dict.fromkeys(artifact_ids or []))
        if not selected_runs and not selected_artifacts:
            raise NotebookContextError("select at least one run or scientific artifact")

        run_workspace = RunWorkspace(self.workspace.root, artifact_root)
        runs = run_workspace.require_runs(selected_runs) if selected_runs else []
        catalog = ScientificArtifactCatalog(self.workspace.root)
        artifacts = [catalog.require(artifact_id) for artifact_id in selected_artifacts]
        payload_seed = {
            "run_ids": selected_runs,
            "artifact_ids": selected_artifacts,
            "artifact_root": artifact_root,
        }
        context_id = hashlib.sha256(
            json.dumps(payload_seed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        relative_context_path = self._context_path(context_id).relative_to(self.workspace.root).as_posix()
        payload = {
            "schema_version": 1,
            "context_id": context_id,
            "label": label or f"analysis-{context_id[:8]}",
            "created_at": utc_now(),
            "workspace": str(self.workspace.root),
            "artifact_root": artifact_root,
            "run_ids": selected_runs,
            "artifact_ids": selected_artifacts,
            "runs": runs,
            "artifacts": artifacts,
            "context_path": relative_context_path,
            "notebook_path": notebook_path,
        }
        atomic_write_json(self._context_path(context_id), payload)

        if notebook_path is not None:
            self._create_notebook(
                notebook_path,
                context_path=relative_context_path,
                kernel_name=kernel_name,
            )
        return payload

    def _create_notebook(
        self,
        notebook_path: str,
        *,
        context_path: str,
        kernel_name: str,
    ) -> None:
        destination = self.workspace.resolve(notebook_path)
        if not notebook_path.lower().endswith(".ipynb"):
            raise NotebookContextError("context notebook path must end with .ipynb")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise NotebookContextError(f"notebook already exists: {notebook_path}")
        try:
            import nbformat
        except ImportError as exc:
            raise NotebookContextError(
                "creating a context notebook requires the UI notebook dependencies"
            ) from exc

        source = (
            "from pathlib import Path\n"
            "import json\n\n"
            f"RA_CONTEXT_PATH = Path({context_path!r})\n"
            "RA_CONTEXT = json.loads(RA_CONTEXT_PATH.read_text(encoding='utf-8'))\n"
            "RUNS = RA_CONTEXT['runs']\n"
            "ARTIFACTS = RA_CONTEXT['artifacts']\n"
            "RA_CONTEXT\n"
        )
        notebook = nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_markdown_cell(
                    "# ResearchAssistant analysis context\n\n"
                    "This notebook is bound to an immutable selection of runs and artifacts."
                ),
                nbformat.v4.new_code_cell(source),
            ],
            metadata={
                "kernelspec": {
                    "name": kernel_name,
                    "display_name": kernel_name,
                    "language": "python",
                },
                "research_assistant": {
                    "context_path": context_path,
                    "schema_version": 1,
                },
            },
        )
        destination.write_text(nbformat.writes(notebook, version=4) + "\n", encoding="utf-8")

    def require(self, context_id: str) -> dict[str, Any]:
        path = self._context_path(context_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NotebookContextError(f"unknown notebook context {context_id!r}") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise NotebookContextError(f"cannot read notebook context {context_id!r}: {exc}") from exc
        if not isinstance(value, dict):
            raise NotebookContextError(f"invalid notebook context {context_id!r}")
        return value

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(value, dict):
                rows.append(value)
            if len(rows) >= limit:
                break
        return rows
