from __future__ import annotations

from pathlib import Path
from typing import Any

from research_assistant.errors import ResearchAssistantError

_INSTALLED = False


def _register(app) -> None:
    try:
        from fastapi import Query, Request
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = app.state.workspace
    static_root = Path(__file__).with_name("ui") / "static"
    scripts = {
        "/api/extensions/explorer-plus.js": static_root / "explorer-plus.js",
        "/api/extensions/component-search.js": static_root / "component-search.js",
    }

    @app.middleware("http")
    async def workspace_browser_extensions(request: Request, call_next):
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
        additions = []
        for source in scripts:
            if source not in html:
                additions.append(f'  <script type="module" src="{source}"></script>')
        if additions:
            html = html.replace("</head>", "\n".join(additions) + "\n  </head>")
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() != "content-length"
        }
        result = HTMLResponse(html, status_code=response.status_code, headers=headers)
        result.headers["Cache-Control"] = "no-store"
        return result

    for route, path in scripts.items():

        def javascript(path: Path = path):
            if not path.is_file():
                raise ResearchAssistantError(f"the UI extension is missing: {path.name}")
            response = Response(
                path.read_text(encoding="utf-8"),
                media_type="application/javascript",
            )
            response.headers["Cache-Control"] = "no-store"
            return response

        app.add_api_route(route, javascript, methods=["GET"])

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


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from research_assistant.ui import server

    original_create_app = server.create_app

    def create_app(root, plugins=None, *, ssh_mode=None):
        app = original_create_app(root, plugins, ssh_mode=ssh_mode)
        _register(app)
        return app

    server.create_app = create_app
    _INSTALLED = True
