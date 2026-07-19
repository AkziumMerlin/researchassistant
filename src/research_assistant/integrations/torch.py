from __future__ import annotations

import math
import os
import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_assistant.errors import ExecutionError
from research_assistant.execution import StageContext, StageResult
from research_assistant.registry import Registry


@dataclass(frozen=True, slots=True)
class TorchStep:
    """The framework-neutral result of one recipe step.

    ``loss`` is differentiated by the fit stage. Metrics are reduced as weighted means, using
    ``weight`` as the number of represented samples (or any other recipe-defined mass).
    """

    loss: Any | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class TorchDataLoaders:
    """Re-iterable loaders exposed by a data component."""

    train: Iterable[Any] | None = None
    evaluation: Mapping[str, Iterable[Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TorchRecipe:
    """Task semantics consumed by the generic PyTorch stages.

    Batch structure and device transfer deliberately remain inside the step callables. This is
    what lets the same stage train tensors, mappings, graphs, trajectories, and rollouts.
    """

    optimizer: Callable[[Any], Any]
    train_step: Callable[[Any, Any, Any], TorchStep]
    eval_step: Callable[[Any, Any, Any, str], TorchStep]
    scheduler: Callable[[Any], Any] | None = None
    scheduler_step: Callable[[Any, Mapping[str, float]], None] | None = None


class TorchFitParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epochs: int = Field(default=1, ge=1)
    monitor: str = "val/loss"
    mode: Literal["min", "max"] = "min"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    amp: bool = False
    gradient_clip_norm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_monitor(self) -> TorchFitParams:
        if not self.monitor or self.monitor.startswith("train/"):
            raise ValueError("monitor must name a non-training metric such as 'val/loss'")
        return self


class TorchEvaluateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_stage: str = "fit"
    checkpoint: str = "best"
    splits: list[str] | None = None
    device: Literal["auto", "cpu", "cuda"] = "auto"


def _torch() -> Any:
    try:
        return import_module("torch")
    except ModuleNotFoundError as exc:
        raise ExecutionError(
            "PyTorch is required for this stage; install ResearchAssistant with the 'torch' extra"
        ) from exc


def _resolve_device(torch: Any, context: StageContext, requested: str) -> Any:
    resources = context.manifest.config.resources
    if resources.devices != 1:
        raise ExecutionError("the built-in PyTorch stages currently support exactly one device")

    choice = requested
    if choice == "auto":
        choice = resources.accelerator
    if choice == "auto":
        choice = "cuda" if torch.cuda.is_available() else "cpu"
    if choice == "cuda" and not torch.cuda.is_available():
        raise ExecutionError("CUDA was requested but torch.cuda.is_available() is false")
    return torch.device(choice)


def _seed_everything(torch: Any, seed: int | None) -> None:
    if seed is None:
        return
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    try:
        numpy = import_module("numpy")
    except ModuleNotFoundError:
        return
    numpy.random.seed(seed)


def _capture_rng(torch: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "python": random.getstate(),
        "torch": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    try:
        numpy = import_module("numpy")
    except ModuleNotFoundError:
        return state
    state["numpy"] = numpy.random.get_state()
    return state


def _restore_rng(torch: Any, state: Mapping[str, Any]) -> None:
    if "python" in state:
        random.setstate(state["python"])
    if "torch" in state:
        torch.set_rng_state(state["torch"])
    if "cuda" in state and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])
    if "numpy" in state:
        try:
            numpy = import_module("numpy")
        except ModuleNotFoundError:
            pass
        else:
            numpy.random.set_state(state["numpy"])


def _require_components(context: StageContext) -> tuple[Any, TorchDataLoaders, TorchRecipe]:
    model = context.component("model")
    data = context.component("data")
    recipe = context.component("recipe")
    if not isinstance(data, TorchDataLoaders):
        raise ExecutionError("a torch stage requires data to return TorchDataLoaders")
    if not isinstance(recipe, TorchRecipe):
        raise ExecutionError("a torch stage requires recipe to return TorchRecipe")
    for method in ("to", "train", "eval", "state_dict", "load_state_dict"):
        if not callable(getattr(model, method, None)):
            raise ExecutionError(f"the model component lacks required method {method}()")
    return model, data, recipe


def _as_float(value: Any, *, name: str) -> float:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "item"):
        value = value.item()
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"metric {name!r} must be scalar, got {type(value).__name__}") from exc
    if not math.isfinite(result):
        raise ExecutionError(f"metric {name!r} is not finite: {result}")
    return result


