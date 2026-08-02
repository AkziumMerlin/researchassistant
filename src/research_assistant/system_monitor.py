from __future__ import annotations

import csv
import json
import math
import os
import pwd
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from research_assistant.errors import ResearchAssistantError

ProcessSort = Literal["cpu", "memory", "gpu", "pid", "runtime"]
ProcessScope = Literal["all", "user", "gpu", "ra"]
_ALLOWED_SIGNALS = {
    "INT": signal.SIGINT,
    "TERM": signal.SIGTERM,
    "KILL": signal.SIGKILL,
    "HUP": signal.SIGHUP,
    "STOP": signal.SIGSTOP,
    "CONT": signal.SIGCONT,
}


class SystemMonitorError(ResearchAssistantError):
    pass


def _optional_float(value: str) -> float | None:
    normalized = value.strip()
    if not normalized or normalized.lower() in {"n/a", "[n/a]", "not supported"}:
        return None
    try:
        result = float(normalized)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _tail_text(path: Path, limit: int = 256 * 1024) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            payload = stream.read(limit)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"[cannot read {path.name}: {exc}]"
    text = payload.decode("utf-8", errors="replace")
    return ("[… earlier output omitted …]\n" if size > limit else "") + text


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _parse_key_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key] = value.strip()
    return result


def _parse_proc_stat(line: str) -> dict[str, Any]:
    left = line.find("(")
    right = line.rfind(")")
    if left <= 0 or right <= left:
        raise ValueError("invalid /proc stat line")
    pid = int(line[:left].strip())
    name = line[left + 1 : right]
    values = line[right + 1 :].strip().split()
    if len(values) < 22:
        raise ValueError("short /proc stat line")
    return {
        "pid": pid,
        "name": name,
        "state": values[0],
        "ppid": int(values[1]),
        "utime_ticks": int(values[11]),
        "stime_ticks": int(values[12]),
        "priority": int(values[15]),
        "nice": int(values[16]),
        "threads": int(values[17]),
        "start_ticks": int(values[19]),
        "virtual_bytes": int(values[20]),
        "rss_pages": int(values[21]),
    }


def _cpu_counters(proc_root: Path) -> dict[str, tuple[int, int]]:
    lines = (proc_root / "stat").read_text(encoding="utf-8").splitlines()
    counters: dict[str, tuple[int, int]] = {}
    for line in lines:
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        try:
            values = [int(value) for value in parts[1:9]]
        except ValueError:
            continue
        if len(values) < 4:
            continue
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        counters[parts[0]] = (total, idle)
    return counters


def _cpu_percent(
    current: tuple[int, int],
    previous: tuple[int, int] | None,
) -> float:
    if previous is None:
        return 0.0
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def _memory_snapshot(proc_root: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in (proc_root / "meminfo").read_text(encoding="utf-8").splitlines():
        key, separator, raw = line.partition(":")
        if not separator:
            continue
        parts = raw.strip().split()
        try:
            amount = float(parts[0])
        except (IndexError, ValueError):
            continue
        unit = parts[1].lower() if len(parts) > 1 else ""
        values[key] = amount * (1024.0 if unit == "kb" else 1.0)
    total = values.get("MemTotal", 0.0)
    available = values.get("MemAvailable", values.get("MemFree", 0.0))
    used = max(0.0, total - available)
    swap_total = values.get("SwapTotal", 0.0)
    swap_free = values.get("SwapFree", 0.0)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent": 100.0 * used / total if total else 0.0,
        "cached_bytes": values.get("Cached", 0.0) + values.get("SReclaimable", 0.0),
        "buffers_bytes": values.get("Buffers", 0.0),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0.0, swap_total - swap_free),
        "swap_percent": 100.0 * (swap_total - swap_free) / swap_total if swap_total else 0.0,
    }


