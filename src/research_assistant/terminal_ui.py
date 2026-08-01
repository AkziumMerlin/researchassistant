from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.errors import ResearchAssistantError
from research_assistant.terminal import TerminalError, TerminalSessionManager

_INSTALLED = False


class TerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TerminalCreateRequest(TerminalRequest):
    cwd: str | None = None
    shell: str | None = None
    title: str | None = None
    cols: int = Field(default=100, ge=2, le=500)
    rows: int = Field(default=30, ge=2, le=300)


class TerminalResizeRequest(TerminalRequest):
    cols: int = Field(ge=2, le=500)
    rows: int = Field(ge=2, le=300)


def _register(app) -> None:
    try:
        from fastapi import Request, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    workspace = Path(app.state.workspace.root).resolve()
    manager = TerminalSessionManager(workspace)
    app.state.terminal_manager = manager
    static_root = Path(__file__).with_name("ui") / "static"
    extension_path = static_root / "terminal-extension.js"
    runtime_path = static_root / "terminal-runtime.js"

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def terminal_lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                manager.shutdown()

    app.router.lifespan_context = terminal_lifespan

    @app.middleware("http")
    async def terminal_extension(request: Request, call_next):
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
        source = "/api/extensions/terminal.js"
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

    @app.get("/api/extensions/terminal.js")
    def terminal_javascript():
        if not extension_path.is_file():
            raise ResearchAssistantError("the terminal UI extension is missing")
        response = Response(
            extension_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/extensions/terminal-runtime.js")
    def terminal_runtime():
        if not runtime_path.is_file():
            raise ResearchAssistantError(
                "the terminal runtime is missing; rebuild the frontend assets"
            )
        response = Response(
            runtime_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/terminals")
    def terminal_list() -> dict[str, Any]:
        return {
            "workspace": str(workspace),
            "default_shell": manager.default_shell,
            "sessions": manager.list(),
        }

    @app.post("/api/terminals")
    def terminal_create(payload: TerminalCreateRequest) -> dict[str, Any]:
        return manager.create(
            cwd=payload.cwd,
            shell=payload.shell,
            title=payload.title,
            cols=payload.cols,
            rows=payload.rows,
        )

    @app.post("/api/terminals/{session_id}/resize")
    def terminal_resize(
        session_id: str,
        payload: TerminalResizeRequest,
    ) -> dict[str, Any]:
        return manager.resize(session_id, cols=payload.cols, rows=payload.rows)

    @app.delete("/api/terminals/{session_id}")
    def terminal_close(session_id: str) -> dict[str, Any]:
        return manager.remove(session_id)

    @app.websocket("/api/terminals/{session_id}/ws")
    async def terminal_websocket(websocket: WebSocket, session_id: str) -> None:
        try:
            manager.require(session_id)
        except TerminalError:
            await websocket.close(code=4404)
            return

        await websocket.accept()
        token, queue, replay, metadata = manager.subscribe(
            session_id,
            asyncio.get_running_loop(),
        )
        await websocket.send_json({"type": "ready", "session": metadata})
        if replay:
            await websocket.send_bytes(replay)

        async def send_output() -> None:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    await websocket.send_json(
                        {
                            "type": "exit",
                            "session": manager.require(session_id).metadata(),
                        }
                    )
                    return
                await websocket.send_bytes(chunk)

        async def receive_input() -> None:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                text = message.get("text")
                if text is None:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                message_type = payload.get("type")
                if message_type == "input":
                    data = payload.get("data")
                    if isinstance(data, str):
                        manager.write(session_id, data.encode("utf-8"))
                elif message_type == "resize":
                    cols = payload.get("cols")
                    rows = payload.get("rows")
                    if isinstance(cols, int) and isinstance(rows, int):
                        manager.resize(session_id, cols=cols, rows=rows)

        sender = asyncio.create_task(send_output())
        receiver = asyncio.create_task(receive_input())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TerminalError, RuntimeError):
            pass
        finally:
            manager.unsubscribe(session_id, token)


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
