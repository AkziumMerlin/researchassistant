from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from research_assistant.errors import ResearchAssistantError
from research_assistant.integrations.parameterized_torch_graph import (
    ParameterizedTorchGraphParams,
    validate_parameterized_graph,
)


class ParameterizedGraphValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: ParameterizedTorchGraphParams


def register_architecture_routes(app) -> None:
    try:
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("UI dependencies are not installed") from exc

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
        return {
            "frontend": "vite",
            "extensions": "bundled",
            "architecture_language_version": 2,
        }

