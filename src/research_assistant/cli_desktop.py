from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from research_assistant.desktop import launch_desktop
from research_assistant.errors import ResearchAssistantError


def install(app: typer.Typer) -> None:
    """Replace the legacy browser ``ui`` command with the Theia desktop launcher."""
    app.registered_commands[:] = [
        command
        for command in app.registered_commands
        if (command.name or getattr(command.callback, "__name__", None)) not in {"ui", "desktop"}
    ]

    @app.command("ui")
    def ui(
        path: Annotated[Path, typer.Argument()] = Path("."),
        plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
        executable: Annotated[Path | None, typer.Option("--executable")] = None,
        development: Annotated[bool, typer.Option("--dev")] = False,
        host: Annotated[str, typer.Option("--host", hidden=True)] = "127.0.0.1",
        port: Annotated[int, typer.Option("--port", hidden=True)] = 8765,
        open_browser: Annotated[bool, typer.Option("--open/--no-open", hidden=True)] = True,
        ssh: Annotated[bool, typer.Option("--ssh", hidden=True)] = False,
        ssh_target: Annotated[str | None, typer.Option("--ssh-target", hidden=True)] = None,
    ) -> None:
        """Open the Eclipse Theia desktop workbench for a ResearchAssistant project."""
        del port, open_browser, ssh, ssh_target
        if host not in {"127.0.0.1", "localhost", "::1"}:
            typer.secho(
                "error: ResearchAssistant only binds to localhost; use a desktop or SSH workspace",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        try:
            launch_desktop(
                path,
                plugins=plugin or [],
                executable=executable,
                development=development,
            )
        except ResearchAssistantError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc

    @app.command("desktop")
    def desktop(
        path: Annotated[Path, typer.Argument()] = Path("."),
        plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
        executable: Annotated[Path | None, typer.Option("--executable")] = None,
        development: Annotated[bool, typer.Option("--dev")] = False,
    ) -> None:
        """Alias for ``ra ui``."""
        ui(path=path, plugin=plugin, executable=executable, development=development)
