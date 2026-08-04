from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.errors import ResearchAssistantError
from research_assistant.notebooks import NotebookError, NotebookKernelManager, NotebookStore



class NotebookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotebookCreateRequest(NotebookRequest):
    path: str = Field(min_length=1)
    kernel_name: str = Field(default="python3", min_length=1)


class NotebookWriteRequest(NotebookRequest):
    notebook: dict[str, Any]
    revision: str | None = None


class KernelStartRequest(NotebookRequest):
    notebook_path: str = Field(min_length=1)
    kernel_name: str | None = None
    reuse: bool = True


class KernelExecuteRequest(NotebookRequest):
    cell_id: str = Field(min_length=1)
    code: str
    store_history: bool = True


def register_notebook_routes(app) -> None:
    try:
        from fastapi import Query, WebSocket, WebSocketDisconnect
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    globals()["WebSocket"] = WebSocket
    workspace = app.state.workspace
    store = NotebookStore(workspace)
    manager = NotebookKernelManager(workspace)
    app.state.notebook_store = store
    app.state.notebook_kernels = manager
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def notebook_lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                manager.detach()

    app.router.lifespan_context = notebook_lifespan

    @app.get("/api/notebooks/file")
    def notebook_read(path: str = Query(min_length=1)) -> dict[str, Any]:
        return store.read(path)

    @app.post("/api/notebooks/file", status_code=201)
    def notebook_create(payload: NotebookCreateRequest) -> dict[str, Any]:
        destination = workspace.resolve(payload.path)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise NotebookError(
                f"cannot create notebook directory {destination.parent}: {exc}"
            ) from exc
        return store.create(payload.path, kernel_name=payload.kernel_name)

    @app.put("/api/notebooks/file")
    def notebook_write(
        payload: NotebookWriteRequest,
        path: str = Query(min_length=1),
    ) -> dict[str, Any]:
        return store.write(
            path,
            payload.notebook,
            expected_revision=payload.revision,
        )

    @app.get("/api/notebooks/kernels")
    def kernel_list() -> dict[str, Any]:
        return {
            "available": manager.available_kernels(),
            "sessions": manager.list(),
        }

    @app.post("/api/notebooks/kernels", status_code=201)
    def kernel_start(payload: KernelStartRequest) -> dict[str, Any]:
        return manager.start(
            payload.notebook_path,
            kernel_name=payload.kernel_name,
            reuse=payload.reuse,
        )

    @app.post("/api/notebooks/kernels/{kernel_id}/execute")
    def kernel_execute(
        kernel_id: str,
        payload: KernelExecuteRequest,
    ) -> dict[str, Any]:
        return manager.execute(
            kernel_id,
            cell_id=payload.cell_id,
            code=payload.code,
            store_history=payload.store_history,
        )

    @app.post("/api/notebooks/kernels/{kernel_id}/interrupt")
    def kernel_interrupt(kernel_id: str) -> dict[str, Any]:
        return manager.interrupt(kernel_id)

    @app.post("/api/notebooks/kernels/{kernel_id}/restart")
    def kernel_restart(kernel_id: str) -> dict[str, Any]:
        return manager.restart(kernel_id)

    @app.delete("/api/notebooks/kernels/{kernel_id}")
    def kernel_shutdown(kernel_id: str) -> dict[str, Any]:
        return manager.shutdown(kernel_id)

    @app.get("/api/notebooks/kernels/{kernel_id}/log")
    def kernel_log(kernel_id: str, limit: int = Query(default=200_000, ge=1, le=2_000_000)):
        session = manager.require(kernel_id)
        try:
            data = session.log_path.read_bytes()
        except OSError as exc:
            raise NotebookError(f"cannot read kernel log: {exc}") from exc
        return Response(data[-limit:], media_type="text/plain; charset=utf-8")

    @app.websocket("/api/notebooks/kernels/{kernel_id}/ws")
    async def kernel_websocket(websocket: WebSocket, kernel_id: str) -> None:
        try:
            session = manager.require(kernel_id)
        except NotebookError:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        token, target, replay = manager.subscribe(
            kernel_id,
            asyncio.get_running_loop(),
        )
        await websocket.send_json({"type": "ready", "kernel": session.metadata()})
        for event in replay[-500:]:
            await websocket.send_json(event)

        async def send_events() -> None:
            while True:
                event = await target.get()
                if event is None:
                    return
                await websocket.send_json(event)

        async def receive_commands() -> None:
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
                if message_type == "execute":
                    cell_id = payload.get("cell_id")
                    code = payload.get("code")
                    if isinstance(cell_id, str) and isinstance(code, str):
                        manager.execute(
                            kernel_id,
                            cell_id=cell_id,
                            code=code,
                            store_history=bool(payload.get("store_history", True)),
                        )
                elif message_type == "interrupt":
                    manager.interrupt(kernel_id)
                elif message_type == "ping":
                    await websocket.send_json({"type": "pong"})

        sender = asyncio.create_task(send_events())
        receiver = asyncio.create_task(receive_commands())
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
        except (asyncio.CancelledError, WebSocketDisconnect, NotebookError, RuntimeError):
            pass
        finally:
            manager.unsubscribe(kernel_id, token)

