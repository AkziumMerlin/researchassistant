class ResearchAssistantError(Exception):
    """Base class for expected, user-facing errors."""


class ConfigError(ResearchAssistantError):
    """Raised when a configuration cannot be loaded or validated."""


class RegistryError(ResearchAssistantError):
    """Raised for invalid, missing, or conflicting components."""


class ExecutionError(ResearchAssistantError):
    """Raised when a run cannot be safely executed or resumed."""


class LaunchError(ResearchAssistantError):
    """Raised when a launcher cannot safely schedule or monitor a run."""
