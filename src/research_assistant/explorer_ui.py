from __future__ import annotations

from pathlib import Path

from research_assistant.errors import ResearchAssistantError

_INSTALLED = False


def _register(app, server_module) -> None:
    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    index_path = Path(server_module.__file__).with_name("static") / "index.html"
    compatibility_script = '<script src="/assets/explorer-bootstrap.js"></script>'
    extension_scripts = (
        '<script type="module" src="/api/extensions/jobs.js"></script>\n'
        '<script type="module" src="/api/extensions/pipeline.js"></script>\n'
        '<script type="module" src="/api/extensions/research.js"></script>'
    )

    @app.middleware("http")
    async def explorer_root(request: Request, call_next):
        if request.method != "GET" or request.url.path != "/":
            return await call_next(request)

        html = index_path.read_text(encoding="utf-8")
        if compatibility_script not in html:
            marker = '<script type="module"'
            html = html.replace(marker, f"{compatibility_script}\n    {marker}", 1)
        if "/api/extensions/research.js" not in html:
            html = html.replace("</head>", f"  {extension_scripts}\n  </head>")

        response = HTMLResponse(html)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; img-src 'self' data: blob:; connect-src 'self'; "
            "font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


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