def _validate_step(value: Any, *, training: bool) -> TorchStep:
    if not isinstance(value, TorchStep):
        raise ExecutionError("torch recipe steps must return TorchStep")
    if training and value.loss is None:
        raise ExecutionError("a training TorchStep must define loss")
    if not math.isfinite(float(value.weight)) or value.weight <= 0:
        raise ExecutionError("TorchStep.weight must be a finite positive number")
    return value


def _run_loader(
    torch: Any,
    loader: Iterable[Any],
    *,
    model: Any,
    device: Any,
    step: Callable[[Any], TorchStep],
    training: bool,
    optimizer: Any | None = None,
    scaler: Any | None = None,
    amp: bool = False,
    gradient_clip_norm: float | None = None,
) -> dict[str, float]:
    totals: dict[str, float] = {}
    weights: dict[str, float] = {}
    batches = 0
    model.train(training)

    grad_context = torch.enable_grad if training else torch.no_grad
    with grad_context():
        for batch in loader:
            batches += 1
            if training:
                optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=amp):
                output = _validate_step(step(batch), training=training)

            metrics = dict(output.metrics)
            if output.loss is not None:
                metrics.setdefault("loss", output.loss)
            for name, value in metrics.items():
                normalized = _as_float(value, name=str(name))
                totals[str(name)] = totals.get(str(name), 0.0) + normalized * output.weight
                weights[str(name)] = weights.get(str(name), 0.0) + output.weight

            if training:
                scaler.scale(output.loss).backward()
                if gradient_clip_norm is not None:
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip_norm)
                scaler.step(optimizer)
                scaler.update()

    if batches == 0:
        raise ExecutionError("a torch data loader produced no batches")
    return {name: total / weights[name] for name, total in totals.items()}


def _prefix_metrics(prefix: str, metrics: Mapping[str, float]) -> dict[str, float]:
    return {f"{prefix}/{name}": float(value) for name, value in metrics.items()}


