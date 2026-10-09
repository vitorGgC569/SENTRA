"""Ownership-scoped ACP process trees: POSIX sessions / Windows kill-on-close job.

Windows children start suspended and join the job before their initial thread
is resumed. This closes the descendant-spawn race of assigning an already
running agent to a job. No PID reattachment or shell-based process cleanup.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from typing import Any


class WindowsAgentJob:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", w.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", w.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class IOCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IOCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def attach_and_resume(self, pid: int) -> None:
        import ctypes
        from ctypes import wintypes as w

        process = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(process)

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                        ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG),
                        ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]

        self.kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
        self.kernel.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.kernel.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.kernel.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenThread.restype = w.HANDLE
        self.kernel.ResumeThread.argtypes = [w.HANDLE]
        self.kernel.ResumeThread.restype = w.DWORD
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot == w.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = False
        try:
            entry = ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    thread = self.kernel.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self.kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        resumed = True
                    finally:
                        self.kernel.CloseHandle(thread)
                more = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(snapshot)
        if not resumed:
            raise OSError("ACP suspended process has no initial thread")

    def close(self) -> None:
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise self.ctypes.WinError(self.ctypes.get_last_error())


class ACPProcessOwner:
    def __init__(self, process: asyncio.subprocess.Process, job: WindowsAgentJob | None) -> None:
        self.process, self.job = process, job
        self._lock = asyncio.Lock()
        self._closed = False

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            if self.job is not None:
                self.job.close()  # Kills descendants even when direct child already exited.
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                # A reaped leader does not prove its group is gone.
                deadline = asyncio.get_running_loop().time() + 1
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        os.killpg(self.process.pid, 0)
                    except ProcessLookupError:
                        break
                    await asyncio.sleep(.025)
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if self.process.returncode is None:
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await asyncio.wait_for(self.process.wait(), 3)
            self._closed = True


async def spawn_owned(executable: str, args: tuple[str, ...], *, checkpoint=None, **kwargs: Any):
    job = WindowsAgentJob() if os.name == "nt" else None
    flags = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004 | 0x08000000}
             if job is not None else {"start_new_session": True})
    process = None
    async def create():
        if checkpoint is not None:
            checkpoint()
        return await asyncio.create_subprocess_exec(executable, *args, **kwargs, **flags)
    spawn = asyncio.create_task(create())
    try:
        # If launch is cancelled/timed out while spawning, acquire the handle
        # before cleanup; never discard a still-running spawn task.
        process = await asyncio.shield(spawn)
        if job is not None:
            if checkpoint is not None:
                checkpoint()
            job.attach_and_resume(process.pid)
        return process, ACPProcessOwner(process, job)
    except BaseException:
        if process is None:
            try:
                process = await spawn
            except BaseException:
                if job is not None:
                    job.close()
                raise
        if job is not None:
            job.close()
            if process.returncode is None:
                process.kill()
                await process.wait()
        else:
            await ACPProcessOwner(process, None).close()
        raise
