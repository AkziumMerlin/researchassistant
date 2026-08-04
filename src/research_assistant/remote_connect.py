from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import selectors
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from research_assistant import __version__
from research_assistant.artifacts import atomic_write_json, utc_now
from research_assistant.desktop import launch_desktop
from research_assistant.errors import ResearchAssistantError


class RemoteConnectionError(ResearchAssistantError):
    pass


def _config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _cache_root() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


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
    reconnect: bool = True
    startup_timeout: float = 45.0
    ssh_options: tuple[str, ...] = ()
    reconnect_delays: tuple[float, ...] = field(
        default=(1.0, 2.0, 5.0, 10.0, 20.0),
        repr=False,
    )
    # Retained for source compatibility with 0.3.x profiles/callers. The Theia
    # implementation never opens a browser.
    open_browser: bool = False

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


def build_remote_ui_command(
    spec: RemoteConnectSpec,
    remote_port: int,
    token: str = "research-assistant-session",
) -> str:
    """Build the remote command that starts only the authenticated Python sidecar."""
    spec.validate()
    arguments = [
        "-m",
        "research_assistant.desktop_server",
        "--root",
        ".",
        "--host",
        "127.0.0.1",
        "--port",
        str(remote_port),
        "--connection-mode",
        "ssh",
    ]
    for plugin in spec.plugins:
        arguments.extend(["--plugin", plugin])
    invocation = _python_invocation(spec, arguments)
    return (
        "IFS= read -r RA_DESKTOP_TOKEN || exit 125; "
        "export RA_DESKTOP_TOKEN; "
        f"cd {_quote_remote_path(spec.workspace)} || exit $?; "
        "export RA_MANAGED_REMOTE=1; "
        f"{invocation}"
    )


