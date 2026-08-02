from __future__ import annotations

import json
import os
import random
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from research_assistant import __version__
from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.errors import ResearchAssistantError


class RemoteConnectionError(ResearchAssistantError):
    pass


def _config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


class RemoteProfileCatalog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (
            path or _config_root() / "research-assistant" / "remotes.json"
        ).expanduser().resolve()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "profiles": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RemoteConnectionError(
                f"cannot read remote profile catalog {self.path}: {exc}"
            ) from exc
        if not isinstance(value, dict) or not isinstance(value.get("profiles"), dict):
            raise RemoteConnectionError("invalid remote profile catalog")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, value)

    def list(self) -> list[dict[str, Any]]:
        rows = [dict(value) for value in self._load()["profiles"].values()]
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows

    def get(self, name: str) -> dict[str, Any] | None:
        value = self._load()["profiles"].get(name)
        return dict(value) if isinstance(value, dict) else None

    def add(
        self,
        name: str,
        *,
        target: str,
        workspace: str,
        conda_env: str | None = None,
        remote_python: str | None = None,
        plugins: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        normalized = name.strip()
        if not normalized or len(normalized) > 160:
            raise RemoteConnectionError("profile name must contain 1-160 characters")
        if not target.strip():
            raise RemoteConnectionError("SSH target must not be empty")
        if not workspace.strip():
            raise RemoteConnectionError("remote workspace must not be empty")
        if conda_env and remote_python:
            raise RemoteConnectionError(
                "a remote profile cannot set both conda_env and remote_python"
            )
        catalog = self._load()
        previous = catalog["profiles"].get(normalized, {})
        now = utc_now()
        record = {
            "name": normalized,
            "target": target.strip(),
            "workspace": workspace.strip(),
            "conda_env": conda_env,
            "remote_python": remote_python,
            "plugins": list(dict.fromkeys(str(value) for value in plugins)),
            "created_at": (
                previous.get("created_at", now)
                if isinstance(previous, dict)
                else now
            ),
            "updated_at": now,
        }
        catalog["profiles"][normalized] = record
        self._save(catalog)
        return record

    def remove(self, name: str) -> None:
        catalog = self._load()
        if name not in catalog["profiles"]:
            raise RemoteConnectionError(f"unknown remote profile {name!r}")
        del catalog["profiles"][name]
        self._save(catalog)


@dataclass(frozen=True)
class RemoteConnectSpec:
    target: str
    workspace: str
    plugins: tuple[str, ...] = ()
    conda_env: str | None = None
    remote_python: str | None = None
    local_port: int = 0
    remote_port: int = 0
    open_browser: bool = True
    reconnect: bool = True
    startup_timeout: float = 45.0
    ssh_options: tuple[str, ...] = ()
    reconnect_delays: tuple[float, ...] = field(
        default=(1.0, 2.0, 5.0, 10.0, 20.0),
        repr=False,
    )

    def validate(self) -> None:
        if not self.target.strip():
            raise RemoteConnectionError("SSH target must not be empty")
        if not self.workspace.strip():
            raise RemoteConnectionError("remote workspace must not be empty")
        if self.conda_env and self.remote_python:
            raise RemoteConnectionError("--conda-env and --remote-python are mutually exclusive")
        for name, port in (("local", self.local_port), ("remote", self.remote_port)):
            if port < 0 or port > 65535:
                raise RemoteConnectionError(f"{name} port must be between 0 and 65535")
        if self.startup_timeout <= 0:
            raise RemoteConnectionError("startup timeout must be positive")
        if self.reconnect and not self.reconnect_delays:
            raise RemoteConnectionError("at least one reconnect delay is required")


def find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def choose_remote_port() -> int:
    return random.SystemRandom().randint(20000, 54999)


def _quote_remote_path(value: str) -> str:
    if value == "~":
        return '"$HOME"'
    if value.startswith("~/"):
        return f'"$HOME"/{shlex.quote(value[2:])}'
    return shlex.quote(value)


_REMOTE_SERVER_CODE = (
    "import sys;"
    "import research_assistant.cli_workbench;"
    "import uvicorn;"
    "from research_assistant.ui.server import create_app;"
    "root=sys.argv[1];"
    "port=int(sys.argv[2]);"
    "plugins=sys.argv[3:];"
    "uvicorn.run("
    "create_app(root, plugins, ssh_mode=True),"
    "host='127.0.0.1',"
    "port=port,"
    "log_level='info'"
    ")"
)


def _python_invocation(spec: RemoteConnectSpec, arguments: list[str]) -> str:
    rendered = " ".join(shlex.quote(value) for value in arguments)
    if spec.conda_env:
        candidates = (
            '"$HOME/miniconda3/bin/conda" '
            '"$HOME/anaconda3/bin/conda" '
            '"$HOME/miniforge3/bin/conda" '
            '"$HOME/mambaforge/bin/conda"'
        )
        return (
            'CONDA_EXE="${CONDA_EXE:-$(command -v conda || true)}"; '
            'if [ -z "$CONDA_EXE" ]; then '
            f"for candidate in {candidates}; do "
            'if [ -x "$candidate" ]; then CONDA_EXE="$candidate"; break; fi; '
            "done; fi; "
            'if [ ! -x "$CONDA_EXE" ]; then '
            'echo "ResearchAssistant: conda executable was not found" >&2; exit 127; '
            "fi; "
            f'exec "$CONDA_EXE" run --no-capture-output '
            f"-n {shlex.quote(spec.conda_env)} python {rendered}"
        )
    if spec.remote_python:
        return f"exec {_quote_remote_path(spec.remote_python)} {rendered}"
    return f"exec python3 {rendered}"


def build_remote_ui_command(spec: RemoteConnectSpec, remote_port: int) -> str:
    spec.validate()
    # Resolve the user-supplied path once with `cd`, then pass the current directory
    # to Python. Passing a relative path again after `cd` would resolve it twice.
    arguments = [
        "-c",
        _REMOTE_SERVER_CODE,
        ".",
        str(remote_port),
        *spec.plugins,
    ]
    invocation = _python_invocation(spec, arguments)
    return (
        f"cd {_quote_remote_path(spec.workspace)} || exit $?; "
        "export RA_MANAGED_REMOTE=1; "
        f"{invocation}"
    )


def build_ssh_argv(
    spec: RemoteConnectSpec,
    *,
    local_port: int,
    remote_port: int,
    ssh_executable: str = "ssh",
) -> list[str]:
    command = build_remote_ui_command(spec, remote_port)
    argv = [
        ssh_executable,
        "-T",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-L",
        f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
    ]
    for option in spec.ssh_options:
        argv.extend(["-o", option])
    argv.extend([spec.target, "sh", "-lc", shlex.quote(command)])
    return argv


_EXPECTED_FORWARD_REFUSAL = re.compile(
    r"^channel \d+: open failed: connect failed: Connection refused\s*$"
)


class _RemoteOutput:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.lines: deque[str] = deque(maxlen=80)
        self.thread = threading.Thread(target=self._pump, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def join(self, timeout: float = 1.0) -> None:
        self.thread.join(timeout=timeout)

    def tail(self) -> str:
        return "".join(self.lines).strip()

    def _pump(self) -> None:
        for line in self.stream:
            if _EXPECTED_FORWARD_REFUSAL.fullmatch(line.rstrip("\n")):
                continue
            self.lines.append(line)
            print(f"[remote] {line}", end="", file=sys.stderr, flush=True)


def _read_bootstrap(local_port: int, timeout: float = 1.0) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{local_port}/api/bootstrap",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RemoteConnectionError("remote bootstrap returned an unexpected payload")
    return payload


def _wait_until_ready(
    process: subprocess.Popen[str],
    local_port: int,
    startup_timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + startup_timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RemoteConnectionError(
                f"SSH session exited before the remote UI became ready (exit {return_code})"
            )
        try:
            return _read_bootstrap(local_port)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.25)
    detail = f": {last_error}" if last_error else ""
    raise RemoteConnectionError(
        f"remote UI did not become ready within {startup_timeout:g} seconds{detail}"
    )


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _diagnostic_version(bootstrap: dict[str, Any]) -> str | None:
    diagnostics = bootstrap.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    version = diagnostics.get("research_assistant")
    return str(version) if version is not None else None


def connect_remote(spec: RemoteConnectSpec) -> None:
    spec.validate()
    ssh_executable = shutil.which("ssh")
    if ssh_executable is None:
        raise RemoteConnectionError("OpenSSH client is not installed or not available on PATH")

    local_port = spec.local_port or find_free_local_port()
    local_url = f"http://127.0.0.1:{local_port}"
    ready_once = False
    browser_opened = False
    reconnect_index = 0

    while True:
        remote_port = spec.remote_port or choose_remote_port()
        argv = build_ssh_argv(
            spec,
            local_port=local_port,
            remote_port=remote_port,
            ssh_executable=ssh_executable,
        )
        print(
            f"Connecting {spec.target} · {spec.workspace} "
            f"(local {local_port}, remote {remote_port})"
        )
        process = subprocess.Popen(
            argv,
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        output = _RemoteOutput(process.stdout)
        output.start()

        try:
            bootstrap = _wait_until_ready(process, local_port, spec.startup_timeout)
        except KeyboardInterrupt:
            _terminate(process)
            output.join()
            return
        except RemoteConnectionError as exc:
            _terminate(process)
            output.join()
            tail = output.tail()
            if not ready_once:
                suffix = f"\nRemote output:\n{tail}" if tail else ""
                raise RemoteConnectionError(f"{exc}{suffix}") from exc
            if not spec.reconnect:
                raise
            delay = spec.reconnect_delays[
                min(reconnect_index, len(spec.reconnect_delays) - 1)
            ]
            reconnect_index += 1
            print(f"Connection lost; retrying in {delay:g}s", file=sys.stderr)
            time.sleep(delay)
            continue

        ready_once = True
        reconnect_index = 0
        remote_version = _diagnostic_version(bootstrap)
        if remote_version and remote_version != __version__:
            print(
                "warning: local ResearchAssistant "
                f"{__version__} differs from remote {remote_version}",
                file=sys.stderr,
            )
        connection = bootstrap.get("connection")
        hostname = connection.get("hostname") if isinstance(connection, dict) else None
        label = f" on {hostname}" if hostname else ""
        print(f"Remote workspace ready{label}: {local_url}")
        if spec.open_browser and not browser_opened:
            webbrowser.open_new_tab(local_url)
            browser_opened = True

        try:
            return_code = process.wait()
        except KeyboardInterrupt:
            _terminate(process)
            output.join()
            return
        output.join()

        if not spec.reconnect:
            if return_code != 0:
                tail = output.tail()
                suffix = f"\nRemote output:\n{tail}" if tail else ""
                raise RemoteConnectionError(
                    f"SSH session exited with code {return_code}{suffix}"
                )
            return

        delay = spec.reconnect_delays[
            min(reconnect_index, len(spec.reconnect_delays) - 1)
        ]
        reconnect_index += 1
        print(
            f"SSH session ended with code {return_code}; reconnecting in {delay:g}s",
            file=sys.stderr,
        )
        time.sleep(delay)
