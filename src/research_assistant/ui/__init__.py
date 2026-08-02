"""Local browser workbench for ResearchAssistant projects."""

import importlib.util

from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

__all__ = ["Workspace", "WorkspaceConflict", "WorkspaceError"]

if importlib.util.find_spec("fastapi") is not None:
    from research_assistant.notebook_ui import install as install_notebook_ui
    from research_assistant.system_monitor_ui import install as install_system_monitor_ui
    from research_assistant.terminal_ui import install as install_terminal_ui
    from research_assistant.workspace_browser_ui import install as install_workspace_browser_ui

    install_terminal_ui()
    install_system_monitor_ui()
    install_workspace_browser_ui()
    install_notebook_ui()
