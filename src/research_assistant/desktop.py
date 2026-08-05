from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from research_assistant.errors import ResearchAssistantError


@dataclass(frozen=True)
class DesktopCommand:
    argv: tuple[str, ...]
    cwd: Path | None
    development: bool


def _candidate_executables(package_root: Path) -> list[Path]:
    names = ["ResearchAssistant", "research-assistant", "researchassistant"]
    application = package_root / "desktop" / "application"
    candidates: list[Path] = []
    for base in (
        application / "electron-app",
        application / "dist",
        application / "dist" / "linux-unpacked",
        application / "dist" / "win-unpacked",
        application / "dist" / "mac" / "ResearchAssistant.app" / "Contents" / "MacOS",
        application / "dist" / "mac-arm64" / "ResearchAssistant.app" / "Contents" / "MacOS",
        application / "dist" / "mac-x64" / "ResearchAssistant.app" / "Contents" / "MacOS",
        package_root / "desktop" / "dist",
    ):
        candidates.extend(base / name for name in names)
        candidates.extend((base / f"{name}.exe") for name in names)
    return candidates


def normalize_theia_workspace_file(workspace: str | Path) -> Path:
    """Normalize ResearchAssistant virtual roots for Theia's workspace schema.

    Theia 1.73 reads ``folders[].path`` even when the value is a non-file URI.
    Older VS Code-style ``folders[].uri`` entries are therefore silently ignored,
    leaving the Navigator without a root. Only ``ra-remote`` entries are changed.
    """
    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_file() or workspace_path.suffix != ".theia-workspace":
        return workspace_path
    try:
        document = json.loads(workspace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return workspace_path
    if not isinstance(document, dict):
        return workspace_path
    folders = document.get("folders")
    if not isinstance(folders, list):
        return workspace_path

    changed = False
    for folder in folders:
        if not isinstance(folder, dict) or "path" in folder:
            continue
        uri = folder.get("uri")
        if isinstance(uri, str) and uri.startswith("ra-remote://"):
            folder["path"] = uri
            folder.pop("uri", None)
            changed = True
    if not changed:
        return workspace_path

    temporary = workspace_path.with_name(
        f".{workspace_path.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, workspace_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ResearchAssistantError(
            f"cannot normalize remote Theia workspace {workspace_path}: {exc}"
        ) from exc
    return workspace_path


def resolve_desktop_command(
    workspace: str | Path,
    *,
    executable: str | Path | None = None,
    development: bool = False,
    environ: Mapping[str, str] | None = None,
    package_root: str | Path | None = None,
) -> DesktopCommand:
    env = dict(os.environ if environ is None else environ)
    root = Path(package_root or Path(__file__).resolve().parents[2]).resolve()
    selected = executable or env.get("RA_DESKTOP_EXECUTABLE")
    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.exists():
        raise ResearchAssistantError(f"workspace does not exist: {workspace_path}")
    if not workspace_path.is_dir() and workspace_path.suffix != ".theia-workspace":
        raise ResearchAssistantError(
            f"workspace must be a directory or .theia-workspace file: {workspace_path}"
        )

    if selected:
        binary = Path(selected).expanduser().resolve()
        if not binary.is_file():
            raise ResearchAssistantError(f"desktop executable does not exist: {binary}")
        return DesktopCommand((str(binary), str(workspace_path)), None, False)

    if not development:
        for candidate in _candidate_executables(root):
            if candidate.is_file():
                return DesktopCommand((str(candidate), str(workspace_path)), None, False)

    desktop_root = root / "desktop"
    package_json = desktop_root / "package.json"
    npm = shutil.which("npm")
    if package_json.is_file() and npm:
        return DesktopCommand(
            (npm, "--prefix", str(desktop_root), "run", "start", "--", str(workspace_path)),
            root,
            True,
        )

    raise ResearchAssistantError(
        "ResearchAssistant Desktop is not built. Run `npm install --prefix desktop` and "
        "`npm run build --prefix desktop`, or set RA_DESKTOP_EXECUTABLE."
    )


def desktop_environment(
    workspace: str | Path,
    *,
    plugins: Sequence[str] = (),
    environ: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.update(
        {
            "RA_WORKSPACE": str(Path(workspace).expanduser().resolve()),
            "RA_PYTHON": sys.executable,
            "RA_PLUGINS": json.dumps(list(dict.fromkeys(plugins))),
        }
    )
    if extra:
        result.update({str(key): str(value) for key, value in extra.items()})
    return result


def launch_desktop(
    workspace: str | Path,
    *,
    plugins: Sequence[str] = (),
    executable: str | Path | None = None,
    development: bool = False,
    extra_environment: Mapping[str, str] | None = None,
) -> int:
    root = normalize_theia_workspace_file(workspace)
    if not root.exists():
        raise ResearchAssistantError(f"workspace does not exist: {root}")
    if not root.is_dir() and root.suffix != ".theia-workspace":
        raise ResearchAssistantError(
            f"workspace must be a directory or .theia-workspace file: {root}"
        )
    command = resolve_desktop_command(
        root,
        executable=executable,
        development=development,
    )
    completed = subprocess.run(
        command.argv,
        cwd=command.cwd,
        env=desktop_environment(root, plugins=plugins, extra=extra_environment),
        check=False,
    )
    if completed.returncode:
        raise ResearchAssistantError(
            f"ResearchAssistant Desktop exited with status {completed.returncode}"
        )
    return completed.returncode
