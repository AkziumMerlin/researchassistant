"""ResearchAssistant public API."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version

from research_assistant.config import load_config
from research_assistant.planning import Plan, RunManifest, compile_plan
from research_assistant.registry import Registry
from research_assistant.runtime import install_runtime

try:
    __version__ = distribution_version("research-assistant")
except PackageNotFoundError:  # pragma: no cover - only possible outside an installed checkout
    __version__ = "0.0.0+unknown"

install_runtime()

__all__ = [
    "Plan",
    "Registry",
    "RunManifest",
    "__version__",
    "compile_plan",
    "load_config",
]
