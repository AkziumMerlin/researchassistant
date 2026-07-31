from __future__ import annotations

import re
from pathlib import Path

from research_assistant.errors import ResearchAssistantError

_INSTALLED = False
_PATCH_SUFFIX = "-explorer4"
_ORIGINAL_MAIN_SCRIPT_PATTERN = re.compile(
    r'(?P<prefix>src="/assets/(?P<name>index-[^"/?]+)\.js)(?P<suffix>\")'
)
_PATCHED_MAIN_BUNDLE_PATTERN = re.compile(
    rf"/assets/(?P<name>index-[^/?]+){_PATCH_SUFFIX}\.js$"
)
_BUNDLE_PRELUDE = r'''
const __raOriginalFromEntries = Object.fromEntries;
Object.fromEntries = function researchAssistantFromEntries(iterable) {
  const entries = Array.from(iterable);
  const workspaceRegistry = entries.some(
    (entry) => Array.isArray(entry) && entry[0] === "workspace-name",
  );
  if (
    workspaceRegistry &&
    !entries.some((entry) => Array.isArray(entry) && entry[0] === "connection-status")
  ) {
    entries.push(["connection-status", document.getElementById("connection-status")]);
  }
  const result = __raOriginalFromEntries(entries);
  if (workspaceRegistry) Object.fromEntries = __raOriginalFromEntries;
  return result;
};
'''.strip()


def _virtualize_main_script(html: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        return (
            f'{match.group("prefix")[:-3]}{_PATCH_SUFFIX}.js'
            f'{match.group("suffix")}'
        )

    return _ORIGINAL_MAIN_SCRIPT_PATTERN.sub(replacement, html, count=1)


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
        if request.method == "GET":
            match = _PATCHED_MAIN_BUNDLE_PATTERN.fullmatch(request.url.path)
            if match is not None:
                asset_path = static_root / "assets" / f'{match.group("name")}.js'
                if asset_path.is_file():
                    source = asset_path.read_text(encoding="utf-8")
                    response = Response(
                        f"{_BUNDLE_PRELUDE}\n{source}",
                        media_type="application/javascript",
                    )
                    response.headers["Cache-Control"] = "no-store"
                    response.headers["X-ResearchAssistant-Explorer-Patch"] = "applied"
                    return response

        if request.method != "GET" or request.url.path != "/":
            return await call_next(request)

        html = _virtualize_main_script(index_path.read_text(encoding="utf-8"))
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
