from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from research_assistant.errors import ResearchAssistantError


@dataclass(frozen=True)
class DesktopCommand:
    argv: tuple[str, ...]
    cwd: Path | None
    development: bool


def _candidate_executables(package_root: Path) -> list[Path]:
    names = ["ResearchAssistant", "research-assistant", "researchassistant"]
    candidates: list[Path] = []
    for base in (
        package_root / "desktop" / "application" / "electron-app",
        package_root / "desktop" / "application" / "dist",
        package_root / "desktop" / "dist",
    ):
        candidates.extend(base / name for name in names)
        candidates.extend((base / f"{name}.exe") for name in names)
    return candidates


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
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.update(
        {
            "RA_WORKSPACE": str(Path(workspace).expanduser().resolve()),
            "RA_PYTHON": sys.executable,
            "RA_PLUGINS": json.dumps(list(dict.fromkeys(plugins))),
        }
    )
    return result


def launch_desktop(
    workspace: str | Path,
    *,
    plugins: Sequence[str] = (),
    executable: str | Path | None = None,
    development: bool = False,
) -> int:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ResearchAssistantError(f"workspace directory does not exist: {root}")
    command = resolve_desktop_command(
        root,
        executable=executable,
        development=development,
    )
    completed = subprocess.run(
        command.argv,
        cwd=command.cwd,
        env=desktop_environment(root, plugins=plugins),
        check=False,
    )
    if completed.returncode:
        raise ResearchAssistantError(
            f"ResearchAssistant Desktop exited with status {completed.returncode}"
        )
    return completed.returncode
