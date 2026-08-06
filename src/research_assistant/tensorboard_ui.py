from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.analytics import bounded_artifact_root
from research_assistant.tensorboard_compat import (
    TensorBoardCompatibilityError,
    TensorBoardStore,
)


class TensorBoardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TensorBoardCatalogRequest(TensorBoardModel):
    logdir: str = Field(default="runs", min_length=1)
    reload: bool = False
    max_runs: int = Field(default=500, ge=1, le=2000)


class TensorBoardChartRequest(TensorBoardModel):
    logdir: str = Field(default="runs", min_length=1)
    runs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(min_length=1)
    x_axis: Literal["step", "relative_time", "wall_time"] = "step"
    smoothing: float = Field(default=0.0, ge=0.0, le=0.999)
    max_points: int = Field(default=1000, ge=20, le=5000)
    max_series: int = Field(default=50, ge=1, le=200)
    y_scale: Literal["linear", "log"] = "linear"
    title: str | None = None
    reload: bool = False


def register_tensorboard_routes(app) -> None:
    workspace = app.state.workspace
    store = getattr(app.state, "tensorboard_store", None)
    if store is None:
        store = TensorBoardStore(workspace.root)
        app.state.tensorboard_store = store

    def resolve_logdir(logdir: str):
        root = bounded_artifact_root(workspace.root, logdir)
        if not root.is_dir():
            raise TensorBoardCompatibilityError(
                f"TensorBoard log directory does not exist: {logdir}"
            )
        return root

    @app.post("/api/tensorboard/catalog")
    def tensorboard_catalog(payload: TensorBoardCatalogRequest):
        return store.catalog(
            resolve_logdir(payload.logdir),
            force=payload.reload,
            max_runs=payload.max_runs,
        )

    @app.post("/api/tensorboard/chart")
    def tensorboard_chart(payload: TensorBoardChartRequest):
        return store.chart(
            resolve_logdir(payload.logdir),
            runs=payload.runs,
            tags=payload.tags,
            x_axis=payload.x_axis,
            smoothing=payload.smoothing,
            max_points=payload.max_points,
            max_series=payload.max_series,
            y_scale=payload.y_scale,
            title=payload.title,
            force=payload.reload,
        )
