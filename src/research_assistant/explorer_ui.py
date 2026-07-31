from __future__ import annotations

import re
from pathlib import Path

from research_assistant.errors import ResearchAssistantError

_INSTALLED = False
_MAIN_BUNDLE_PATTERN = re.compile(r"/assets/index-[^/?]+\.js$")
_ELEMENT_PAIR_PATTERN = re.compile(
    r"(?P<workspace_quote>[\"'])workspace-name(?P=workspace_quote)\s*,\s*"
    r"(?P<file_quote>[\"'])file-count(?P=file_quote)"
)
_MAIN_SCRIPT_PATTERN = re.compile(
    r'(?P<prefix>src="/assets/index-[^"?]+\.js)(?:\?[^\"]*)?(?P<suffix>\")'
)
_CACHE_BUSTER = "explorer=4"


def _patch_main_bundle(source: str) -> tuple[str, bool]:
    def replacement(match: re.Match[str]) -> str:
        workspace_quote = match.group("workspace_quote")
        file_quote = match.group("file_quote")
        return (
            f"{workspace_quote}workspace-name{workspace_quote},"
            f"{workspace_quote}connection-status{workspace_quote},"
            f"{file_quote}file-count{file_quote}"
        )

    patched, count = _ELEMENT_PAIR_PATTERN.subn(replacement, source, count=1)
    return patched, count == 1


def _cache_bust_main_script(html: str) -> str:
    return _MAIN_SCRIPT_PATTERN.sub(
        rf"\g<prefix>?{_CACHE_BUSTER}\g<suffix>",
        html,
        count=1,
    )


def _register(app, server_module) -> None:
    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    static_root = Path(server_module.__file__).with_name("static")
    index_path = static_root / "index.html"
    script_path = static_root / "assets" / "explorer-bootstrap.js"
    compatibility_script = '<script src="/api/extensions/explorer-bootstrap.js"></script>'
    extension_scripts = (
        '<script type="module" src="/api/extensions/jobs.js"></script>\n'
        '<script type="module" src="/api/extensions/pipeline.js"></script>\n'
        '<script type="module" src="/api/extensions/research.js"></script>'
    )

    @app.middleware("http")
    async def explorer_assets(request: Request, call_next):
        if request.method == "GET" and _MAIN_BUNDLE_PATTERN.fullmatch(request.url.path):
            asset_path = static_root / request.url.path.removeprefix("/")
            if asset_path.is_file():
                source = asset_path.read_text(encoding="utf-8")
                patched, applied = _patch_main_bundle(source)
                response = Response(patched, media_type="application/javascript")
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-ResearchAssistant-Explorer-Patch"] = (
                    "applied" if applied else "not-needed"
                )
                return response

        if request.method != "GET" or request.url.path != "/":
            return await call_next(request)

        html = index_path.read_text(encoding="utf-8")
        html = _cache_bust_main_script(html)
        if compatibility_script not in html:
            marker = '<script type="module"'
            html = html.replace(marker, f"{compatibility_script}\n    {marker}", 1)
        if "/api/extensions/research.js" not in html:
            html = html.replace("</head>", f"  {extension_scripts}\n  </head>")

        response = HTMLResponse(html)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; img-src 'self' data: blob:; connect-src 'self'; "
            "font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/extensions/explorer-bootstrap.js")
    def explorer_bootstrap_javascript():
        response = Response(
            script_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
        response.headers["Cache-Control"] = "no-store"
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
