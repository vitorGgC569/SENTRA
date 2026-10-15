"""Deterministic resource catalog for SENTRA scheduling.

This registry is descriptive/admission-oriented only. It does not own leases,
fencing or task/run transitions; those remain Control Plane/Durable Core duties.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import importlib.util
import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Any, Iterable


_READY_STATES = {"READY", "ONLINE", "IDLE"}


@dataclass
class ResourceDescriptor:
    resource_id: str
    resource_type: str
    state: str
    capacity: int = 1
    capabilities: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, resource_type: str, data: dict[str, Any]) -> "ResourceDescriptor":
        resource_id = str(data.get("resource_id") or "").strip()
        if not resource_id:
            raise ValueError("resource_id is required")
        state = str(data.get("state") or "OFFLINE").strip().upper()
        capacity = int(data.get("capacity") or 1)
        if capacity < 1:
            raise ValueError("resource capacity must be positive")
        capabilities = data.get("capabilities") or {}
        labels = data.get("labels") or {}
        if not isinstance(capabilities, dict) or not isinstance(labels, dict):
            raise ValueError("resource capabilities/labels must be objects")
        known = {"resource_id", "state", "capacity", "capabilities", "labels"}
        return cls(
            resource_id=resource_id,
            resource_type=str(resource_type or "").strip() or "generic",
            state=state,
            capacity=capacity,
            capabilities=dict(capabilities),
            labels=dict(labels),
            metadata={k: deepcopy(v) for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "state": self.state,
            "capacity": self.capacity,
            "capabilities": deepcopy(self.capabilities),
            "labels": deepcopy(self.labels),
            **deepcopy(self.metadata),
        }


class ResourceRegistry:
    """Merge scheduler-facing manifests and select compatible resources."""

    def __init__(self) -> None:
        self._resources: dict[str, ResourceDescriptor] = {}

    def ingest_manifest(self, manifest: dict[str, Any]) -> list[str]:
        if not isinstance(manifest, dict):
            raise TypeError("resource manifest must be an object")
        resource_type = str(manifest.get("resource_type") or "generic").strip()
        resources = manifest.get("resources") or []
        if not isinstance(resources, list):
            raise ValueError("resource manifest resources must be a list")

        seen: set[str] = set()
        for raw in resources:
            if not isinstance(raw, dict):
                raise ValueError("resource entry must be an object")
            item = ResourceDescriptor.from_dict(resource_type, raw)
            if item.resource_id in seen:
                raise ValueError("resource manifest contains duplicate resource_id")
            seen.add(item.resource_id)
            self._resources[item.resource_id] = item
        return sorted(seen)

    def remove(self, resource_id: str) -> bool:
        return self._resources.pop(str(resource_id), None) is not None

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            self._resources[key].to_dict()
            for key in sorted(self._resources)
        ]

    @staticmethod
    def _matches_value(actual: Any, expected: Any) -> bool:
        if isinstance(expected, list):
            if isinstance(actual, (list, tuple, set)):
                return all(item in actual for item in expected)
            return False
        if isinstance(expected, bool):
            return bool(actual) is expected
        return actual == expected

    def select(
        self,
        *,
        resource_type: str | None = None,
        requirements: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        count: int = 1,
    ) -> list[dict[str, Any]]:
        if not 1 <= int(count) <= 1000:
            raise ValueError("count must be between 1 and 1000")
        requirements = dict(requirements or {})
        labels = dict(labels or {})
        candidates: list[ResourceDescriptor] = []
        for item in self._resources.values():
            if item.state not in _READY_STATES:
                continue
            if resource_type and item.resource_type != resource_type:
                continue
            if any(
                not self._matches_value(item.capabilities.get(key), expected)
                for key, expected in requirements.items()
            ):
                continue
            if any(
                not self._matches_value(item.labels.get(key), expected)
                for key, expected in labels.items()
            ):
                continue
            candidates.append(item)

        # Deterministic ordering. Capacity is a tie-break preference, not authority.
        candidates.sort(key=lambda item: (-item.capacity, item.resource_id))
        return [item.to_dict() for item in candidates[: int(count)]]



def _norm_capability(value: str) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class NodeCapabilityManifest:
    """Scheduler-facing capability projection for one execution node."""

    node_id: str
    os: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    workspaces: tuple[str, ...] = ()
    cpu_count: int = 0
    max_concurrency: int = 1
    health: str = "ONLINE"
    metadata: dict[str, Any] = field(default_factory=dict)

    def missing(self, required: Iterable[str]) -> list[str]:
        required_set = {
            _norm_capability(item)
            for item in required
            if _norm_capability(item)
        }
        return sorted(required_set - set(self.capabilities))

    def supports(self, required: Iterable[str]) -> bool:
        return not self.missing(required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "os": self.os,
            "capabilities": sorted(self.capabilities),
            "workspaces": list(self.workspaces),
            "cpu_count": self.cpu_count,
            "max_concurrency": self.max_concurrency,
            "health": self.health,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeCapabilityManifest":
        return cls(
            node_id=str(data.get("node_id") or "node"),
            os=_norm_capability(data.get("os") or platform.system()),
            capabilities=frozenset(
                _norm_capability(item)
                for item in data.get("capabilities", [])
                if _norm_capability(item)
            ),
            workspaces=tuple(
                str(item) for item in data.get("workspaces", [])
                if str(item).strip()
            ),
            cpu_count=max(0, int(data.get("cpu_count") or 0)),
            max_concurrency=max(1, int(data.get("max_concurrency") or 1)),
            health=str(data.get("health") or "ONLINE").upper(),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def probe_local(
        cls,
        workspace: str | Path,
        *,
        max_concurrency: int = 1,
        extra: Iterable[str] = (),
    ) -> "NodeCapabilityManifest":
        system = _norm_capability(platform.system())
        capabilities = {"local", "filesystem", "workspace", "python", system}
        if importlib.util.find_spec("pytest") is not None:
            capabilities.add("pytest")
        for capability, command in {
            "git": "git",
            "node": "node",
            "npm": "npm",
            "powershell": "powershell",
            "docker": "docker",
        }.items():
            if shutil.which(command):
                capabilities.add(capability)
        capabilities.update(
            _norm_capability(item) for item in extra if _norm_capability(item)
        )
        return cls(
            node_id=f"local:{socket.gethostname()}",
            os=system,
            capabilities=frozenset(capabilities),
            workspaces=(str(Path(workspace).resolve()),),
            cpu_count=os.cpu_count() or 0,
            max_concurrency=max(1, int(max_concurrency)),
            health="ONLINE",
            metadata={"source": "local-probe"},
        )

    def as_resource_descriptor(self) -> ResourceDescriptor:
        return ResourceDescriptor(
            resource_id=self.node_id,
            resource_type="node",
            state=self.health,
            capacity=self.max_concurrency,
            capabilities={name: True for name in sorted(self.capabilities)},
            labels={"os": self.os},
            metadata={
                "workspaces": list(self.workspaces),
                "cpu_count": self.cpu_count,
                **deepcopy(self.metadata),
            },
        )


class ResourceCapabilityRegistry:
    """Node-centric scheduler view backed by deterministic capability manifests."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeCapabilityManifest] = {}

    def upsert(self, manifest: NodeCapabilityManifest) -> None:
        if not isinstance(manifest, NodeCapabilityManifest):
            raise TypeError("manifest must be a NodeCapabilityManifest")
        self._nodes[manifest.node_id] = manifest

    def remove(self, node_id: str) -> None:
        self._nodes.pop(str(node_id), None)

    def get(self, node_id: str) -> NodeCapabilityManifest | None:
        return self._nodes.get(str(node_id))

    def compatible(self, required: Iterable[str]) -> list[NodeCapabilityManifest]:
        return sorted(
            (
                node for node in self._nodes.values()
                if node.health in _READY_STATES and node.supports(required)
            ),
            key=lambda node: (-node.max_concurrency, node.node_id),
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            self._nodes[key].to_dict()
            for key in sorted(self._nodes)
        ]

    def to_resource_registry(self) -> ResourceRegistry:
        registry = ResourceRegistry()
        registry.ingest_manifest({
            "resource_type": "node",
            "resources": [
                node.as_resource_descriptor().to_dict()
                for node in self._nodes.values()
            ],
        })
        return registry


