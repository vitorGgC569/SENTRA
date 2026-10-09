"""Exact-title, PID-scoped discovery of a *caller-owned* Tk lab window.

This is NOT host window enumeration. It returns only an HWND matching both
the caller-supplied process ID and a lab-only random title. Real execution
requires caller to own the spawned child; PID ownership is not OS isolation.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class LabWindow:
    pid: int
    hwnd: int
    title: str


def _probe_exact_window(title: str) -> tuple[int, int] | None:
    if sys.platform != "win32":
        raise RuntimeError("windows_only")
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    owner = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if not thread_id or not owner.value:
        return None
    return int(owner.value), int(hwnd)


def discover_owned_tk_lab(
    *, pid: int, title: str,
    probe: Callable[[str], tuple[int, int] | None] | None = None,
) -> LabWindow:
    """Validate exactly one declared lab window; no process scanning or launch."""
    if (type(pid) is not int or pid <= 0 or
            type(title) is not str or not title.startswith("SENTRA-UIA-LAB-") or
            len(title) > 80 or len(title) < len("SENTRA-UIA-LAB-") + 8):
        raise ValueError("invalid_owned_lab_identity")
    match = (probe or _probe_exact_window)(title)
    if match is None:
        raise LookupError("lab_window_not_found")
    found_pid, hwnd = match
    if (type(found_pid) is not int or type(hwnd) is not int or
            found_pid != pid or hwnd <= 0):
        raise PermissionError("lab_pid_or_hwnd_scope_mismatch")
    return LabWindow(pid, hwnd, title)
