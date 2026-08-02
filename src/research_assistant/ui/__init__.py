"""Local browser workbench for ResearchAssistant projects."""

import importlib.util

from research_assistant.ui.workspace import Workspace, WorkspaceConflict, WorkspaceError

__all__ = ["Workspace", "WorkspaceConflict", "WorkspaceError"]

if importlib.util.find_spec("fastapi") is not None:
    from research_assistant.notebook_ui import (
        _register as register_notebook_ui,
    )
    from research_assistant.notebook_ui import install as install_notebook_ui
    from research_assistant.system_monitor_ui import install as install_system_monitor_ui
    from research_assistant.terminal_ui import install as install_terminal_ui
    from research_assistant.workspace_browser_ui import (
        _register as register_workspace_browser_ui,
    )
    from research_assistant.workspace_browser_ui import install as install_workspace_browser_ui

    install_terminal_ui()
    install_system_monitor_ui()
    install_workspace_browser_ui()
    install_notebook_ui()

    # Package import order can otherwise leave a stale create_app reference during
    # recursive UI initialization. Keep one final wrapper that verifies these two
    # feature sets on every constructed app; both checks are app-local and idempotent.
    from research_assistant.ui import server

    original_create_app = server.create_app

    def create_app(root, plugins=None, *, ssh_mode=None):
        app = original_create_app(root, plugins, ssh_mode=ssh_mode)
        paths = {getattr(route, "path", None) for route in app.routes}
        if "/api/workspace/entries" not in paths:
            register_workspace_browser_ui(app)
        if not hasattr(app.state, "notebook_kernels"):
            register_notebook_ui(app)
        return app

    server.create_app = create_app
