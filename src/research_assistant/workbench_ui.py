from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.analysis_sessions import AnalysisSessionManager, TaskCatalog
from research_assistant.developer_tools import DeveloperTools
from research_assistant.errors import ResearchAssistantError
from research_assistant.lifecycle import LifecycleManager
from research_assistant.scientific_artifacts import ScientificArtifactCatalog
from research_assistant.workspaces import WorkspaceCatalog, conda_environments, inspect_interpreter


_INSTALLED = False


class WorkbenchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceAddRequest(WorkbenchModel):
    name: str
    path: str
    python: str | None = None
    conda_env: str | None = None
    ssh_target: str | None = None


class WorkspaceNameRequest(WorkbenchModel):
    name: str


class InterpreterRequest(WorkbenchModel):
    python: str = sys.executable


class ArtifactRegisterRequest(WorkbenchModel):
    path: str
    kind: str | None = None
    name: str | None = None
    run_id: str | None = None
    stage: str | None = None
    sample_id: str | None = None
    role: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ArtifactDiscoverRequest(WorkbenchModel):
    roots: list[str] = Field(default_factory=lambda: ["runs", "reports"])
    limit: int = Field(default=10000, ge=1, le=100000)


class ArtifactSliceRequest(WorkbenchModel):
    artifact_id: str
    selection: list[str | int] = Field(default_factory=list)
    key: str | None = None
    max_elements: int = Field(default=100000, ge=1, le=1000000)


class ArtifactCompareRequest(WorkbenchModel):
    left_id: str
    right_id: str
    key: str | None = None


class PathRequest(WorkbenchModel):
    path: str
    reason: str | None = None
    force: bool = False


class RestoreRequest(WorkbenchModel):
    trash_id: str
    overwrite: bool = False


class GcRequest(WorkbenchModel):
    older_than_days: int = Field(default=30, ge=0, le=36500)
    dry_run: bool = True


class ScriptRequest(WorkbenchModel):
    script: str
    args: list[str] = Field(default_factory=list)
    cwd: str = "."
    python: str = sys.executable
    profile: bool = False
    label: str | None = None


class ScratchpadRequest(WorkbenchModel):
    code: str
    cwd: str = "."
    python: str = sys.executable
    label: str | None = None


class SessionRequest(WorkbenchModel):
    session_id: str


class TaskRequest(WorkbenchModel):
    name: str


class GitDiffRequest(WorkbenchModel):
    staged: bool = False
    path: str | None = None


class GitBranchRequest(WorkbenchModel):
    name: str
    start_point: str | None = None


class GitCommitRequest(WorkbenchModel):
    message: str
    paths: list[str]
    push: bool = False


class SearchRequest(WorkbenchModel):
    query: str
    root: str = "."
    pattern: str = "*"
    case_sensitive: bool = False
    max_results: int = Field(default=1000, ge=1, le=10000)


class MoveRequest(WorkbenchModel):
    source: str
    destination: str
    overwrite: bool = False


class MkdirRequest(WorkbenchModel):
    path: str