_SURFACES = ("canvas", "terminal", "vm")
_VM_EXES = {"vboxheadless.exe", "virtualboxvm.exe", "vboxsvc.exe"}
_CANVAS_EXES = {"sentra.exe", "electron.exe"}
_TERMINAL_EXES = {
    "windowsterminal.exe", "openconsole.exe", "powershell.exe", "pwsh.exe",
    "cmd.exe", "python.exe", "pythonw.exe", "py.exe", "conhost.exe",
}
_TERMINAL_HINTS = ("terminal", "conpty", "sentra-cli", "opencode", "codex")
# Live probe opens VM and canvas images, plus the terminal host executables.
# python/powershell/cmd/conhost stay out of the probe: without a command line
# they cannot be attributed to SENTRA, and opening every one of them is enough
# to stall a busy machine. Callers that already have a command line classify
# those names through sample_surfaces.
_PROBE_EXES = _VM_EXES | _CANVAS_EXES | {"windowsterminal.exe", "openconsole.exe"}


@dataclass(frozen=True)
class ResourceCeiling:
    """Host headroom. Ceilings stay below 100% so admission cannot pin the machine."""

    host_reserve_mb: int = 2048
    max_ram_percent: float = 80.0
    max_cpu_percent: float = 85.0
    canvas_ram_mb: int = 2048
    terminal_ram_mb: int = 1024
    vm_ram_mb: int = 8192
    hot_execution_cap: int = 40

    def __post_init__(self) -> None:
        if type(self.host_reserve_mb) is not int or self.host_reserve_mb < 512:
            raise ValueError("host reserve must be at least 512 MB")
        if isinstance(self.max_ram_percent, bool) or not isinstance(self.max_ram_percent, (int, float)):
            raise ValueError("max_ram_percent must be a number")
        if not 1 <= float(self.max_ram_percent) <= 90:
            raise ValueError("ram percent ceiling must stay inside 1..90")
        if isinstance(self.max_cpu_percent, bool) or not isinstance(self.max_cpu_percent, (int, float)):
            raise ValueError("max_cpu_percent must be a number")
        if not 1 <= float(self.max_cpu_percent) <= 95:
            raise ValueError("cpu percent ceiling must stay inside 1..95")
        for name, value in (
            ("canvas", self.canvas_ram_mb),
            ("terminal", self.terminal_ram_mb),
            ("vm", self.vm_ram_mb),
        ):
            if type(value) is not int or value < 128:
                raise ValueError(f"{name} ram ceiling must be an int >= 128")
        if type(self.hot_execution_cap) is not int or not 10 <= self.hot_execution_cap <= 100:
            raise ValueError("hot_execution_cap must be an int inside 10..100")

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_reserve_mb": self.host_reserve_mb,
            "max_ram_percent": self.max_ram_percent,
            "max_cpu_percent": self.max_cpu_percent,
            "canvas_ram_mb": self.canvas_ram_mb,
            "terminal_ram_mb": self.terminal_ram_mb,
            "vm_ram_mb": self.vm_ram_mb,
            "hot_execution_cap": self.hot_execution_cap,
        }


