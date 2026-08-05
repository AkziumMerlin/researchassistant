from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_assistant.artifacts import atomic_write_json
from research_assistant.desktop import launch_desktop
from research_assistant.remote_connect import (
    PreparedRemoteDesktop,
    RemoteConnectSpec,
    RemoteDesktopTunnel,
    _cache_root,
    _workspace_id,
)
from research_assistant.remote_connect import (
    prepare_remote_desktop as prepare_generated_remote_desktop,
)

_REMOTE_SCHEME = "ra-remote"
_CORRUPTED_REMOTE_PATH = re.compile(r"(?:^|[/\\])ra-remote:(?:[/\\]|$)")


def _workspace_file(spec: RemoteConnectSpec) -> Path:
    workspace_id = _workspace_id(spec)
    return (
        _cache_root()
        / "research-assistant"
        / "remote-desktop"
        / workspace_id
        / "remote.theia-workspace"
    ).resolve()


def _read_workspace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _folder_resource(folder: dict[str, Any]) -> str | None:
    for key in ("path", "uri"):
        value = folder.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalized_folder(folder: dict[str, Any]) -> dict[str, Any] | None:
    resource = _folder_resource(folder)
    if resource is None:
        return None
    normalized = dict(folder)
    normalized["path"] = resource
    normalized.pop("uri", None)
    name = normalized.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        normalized.pop("name", None)
    return normalized


def _is_remote_folder(folder: dict[str, Any], remote_label: str) -> bool:
    resource = _folder_resource(folder)
    if resource is None:
        return False
    if urlsplit(resource).scheme.lower() == _REMOTE_SCHEME:
        return True
    return (
        folder.get("name") == remote_label
        and _CORRUPTED_REMOTE_PATH.search(resource) is not None
    )


def _deduplicated_folders(folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for folder in folders:
        normalized = _normalized_folder(folder)
        if normalized is None:
            continue
        key = str(normalized["path"])
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _merge_settings(
    previous: object,
    generated: object,
) -> dict[str, Any]:
    result = dict(previous) if isinstance(previous, dict) else {}
    generated_settings = dict(generated) if isinstance(generated, dict) else {}

    profile_key = "terminal.integrated.profiles.linux"
    previous_profiles = result.get(profile_key)
    generated_profiles = generated_settings.get(profile_key)
    profiles = dict(previous_profiles) if isinstance(previous_profiles, dict) else {}
    if isinstance(generated_profiles, dict):
        profiles.update(generated_profiles)
    if profiles:
        result[profile_key] = profiles

    for key, value in generated_settings.items():
        if key != profile_key:
            result[key] = value
    return result


def prepare_remote_desktop(spec: RemoteConnectSpec) -> PreparedRemoteDesktop:
    """Generate an SSH workspace without discarding valid user-added local roots."""
    existing_path = _workspace_file(spec)
    existing = _read_workspace(existing_path)
    remote_label = f"{spec.target}:{spec.workspace}"

    preserved: list[dict[str, Any]] = []
    folders = existing.get("folders")
    if isinstance(folders, list):
        for value in folders:
            if not isinstance(value, dict) or _is_remote_folder(value, remote_label):
                continue
            normalized = _normalized_folder(value)
            if normalized is not None:
                preserved.append(normalized)

    prepared = prepare_generated_remote_desktop(spec)
    generated = _read_workspace(prepared.workspace_file)
    generated_folders = generated.get("folders")
    remote_folders = _deduplicated_folders(
        [dict(value) for value in generated_folders if isinstance(value, dict)]
        if isinstance(generated_folders, list)
        else []
    )

    merged = dict(existing)
    for key, value in generated.items():
        if key not in {"folders", "settings"}:
            merged[key] = value
    merged["folders"] = _deduplicated_folders([*remote_folders, *preserved])
    merged["settings"] = _merge_settings(
        existing.get("settings"),
        generated.get("settings"),
    )
    atomic_write_json(prepared.workspace_file, merged)
    return prepared


def connect_remote(
    spec: RemoteConnectSpec,
    *,
    executable: str | Path | None = None,
    development: bool = False,
) -> None:
    """Open a persistent mixed local/SSH workspace in the local Theia desktop."""
    prepared = prepare_remote_desktop(spec)
    tunnel = RemoteDesktopTunnel(spec, prepared)
    tunnel.start()
    environment = {
        "RA_REMOTE_ENDPOINT": tunnel.endpoint,
        "RA_REMOTE_TOKEN": prepared.token,
        "RA_REMOTE_SPEC": json.dumps(prepared.descriptor, sort_keys=True),
    }
    try:
        launch_desktop(
            prepared.workspace_file,
            plugins=(),
            executable=executable,
            development=development,
            extra_environment=environment,
        )
    finally:
        tunnel.stop()
