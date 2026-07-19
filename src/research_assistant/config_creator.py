from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import typer
import yaml
from pydantic import ValidationError
from pydantic_core import PydanticUndefined

from research_assistant.config import parse_config
from research_assistant.errors import ConfigError
from research_assistant.models import ExperimentConfig
from research_assistant.registry import ComponentSpec, Registry


class CreatorPrompt(Protocol):
    def ask(self, label: str, *, default: str | None = None) -> str: ...

    def choose(self, label: str, options: Sequence[str], *, default: int = 0) -> int: ...

    def confirm(self, label: str, *, default: bool = False) -> bool: ...

    def write(self, message: str) -> None: ...


class TerminalPrompt:
    def ask(self, label: str, *, default: str | None = None) -> str:
        if default is None:
            return str(typer.prompt(label, type=str))
        return str(typer.prompt(label, default=default, type=str, show_default=True))

    def choose(self, label: str, options: Sequence[str], *, default: int = 0) -> int:
        if not options:
            raise ConfigError(f"no choices available for {label}")
        for index, option in enumerate(options, start=1):
            typer.echo(f"  {index}. {option}")
        while True:
            selected = typer.prompt(label, default=default + 1, type=int)
            if 1 <= selected <= len(options):
                return selected - 1
            typer.secho(f"choose a number from 1 to {len(options)}", fg=typer.colors.YELLOW)

    def confirm(self, label: str, *, default: bool = False) -> bool:
        return bool(typer.confirm(label, default=default))

    def write(self, message: str) -> None:
        typer.echo(message)