def _register(app, server_module) -> None:
    try:
        from fastapi import Query, Request
        from fastapi.responses import FileResponse, HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace.root
    trusted = os.environ.get("RA_TRUSTED_DEV", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    app.state.trusted_dev = trusted
    script_path = Path(__file__).with_name("ui") / "static" / "workbench-extension.js"

    @app.middleware("http")
    async def workbench_extension(request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET" or request.url.path != "/":
            return response
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        html = body.decode("utf-8")
        source = "/api/extensions/workbench.js"
        if source not in html:
            html = html.replace(
                "</head>",
                f'  <script type="module" src="{source}"></script>\n  </head>',
            )
        headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
        result = HTMLResponse(html, status_code=response.status_code, headers=headers)
        result.headers["Cache-Control"] = "no-store"
        return result

    def artifact_catalog() -> ScientificArtifactCatalog:
        return ScientificArtifactCatalog(workspace)

    def lifecycle() -> LifecycleManager:
        return LifecycleManager(workspace)

    def sessions() -> AnalysisSessionManager:
        return AnalysisSessionManager(workspace)

    def developer() -> DeveloperTools:
        return DeveloperTools(workspace, trusted=trusted)

    @app.get("/api/extensions/workbench.js")
    def workbench_javascript():
        if not script_path.is_file():
            raise ResearchAssistantError("the workbench UI extension is missing")
        response = Response(script_path.read_text(encoding="utf-8"), media_type="application/javascript")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/workbench/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "trusted_dev": trusted,
            "workspace": str(workspace),
            "python": sys.executable,
            "conda_prefix": os.environ.get("CONDA_PREFIX"),
            "features": {
                "visual_protocols": True,
                "scientific_artifacts": True,
                "lifecycle": True,
                "analysis_sessions": True,
                "workspaces": True,
                "developer_tools": trusted,
            },
        }

    @app.get("/api/workbench/workspaces")
    def workspace_list() -> dict[str, Any]:
        return {"workspaces": WorkspaceCatalog().list()}

    @app.post("/api/workbench/workspaces")
    def workspace_add(payload: WorkspaceAddRequest) -> dict[str, Any]:
        return WorkspaceCatalog().add(
            payload.name,
            payload.path,
            python=payload.python,
            conda_env=payload.conda_env,
            ssh_target=payload.ssh_target,
        )

    @app.post("/api/workbench/workspaces/remove")
    def workspace_remove(payload: WorkspaceNameRequest) -> dict[str, Any]:
        WorkspaceCatalog().remove(payload.name)
        return {"removed": payload.name}

    @app.get("/api/workbench/environments")
    def environments() -> dict[str, Any]:
        return {"current": inspect_interpreter(sys.executable), "conda": conda_environments()}

    @app.post("/api/workbench/environments/inspect")
    def environment_inspect(payload: InterpreterRequest) -> dict[str, Any]:
        return inspect_interpreter(payload.python)

    @app.get("/api/workbench/artifacts")
    def artifact_list(
        kind: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        sample_id: str | None = Query(default=None),
        search: str | None = Query(default=None),
        limit: int = Query(default=2000, ge=1, le=10000),
    ) -> dict[str, Any]:
        return {
            "artifacts": artifact_catalog().list(
                kind=kind,
                run_id=run_id,
                sample_id=sample_id,
                search=search,
                limit=limit,
            )
        }

    @app.post("/api/workbench/artifacts/register")
    def artifact_register(payload: ArtifactRegisterRequest) -> dict[str, Any]:
        return artifact_catalog().register(
            payload.path,
            kind=payload.kind,  # type: ignore[arg-type]
            name=payload.name,
            run_id=payload.run_id,
            stage=payload.stage,
            sample_id=payload.sample_id,
            role=payload.role,
            dimensions=payload.dimensions,
            metadata=payload.metadata,
            tags=payload.tags,
        )

    @app.post("/api/workbench/artifacts/discover")
    def artifact_discover(payload: ArtifactDiscoverRequest) -> dict[str, Any]:
        return artifact_catalog().discover(payload.roots, limit=payload.limit)

    @app.get("/api/workbench/artifacts/{artifact_id}")
    def artifact_show(artifact_id: str, refresh: bool = Query(default=False)) -> dict[str, Any]:
        return artifact_catalog().require(artifact_id, refresh=refresh)

    @app.get("/api/workbench/artifacts/{artifact_id}/content")
    def artifact_content(artifact_id: str):
        item = artifact_catalog().require(artifact_id)
        path = (workspace / item["path"]).resolve()
        if not path.is_relative_to(workspace) or not path.is_file():
            raise ResearchAssistantError("artifact content is unavailable")
        return FileResponse(path)

    @app.post("/api/workbench/artifacts/slice")
    def artifact_slice(payload: ArtifactSliceRequest) -> dict[str, Any]:
        return artifact_catalog().slice(
            payload.artifact_id,
            selection=payload.selection,
            key=payload.key,
            max_elements=payload.max_elements,
        )

    @app.post("/api/workbench/artifacts/compare")
    def artifact_compare(payload: ArtifactCompareRequest) -> dict[str, Any]:
        return artifact_catalog().compare(payload.left_id, payload.right_id, key=payload.key)

    @app.get("/api/workbench/lifecycle")
    def lifecycle_state() -> dict[str, Any]:
        return lifecycle().state()

    @app.get("/api/workbench/lifecycle/protection")
    def lifecycle_protection(path: str = Query(...)) -> dict[str, Any]:
        return lifecycle().protection(path)

    @app.post("/api/workbench/lifecycle/pin")
    def lifecycle_pin(payload: PathRequest) -> dict[str, Any]:
        return lifecycle().pin(payload.path, reason=payload.reason)

    @app.post("/api/workbench/lifecycle/unpin")
    def lifecycle_unpin(payload: PathRequest) -> dict[str, Any]:
        lifecycle().unpin(payload.path)
        return {"unpinned": payload.path}

    @app.post("/api/workbench/lifecycle/archive")
    def lifecycle_archive(payload: PathRequest) -> dict[str, Any]:
        return lifecycle().archive(payload.path, reason=payload.reason)

    @app.post("/api/workbench/lifecycle/unarchive")
    def lifecycle_unarchive(payload: PathRequest) -> dict[str, Any]:
        lifecycle().unarchive(payload.path)
        return {"unarchived": payload.path}

    @app.post("/api/workbench/lifecycle/trash")
    def lifecycle_trash(payload: PathRequest) -> dict[str, Any]:
        return lifecycle().trash(payload.path, reason=payload.reason, force=payload.force)

    @app.post("/api/workbench/lifecycle/restore")
    def lifecycle_restore(payload: RestoreRequest) -> dict[str, Any]:
        return lifecycle().restore(payload.trash_id, overwrite=payload.overwrite)

    @app.post("/api/workbench/lifecycle/gc")
    def lifecycle_gc(payload: GcRequest) -> dict[str, Any]:
        return lifecycle().gc(older_than_days=payload.older_than_days, dry_run=payload.dry_run)

    @app.get("/api/workbench/analysis/sessions")
    def analysis_list(limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
        return {"sessions": sessions().list(limit=limit)}

    @app.post("/api/workbench/analysis/script")
    def analysis_script(payload: ScriptRequest) -> dict[str, Any]:
        developer().require_trusted()
        return sessions().start_script(
            payload.script,
            args=payload.args,
            cwd=payload.cwd,
            python=payload.python,
            profile=payload.profile,
            label=payload.label,
        )

    @app.post("/api/workbench/analysis/scratchpad")
    def analysis_scratchpad(payload: ScratchpadRequest) -> dict[str, Any]:
        if not trusted:
            raise ResearchAssistantError("inline scratchpads require trusted developer mode")
        return sessions().start_scratchpad(
            payload.code,
            cwd=payload.cwd,
            python=payload.python,
            label=payload.label,
        )

    @app.get("/api/workbench/analysis/sessions/{session_id}")
    def analysis_status(session_id: str) -> dict[str, Any]:
        return sessions().status(session_id)

    @app.get("/api/workbench/analysis/sessions/{session_id}/logs")
    def analysis_logs(
        session_id: str,
        stream: Literal["stdout", "stderr"] = Query(default="stdout"),
        tail_bytes: int = Query(default=200000, ge=1, le=2000000),
    ) -> dict[str, Any]:
        return {"stream": stream, "content": sessions().logs(session_id, stream=stream, tail_bytes=tail_bytes)}

    @app.post("/api/workbench/analysis/stop")
    def analysis_stop(payload: SessionRequest) -> dict[str, Any]:
        return sessions().stop(payload.session_id)

    @app.get("/api/workbench/dev/tasks")
    def dev_tasks() -> dict[str, Any]:
        return {"tasks": TaskCatalog(workspace).list(), "trusted": trusted}

    @app.post("/api/workbench/dev/tasks/run")
    def dev_task_run(payload: TaskRequest) -> dict[str, Any]:
        developer().require_trusted()
        return TaskCatalog(workspace).run(payload.name, sessions())

    @app.get("/api/workbench/dev/diagnostics")
    def dev_diagnostics() -> dict[str, Any]:
        return developer().diagnostics()

    @app.get("/api/workbench/dev/git/status")
    def dev_git_status() -> dict[str, Any]:
        return developer().git_status()

    @app.post("/api/workbench/dev/git/diff")
    def dev_git_diff(payload: GitDiffRequest) -> dict[str, Any]:
        return developer().git_diff(staged=payload.staged, path=payload.path)

    @app.get("/api/workbench/dev/git/log")
    def dev_git_log(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        return developer().git_log(limit=limit)

    @app.get("/api/workbench/dev/git/branches")
    def dev_git_branches() -> dict[str, Any]:
        return developer().git_branches()

    @app.post("/api/workbench/dev/git/branch")
    def dev_git_branch(payload: GitBranchRequest) -> dict[str, Any]:
        return developer().git_create_branch(payload.name, start_point=payload.start_point)

    @app.post("/api/workbench/dev/git/switch")
    def dev_git_switch(payload: GitBranchRequest) -> dict[str, Any]:
        return developer().git_switch(payload.name)

    @app.post("/api/workbench/dev/git/commit")
    def dev_git_commit(payload: GitCommitRequest) -> dict[str, Any]:
        return developer().git_commit(payload.message, paths=payload.paths, push=payload.push)

    @app.post("/api/workbench/dev/git/push")
    def dev_git_push() -> dict[str, Any]:
        return developer().git_push()

    @app.post("/api/workbench/dev/search")
    def dev_search(payload: SearchRequest) -> dict[str, Any]:
        return developer().search(
            payload.query,
            root=payload.root,
            pattern=payload.pattern,
            case_sensitive=payload.case_sensitive,
            max_results=payload.max_results,
        )

    @app.post("/api/workbench/dev/move")
    def dev_move(payload: MoveRequest) -> dict[str, Any]:
        return developer().move(payload.source, payload.destination, overwrite=payload.overwrite)

    @app.post("/api/workbench/dev/mkdir")
    def dev_mkdir(payload: MkdirRequest) -> dict[str, Any]:
        return developer().mkdir(payload.path)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from research_assistant.ui import server

    original_create_app = server.create_app

    def create_app(root, plugins=None, *, ssh_mode=None):
        app = original_create_app(root, plugins, ssh_mode=ssh_mode)
        _register(app, server)
        return app

    server.create_app = create_app
    _INSTALLED = True
