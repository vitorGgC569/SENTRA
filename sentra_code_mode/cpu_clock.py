"""CPU accounting for our current guest worker; no process-wide estimates."""
from __future__ import annotations
import os
import threading
import time
from . import CodeModeUnavailable


class WorkerCPUClock:
    def __init__(self):
        self._handle = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self._ctypes, self._filetime = ctypes, wintypes.FILETIME
            self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self._kernel.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            self._kernel.OpenThread.restype = wintypes.HANDLE
            self._kernel.GetThreadTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
            self._kernel.GetThreadTimes.restype = wintypes.BOOL
            self._kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            self._kernel.CloseHandle.restype = wintypes.BOOL
            self._handle = self._kernel.OpenThread(0x0800, False, threading.get_native_id())
            if not self._handle:
                raise CodeModeUnavailable("guest worker CPU clock unavailable")
            self._read = self._windows_seconds
        else:
            try:
                self._clock_id = time.pthread_getcpuclockid(threading.get_ident())
                self._read = lambda: time.clock_gettime(self._clock_id)
            except (AttributeError, OSError) as exc:
                raise CodeModeUnavailable("guest worker CPU clock unavailable") from exc
        try:
            self._baseline = self._read()
        except BaseException:
            self.close()
            raise

    def _windows_seconds(self):
        values = [self._filetime() for _ in range(4)]
        if not self._kernel.GetThreadTimes(self._handle, *(self._ctypes.byref(v) for v in values)):
            raise CodeModeUnavailable("guest worker CPU accounting failed")
        return sum((v.dwHighDateTime << 32) | v.dwLowDateTime for v in values[2:]) / 10_000_000

    def seconds(self):
        return max(0.0, self._read() - self._baseline)

    def close(self):
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
