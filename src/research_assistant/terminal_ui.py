from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.errors import ResearchAssistantError
from research_assistant.terminal import TerminalError, TerminalSessionManager
from research_assistant.tmux_terminal import TmuxTerminalSessionManager



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


def _terminal_manager(workspace: Path):
    tmux_executable = shutil.which("tmux")
    if tmux_executable is not None:
        return TmuxTerminalSessionManager(
            workspace,
            tmux_executable=tmux_executable,
        )
    return TerminalSessionManager(workspace)


def register_terminal_routes(app) -> None:
    try:
        from fastapi import WebSocket, WebSocketDisconnect
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    # FastAPI resolves postponed endpoint annotations in the module namespace.
    globals()["WebSocket"] = WebSocket

    workspace = Path(app.state.workspace.root).resolve()
    manager = _terminal_manager(workspace)
    app.state.terminal_manager = manager
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def terminal_lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                manager.shutdown()

    app.router.lifespan_context = terminal_lifespan

    @app.get("/api/terminals")
    def terminal_list() -> dict[str, Any]:
        persistent = bool(getattr(manager, "persistent", False))
        backend = str(getattr(manager, "persistence_backend", "process"))
        return {
            "workspace": str(workspace),
            "default_shell": manager.default_shell,
            "sessions": manager.list(),
            "persistent": persistent,
            "backend": backend,
            "persistence_message": (
                "Terminal sessions survive UI and SSH reconnects through tmux."
                if persistent
                else "Install tmux on the server to preserve terminals across UI restarts."
            ),
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
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
        except (asyncio.CancelledError, WebSocketDisconnect, TerminalError, RuntimeError):
            pass
        finally:
            manager.unsubscribe(session_id, token)

