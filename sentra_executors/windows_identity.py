"""Opt-in identity-and-fencing guard for *read-only* lab Windows UIA.

OS-enforced isolation NOT provided. Process/window identity snapshots and
lease-reader callbacks reduce PID reuse and stale-fencing risk but cannot make
COM provider calls atomic or substitute for Windows security boundaries.
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import re
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from sentra_runtime.contracts import Capability, Machine
from ._base import GuardedExecutor
from .windows_uia import WindowsUIABinding, PywinautoUIABackend


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    hwnd: int
    creation_filetime: int
    executable_sha256: str

    def __post_init__(self):
        if (type(self.pid) is not int or self.pid <= 0 or
                type(self.hwnd) is not int or self.hwnd <= 0 or
                type(self.creation_filetime) is not int or
                self.creation_filetime <= 0 or
                type(self.executable_sha256) is not str or
                not re.fullmatch("[0-9a-f]{64}", self.executable_sha256)):
            raise ValueError("invalid_process_identity")


@dataclass(frozen=True)
class FenceLease:
    lease_id: str
    token: int
    expires_monotonic: float

    def __post_init__(self):
        if (not self.lease_id or type(self.token) is not int or self.token < 1 or
                type(self.expires_monotonic) not in (float, int) or
                not math.isfinite(self.expires_monotonic) or
                self.expires_monotonic <= 0):
            raise ValueError("invalid_fence_lease")


@dataclass(frozen=True)
class IdentityUIABinding:
    target: WindowsUIABinding
    identity: ProcessIdentity
    lease: FenceLease

    def __post_init__(self):
        if (self.target.pid != self.identity.pid or
                self.target.hwnd != self.identity.hwnd or
                not self.target.window_title.startswith("SENTRA-UIA-LAB-") or
                self.target.allowed_actions != ("read_window_title",)):
            raise ValueError("hardened_lab_must_be_read_only")

    @property
    def capability_id(self):
        return self.target.capability_id

    @property
    def timeout_seconds(self):
        return self.target.timeout_seconds


class WindowsIdentityProbe:
    """Windows native probe ONLY for a pre-authorized exact PID+HWND.

    Reads binary to hash only the executable of caller-owned test process.
    No process enumeration, no elevation, no window input or process launch.
    """
    def __call__(self, pid: int, hwnd: int) -> ProcessIdentity:
        if sys.platform != "win32":
            raise RuntimeError("windows_only")
        user = ctypes.windll.user32
        kernel = ctypes.windll.kernel32
        user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user.GetWindowThreadProcessId.restype = wintypes.DWORD
        owner = wintypes.DWORD()
        if not user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)) or owner.value != pid:
            raise RuntimeError("window_not_owned_by_process")
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            raise PermissionError("cannot_verify_process_identity")
        try:
            class FileTime(ctypes.Structure):
                _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
            a, b, c, e = FileTime(), FileTime(), FileTime(), FileTime()
            kernel.GetProcessTimes.argtypes = (
                wintypes.HANDLE, ctypes.POINTER(FileTime),
                ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
                ctypes.POINTER(FileTime))
            if not kernel.GetProcessTimes(handle, ctypes.byref(a), ctypes.byref(b),
                                          ctypes.byref(c), ctypes.byref(e)):
                raise RuntimeError("process_creation_time_unavailable")
            created = (a.high << 32) | a.low
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            kernel.QueryFullProcessImageNameW.argtypes = (
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD))
            if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                raise RuntimeError("executable_path_unavailable")
            hasher = hashlib.sha256()
            with open(path.value, "rb") as exe:
                for chunk in iter(lambda: exe.read(1024 * 256), b""):
                    hasher.update(chunk)
            return ProcessIdentity(pid, hwnd, created, hasher.hexdigest())
        finally:
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            kernel.CloseHandle(handle)


class IdentityGuardedUIAExecutor(GuardedExecutor):
    kind = "windows_uia_hardened"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[IdentityUIABinding, ...],
                 policy, identity_probe: Callable,
                 lease_reader: Callable, backend=None):
        if (not callable(identity_probe) or not callable(lease_reader) or
                len({b.capability_id for b in bindings}) != len(bindings)):
            raise ValueError("trusted_identity_and_fence_sources_required")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.identity_probe = identity_probe
        self.lease_reader = lease_reader
        self.backend = backend if backend is not None else PywinautoUIABackend()

    def _validate(self, request, binding: IdentityUIABinding) -> dict:
        args = dict(request.arguments)
        if (set(args) != {"action", "pid", "hwnd", "lease_id", "fencing_token"} or
                args["action"] != "read_window_title" or
                type(args["pid"]) is not int or type(args["hwnd"]) is not int or
                type(args["fencing_token"]) is not int or
                args["pid"] != binding.identity.pid or
                args["hwnd"] != binding.identity.hwnd or
                args["lease_id"] != binding.lease.lease_id or
                args["fencing_token"] != binding.lease.token):
            raise ValueError("invalid_hardened_identity_or_fence")
        return args

    def _assert_live_identity_fence(self, binding: IdentityUIABinding):
        live = self.identity_probe(binding.identity.pid, binding.identity.hwnd)
        lease = self.lease_reader(binding.lease.lease_id)
        if type(live) is not ProcessIdentity or live != binding.identity:
            raise PermissionError("process_identity_drift")
        if (type(lease) is not FenceLease or lease != binding.lease or
                time.monotonic() >= lease.expires_monotonic):
            raise PermissionError("fencing_lease_expired_or_replaced")

    def _execute(self, binding: IdentityUIABinding, arguments: dict) -> dict:
        # Both sources are trusted/injected, NOT claims supplied by agents.
        self._assert_live_identity_fence(binding)
        ui_args = {"action": "read_window_title", "pid": binding.identity.pid,
                   "hwnd": binding.identity.hwnd}
        evidence = self.backend.run(binding.target, ui_args)
        self._assert_live_identity_fence(binding)
        return evidence


def declare_hardened_windows_machine(*, machine_id: str, owner_principal_id: str,
                                     bindings: tuple[IdentityUIABinding, ...],
                                     policy, identity_probe, lease_reader,
                                     backend=None):
    from .discovery import MachineDeclaration
    caps = tuple(Capability(b.capability_id,
                            "Read-only UIA with process identity and lease fencing",
                            "high") for b in bindings)
    machine = Machine(machine_id, "windows_uia_hardened", owner_principal_id, caps)
    adapter = IdentityGuardedUIAExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, identity_probe=identity_probe,
        lease_reader=lease_reader, backend=backend)
    return MachineDeclaration(machine, adapter)
