from __future__ import annotations

from typing import Any

from research_assistant.errors import ResearchAssistantError


def register_workspace_browser_routes(app) -> None:
    try:
        from fastapi import Query
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace

    @app.get("/api/workspace/entries")
    def workspace_entries(
        path: str = "",
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=250, ge=1, le=1000),
    ) -> dict[str, Any]:
        return workspace.directory(path, offset=offset, limit=limit)

    @app.get("/api/workspace/search")
    def workspace_search(
        query: str = Query(min_length=1),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=250, ge=1, le=1000),
    ) -> dict[str, Any]:
        return workspace.search(query, offset=offset, limit=limit)

