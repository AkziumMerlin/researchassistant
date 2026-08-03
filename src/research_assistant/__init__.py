"""ResearchAssistant public API."""

from importlib.metadata import PackageNotFoundError, version as distribution_version

from research_assistant.config import load_config
from research_assistant.planning import Plan, RunManifest, compile_plan
from research_assistant.registry import Registry

try:
    __version__ = distribution_version("research-assistant")
except PackageNotFoundError:  # pragma: no cover - only possible outside an installed checkout
    __version__ = "0.0.0+unknown"

__all__ = [
    "Plan",
    "Registry",
    "RunManifest",
    "__version__",
    "compile_plan",
    "load_config",
]
