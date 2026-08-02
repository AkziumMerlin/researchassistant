from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from research_assistant.errors import ResearchAssistantError
from research_assistant.system_monitor import SystemMonitor

_INSTALLED = False


class MonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProcessSignalRequest(MonitorRequest):
    signal: Literal["INT", "TERM", "KILL", "HUP", "STOP", "CONT"]


def _register(app) -> None:
    try:
        from fastapi import Query, Request
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    monitor = SystemMonitor(app.state.workspace.root)
    app.state.system_monitor = monitor
    script_path = Path(__file__).with_name("ui") / "static" / "system-monitor-extension.js"

    @app.middleware("http")
    async def system_monitor_extension(request: Request, call_next):
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
        source = "/api/extensions/system-monitor.js"
        if source not in html:
            html = html.replace(
                "</head>",
                f'  <script type="module" src="{source}"></script>\n  </head>',
            )
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() != "content-length"
        }
        result = HTMLResponse(html, status_code=response.status_code, headers=headers)
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.get("/api/extensions/system-monitor.js")
    def system_monitor_javascript():
        if not script_path.is_file():
            raise ResearchAssistantError("the system monitor UI extension is missing")
        response = Response(
            script_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/system-monitor/snapshot")
    def system_monitor_snapshot(
        limit: int = Query(default=300, ge=1, le=2000),
        sort: Literal["cpu", "memory", "gpu", "pid", "runtime"] = Query(default="cpu"),
        scope: Literal["all", "user", "gpu", "ra"] = Query(default="all"),
        search: str | None = Query(default=None, max_length=300),
    ) -> dict[str, Any]:
        return monitor.snapshot(
            process_limit=limit,
            process_sort=sort,
            process_scope=scope,
            search=search,
        )

    @app.get("/api/system-monitor/processes/{pid}")
    def system_monitor_process(pid: int) -> dict[str, Any]:
        return monitor.process_context(pid)

    @app.post("/api/system-monitor/processes/{pid}/signal")
    def system_monitor_signal(pid: int, payload: ProcessSignalRequest) -> dict[str, Any]:
        return monitor.send_signal(pid, payload.signal)


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