def classify_surface(name: str, image_path: str = "", command_line: str = "") -> str | None:
    """Classify a SENTRA-owned process. Unrelated host processes return None."""
    exe = str(name or "").strip().lower()
    image = str(image_path or "").replace("/", "\\").lower()
    command = str(command_line or "").lower()
    if exe in _VM_EXES:
        return "vm"
    sentra_owned = "sentra" in image or "sentra" in command
    if exe in _CANVAS_EXES and sentra_owned:
        return "canvas"
    if exe in _TERMINAL_EXES and sentra_owned and any(
        hint in command or hint in image for hint in _TERMINAL_HINTS
    ):
        return "terminal"
    return None


def sample_surfaces(processes: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sum RSS and CPU time for canvas, terminal, and VM processes only."""
    buckets = {
        name: {"rss_bytes": 0, "cpu_time_s": 0.0, "pids": set()}
        for name in _SURFACES
    }
    for proc in processes:
        if not isinstance(proc, dict):
            raise ValueError("process sample must be an object")
        surface = classify_surface(
            str(proc.get("name") or ""),
            str(proc.get("image_path") or ""),
            str(proc.get("command_line") or ""),
        )
        if surface is None:
            continue
        rss = proc.get("rss_bytes") or 0
        cpu_time = proc.get("cpu_time_s") or 0
        if isinstance(rss, bool) or not isinstance(rss, (int, float)) or rss < 0:
            raise ValueError("rss_bytes must be a non-negative number")
        if isinstance(cpu_time, bool) or not isinstance(cpu_time, (int, float)) or cpu_time < 0:
            raise ValueError("cpu_time_s must be a non-negative number")
        buckets[surface]["rss_bytes"] += int(rss)
        buckets[surface]["cpu_time_s"] += float(cpu_time)
        pid = proc.get("pid") or 0
        if type(pid) is not int:
            raise ValueError("pid must be an int")
        if pid:
            buckets[surface]["pids"].add(pid)
    result = {}
    for name, bucket in buckets.items():
        pids = tuple(sorted(bucket["pids"]))
        result[name] = {
            "rss_mb": bucket["rss_bytes"] / (1024 * 1024),
            "cpu_time_s": bucket["cpu_time_s"],
            "process_count": len(pids),
            "pids": pids,
        }
    return result


def cpu_percent_between(
    first_cpu_time_s: float,
    second_cpu_time_s: float,
    *,
    elapsed_s: float,
    cpu_count: int,
) -> float:
    """CPU percent from two cumulative samples. The caller owns the wait."""
    if isinstance(elapsed_s, bool) or not isinstance(elapsed_s, (int, float)) or elapsed_s <= 0:
        raise ValueError("elapsed_s must be positive")
    if type(cpu_count) is not int or cpu_count < 1:
        raise ValueError("cpu_count must be a positive int")
    if isinstance(first_cpu_time_s, bool) or isinstance(second_cpu_time_s, bool):
        raise ValueError("cpu time must be a number")
    used = float(second_cpu_time_s) - float(first_cpu_time_s)
    if used < 0:
        raise ValueError("cpu time went backwards")
    percent = (used / float(elapsed_s)) * 100.0 / cpu_count
    return max(0.0, min(100.0, percent))


def _surface_rss(surfaces: dict[str, Any], surface: str) -> float:
    raw = surfaces.get(surface) or {}
    if isinstance(raw, dict):
        value = raw.get("rss_mb") or 0
    else:
        value = getattr(raw, "rss_mb", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError("surface rss_mb must be a non-negative number")
    return float(value)


def evaluate_admission(
    *,
    ceiling: ResourceCeiling,
    host: dict[str, Any],
    surfaces: dict[str, Any],
    surface: str,
    ram_mb: int,
    cpu_percent: float = 0.0,
) -> dict[str, Any]:
    """Decide whether new work fits. Never kills a process or changes priority."""
    if not isinstance(ceiling, ResourceCeiling):
        raise TypeError("ceiling must be a ResourceCeiling")
    if surface not in _SURFACES:
        raise ValueError("unknown surface")
    if not isinstance(host, dict) or not isinstance(surfaces, dict):
        raise TypeError("host and surfaces must be objects")
    total = host.get("total_mb")
    available = host.get("available_mb")
    if type(total) is not int or type(available) is not int or total <= 0 or available < 0 or available > total:
        raise ValueError("invalid host memory sample")
    if type(ram_mb) is not int or ram_mb < 0:
        raise ValueError("ram_mb must be a non-negative int")
    if isinstance(cpu_percent, bool) or not isinstance(cpu_percent, (int, float)) or cpu_percent < 0:
        raise ValueError("cpu_percent must be a non-negative number")
    allowed = True
    reasons: list[str] = []
    if available - ram_mb < ceiling.host_reserve_mb:
        allowed = False
        reasons.append("host reserve")
    used_after = (total - available) + ram_mb
    if (used_after / total) * 100 > ceiling.max_ram_percent:
        allowed = False
        reasons.append("ram percent ceiling")
    caps = {
        "canvas": ceiling.canvas_ram_mb,
        "terminal": ceiling.terminal_ram_mb,
        "vm": ceiling.vm_ram_mb,
    }
    if _surface_rss(surfaces, surface) + ram_mb > caps[surface]:
        allowed = False
        reasons.append(surface + " ram ceiling")
    cpu = host.get("cpu_percent")
    if cpu is not None:
        if isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or not 0 <= float(cpu) <= 100:
            raise ValueError("host.cpu_percent must be a number inside 0..100 or null")
        if float(cpu) >= ceiling.max_cpu_percent or float(cpu) + float(cpu_percent) > ceiling.max_cpu_percent:
            allowed = False
            reasons.append("cpu ceiling")
    return {
        "allowed": allowed,
        "reasons": reasons,
        "kills_processes": False,
        "changes_priority": False,
        "authorizes_effects": False,
    }


def read_host_memory() -> dict[str, Any]:
    """One GlobalMemoryStatusEx sample. Does not sleep or change process priority."""
    if os.name != "nt":
        raise OSError("Windows host memory probe is unavailable")
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise OSError("GlobalMemoryStatusEx failed")
    total = int(stat.ullTotalPhys)
    available = int(stat.ullAvailPhys)
    return {
        "total_mb": total // (1024 * 1024),
        "available_mb": available // (1024 * 1024),
        "ram_percent": float(stat.dwMemoryLoad),
        "cpu_percent": None,
        "cpu_count": os.cpu_count() or 0,
        "authorizes_effects": False,
    }


def _invalid_handle(handle: int | None) -> bool:
    if not handle:
        return True
    return int(handle) in {-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF}


def read_process_samples() -> list[dict[str, Any]]:
    """One toolhelp pass over VM, canvas, and Windows Terminal host images.

    python, powershell, cmd, and conhost are not opened. They are classified
    only when the caller already has a command line. Access denied on a single
    process omits that process. Does not change priority and does not
    terminate anything.
    """
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = ctypes.c_void_p

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if _invalid_handle(snapshot):
        return []
    samples: list[dict[str, Any]] = []
    shell_seen = 0
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            err = ctypes.get_last_error()
            raise OSError(err, "Process32FirstW failed")
        while True:
            name = str(entry.szExeFile or "")
            pid = int(entry.th32ProcessID)
            lowered = name.lower()
            if pid and (lowered in _PROBE_EXES or (lowered in _SHELL_EXES and shell_seen < _SHELL_PROBE_CAP)):
                if lowered in _SHELL_EXES:
                    shell_seen += 1
                samples.append(_sample_one(kernel, psapi, PROCESS_MEMORY_COUNTERS, pid, name))
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel.CloseHandle(snapshot)
    return samples


def _filetime_seconds(value: Any) -> float:
    return ((int(value.dwHighDateTime) << 32) + int(value.dwLowDateTime)) / 10_000_000


def _sample_one(kernel: Any, psapi: Any, counters_type: Any, pid: int, name: str) -> dict[str, Any]:
    import ctypes
    from ctypes import wintypes

    sample = {
        "pid": pid,
        "name": name,
        "image_path": "",
        "command_line": "",
        "rss_bytes": 0,
        "cpu_time_s": 0.0,
    }
    handle = kernel.OpenProcess(0x1000, False, pid)
    if _invalid_handle(handle):
        return sample
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            sample["image_path"] = buf.value
        counters = counters_type()
        counters.cb = ctypes.sizeof(counters_type)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            sample["rss_bytes"] = int(counters.WorkingSetSize)
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if kernel.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel_time), ctypes.byref(user_time),
        ):
            sample["cpu_time_s"] = _filetime_seconds(kernel_time) + _filetime_seconds(user_time)
        sample["command_line"] = _command_line(handle)
    finally:
        kernel.CloseHandle(handle)
    return sample


_VM_ID = __import__("re").compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_SHELL_EXES = {"python.exe", "pythonw.exe", "py.exe", "powershell.exe", "pwsh.exe", "cmd.exe"}
_SHELL_PROBE_CAP = 32


def attribute_processes(processes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attribute canvas, terminal, and VM samples without calling VBoxManage.

    A VM id is taken only from a UUID already present on that process command
    line. Command lines themselves are not returned.
    """
    rows = []
    for proc in processes:
        if not isinstance(proc, dict):
            raise ValueError("process sample must be an object")
        surface = classify_surface(
            str(proc.get("name") or ""),
            str(proc.get("image_path") or ""),
            str(proc.get("command_line") or ""),
        )
        if surface is None:
            continue
        command = str(proc.get("command_line") or "")
        found = _VM_ID.search(command) if surface == "vm" else None
        pid = proc.get("pid") or 0
        if type(pid) is not int:
            raise ValueError("pid must be an int")
        rss = proc.get("rss_bytes") or 0
        if isinstance(rss, bool) or not isinstance(rss, (int, float)) or rss < 0:
            raise ValueError("rss_bytes must be a non-negative number")
        rows.append({
            "surface": surface,
            "pid": pid,
            "name": str(proc.get("name") or ""),
            "vm_id": found.group(0).lower() if found else None,
            "rss_bytes": int(rss),
            "authorizes_effects": False,
        })
    rows.sort(key=lambda row: (row["surface"], row["pid"], row["name"]))
    return rows


def admit_surface(
    *,
    ceiling: ResourceCeiling,
    host: dict[str, Any],
    surfaces: dict[str, Any],
    surface: str,
    ram_mb: int,
    cpu_percent: float = 0.0,
    budget: Any = None,
    dot_id: str | None = None,
) -> dict[str, Any]:
    """Connect a measurement to the host budget. This does not change a VM."""
    decision = evaluate_admission(
        ceiling=ceiling, host=host, surfaces=surfaces, surface=surface,
        ram_mb=ram_mb, cpu_percent=cpu_percent,
    )
    if not decision["allowed"]:
        return {
            "admitted": False,
            "reservation_id": None,
            "decision": decision,
            "executed": False,
            "authorizes_effects": False,
        }
    reservation_id = None
    if budget is not None:
        if not dot_id:
            raise ValueError("dot_id is required to reserve")
        try:
            reservation = budget.reserve(dot_id, surface, ram_mb, cpu_percent)
        except Exception as exc:
            from orchestrator.budgets import BudgetExceeded

            if not isinstance(exc, BudgetExceeded):
                raise
            refused = dict(decision)
            refused["allowed"] = False
            refused["reasons"] = list(decision["reasons"]) + [str(exc)]
            return {
                "admitted": False,
                "reservation_id": None,
                "decision": refused,
                "executed": False,
                "authorizes_effects": False,
            }
        reservation_id = reservation.id
    return {
        "admitted": True,
        "reservation_id": reservation_id,
        "decision": decision,
        "executed": False,
        "authorizes_effects": False,
    }


def read_host_snapshot() -> dict[str, Any]:
    """Read-only host RAM plus SENTRA surface RSS. Does not mutate processes."""
    host = read_host_memory()
    try:
        processes = read_process_samples()
    except OSError:
        processes = []
    surfaces = sample_surfaces(processes)
    return {
        "host": host,
        "surfaces": {
            name: {
                "rss_mb": round(bucket["rss_mb"], 3),
                "cpu_time_s": round(bucket["cpu_time_s"], 3),
                "process_count": bucket["process_count"],
            }
            for name, bucket in surfaces.items()
        },
        "process_count": len(processes),
        "attributed": [
            {key: row[key] for key in ("surface", "pid", "name", "vm_id", "rss_bytes")}
            for row in attribute_processes(processes)
        ],
        "authorizes_effects": False,
        "kills_processes": False,
        "changes_priority": False,
    }


def _command_line(handle: int) -> str:
    """Best-effort command line. Failure returns an empty string."""
    import ctypes
    from ctypes import wintypes

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", ctypes.c_void_p),
        ]

    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtQueryInformationProcess.argtypes = [
        ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
    ]
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG
    raw = ctypes.create_string_buffer(4096)
    returned = wintypes.ULONG(0)
    status = ntdll.NtQueryInformationProcess(handle, 60, raw, len(raw), ctypes.byref(returned))
    if status != 0 or returned.value < ctypes.sizeof(UNICODE_STRING):
        return ""
    info = UNICODE_STRING.from_buffer_copy(raw)
    if not info.Buffer or info.Length <= 0:
        return ""
    try:
        return ctypes.wstring_at(info.Buffer, info.Length // 2)[:2000]
    except (OSError, ValueError):
        return ""
