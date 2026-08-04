from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from research_assistant.errors import ResearchAssistantError
from research_assistant.system_monitor import SystemMonitor


class MonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProcessSignalRequest(MonitorRequest):
    signal: Literal["INT", "TERM", "KILL", "HUP", "STOP", "CONT"]


def register_system_monitor_routes(app) -> None:
    try:
        from fastapi import Query
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    monitor = SystemMonitor(app.state.workspace.root)
    app.state.system_monitor = monitor
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

