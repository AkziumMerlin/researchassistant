from __future__ import annotations

import json
from typing import Annotated, Any

import typer
import yaml

from research_assistant.cli import _abort
from research_assistant.errors import ResearchAssistantError
from research_assistant.remote_connect import (
    RemoteConnectionError,
    RemoteConnectSpec,
    RemoteProfileCatalog,
    connect_remote,
)

_INSTALLED = False
remote_app = typer.Typer(help="Manage reusable SSH workspace profiles.")


def _echo(value: object, *, json_output: bool = False) -> None:
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        typer.echo(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())


def _profile_values(
    target_or_profile: str,
    *,
    workspace: str | None,
    conda_env: str | None,
    remote_python: str | None,
    plugins: list[str] | None,
) -> tuple[str, str, str | None, str | None, tuple[str, ...]]:
    profile = RemoteProfileCatalog().get(target_or_profile)
    if profile is None:
        if workspace is None:
            raise RemoteConnectionError(
                "--workspace is required when the first argument is not a saved profile"
            )
        return (
            target_or_profile,
            workspace,
            conda_env,
            remote_python,
            tuple(dict.fromkeys(plugins or [])),
        )

    target = str(profile["target"])
    resolved_workspace = workspace or str(profile["workspace"])
    resolved_conda = conda_env if conda_env is not None else profile.get("conda_env")
    resolved_python = (
        remote_python if remote_python is not None else profile.get("remote_python")
    )
    profile_plugins = profile.get("plugins")
    stored_plugins = (
        [str(value) for value in profile_plugins]
        if isinstance(profile_plugins, list)
        else []
    )
    resolved_plugins = tuple(dict.fromkeys([*stored_plugins, *(plugins or [])]))
    return (
        target,
        resolved_workspace,
        str(resolved_conda) if resolved_conda else None,
        str(resolved_python) if resolved_python else None,
        resolved_plugins,
    )


def connect_command(
    target_or_profile: Annotated[
        str,
        typer.Argument(
            help="SSH host/alias, or a profile created with `ra remote add`."
        ),
    ],
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            "-w",
            help=(
                "Workspace path on the server; relative paths are resolved from "
                "the SSH login directory."
            ),
        ),
    ] = None,
    conda_env: Annotated[
        str | None,
        typer.Option("--conda-env", help="Conda environment name on the server."),
    ] = None,
    remote_python: Annotated[
        str | None,
        typer.Option(
            "--remote-python",
            help="Explicit remote Python executable; mutually exclusive with --conda-env.",
        ),
    ] = None,
    plugin: Annotated[
        list[str] | None,
        typer.Option("--plugin", help="Remote project plugin module; repeat as needed."),
    ] = None,
    local_port: Annotated[
        int,
        typer.Option("--local-port", min=0, max=65535, help="0 chooses a free port."),
    ] = 0,
    remote_port: Annotated[
        int,
        typer.Option("--remote-port", min=0, max=65535, help="0 chooses a high port."),
    ] = 0,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
    reconnect: Annotated[
        bool,
        typer.Option("--reconnect/--no-reconnect"),
    ] = True,
    startup_timeout: Annotated[
        float,
        typer.Option("--startup-timeout", min=1.0, max=600.0),
    ] = 45.0,
    ssh_option: Annotated[
        list[str] | None,
        typer.Option(
            "--ssh-option",
            help="Additional OpenSSH -o option, for example ProxyJump=bastion.",
        ),
    ] = None,
    save: Annotated[
        str | None,
        typer.Option("--save", help="Save the resolved connection as a profile."),
    ] = None,
) -> None:
    """Open a remote ResearchAssistant workspace in the local browser."""
    try:
        (
            target,
            resolved_workspace,
            resolved_conda,
            resolved_python,
            resolved_plugins,
        ) = _profile_values(
            target_or_profile,
            workspace=workspace,
            conda_env=conda_env,
            remote_python=remote_python,
            plugins=plugin,
        )
        spec = RemoteConnectSpec(
            target=target,
            workspace=resolved_workspace,
            plugins=resolved_plugins,
            conda_env=resolved_conda,
            remote_python=resolved_python,
            local_port=local_port,
            remote_port=remote_port,
            open_browser=open_browser,
            reconnect=reconnect,
            startup_timeout=startup_timeout,
            ssh_options=tuple(ssh_option or []),
        )
        spec.validate()
        if save is not None:
            RemoteProfileCatalog().add(
                save,
                target=target,
                workspace=resolved_workspace,
                conda_env=resolved_conda,
                remote_python=resolved_python,
                plugins=resolved_plugins,
            )
        connect_remote(spec)
    except ResearchAssistantError as exc:
        _abort(exc)


@remote_app.command("list")
def remote_list(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _echo(RemoteProfileCatalog().list(), json_output=json_output)


@remote_app.command("add")
def remote_add(
    name: str,
    target: Annotated[str, typer.Option("--target")],
    workspace: Annotated[str, typer.Option("--workspace", "-w")],
    conda_env: Annotated[str | None, typer.Option("--conda-env")] = None,
    remote_python: Annotated[str | None, typer.Option("--remote-python")] = None,
    plugin: Annotated[list[str] | None, typer.Option("--plugin")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        value = RemoteProfileCatalog().add(
            name,
            target=target,
            workspace=workspace,
            conda_env=conda_env,
            remote_python=remote_python,
            plugins=plugin or [],
        )
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo(value, json_output=json_output)


@remote_app.command("remove")
def remote_remove(name: str) -> None:
    try:
        RemoteProfileCatalog().remove(name)
    except ResearchAssistantError as exc:
        _abort(exc)
    _echo({"removed": name})


def install(app: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    app.command("connect")(connect_command)
    app.add_typer(remote_app, name="remote")
    _INSTALLED = True
