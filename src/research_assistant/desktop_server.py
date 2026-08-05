from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any

from research_assistant import __version__
from research_assistant.errors import ResearchAssistantError


def _remove_legacy_frontend_routes(app) -> None:
    """Keep the desktop sidecar headless even while legacy assets remain in the package."""
    retired_paths = {"/", "/assets"}
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) not in retired_paths
    ]


def create_desktop_app(
    root: str | Path,
    *,
    plugins: list[str] | None = None,
    token: str,
    connection_mode: str = "local",
):
    """Create the authenticated loopback API used by the Theia desktop backend."""
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise ResearchAssistantError(
            "desktop API dependencies are missing; install research-assistant[desktop]"
        ) from exc

    workspace_root = Path(root).expanduser().resolve()
    os.environ["RA_PROJECT_ROOT"] = str(workspace_root)

    from research_assistant.ui.server import create_app

    app = create_app(
        workspace_root,
        plugins or [],
        ssh_mode=connection_mode == "ssh",
    )
    from research_assistant.desktop_files import register_desktop_file_routes
    from research_assistant.ui.legacy_routes import register_legacy_routes

    register_desktop_file_routes(app)
    register_legacy_routes(app)
    _remove_legacy_frontend_routes(app)
    app.title = "ResearchAssistant Desktop API"

    @app.middleware("http")
    async def desktop_session_auth(request: Request, call_next):
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {token}"):
            return JSONResponse(status_code=401, content={"detail": "invalid desktop session"})
        return await call_next(request)

    @app.get("/api/desktop/health")
    def desktop_health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "workspace": str(workspace_root),
            "frontend": "theia-electron",
            "headless": True,
            "connection_mode": connection_mode,
        }

    return app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ResearchAssistant desktop API sidecar")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plugin", action="append", default=[])
    parser.add_argument("--token", default=os.environ.get("RA_DESKTOP_TOKEN"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--connection-mode", choices=("local", "ssh"), default="local"
    )
    return parser


def run_sidecar(
    root: str | Path,
    *,
    plugins: list[str] | None = None,
    token: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    connection_mode: str = "local",
) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise ResearchAssistantError(
            "desktop API dependencies are missing; install research-assistant[desktop]"
        ) from exc

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ResearchAssistantError("desktop sidecar only binds to a loopback interface")
    if port < 0 or port > 65535:
        raise ResearchAssistantError("desktop sidecar port must be between 0 and 65535")
    workspace = Path(root).expanduser().resolve()
    session_token = token or secrets.token_urlsafe(32)
    app = create_desktop_app(
        workspace,
        plugins=plugins or [],
        token=session_token,
        connection_mode=connection_mode,
    )

    bind_host = "::1" if host == "::1" else "127.0.0.1"
    family = socket.AF_INET6 if bind_host == "::1" else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((bind_host, port))
    listener.listen(128)
    port = int(listener.getsockname()[1])

    handshake = {
        "protocol": "research-assistant/desktop-sidecar",
        "version": 1,
        "product_version": __version__,
        "host": bind_host,
        "port": port,
        "token": session_token,
        "workspace": str(workspace),
        "pid": os.getpid(),
        "connection_mode": connection_mode,
    }
    print(json.dumps(handshake, sort_keys=True), flush=True)

    config = uvicorn.Config(app, host=bind_host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run(sockets=[listener])


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        run_sidecar(
            args.root,
            plugins=args.plugin,
            token=args.token,
            host=args.host,
            port=args.port,
            connection_mode=args.connection_mode,
        )
    except ResearchAssistantError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":  # pragma: no cover
    main()
