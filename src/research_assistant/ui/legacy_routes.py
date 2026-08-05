from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.errors import ResearchAssistantError
from research_assistant.legacy import (
    ProjectRegistrationCatalog,
    discover_python_symbols,
    suggest_legacy_entrypoint,
)
from research_assistant.plugins import load_registry


class LegacyUiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PythonRegistrationRequest(LegacyUiModel):
    path: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    kind: str = "model"
    name: str = Field(min_length=1)
    description: str = ""
    catalog: str = "component"
    editor: str | None = None
    replace: bool = False


class LegacyConfigRegistrationRequest(LegacyUiModel):
    path: str = Field(min_length=1)
    entrypoint: str | None = None
    output: str = Field(min_length=1)
    name: str | None = None
    arguments: list[str] = Field(default_factory=list)
    working_directory: str = "."
    description: str = ""
    replace: bool = False


def _project_file(root: Path, value: str) -> Path:
    path = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not path.is_relative_to(root):
        raise ResearchAssistantError(f"path escapes project root: {value}")
    return path


def register_legacy_routes(app) -> None:
    try:
        from fastapi import Query
    except ImportError as exc:  # pragma: no cover
        raise ResearchAssistantError("desktop API dependencies are missing") from exc

    root = Path(app.state.workspace.root).resolve()

    @app.get("/api/legacy/registrations")
    def legacy_registrations() -> dict[str, Any]:
        catalog = ProjectRegistrationCatalog(root)
        return {
            "catalog_path": catalog.path.relative_to(root).as_posix(),
            **catalog.load().model_dump(mode="json"),
        }

    @app.get("/api/legacy/python/discover")
    def legacy_python_discover(path: str = Query(min_length=1)) -> dict[str, Any]:
        source = _project_file(root, path)
        return {
            "path": source.relative_to(root).as_posix(),
            "symbols": discover_python_symbols(source),
        }

    @app.post("/api/legacy/python/register")
    def legacy_python_register(payload: PythonRegistrationRequest) -> dict[str, Any]:
        catalog = ProjectRegistrationCatalog(root)
        registration = catalog.add_python(
            kind=payload.kind,
            name=payload.name,
            path=payload.path,
            symbol=payload.symbol,
            description=payload.description,
            catalog=payload.catalog,
            editor=payload.editor,
            replace=payload.replace,
        )
        registry = load_registry(list(app.state.plugins), project_root=root)
        spec = registry.get(payload.kind, payload.name)
        app.state.registry = registry
        return {
            "registration": registration.model_dump(mode="json"),
            "provider": spec.provider,
            "schema": spec.schema.model_json_schema(),
            "restart_required": True,
        }

    @app.post("/api/legacy/config/register")
    def legacy_config_register(payload: LegacyConfigRegistrationRequest) -> dict[str, Any]:
        entrypoint = payload.entrypoint
        if not entrypoint:
            suggested = suggest_legacy_entrypoint(root)
            if suggested is None:
                raise ResearchAssistantError(
                    "no legacy YAML runner was found; specify entrypoint"
                )
            entrypoint = suggested.relative_to(root).as_posix()
        catalog = ProjectRegistrationCatalog(root)
        registration, content = catalog.add_legacy_config(
            path=payload.path,
            entrypoint=entrypoint,
            output=payload.output,
            name=payload.name,
            arguments=payload.arguments,
            working_directory=payload.working_directory,
            description=payload.description,
            replace=payload.replace,
        )
        return {
            "registration": registration.model_dump(mode="json"),
            "content": content,
            "command": f"ra run {registration.output}",
        }
