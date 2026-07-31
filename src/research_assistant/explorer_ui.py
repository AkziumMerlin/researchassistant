from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from research_assistant.errors import ResearchAssistantError
from research_assistant.integrations.parameterized_torch_graph import (
    ParameterizedTorchGraphParams,
    validate_parameterized_graph,
)

_INSTALLED = False
_PATCH_VERSION = 9
_PATCH_SUFFIX = f"-explorer{_PATCH_VERSION}"
_ORIGINAL_MAIN_SCRIPT_PATTERN = re.compile(
    r'(?P<prefix>src="/assets/(?P<name>index-[^"/?]+)\.js)(?P<suffix>\")'
)
_PATCHED_MAIN_BUNDLE_PATTERN = re.compile(
    rf"/assets/(?P<name>index-[^/?]+){_PATCH_SUFFIX}\.js$"
)
_EXPLORER_REGISTRY_PATCH_MARKER = "researchAssistantExplorerRegistryProxy"
_EXPLORER_REGISTRY_PRELUDE = f"""const {_EXPLORER_REGISTRY_PATCH_MARKER}=(()=>{{
const originalFromEntries=Object.fromEntries;
Object.fromEntries=function researchAssistantFromEntries(iterable){{
const result=originalFromEntries.call(Object,iterable);
if(Object.prototype.hasOwnProperty.call(result,"workspace-name")){{
Object.fromEntries=originalFromEntries;
return new Proxy(result,{{
get(target,property,receiver){{
if(typeof property==="string"&&!Reflect.has(target,property)){{
const element=document.getElementById(property);
if(element!==null){{
target[property]=element;
return element;
}}
throw new Error(`UI element #${{property}} is not registered and does not exist in DOM`);
}}
return Reflect.get(target,property,receiver);
}}
}});
}}
return result;
}};
return true;
}})();
"""


class ParameterizedGraphValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: ParameterizedTorchGraphParams


def _virtualize_main_script(html: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        return f'{match.group("prefix")[:-3]}{_PATCH_SUFFIX}.js{match.group("suffix")}'

    patched, replacements = _ORIGINAL_MAIN_SCRIPT_PATTERN.subn(replacement, html, count=1)
    if replacements != 1:
        raise ResearchAssistantError("could not locate the packaged UI entry bundle")
    return patched


def _main_asset_names(html: str) -> tuple[str, str]:
    match = _ORIGINAL_MAIN_SCRIPT_PATTERN.search(html)
    if match is None:
        raise ResearchAssistantError("could not locate the packaged UI entry bundle")
    source = f'/assets/{match.group("name")}.js'
    served = f'/assets/{match.group("name")}{_PATCH_SUFFIX}.js'
    return source, served


def _patch_explorer_bundle(source: str) -> tuple[str, bool]:
    if _EXPLORER_REGISTRY_PATCH_MARKER in source:
        return source, False
    return f"{_EXPLORER_REGISTRY_PRELUDE}{source}", True


def _inject_extension_scripts(html: str) -> str:
    scripts = (
        "/api/extensions/jobs.js",
        "/api/extensions/pipeline.js",
        "/api/extensions/research.js",
        "/api/extensions/architectures.js",
    )
    for source in scripts:
        if source not in html:
            html = html.replace(
                "</head>",
                f'  <script type="module" src="{source}"></script>\n  </head>',
            )
    return html


def _register(app, server_module) -> None:
    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse, JSONResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

    static_root = Path(server_module.__file__).with_name("static")
    index_path = static_root / "index.html"
    architecture_script_path = static_root / "architecture-extension.js"

    @app.middleware("http")
    async def explorer_assets(request: Request, call_next):
        if request.method == "GET":
            match = _PATCHED_MAIN_BUNDLE_PATTERN.fullmatch(request.url.path)
            if match is not None:
                asset_path = static_root / "assets" / f'{match.group("name")}.js'
                if asset_path.is_file():
                    source = asset_path.read_text(encoding="utf-8")
                    patched_source, applied = _patch_explorer_bundle(source)
                    response = Response(patched_source, media_type="application/javascript")
                    response.headers["Cache-Control"] = "no-store"
                    response.headers["X-ResearchAssistant-Explorer-Patch"] = (
                        "applied" if applied else "not-needed"
                    )
                    response.headers["X-ResearchAssistant-UI-Build"] = str(_PATCH_VERSION)
                    return response

        if request.method != "GET" or request.url.path != "/":
            return await call_next(request)

        html = _virtualize_main_script(index_path.read_text(encoding="utf-8"))
        html = _inject_extension_scripts(html)
        response = HTMLResponse(html)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-ResearchAssistant-UI-Build"] = str(_PATCH_VERSION)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; img-src 'self' data: blob:; connect-src 'self'; "
            "font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/architectures")
    def list_architectures():
        architecture_root = (app.state.workspace.root / "architectures").resolve()
        rows: list[dict[str, object]] = []
        if (
            architecture_root.is_dir()
            and architecture_root.is_relative_to(app.state.workspace.root)
        ):
            for path in sorted(architecture_root.rglob("*.json")):
                resolved = path.resolve()
                if not resolved.is_file() or not resolved.is_relative_to(architecture_root):
                    continue
                rows.append(
                    {
                        "path": resolved.relative_to(app.state.workspace.root).as_posix(),
                        "name": resolved.name,
                        "kind": "file",
                        "size": resolved.stat().st_size,
                        "editable": True,
                    }
                )
                if len(rows) >= 2000:
                    break
        response = JSONResponse({"architectures": rows, "truncated": len(rows) >= 2000})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/extensions/architectures.js")
    def architectures_extension():
        if not architecture_script_path.is_file():
            raise ResearchAssistantError("the architecture UI extension is missing")
        response = Response(
            architecture_script_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-ResearchAssistant-UI-Build"] = str(_PATCH_VERSION)
        return response

    @app.post("/api/torch/parameterized-graph/validate")
    def validate_parameterized_torch_graph(payload: ParameterizedGraphValidateRequest):
        validate_parameterized_graph(payload.params, app.state.registry)
        subgraph_nodes = sum(
            len(template.nodes) for template in payload.params.subgraphs.values()
        )
        return {
            "valid": True,
            "nodes": len(payload.params.nodes) + subgraph_nodes,
            "root_nodes": len(payload.params.nodes),
            "subgraph_nodes": subgraph_nodes,
            "subgraphs": len(payload.params.subgraphs),
            "inputs": payload.params.input_names,
            "outputs": payload.params.outputs,
            "variables": len(payload.params.variables),
            "typed_variables": len(payload.params.variable_specs),
            "language_version": 2,
        }

    @app.get("/api/ui-build")
    def ui_build():
        index_html = index_path.read_text(encoding="utf-8")
        source_asset, served_asset = _main_asset_names(index_html)
        response = JSONResponse(
            {
                "patch_version": _PATCH_VERSION,
                "patch_marker": _EXPLORER_REGISTRY_PATCH_MARKER,
                "source_asset": source_asset,
                "served_asset": served_asset,
                "architectures_extension": "/api/extensions/architectures.js",
                "architecture_language_version": 2,
                "explorer_module": str(Path(__file__).resolve()),
                "server_module": str(Path(server_module.__file__).resolve()),
                "static_root": str(static_root.resolve()),
            }
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
