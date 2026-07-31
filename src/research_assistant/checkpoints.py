from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from research_assistant.config import apply_overrides, load_config, parse_config
from research_assistant.errors import ConfigError, ResearchAssistantError
from research_assistant.models import ComponentRef, ExperimentConfig, ExperimentMeta, StageConfig
from research_assistant.planning import Plan, RunManifest, compile_plan
from research_assistant.registry import Registry

CHECKPOINT_SUFFIXES = frozenset({".pt", ".pth", ".ckpt"})


class CheckpointError(ResearchAssistantError):
    pass


@dataclass(frozen=True, slots=True)
class CheckpointDescriptor:
    path: Path
    managed: bool
    name: str
    size: int
    modified_at: str
    study_id: str | None = None
    trial_id: str | None = None
    run_id: str | None = None
    stage: str | None = None
    model: ComponentRef | None = None
    manifest: RunManifest | None = None

    def as_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        path = self.path
        if relative_to is not None and path.is_relative_to(relative_to):
            rendered_path = path.relative_to(relative_to).as_posix()
        else:
            rendered_path = str(path)
        return {
            "path": rendered_path,
            "managed": self.managed,
            "name": self.name,
            "size": self.size,
            "modified_at": self.modified_at,
            "study_id": self.study_id,
            "trial_id": self.trial_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "model": self.model.model_dump(mode="json") if self.model is not None else None,
        }


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _effective_component(
    config: ExperimentConfig,
    stage: StageConfig | None,
    kind: str,
) -> ComponentRef | None:
    if stage is not None and kind in stage.components:
        return stage.components[kind]
    return config.components.get(kind)


def _stage(config: ExperimentConfig, name: str | None) -> StageConfig | None:
    if name is None:
        return None
    return next((candidate for candidate in config.stages if candidate.name == name), None)


def _checkpoint_stage_from_status(run_dir: Path, checkpoint_path: Path) -> str | None:
    status = _read_mapping(run_dir / "status.json")
    stages = status.get("stages")
    if not isinstance(stages, dict):
        return None
    relative = checkpoint_path.relative_to(run_dir).as_posix()
    for stage_name, stage_status in stages.items():
        if not isinstance(stage_status, dict):
            continue
        artifacts = stage_status.get("artifacts")
        if isinstance(artifacts, dict) and relative in map(str, artifacts.values()):
            return str(stage_name)
    return None


def inspect_checkpoint(path: str | Path) -> CheckpointDescriptor:
    checkpoint_path = Path(path).expanduser().resolve()
    if checkpoint_path.suffix.lower() not in CHECKPOINT_SUFFIXES:
        raise CheckpointError("checkpoint must have a .pt, .pth, or .ckpt extension")
    if not checkpoint_path.is_file():
        raise CheckpointError(f"checkpoint does not exist: {checkpoint_path}")

    stat = checkpoint_path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    run_dir = checkpoint_path.parents[2] if len(checkpoint_path.parents) >= 3 else None
    manifest_path = run_dir / "manifest.json" if run_dir is not None else None
    manifest: RunManifest | None = None
    if manifest_path is not None and manifest_path.is_file():
        try:
            manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None

    if manifest is None or run_dir is None or not checkpoint_path.is_relative_to(run_dir):
        return CheckpointDescriptor(
            path=checkpoint_path,
            managed=False,
            name=checkpoint_path.stem,
            size=stat.st_size,
            modified_at=modified_at,
        )

    stage_name = _checkpoint_stage_from_status(run_dir, checkpoint_path)
    if stage_name is None and checkpoint_path.parent.parent.name == "checkpoints":
        stage_name = checkpoint_path.parent.name
    source_stage = _stage(manifest.config, stage_name)
    model = _effective_component(manifest.config, source_stage, "model")
    return CheckpointDescriptor(
        path=checkpoint_path,
        managed=True,
        name=checkpoint_path.stem,
        size=stat.st_size,
        modified_at=modified_at,
        study_id=manifest.study_id,
        trial_id=manifest.trial_id,
        run_id=manifest.run_id,
        stage=stage_name,
        model=model,
        manifest=manifest,
    )