def _atomic_save(torch: Any, checkpoint: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        torch.save(dict(checkpoint), temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_checkpoint(torch: Any, path: Path) -> Mapping[str, Any]:
    # Checkpoints are generated inside the immutable run directory. Explicit weights_only=False
    # is needed because RNG state includes standard Python and optional NumPy objects.
    try:
        value = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:  # PyTorch < 2.6 compatibility.
        value = torch.load(path, map_location="cpu")
    if not isinstance(value, Mapping) or value.get("format") != "research-assistant/torch-v1":
        raise ExecutionError(f"unsupported ResearchAssistant checkpoint: {path}")
    return value


def _checkpoint(
    torch: Any,
    *,
    epoch: int,
    model: Any,
    optimizer: Any,
    scheduler: Any | None,
    scaler: Any,
    best_value: float,
    best_epoch: int,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": "research-assistant/torch-v1",
        "epoch": epoch,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict() if scheduler is not None else None,
        "scaler": scaler.state_dict(),
        "best_value": best_value,
        "best_epoch": best_epoch,
        "history": history,
        "rng": _capture_rng(torch),
    }


def run_fit(params: TorchFitParams, context: StageContext) -> StageResult:
    torch = _torch()
    device = _resolve_device(torch, context, params.device)
    if params.amp and device.type != "cuda":
        raise ExecutionError("automatic mixed precision is currently supported only on CUDA")

    _seed_everything(torch, context.seed)
    model, data, recipe = _require_components(context)
    if data.train is None:
        raise ExecutionError("torch/fit requires a training loader")
    if not data.evaluation:
        raise ExecutionError("torch/fit requires at least one evaluation loader for selection")

    model.to(device)
    optimizer = recipe.optimizer(model)
    scheduler = recipe.scheduler(optimizer) if recipe.scheduler is not None else None
    scaler = torch.amp.GradScaler(device.type, enabled=params.amp)

    checkpoint_dir = context.run_dir / "checkpoints" / context.stage.name
    last_path = checkpoint_dir / "last.pt"
    best_path = checkpoint_dir / "best.pt"
    start_epoch = 0
    best_value = math.inf if params.mode == "min" else -math.inf
    best_epoch = -1
    history: list[dict[str, Any]] = []

    if context.resume and last_path.exists():
        saved = _load_checkpoint(torch, last_path)
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        if scheduler is not None and saved.get("scheduler") is not None:
            scheduler.load_state_dict(saved["scheduler"])
        if saved.get("scaler"):
            scaler.load_state_dict(saved["scaler"])
        start_epoch = int(saved["epoch"]) + 1
        best_value = float(saved["best_value"])
        best_epoch = int(saved["best_epoch"])
        history = list(saved.get("history") or [])
        _restore_rng(torch, saved.get("rng") or {})

    for epoch in range(start_epoch, params.epochs):
        train_metrics = _run_loader(
            torch,
            data.train,
            model=model,
            device=device,
            step=lambda batch: recipe.train_step(model, batch, device),
            training=True,
            optimizer=optimizer,
            scaler=scaler,
            amp=params.amp,
            gradient_clip_norm=params.gradient_clip_norm,
        )
        epoch_metrics = _prefix_metrics("train", train_metrics)

        for split, loader in data.evaluation.items():
            split_metrics = _run_loader(
                torch,
                loader,
                model=model,
                device=device,
                step=lambda batch, split=split: recipe.eval_step(model, batch, device, split),
                training=False,
                amp=params.amp,
            )
            epoch_metrics.update(_prefix_metrics(split, split_metrics))

        if params.monitor not in epoch_metrics:
            available = ", ".join(sorted(epoch_metrics)) or "none"
            raise ExecutionError(
                f"monitor {params.monitor!r} was not produced; available metrics: {available}"
            )
        monitor_value = epoch_metrics[params.monitor]
        improved = (
            monitor_value < best_value if params.mode == "min" else monitor_value > best_value
        )
        if improved:
            best_value = monitor_value
            best_epoch = epoch

        if scheduler is not None:
            if recipe.scheduler_step is not None:
                recipe.scheduler_step(scheduler, epoch_metrics)
            else:
                scheduler.step()

        history.append({"epoch": epoch, "metrics": epoch_metrics})
        checkpoint = _checkpoint(
            torch,
            epoch=epoch,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            best_value=best_value,
            best_epoch=best_epoch,
            history=history,
        )
        _atomic_save(torch, checkpoint, last_path)
        if improved:
            _atomic_save(torch, checkpoint, best_path)
        context.log_metrics(epoch_metrics, step=epoch)

    if not history or not best_path.exists():
        raise ExecutionError("fit completed without a checkpoint")
    final_metrics = {str(key): float(value) for key, value in history[-1]["metrics"].items()}
    final_metrics[f"best/{params.monitor}"] = best_value
    return StageResult(
        metrics=final_metrics,
        artifacts={"best": str(best_path), "last": str(last_path)},
    )


def run_evaluate(params: TorchEvaluateParams, context: StageContext) -> StageResult:
    torch = _torch()
    device = _resolve_device(torch, context, params.device)
    _seed_everything(torch, context.seed)
    model, data, recipe = _require_components(context)
    model.to(device)

    checkpoint_path = context.artifact(params.checkpoint_stage, params.checkpoint)
    saved = _load_checkpoint(torch, checkpoint_path)
    model.load_state_dict(saved["model"])

    splits = params.splits or list(data.evaluation)
    if not splits:
        raise ExecutionError("torch/evaluate requires at least one evaluation split")
    missing = [split for split in splits if split not in data.evaluation]
    if missing:
        available = ", ".join(sorted(data.evaluation)) or "none"
        raise ExecutionError(
            f"unknown evaluation splits {', '.join(missing)}; available: {available}"
        )

    metrics: dict[str, float] = {}
    for split in splits:
        split_metrics = _run_loader(
            torch,
            data.evaluation[split],
            model=model,
            device=device,
            step=lambda batch, split=split: recipe.eval_step(model, batch, device, split),
            training=False,
        )
        metrics.update(_prefix_metrics(split, split_metrics))
    return StageResult(metrics=metrics)


def register(registry: Registry) -> None:
    registry.add(
        "stage",
        "torch/fit",
        factory=run_fit,
        schema=TorchFitParams,
        description="Train a registered PyTorch model with a project-defined recipe.",
        provider="research-assistant[torch]",
    )
    registry.add(
        "stage",
        "torch/evaluate",
        factory=run_evaluate,
        schema=TorchEvaluateParams,
        description="Evaluate a registered PyTorch model from a named checkpoint artifact.",
        provider="research-assistant[torch]",
    )
