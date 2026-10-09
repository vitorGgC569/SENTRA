"""Opt-in, read-only Windows UIA integration against our *own* Tk lab window.

Run only when explicitly enabled:
  $env:SENTRA_UIA_LAB_RUN='1'
  python -m pytest -q tests/unit/test_sentra_executors_uia_lab.py

Never attach to an existing user's window; do not install pywinauto here.
"""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import os
import subprocess
import sys
import time
import uuid

import pytest

from sentra_executors import plan_read_only_tk_lab, discover_owned_tk_lab
from sentra_runtime.contracts import PolicyDecision
from sentra_runtime.executor import ExecutorRegistry


@pytest.mark.skipif(
    (sys.platform != "win32" or
     os.environ.get("SENTRA_UIA_LAB_RUN") != "1" or
     os.environ.get("SENTRA_UIA_LAB_VM_CONFIRMED") != "1"),
    reason="read-only UIA lab requires explicit opt-in AND operator-confirmed isolated VM",
)
def test_read_own_tk_window_title_through_real_uia_and_registry():
    pytest.importorskip("pywinauto.application", reason="optional pywinauto absent")
    pytest.importorskip("tkinter", reason="Tk lab GUI unavailable")
    title = "SENTRA-UIA-LAB-" + uuid.uuid4().hex[:10]
    # One freshly created lab process only. The test never touches user apps.
    program = (
        "import tkinter as tk\n"
        "root = tk.Tk()\n"
        f"root.title({title!r})\n"
        "root.geometry('240x90')\n"
        "root.mainloop()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        user32.FindWindowW.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        hwnd = 0
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Tk lab child exited before its window appeared")
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value == process.pid:
                    break
                hwnd = 0
            time.sleep(0.1)
        assert hwnd, "isolated Tk lab window did not appear"
        owned = discover_owned_tk_lab(pid=process.pid, title=title)
        assert owned.hwnd == int(hwnd)

        authorize = lambda _req: PolicyDecision(True, "explicit-tk-lab")
        plan = plan_read_only_tk_lab(
            machine_id="lab-uia-machine",
            owner_principal_id="lab-principal",
            pid=process.pid, hwnd=int(hwnd), window_title=title,
            policy=authorize,
        )
        registry = ExecutorRegistry(authorize=authorize)
        plan.declaration.register(registry)
        request = plan.request(
            operation_id="lab-read-title", idempotency_key="lab-title-key",
            work_item_id="lab-work-item",
        )
        result = asyncio.run(registry.submit(request))
        assert result.state == "SUCCEEDED"
        assert result.evidence["window_title_sha256"] == hashlib.sha256(
            title.encode("utf-8")).hexdigest()
        assert result.evidence["pid"] == process.pid
        assert result.evidence["hwnd"] == hwnd
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