def catalog_checkpoints(root: str | Path) -> list[CheckpointDescriptor]:
    artifact_root = Path(root).expanduser().resolve()
    if not artifact_root.exists():
        return []
    descriptors: list[CheckpointDescriptor] = []
    for path in sorted(artifact_root.glob("*/*/checkpoints/*/*")):
        if path.is_file() and path.suffix.lower() in CHECKPOINT_SUFFIXES:
            descriptors.append(inspect_checkpoint(path))
    descriptors.sort(key=lambda item: item.modified_at, reverse=True)
    return descriptors


def _target_stage(config: ExperimentConfig) -> StageConfig | None:
    for stage in config.stages:
        if stage.type in {"torch/evaluate", "torch/predict"}:
            return stage
    for stage in config.stages:
        if stage.type == "torch/fit":
            return stage
    return config.stages[0] if config.stages else None


def _load_inference_base(
    descriptor: CheckpointDescriptor,
    *,
    config_path: str | Path | None,
    overrides: list[str],
) -> ExperimentConfig:
    if config_path is not None:
        return load_config(config_path, overrides)
    if descriptor.manifest is None:
        raise CheckpointError("an external checkpoint requires --config")
    document = descriptor.manifest.config.model_dump(mode="python")
    document = apply_overrides(document, overrides)
    return parse_config(document)


def build_inference_config(
    checkpoint: str | Path,
    registry: Registry,
    *,
    base_config: ExperimentConfig | None = None,
    config_path: str | Path | None = None,
    overrides: list[str] | None = None,
    splits: list[str] | None = None,
    device: Literal["auto", "cpu", "cuda"] = "auto",
    predict: bool = False,
) -> tuple[ExperimentConfig, dict[str, Any]]:
    descriptor = inspect_checkpoint(checkpoint)
    base = base_config or _load_inference_base(
        descriptor,
        config_path=config_path,
        overrides=overrides or [],
    )
    target_stage = _target_stage(base)
    target_model = _effective_component(base, target_stage, "model")
    if target_model is None:
        raise ConfigError("inference config does not define a model component")
    if descriptor.model is not None and descriptor.model != target_model:
        raise CheckpointError(
            "checkpoint model does not exactly match the inference config: "
            f"{descriptor.model.type} != {target_model.type}"
        )

    components = copy.deepcopy(base.components)
    for kind in ("model", "data", "recipe"):
        reference = _effective_component(base, target_stage, kind)
        if reference is not None:
            components[kind] = reference

    selected_splits = list(dict.fromkeys(splits or ["test"]))
    if not selected_splits or any(not split for split in selected_splits):
        raise ConfigError("inference requires at least one non-empty split")
    stage_type = "torch/predict" if predict else "torch/evaluate"
    stage_name = "predict" if predict else selected_splits[0]
    stage_params: dict[str, Any] = {
        "checkpoint_path": str(descriptor.path),
        "splits": selected_splits,
        "device": device,
    }
    inference_config = base.model_copy(
        update={
            "experiment": ExperimentMeta(
                name=f"{base.experiment.name}-inference",
                description=f"Inference from {descriptor.path.name}",
                tags=list(dict.fromkeys([*base.experiment.tags, "inference"])),
            ),
            "matrix": {},
            "components": components,
            "stages": [
                StageConfig(
                    name=stage_name,
                    type=stage_type,
                    params=stage_params,
                )
            ],
            "resources": base.resources.model_copy(update={"accelerator": device}),
        }
    )
    registry.validate("stage", {"type": stage_type, "params": stage_params})
    provenance = {
        "kind": "checkpoint-inference",
        "checkpoint": descriptor.as_dict(),
        "source_run_id": descriptor.run_id,
        "source_trial_id": descriptor.trial_id,
        "source_study_id": descriptor.study_id,
    }
    return inference_config, provenance


def compile_inference_plan(
    config: ExperimentConfig,
    registry: Registry,
    provenance: dict[str, Any],
) -> Plan:
    compiled = compile_plan(config, registry)
    manifests = tuple(
        manifest.model_copy(update={"provenance": copy.deepcopy(provenance)})
        for manifest in compiled.runs
    )
    return Plan(study_id=compiled.study_id, runs=manifests)
