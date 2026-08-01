"""Local browser workbench for ResearchAssistant projects."""

import importlib.util

from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

__all__ = ["Workspace", "WorkspaceConflict", "WorkspaceError"]

if importlib.util.find_spec("fastapi") is not None:
    from research_assistant.terminal_ui import install as install_terminal_ui

    install_terminal_ui()
