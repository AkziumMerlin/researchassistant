import pytest
from pydantic import BaseModel, ConfigDict

from research_assistant.errors import RegistryError
from research_assistant.models import ComponentRef
from research_assistant.registry import Registry


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


def factory(config: Params, _context):
    return config.value


def test_registry_validates_and_invokes() -> None:
    registry = Registry()
    registry.add("value", "test/value", factory=factory, schema=Params)

    result = registry.invoke(
        "value", ComponentRef(type="test/value", params={"value": 3}), context=None
    )

    assert result == 3


def test_registry_rejects_unknown_params() -> None:
    registry = Registry()
    registry.add("value", "test/value", factory=factory, schema=Params)

    with pytest.raises(RegistryError, match="invalid parameters"):
        registry.validate("value", ComponentRef(type="test/value", params={"value": 3, "extra": 1}))
