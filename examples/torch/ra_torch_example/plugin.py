from typing import Any

import torch
from pydantic import BaseModel, ConfigDict, Field
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from research_assistant.integrations.torch import TorchDataLoaders, TorchRecipe, TorchStep
from research_assistant.registry import Registry


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=16, ge=1)


def build_model(config: ModelConfig, _context: Any) -> nn.Module:
    return nn.Sequential(nn.Linear(1, config.width), nn.Tanh(), nn.Linear(config.width, 1))


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(default=32, ge=1)


def build_data(config: DataConfig, _context: Any) -> TorchDataLoaders:
    x = torch.linspace(-2.0, 2.0, 256).unsqueeze(1)
    y = x.sin() + 0.2 * x
    train = TensorDataset(x[:160], y[:160])
    validation = TensorDataset(x[160:208], y[160:208])
    test = TensorDataset(x[208:], y[208:])
    return TorchDataLoaders(
        train=DataLoader(train, batch_size=config.batch_size, shuffle=True),
        evaluation={
            "val": DataLoader(validation, batch_size=config.batch_size),
            "test": DataLoader(test, batch_size=config.batch_size),
        },
    )


class RecipeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learning_rate: float = Field(default=0.001, gt=0)


def build_recipe(config: RecipeConfig, _context: Any) -> TorchRecipe:
    def step(model: nn.Module, batch: Any, device: Any, _split: str | None = None) -> TorchStep:
        x, target = (value.to(device) for value in batch)
        prediction = model(x)
        loss = nn.functional.mse_loss(prediction, target)
        return TorchStep(
            loss=loss,
            metrics={"mae": nn.functional.l1_loss(prediction, target)},
            weight=len(x),
        )

    return TorchRecipe(
        optimizer=lambda model: torch.optim.AdamW(
            model.parameters(), lr=config.learning_rate
        ),
        train_step=lambda model, batch, device: step(model, batch, device),
        eval_step=lambda model, batch, device, split: step(model, batch, device, split),
        predict_step=lambda model, batch, device, split: model(batch[0].to(device)).cpu(),
    )


def register(registry: Registry) -> None:
    registry.add("model", "torch_example/mlp", factory=build_model, schema=ModelConfig)
    registry.add("data", "torch_example/regression", factory=build_data, schema=DataConfig)
    registry.add("recipe", "torch_example/mse", factory=build_recipe, schema=RecipeConfig)
