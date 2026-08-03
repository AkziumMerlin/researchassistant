from __future__ import annotations

from typing import Any

_INSTALLED = False


def install_runtime() -> None:
    """Install optional compatibility hooks before the CLI imports UI modules."""
    global _INSTALLED
    if _INSTALLED:
        return

    from research_assistant.durable_launches import DurableLaunchManager
    from research_assistant.ui import launches

    launches.LaunchManager = DurableLaunchManager

    from research_assistant import workbench_ui

    original_install = workbench_ui.install

    def install_workbench_with_workspace() -> None:
        original_install()
        from research_assistant.research_workspace_ui import register_research_workspace
        from research_assistant.ui import server

        current_create_app = server.create_app
        if getattr(current_create_app, "_research_workspace_v2", False):
            return

        def create_app(
            root: Any,
            plugins: list[str] | None = None,
            *,
            ssh_mode: bool | None = None,
        ):
            app = current_create_app(root, plugins, ssh_mode=ssh_mode)
            paths = {getattr(route, "path", None) for route in app.routes}
            if "/api/workspace-v2/capabilities" not in paths:
                register_research_workspace(app)
            return app

        create_app._research_workspace_v2 = True
        server.create_app = create_app

    workbench_ui.install = install_workbench_with_workspace
    _INSTALLED = True