def _inline_yaml(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    rendered = yaml.safe_dump(value, default_flow_style=True, sort_keys=False).strip()
    return rendered.removesuffix("\n...").removesuffix("...").strip()


def _parse_yaml(raw: str, *, label: str) -> Any:
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML value for {label}: {exc}") from exc


def _property_hint(property_schema: Mapping[str, Any]) -> str:
    if "enum" in property_schema:
        return "one of: " + ", ".join(map(str, property_schema["enum"]))
    if "type" in property_schema:
        value = property_schema["type"]
        return "/".join(map(str, value)) if isinstance(value, list) else str(value)
    variants = property_schema.get("anyOf") or []
    types = [variant.get("type") for variant in variants if variant.get("type")]
    return "/".join(map(str, types)) or "YAML"


def prompt_component_params(spec: ComponentSpec, prompt: CreatorPrompt) -> dict[str, Any]:
    schema = spec.schema.model_json_schema()
    properties = schema.get("properties") or {}
    while True:
        values: dict[str, Any] = {}
        prompt.write(f"Parameters for {spec.kind} {spec.name}:")
        for name, model_field in spec.schema.model_fields.items():
            property_schema = properties.get(name) or {}
            hint = _property_hint(property_schema)
            description = property_schema.get("description")
            required = model_field.is_required()
            if required:
                label = f"  {name} [{hint}; required]"
                default = None
            else:
                raw_default = model_field.get_default(call_default_factory=True)
                if raw_default is PydanticUndefined:
                    raw_default = None
                label = f"  {name} [{hint}]"
                default = _inline_yaml(raw_default)
            if description:
                prompt.write(f"    {description}")
            raw = prompt.ask(label, default=default)
            if not required and raw == "":
                continue
            try:
                values[name] = _parse_yaml(raw, label=name)
            except ConfigError as exc:
                prompt.write(f"error: {exc}")
                break
        else:
            try:
                validated = spec.schema.model_validate(values)
            except ValidationError as exc:
                prompt.write(f"error: {exc}")
            else:
                return validated.model_dump(mode="json", exclude_defaults=True)
        if not prompt.confirm("Retry these parameters?", default=True):
            raise ConfigError(f"parameters for {spec.kind} {spec.name} were not completed")


def _validate_unique_assignments(
    assignments: Sequence[tuple[str, str]], *, label: str
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in assignments:
        if key in result:
            raise ConfigError(f"duplicate {label} name {key!r}")
        result[key] = value
    return result


@dataclass(slots=True)
class ConfigCreator:
    registry: Registry
    prompt: CreatorPrompt
    plugins: list[str] = field(default_factory=list)

    def _reference(self, kind: str, name: str) -> dict[str, Any]:
        spec = self.registry.get(kind, name)
        params = prompt_component_params(spec, self.prompt)
        result: dict[str, Any] = {"type": name}
        if params:
            result["params"] = params
        return result

    def _add_interactive_components(
        self, components: dict[str, dict[str, Any]], *, first_default: bool
    ) -> None:
        specs = [
            spec
            for spec in self.registry.list()
            if spec.kind not in {"stage", "launcher"} and spec.kind not in components
        ]
        default = first_default
        while specs and self.prompt.confirm("Add a registered component?", default=default):
            labels = [
                f"{spec.kind}: {spec.name}" + (f" — {spec.description}" if spec.description else "")
                for spec in specs
            ]
            spec = specs[self.prompt.choose("Component", labels)]
            components[spec.kind] = self._reference(spec.kind, spec.name)
            specs = [candidate for candidate in specs if candidate.kind != spec.kind]
            default = False

    def _stage(
        self,
        stage_name: str,
        type_name: str,
        previous_names: list[str],
    ) -> dict[str, Any]:
        if stage_name in previous_names:
            raise ConfigError(f"duplicate stage name {stage_name!r}")
        reference = self._reference("stage", type_name)
        needs: list[str] = []
        if previous_names:
            raw_default = _inline_yaml([previous_names[-1]])
            raw_needs = self.prompt.ask(
                f"Dependencies for stage {stage_name} [YAML list]", default=raw_default
            )
            parsed = _parse_yaml(raw_needs, label=f"stage {stage_name} dependencies")
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise ConfigError(f"dependencies for stage {stage_name!r} must be a list of names")
            unknown = sorted(set(parsed) - set(previous_names))
            if unknown:
                raise ConfigError(
                    f"stage {stage_name!r} depends on stages not created yet: {', '.join(unknown)}"
                )
            needs = parsed
        stage: dict[str, Any] = {"name": stage_name, "type": type_name}
        if needs:
            stage["needs"] = needs
        if reference.get("params"):
            stage["params"] = reference["params"]
        return stage

    def build(
        self,
        *,
        default_name: str,
        selected_components: Sequence[tuple[str, str]] = (),
        selected_stages: Sequence[tuple[str, str]] = (),
    ) -> ExperimentConfig:
        experiment_name = self.prompt.ask("Experiment name", default=default_name)
        description = self.prompt.ask("Description (empty to omit)", default="").strip() or None

        raw_tags = self.prompt.ask("Tags [YAML list]", default="[]")
        tags = _parse_yaml(raw_tags, label="tags")
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise ConfigError("tags must be a YAML list of strings")

        raw_seeds = self.prompt.ask("Seeds [YAML list]", default="[0]")
        seeds = _parse_yaml(raw_seeds, label="seeds")
        if (
            not isinstance(seeds, list)
            or not seeds
            or not all(isinstance(item, int) for item in seeds)
        ):
            raise ConfigError("seeds must be a non-empty YAML list of integers")
        if len(seeds) != len(set(seeds)):
            raise ConfigError("seeds must be unique")

        preselected_components = _validate_unique_assignments(
            selected_components, label="component kind"
        )
        components = {
            kind: self._reference(kind, name)
            for kind, name in preselected_components.items()
        }
        self._add_interactive_components(components, first_default=not components)

        stage_specs = self.registry.list("stage")
        if not stage_specs:
            raise ConfigError("no stage components are registered")
        preselected_stages = _validate_unique_assignments(selected_stages, label="stage")
        stages: list[dict[str, Any]] = []
        for stage_name, type_name in preselected_stages.items():
            stages.append(self._stage(stage_name, type_name, [item["name"] for item in stages]))

        add_default = not stages
        while self.prompt.confirm("Add a stage?", default=add_default):
            labels = [
                spec.name + (f" — {spec.description}" if spec.description else "")
                for spec in stage_specs
            ]
            spec = stage_specs[self.prompt.choose("Stage type", labels)]
            suggested_name = spec.name.rsplit("/", 1)[-1].replace("-", "_")
            stage_name = self.prompt.ask("Stage name", default=suggested_name)
            stages.append(self._stage(stage_name, spec.name, [item["name"] for item in stages]))
            add_default = False
        if not stages:
            raise ConfigError("an experiment must contain at least one stage")

        accelerator_options = ["auto", "cpu", "cuda"]
        accelerator = accelerator_options[
            self.prompt.choose("Accelerator", accelerator_options, default=0)
        ]
        devices = _parse_yaml(self.prompt.ask("Devices", default="1"), label="devices")
        if not isinstance(devices, int):
            raise ConfigError("devices must be an integer")
        raw_memory = self.prompt.ask("Requested memory in GiB (null for automatic)", default="null")
        memory = _parse_yaml(raw_memory, label="memory_gb")
        if memory is not None and not isinstance(memory, (int, float)):
            raise ConfigError("memory_gb must be a number or null")
        artifact_root = self.prompt.ask("Artifact root", default="runs")

        experiment: dict[str, Any] = {"name": experiment_name, "tags": tags}
        if description:
            experiment["description"] = description
        document: dict[str, Any] = {
            "version": 1,
            "experiment": experiment,
            "plugins": list(self.plugins),
            "seed": seeds[0],
            "components": components,
            "stages": stages,
            "resources": {
                "accelerator": accelerator,
                "devices": devices,
                "memory_gb": memory,
            },
            "artifacts": {"root": artifact_root},
        }
        if len(seeds) > 1:
            document["matrix"] = {"seed": seeds}
        return parse_config(document)


def parse_selection(values: Sequence[str], *, option: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ConfigError(f"{option} must use NAME=REGISTERED_TYPE: {value!r}")
        name, type_name = value.split("=", 1)
        if not name or not type_name:
            raise ConfigError(f"{option} must use NAME=REGISTERED_TYPE: {value!r}")
        result.append((name, type_name))
    return result


def preview_config(config: ExperimentConfig) -> str:
    """Stable JSON preview used by alternative prompt frontends and tests."""
    return json.dumps(config.model_dump(mode="json", exclude_none=True), indent=2, sort_keys=True)