def build_ssh_argv(
    spec: RemoteConnectSpec,
    *,
    local_port: int,
    remote_port: int,
    token: str = "research-assistant-session",
    ssh_executable: str = "ssh",
) -> list[str]:
    del token
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
    def __init__(self, stream: TextIO, *, prefix: str = "remote") -> None:
        self.stream = stream
        self.prefix = prefix
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
            print(f"[{self.prefix}] {line}", end="", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class PreparedRemoteDesktop:
    workspace_id: str
    cache_dir: Path
    workspace_file: Path
    terminal_wrapper: Path
    local_port: int
    token: str
    descriptor: dict[str, Any]


def _workspace_id(spec: RemoteConnectSpec) -> str:
    payload = json.dumps(
        {
            "target": spec.target,
            "workspace": spec.workspace,
            "conda_env": spec.conda_env,
            "remote_python": spec.remote_python,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _remote_shell_invocation(spec: RemoteConnectSpec) -> str:
    if spec.conda_env:
        return (
            'CONDA_EXE="${CONDA_EXE:-$(command -v conda || true)}"; '
            'if [ -z "$CONDA_EXE" ]; then '
            'for candidate in "$HOME/miniconda3/bin/conda" '
            '"$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda" '
            '"$HOME/mambaforge/bin/conda"; do '
            'if [ -x "$candidate" ]; then CONDA_EXE="$candidate"; break; fi; done; fi; '
            'if [ ! -x "$CONDA_EXE" ]; then echo "conda not found" >&2; exit 127; fi; '
            f'SHELL_COMMAND=$(printf "%s " "$CONDA_EXE" run --no-capture-output '
            f'-n {shlex.quote(spec.conda_env)} bash --noprofile --norc -i); '
            'if command -v tmux >/dev/null 2>&1; then '
            'exec tmux -L "$2" new-session -A -s "$1" -c . "$SHELL_COMMAND"; fi; '
            'exec "$CONDA_EXE" run --no-capture-output '
            f'-n {shlex.quote(spec.conda_env)} bash --noprofile --norc -i'
        )
    if spec.remote_python:
        python = _quote_remote_path(spec.remote_python)
        return (
            f'PYTHON={python}; '
            'BIN_DIR=$(dirname "$PYTHON"); export PATH="$BIN_DIR:$PATH"; '
            'if command -v tmux >/dev/null 2>&1; then '
            'exec tmux -L "$2" new-session -A -s "$1" -c . '
            '"exec bash --noprofile --norc -i"; fi; '
            'exec bash --noprofile --norc -i'
        )
    return (
        'if command -v tmux >/dev/null 2>&1; then '
        'exec tmux -L "$2" new-session -A -s "$1" -c .; fi; '
        'exec "${SHELL:-bash}" -i'
    )


def _write_terminal_wrapper(path: Path, spec: RemoteConnectSpec, workspace_id: str) -> None:
    ssh = shutil.which("ssh") or "ssh"
    remote_body = (
        f"cd {_quote_remote_path(spec.workspace)} || exit $?; "
        f"{_remote_shell_invocation(spec)}"
    )
    ssh_arguments = [
        ssh,
        "-tt",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]
    for option in spec.ssh_options:
        ssh_arguments.extend(["-o", option])
    ssh_arguments.extend(
        [spec.target, "sh", "-lc", shlex.quote(remote_body), "sh", '"$session"', workspace_id]
    )
    command = " ".join(
        value if value in {'"$session"'} else shlex.quote(value) for value in ssh_arguments
    )
    script = f"""#!/bin/sh
set -u
unset RA_REMOTE_TOKEN RA_REMOTE_ENDPOINT RA_REMOTE_SPEC
session="ra-{workspace_id}-$$"
delay=1
while :; do
    {command}
    status=$?
    if [ "$status" -eq 0 ]; then
        exit 0
    fi
    printf 'Remote terminal disconnected; reconnecting in %ss...\\n' "$delay" >&2
    sleep "$delay"
    if [ "$delay" -lt 10 ]; then delay=$((delay * 2)); fi
done
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)


def prepare_remote_desktop(spec: RemoteConnectSpec) -> PreparedRemoteDesktop:
    spec.validate()
    workspace_id = _workspace_id(spec)
    cache_dir = (_cache_root() / "research-assistant" / "remote-desktop" / workspace_id).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_port = spec.local_port or find_free_local_port()
    token = secrets.token_urlsafe(32)
    terminal_wrapper = cache_dir / "remote-terminal.sh"
    _write_terminal_wrapper(terminal_wrapper, spec, workspace_id)

    descriptor = {
        "version": 1,
        "mode": "ssh",
        "workspaceId": workspace_id,
        "target": spec.target,
        "workspace": spec.workspace,
        "condaEnv": spec.conda_env,
        "remotePython": spec.remote_python,
        "plugins": list(spec.plugins),
        "localPort": local_port,
        "reconnect": spec.reconnect,
        "sshOptions": list(spec.ssh_options),
    }
    workspace_file = cache_dir / "remote.theia-workspace"
    atomic_write_json(
        workspace_file,
        {
            "folders": [
                {
                    "name": f"{spec.target}:{spec.workspace}",
                    "uri": f"ra-remote://{workspace_id}/",
                }
            ],
            "settings": {
                "terminal.integrated.profiles.linux": {
                    "ResearchAssistant SSH": {
                        "path": str(terminal_wrapper),
                        "args": [],
                    }
                },
                "terminal.integrated.defaultProfile.linux": "ResearchAssistant SSH",
            },
        },
    )
    atomic_write_json(cache_dir / "connection.json", descriptor)
    return PreparedRemoteDesktop(
        workspace_id=workspace_id,
        cache_dir=cache_dir,
        workspace_file=workspace_file,
        terminal_wrapper=terminal_wrapper,
        local_port=local_port,
        token=token,
        descriptor=descriptor,
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


def _wait_for_handshake(
    process: subprocess.Popen[str],
    *,
    token: str,
    timeout: float,
) -> dict[str, Any]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise RemoteConnectionError(
                    "SSH session exited before the remote sidecar became ready "
                    f"(exit {return_code})"
                )
            events = selector.select(timeout=min(0.25, max(0.0, deadline - time.monotonic())))
            if not events:
                continue
            line = process.stdout.readline()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                print(f"[remote] {line}", end="", file=sys.stderr, flush=True)
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("protocol") != "research-assistant/desktop-sidecar":
                continue
            if payload.get("version") != 1:
                raise RemoteConnectionError("unsupported remote desktop-sidecar protocol")
            if payload.get("token") != token:
                raise RemoteConnectionError("remote sidecar returned an invalid session token")
            return payload
    finally:
        selector.close()
    raise RemoteConnectionError(
        f"remote sidecar did not become ready within {timeout:g} seconds"
    )


def _read_health(local_port: int, token: str, timeout: float = 2.0) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{local_port}/api/desktop/health",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RemoteConnectionError("remote desktop health returned an unexpected payload")
    return payload


class RemoteDesktopTunnel:
    """Maintain one fixed local endpoint while reconnecting the SSH transport."""

    def __init__(self, spec: RemoteConnectSpec, prepared: PreparedRemoteDesktop) -> None:
        self.spec = spec
        self.prepared = prepared
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._error: Exception | None = None
        self.handshake: dict[str, Any] | None = None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.prepared.local_port}"

    def start(self) -> None:
        if shutil.which("ssh") is None:
            raise RemoteConnectionError("OpenSSH client is not installed or not available on PATH")
        self._thread.start()
        if not self._ready.wait(timeout=self.spec.startup_timeout + 2):
            self.stop()
            if self._error:
                raise RemoteConnectionError(str(self._error)) from self._error
            raise RemoteConnectionError("timed out starting the remote desktop connection")
        if self._error:
            self.stop()
            raise RemoteConnectionError(str(self._error)) from self._error

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            process = self._process
        if process is not None:
            _terminate(process)
        if self._thread.is_alive():
            self._thread.join(timeout=7)

    def _run(self) -> None:
        reconnect_index = 0
        connected_once = False
        while not self._stop.is_set():
            remote_port = self.spec.remote_port or choose_remote_port()
            argv = build_ssh_argv(
                self.spec,
                local_port=self.prepared.local_port,
                remote_port=remote_port,
                token=self.prepared.token,
                ssh_executable=shutil.which("ssh") or "ssh",
            )
            print(
                f"Connecting {self.spec.target} · {self.spec.workspace} "
                f"(local {self.prepared.local_port}, remote {remote_port})"
            )
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._process = process
            assert process.stdin is not None
            process.stdin.write(f"{self.prepared.token}\n")
            process.stdin.flush()
            process.stdin.close()
            assert process.stderr is not None
            stderr = _RemoteOutput(process.stderr)
            stderr.start()
            try:
                handshake = _wait_for_handshake(
                    process,
                    token=self.prepared.token,
                    timeout=self.spec.startup_timeout,
                )
                deadline = time.monotonic() + 5
                last_error: Exception | None = None
                while time.monotonic() < deadline:
                    try:
                        _read_health(self.prepared.local_port, self.prepared.token)
                        last_error = None
                        break
                    except (OSError, ValueError, urllib.error.URLError) as exc:
                        last_error = exc
                        time.sleep(0.1)
                if last_error is not None:
                    raise RemoteConnectionError(
                        f"remote sidecar tunnel is not healthy: {last_error}"
                    )
                self.handshake = handshake
                connected_once = True
                reconnect_index = 0
                self._ready.set()
                remote_version = handshake.get("product_version")
                if remote_version and remote_version != __version__:
                    print(
                        f"warning: local ResearchAssistant {__version__} differs from "
                        f"remote {remote_version}",
                        file=sys.stderr,
                    )
                print(f"Remote desktop backend ready: {self.endpoint}")
                return_code = process.wait()
                if self._stop.is_set():
                    break
                if not self.spec.reconnect:
                    raise RemoteConnectionError(
                        f"SSH session exited with code {return_code}: {stderr.tail()}"
                    )
                delay = self.spec.reconnect_delays[
                    min(reconnect_index, len(self.spec.reconnect_delays) - 1)
                ]
                reconnect_index += 1
                print(
                    f"SSH session ended with code {return_code}; reconnecting in {delay:g}s",
                    file=sys.stderr,
                )
                self._stop.wait(delay)
            except Exception as exc:
                _terminate(process)
                if not connected_once:
                    self._error = exc
                    self._ready.set()
                    break
                if not self.spec.reconnect or self._stop.is_set():
                    self._error = exc
                    break
                delay = self.spec.reconnect_delays[
                    min(reconnect_index, len(self.spec.reconnect_delays) - 1)
                ]
                reconnect_index += 1
                print(f"Remote connection failed; retrying in {delay:g}s: {exc}", file=sys.stderr)
                self._stop.wait(delay)
            finally:
                stderr.join()
                with self._lock:
                    if self._process is process:
                        self._process = None


def connect_remote(
    spec: RemoteConnectSpec,
    *,
    executable: str | Path | None = None,
    development: bool = False,
) -> None:
    """Open a local Theia/Electron window backed by a remote Python sidecar."""
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