def _uptime_seconds(proc_root: Path) -> float:
    try:
        return float((proc_root / "uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def _cpu_model(proc_root: Path) -> str | None:
    try:
        payload = (proc_root / "cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in payload.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"model name", "Hardware", "Processor"}:
            return value.strip()
    return None


def _network_totals(proc_root: Path) -> tuple[int, int]:
    received = 0
    transmitted = 0
    try:
        lines = (proc_root / "net" / "dev").read_text(encoding="utf-8").splitlines()[2:]
    except OSError:
        return 0, 0
    for line in lines:
        interface, separator, values = line.partition(":")
        if not separator or interface.strip() == "lo":
            continue
        fields = values.split()
        try:
            received += int(fields[0])
            transmitted += int(fields[8])
        except (IndexError, ValueError):
            continue
    return received, transmitted


class GpuProbe(Protocol):
    def snapshot(self) -> dict[str, Any]: ...


class NvidiaSystemProbe:
    def __init__(self, executable: str = "nvidia-smi", timeout_seconds: float = 5.0) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def _run(self, *arguments: str) -> tuple[str, str | None]:
        try:
            completed = subprocess.run(
                [self.executable, *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            return "", "nvidia-smi was not found"
        except subprocess.TimeoutExpired:
            return "", "nvidia-smi query timed out"
        if completed.returncode != 0:
            error = completed.stderr.strip() or (
                f"nvidia-smi exited with code {completed.returncode}"
            )
            return "", error
        return completed.stdout, None

    def snapshot(self) -> dict[str, Any]:
        output, error = self._run(
            "--query-gpu=index,uuid,name,pci.bus_id,memory.total,memory.used,memory.free,"
            "utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit",
            "--format=csv,noheader,nounits",
        )
        if error is not None:
            return {"available": False, "error": error, "devices": [], "processes": {}}

        devices: list[dict[str, Any]] = []
        index_by_uuid: dict[str, int] = {}
        for row in csv.reader(output.splitlines(), skipinitialspace=True):
            if len(row) < 12:
                continue
            try:
                index = int(row[0].strip())
                total = float(row[4])
                used = float(row[5])
                free = float(row[6])
            except ValueError:
                continue
            uuid = row[1].strip()
            index_by_uuid[uuid] = index
            utilization = _optional_float(row[7]) or 0.0
            memory_utilization = _optional_float(row[8])
            power = _optional_float(row[10])
            power_limit = _optional_float(row[11])
            devices.append(
                {
                    "index": index,
                    "uuid": uuid,
                    "name": row[2].strip(),
                    "pci_bus_id": row[3].strip(),
                    "memory_total_mb": total,
                    "memory_used_mb": used,
                    "memory_free_mb": free,
                    "memory_percent": 100.0 * used / total if total else 0.0,
                    "utilization_percent": utilization,
                    "memory_utilization_percent": memory_utilization,
                    "temperature_c": _optional_float(row[9]),
                    "power_watts": power,
                    "power_limit_watts": power_limit,
                    "power_percent": (
                        100.0 * power / power_limit
                        if power is not None and power_limit not in {None, 0.0}
                        else None
                    ),
                    "process_count": 0,
                }
            )

        process_output, process_error = self._run(
            "--query-compute-apps=pid,process_name,gpu_uuid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        )
        processes: dict[int, list[dict[str, Any]]] = {}
        if process_error is not None:
            process_output, process_error = self._run(
                "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            )
            with_names = False
        else:
            with_names = True
        if process_error is None:
            for row in csv.reader(process_output.splitlines(), skipinitialspace=True):
                expected = 4 if with_names else 3
                if len(row) < expected:
                    continue
                try:
                    pid = int(row[0].strip())
                except ValueError:
                    continue
                name = row[1].strip() if with_names else ""
                uuid = row[2].strip() if with_names else row[1].strip()
                memory_raw = row[3] if with_names else row[2]
                memory = _optional_float(memory_raw) or 0.0
                processes.setdefault(pid, []).append(
                    {
                        "gpu_uuid": uuid,
                        "gpu_index": index_by_uuid.get(uuid),
                        "memory_mb": memory,
                        "process_name": name,
                    }
                )

        counts: dict[str, int] = {}
        for entries in processes.values():
            for entry in entries:
                uuid = str(entry["gpu_uuid"])
                counts[uuid] = counts.get(uuid, 0) + 1
        for device in devices:
            device["process_count"] = counts.get(str(device["uuid"]), 0)
        return {
            "available": bool(devices),
            "error": None if devices else "no NVIDIA GPUs were reported",
            "devices": sorted(devices, key=lambda item: item["index"]),
            "processes": processes,
        }


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start_ticks: int


class RunProcessIndex:
    def __init__(self, workspace: Path, *, cache_seconds: float = 3.0) -> None:
        self.workspace = workspace.resolve()
        self.cache_seconds = cache_seconds
        self._updated = 0.0
        self._records: dict[int, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _run_record(self, run_dir: Path) -> tuple[int, dict[str, Any]] | None:
        launcher = _read_json(run_dir / "launcher.json")
        worker_pid = launcher.get("worker_pid")
        try:
            pid = int(worker_pid)
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        status = _read_json(run_dir / "status.json")
        manifest = _read_json(run_dir / "manifest.json")
        stages = status.get("stages") if isinstance(status.get("stages"), dict) else {}
        active_stage = next(
            (
                str(name)
                for name, value in stages.items()
                if isinstance(value, dict) and value.get("state") == "running"
            ),
            None,
        )
        gpu = launcher.get("gpu") if isinstance(launcher.get("gpu"), dict) else None
        return pid, {
            "managed": True,
            "role": "worker",
            "run_id": str(status.get("run_id", manifest.get("run_id", run_dir.name))),
            "study_id": str(manifest.get("study_id", run_dir.parent.name)),
            "trial_id": manifest.get("trial_id"),
            "stage": active_stage,
            "state": str(status.get("state", "unknown")),
            "attempt": status.get("attempt"),
            "gpu": gpu,
            "run_dir": _safe_relative(run_dir, self.workspace),
            "worker_log": _safe_relative(run_dir / "worker.log", self.workspace),
            "resource_log": _safe_relative(run_dir / "resource-events.jsonl", self.workspace),
        }

    def _refresh(self) -> dict[int, dict[str, Any]]:
        records: dict[int, dict[str, Any]] = {}
        seen_run_dirs: set[Path] = set()
        launch_root = self.workspace / ".ra" / "ui-launches"
        if launch_root.is_dir():
            for launch_dir in sorted(launch_root.iterdir()):
                if not launch_dir.is_dir():
                    continue
                request = _read_json(launch_dir / "request.json")
                process = _read_json(launch_dir / "process.json")
                try:
                    scheduler_pid = int(process.get("scheduler_pid"))
                except (TypeError, ValueError):
                    scheduler_pid = 0
                if scheduler_pid > 0:
                    records[scheduler_pid] = {
                        "managed": True,
                        "role": "scheduler",
                        "launch_id": str(request.get("launch_id", launch_dir.name)),
                        "state": str(_read_json(launch_dir / "state.json").get("state", "unknown")),
                        "scheduler_log": _safe_relative(
                            launch_dir / "scheduler.log", self.workspace
                        ),
                    }
                artifact_root = Path(str(request.get("artifact_root", "")))
                plan = request.get("plan") if isinstance(request.get("plan"), dict) else {}
                study_id = str(plan.get("study_id", ""))
                for run_id in plan.get("run_ids", []):
                    run_dir = artifact_root / study_id / str(run_id)
                    seen_run_dirs.add(run_dir.resolve())
                    row = self._run_record(run_dir)
                    if row is not None:
                        records[row[0]] = row[1]

        scanned = 0
        for launcher_path in self.workspace.glob("*/*/*/launcher.json"):
            if scanned >= 5000:
                break
            run_dir = launcher_path.parent.resolve()
            if run_dir in seen_run_dirs:
                continue
            scanned += 1
            row = self._run_record(run_dir)
            if row is not None:
                records[row[0]] = row[1]
        return records

    def records(self, *, force: bool = False) -> dict[int, dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            if force or now - self._updated >= self.cache_seconds:
                self._records = self._refresh()
                self._updated = now
            return {pid: dict(value) for pid, value in self._records.items()}


class SystemMonitor:
    def __init__(
        self,
        workspace: str | Path,
        *,
        proc_root: str | Path = "/proc",
        gpu_probe: GpuProbe | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.proc_root = Path(proc_root)
        self.gpu_probe = gpu_probe or NvidiaSystemProbe()
        self.run_index = RunProcessIndex(self.workspace)
        self.clock_ticks = int(os.sysconf("SC_CLK_TCK"))
        self.page_size = int(os.sysconf("SC_PAGE_SIZE"))
        self.cpu_count = max(1, os.cpu_count() or 1)
        self._cpu_previous = _cpu_counters(self.proc_root)
        self._process_previous: dict[ProcessIdentity, int] = {}
        self._network_previous = (*_network_totals(self.proc_root), time.monotonic())
        self._lock = threading.RLock()

    def _read_processes(
        self,
        *,
        total_memory: float,
        total_delta: int,
        gpu_processes: dict[int, list[dict[str, Any]]],
        ra_records: dict[int, dict[str, Any]],
        uptime: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        current_ticks: dict[ProcessIdentity, int] = {}
        user_uid = os.getuid()
        for entry in self.proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = _parse_proc_stat((entry / "stat").read_text(encoding="utf-8"))
                status = _parse_key_values((entry / "status").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pid = int(stat["pid"])
            uid_values = status.get("Uid", "").split()
            try:
                uid = int(uid_values[0])
            except (IndexError, ValueError):
                uid = -1
            try:
                username = pwd.getpwuid(uid).pw_name
            except KeyError:
                username = str(uid)
            try:
                command_raw = (entry / "cmdline").read_bytes()
            except OSError:
                command_raw = b""
            command = " ".join(
                part.decode("utf-8", errors="replace")
                for part in command_raw.split(b"\0")
                if part
            )
            if not command:
                command = f"[{stat['name']}]"
            identity = ProcessIdentity(pid=pid, start_ticks=int(stat["start_ticks"]))
            ticks = int(stat["utime_ticks"]) + int(stat["stime_ticks"])
            current_ticks[identity] = ticks
            previous_ticks = self._process_previous.get(identity)
            cpu_percent = 0.0
            if previous_ticks is not None and total_delta > 0:
                cpu_percent = max(
                    0.0,
                    100.0 * self.cpu_count * (ticks - previous_ticks) / total_delta,
                )
            rss_bytes = max(0, int(stat["rss_pages"])) * self.page_size
            gpu_entries = gpu_processes.get(pid, [])
            gpu_memory = sum(float(item.get("memory_mb", 0.0)) for item in gpu_entries)
            rows.append(
                {
                    "pid": pid,
                    "ppid": int(stat["ppid"]),
                    "uid": uid,
                    "user": username,
                    "same_user": uid == user_uid,
                    "signalable": uid == user_uid and pid not in {1, os.getpid()},
                    "name": str(stat["name"]),
                    "command": command,
                    "state": str(stat["state"]),
                    "cpu_percent": cpu_percent,
                    "memory_rss_bytes": rss_bytes,
                    "memory_percent": 100.0 * rss_bytes / total_memory if total_memory else 0.0,
                    "virtual_memory_bytes": max(0, int(stat["virtual_bytes"])),
                    "threads": int(stat["threads"]),
                    "nice": int(stat["nice"]),
                    "priority": int(stat["priority"]),
                    "runtime_seconds": max(
                        0.0,
                        uptime - int(stat["start_ticks"]) / self.clock_ticks,
                    ),
                    "gpu_memory_mb": gpu_memory,
                    "gpus": gpu_entries,
                    "ra": dict(ra_records.get(pid, {})) or None,
                }
            )
        self._process_previous = current_ticks

        by_pid = {int(row["pid"]): row for row in rows}
        for row in rows:
            if row["ra"] is not None:
                continue
            parent_pid = int(row["ppid"])
            visited: set[int] = set()
            for _ in range(24):
                if parent_pid <= 0 or parent_pid in visited:
                    break
                visited.add(parent_pid)
                parent = by_pid.get(parent_pid)
                if parent is None:
                    break
                if parent["ra"] is not None:
                    inherited = dict(parent["ra"])
                    inherited["parent_role"] = inherited.get("role")
                    inherited["role"] = "child"
                    row["ra"] = inherited
                    break
                parent_pid = int(parent["ppid"])
        return rows

    def _filter_processes(
        self,
        rows: list[dict[str, Any]],
        *,
        scope: ProcessScope,
        search: str | None,
        sort: ProcessSort,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        user_uid = os.getuid()
        filtered = rows
        if scope == "user":
            filtered = [row for row in filtered if row["uid"] == user_uid]
        elif scope == "gpu":
            filtered = [row for row in filtered if row["gpu_memory_mb"] > 0]
        elif scope == "ra":
            filtered = [row for row in filtered if row["ra"] is not None]
        if search:
            needle = search.casefold()
            filtered = [
                row
                for row in filtered
                if needle in str(row["pid"])
                or needle in str(row["user"]).casefold()
                or needle in str(row["command"]).casefold()
                or needle in json.dumps(row.get("ra"), sort_keys=True).casefold()
            ]
        keys = {
            "cpu": lambda row: (float(row["cpu_percent"]), float(row["memory_rss_bytes"])),
            "memory": lambda row: (float(row["memory_rss_bytes"]), float(row["cpu_percent"])),
            "gpu": lambda row: (float(row["gpu_memory_mb"]), float(row["cpu_percent"])),
            "runtime": lambda row: (float(row["runtime_seconds"]), int(row["pid"])),
            "pid": lambda row: (int(row["pid"]), 0),
        }
        reverse = sort != "pid"
        filtered = sorted(filtered, key=keys[sort], reverse=reverse)
        return filtered[:limit], len(filtered)

    def snapshot(
        self,
        *,
        process_limit: int = 300,
        process_sort: ProcessSort = "cpu",
        process_scope: ProcessScope = "all",
        search: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= process_limit <= 2000:
            raise SystemMonitorError("process limit must be between 1 and 2000")
        with self._lock:
            started = time.monotonic()
            current_cpu = _cpu_counters(self.proc_root)
            previous_cpu = self._cpu_previous
            aggregate = current_cpu.get("cpu", (0, 0))
            previous_aggregate = previous_cpu.get("cpu")
            total_delta = aggregate[0] - previous_aggregate[0] if previous_aggregate else 0
            cpu_percent = _cpu_percent(aggregate, previous_aggregate)
            per_core = [
                _cpu_percent(current_cpu[name], previous_cpu.get(name))
                for name in sorted(
                    (name for name in current_cpu if name != "cpu"),
                    key=lambda value: int(value[3:]),
                )
            ]
            self._cpu_previous = current_cpu

            memory = _memory_snapshot(self.proc_root)
            uptime = _uptime_seconds(self.proc_root)
            try:
                load = os.getloadavg()
            except OSError:
                load = (0.0, 0.0, 0.0)
            disk = shutil.disk_usage(self.workspace)
            now = time.monotonic()
            network_rx, network_tx = _network_totals(self.proc_root)
            previous_rx, previous_tx, previous_at = self._network_previous
            network_delta = max(1e-9, now - previous_at)
            self._network_previous = (network_rx, network_tx, now)

            gpu = self.gpu_probe.snapshot()
            raw_gpu_processes = gpu.get("processes")
            gpu_processes = raw_gpu_processes if isinstance(raw_gpu_processes, dict) else {}
            normalized_gpu_processes = {
                int(pid): entries
                for pid, entries in gpu_processes.items()
                if str(pid).isdigit() and isinstance(entries, list)
            }
            ra_records = self.run_index.records()
            rows = self._read_processes(
                total_memory=float(memory["total_bytes"]),
                total_delta=total_delta,
                gpu_processes=normalized_gpu_processes,
                ra_records=ra_records,
                uptime=uptime,
            )
            selected, process_total = self._filter_processes(
                rows,
                scope=process_scope,
                search=search,
                sort=process_sort,
                limit=process_limit,
            )
            timestamp = datetime.now(UTC).isoformat()
            return {
                "schema_version": 1,
                "timestamp": timestamp,
                "sample_duration_seconds": max(0.0, time.monotonic() - started),
                "workspace": str(self.workspace),
                "host": {
                    "hostname": socket.gethostname(),
                    "cpu_model": _cpu_model(self.proc_root),
                    "cpu_count": self.cpu_count,
                    "cpu_percent": cpu_percent,
                    "per_core_percent": per_core,
                    "load_1": load[0],
                    "load_5": load[1],
                    "load_15": load[2],
                    "uptime_seconds": uptime,
                    "boot_time_epoch": time.time() - uptime if uptime else None,
                    "memory": memory,
                    "disk": {
                        "path": str(self.workspace),
                        "total_bytes": disk.total,
                        "used_bytes": disk.used,
                        "free_bytes": disk.free,
                        "percent": 100.0 * disk.used / disk.total if disk.total else 0.0,
                    },
                    "network": {
                        "received_bytes": network_rx,
                        "transmitted_bytes": network_tx,
                        "receive_bytes_per_second": max(
                            0.0, (network_rx - previous_rx) / network_delta
                        ),
                        "transmit_bytes_per_second": max(
                            0.0, (network_tx - previous_tx) / network_delta
                        ),
                    },
                    "process_count": len(rows),
                    "user_process_count": sum(1 for row in rows if row["same_user"]),
                },
                "gpus": {
                    "available": bool(gpu.get("available")),
                    "error": gpu.get("error"),
                    "devices": gpu.get("devices", []),
                },
                "processes": selected,
                "process_total": process_total,
                "process_truncated": process_total > len(selected),
                "process_scope": process_scope,
                "process_sort": process_sort,
                "search": search or "",
            }

    def process_context(self, pid: int) -> dict[str, Any]:
        if pid <= 0:
            raise SystemMonitorError("invalid process identifier")
        snapshot = self.snapshot(process_limit=2000, process_sort="pid")
        process = next((row for row in snapshot["processes"] if row["pid"] == pid), None)
        if process is None:
            raise SystemMonitorError(f"process {pid} is no longer running")
        ra = process.get("ra") if isinstance(process.get("ra"), dict) else {}
        logs: list[dict[str, str]] = []
        for key, label in (
            ("worker_log", "Worker log"),
            ("scheduler_log", "Scheduler log"),
            ("resource_log", "Resource events"),
        ):
            raw = ra.get(key)
            if not isinstance(raw, str) or not raw:
                continue
            candidate = Path(raw)
            path = candidate if candidate.is_absolute() else self.workspace / candidate
            resolved = path.resolve(strict=False)
            if not resolved.is_relative_to(self.workspace):
                continue
            logs.append(
                {
                    "kind": key,
                    "label": label,
                    "path": _safe_relative(resolved, self.workspace),
                    "tail": _tail_text(resolved),
                }
            )
        return {"process": process, "logs": logs}

    def send_signal(self, pid: int, signal_name: str) -> dict[str, Any]:
        if pid <= 1 or pid == os.getpid():
            raise SystemMonitorError("this process cannot be signalled from the monitor")
        normalized = signal_name.upper().removeprefix("SIG")
        selected = _ALLOWED_SIGNALS.get(normalized)
        if selected is None:
            raise SystemMonitorError(
                f"unsupported signal {signal_name!r}; choose one of {sorted(_ALLOWED_SIGNALS)}"
            )
        try:
            status = _parse_key_values(
                (self.proc_root / str(pid) / "status").read_text(encoding="utf-8")
            )
            uid = int(status.get("Uid", "").split()[0])
        except (OSError, ValueError, IndexError) as exc:
            raise SystemMonitorError(f"process {pid} is no longer available") from exc
        if uid != os.getuid():
            raise SystemMonitorError("only processes owned by the current user can be signalled")
        try:
            os.kill(pid, selected)
        except ProcessLookupError as exc:
            raise SystemMonitorError(f"process {pid} is no longer running") from exc
        except PermissionError as exc:
            raise SystemMonitorError(f"permission denied while signalling process {pid}") from exc
        return {
            "pid": pid,
            "signal": normalized,
            "sent_at": datetime.now(UTC).isoformat(),
        }
