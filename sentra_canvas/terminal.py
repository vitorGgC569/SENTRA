"""Windows ConPTY backend. No Maestri or command-by-command shell simulation.

Requires Windows 10 1809+ (CreatePseudoConsole). No host-subprocess fallback is
performed if a pseudoterminal cannot be created.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable
from .owned_process import WindowsJob

class TerminalError(RuntimeError):
    """Unable to operate a real pseudoterminal."""


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class WindowsPTY:
    """Live Windows pseudoconsole with incremental byte output and bounded history.

    ReadFile runs outside the HTTP/UI thread. Closing a PTY never affects other
    independently-created sessions. Call wait() to determine actual process exit.
    """
    def __init__(
        self, argv: list[str], cwd: Path,
        on_output: Callable[[bytes], None] | None = None,
        cols: int = 100, rows: int = 28, *, env: dict[str, str] | None = None,
    ) -> None:
        if os.name != "nt":
            raise TerminalError("ConPTY requires Windows; no implicit host fallback")
        if not argv or not Path(cwd).is_dir():
            raise ValueError("valid argv and existing working directory required")
        if not 20 <= cols <= 500 or not 5 <= rows <= 200:
            raise ValueError("invalid PTY size")
        self._lock = threading.RLock()
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self._kernel
        H = wintypes.HANDLE
        k.CreatePipe.argtypes = [ctypes.POINTER(H), ctypes.POINTER(H),
                                  ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]
        k.CreatePipe.restype = wintypes.BOOL
        k.SetHandleInformation.argtypes = [H, wintypes.DWORD, wintypes.DWORD]
        k.CreatePseudoConsole.argtypes = [COORD, H, H, wintypes.DWORD,
                                           ctypes.POINTER(H)]
        k.CreatePseudoConsole.restype = ctypes.c_long
        k.ResizePseudoConsole.argtypes = [H, COORD]
        k.ResizePseudoConsole.restype = ctypes.c_long
        k.ClosePseudoConsole.argtypes = [H]
        k.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t)]
        k.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        k.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        k.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.c_void_p, ctypes.POINTER(PROCESS_INFORMATION)]
        k.CreateProcessW.restype = wintypes.BOOL
        k.ReadFile.argtypes = [H, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.WriteFile.argtypes = [H, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.WaitForSingleObject.argtypes = [H, wintypes.DWORD]
        k.GetExitCodeProcess.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
        k.TerminateProcess.argtypes = [H, wintypes.UINT]
        k.CloseHandle.argtypes = [H]
        k.ResumeThread.argtypes=[H]
        k.ResumeThread.restype=wintypes.DWORD
        self._hpc = H()
        self._input = H()
        self._output = H()
        self._process = H()
        self.pid = 0
        self._closed = False
        self._finished = threading.Event()
        self._exit_code: int | None = None
        self._on_output = on_output
        self._job=WindowsJob()
        self._start(argv, Path(cwd), cols, rows, env)
        self._reader = threading.Thread(
            target=self._read_loop, name=f"sentra-conpty-{self.pid}", daemon=True)
        self._reader.start()

    def _start(self, argv: list[str], cwd: Path, cols: int, rows: int, env=None) -> None:
        k = self._kernel
        a = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
        in_read, in_write, out_read, out_write = (
            wintypes.HANDLE(), wintypes.HANDLE(),
            wintypes.HANDLE(), wintypes.HANDLE())
        attribute_list = None
        info = PROCESS_INFORMATION()
        success = False
        try:
            if not k.CreatePipe(ctypes.byref(in_read), ctypes.byref(in_write),
                                ctypes.byref(a), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            if not k.CreatePipe(ctypes.byref(out_read), ctypes.byref(out_write),
                                ctypes.byref(a), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            # Prevent inheriting the two parent-side pipe handles.
            if not k.SetHandleInformation(in_write, 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            if not k.SetHandleInformation(out_read, 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            hr = k.CreatePseudoConsole(COORD(cols, rows), in_read, out_write,
                                       0, ctypes.byref(self._hpc))
            if hr < 0:
                raise TerminalError(f"CreatePseudoConsole HRESULT 0x{hr & 0xffffffff:08x}")
            # Keep both original console-side handles until child creation.
            needed = ctypes.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(needed))
            attribute_list = ctypes.create_string_buffer(needed.value)
            ptr = ctypes.cast(attribute_list, ctypes.c_void_p)
            if not k.InitializeProcThreadAttributeList(ptr, 1, 0,
                                                       ctypes.byref(needed)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not k.UpdateProcThreadAttribute(
                ptr, 0, 0x00020016, self._hpc,
                ctypes.sizeof(self._hpc), None, None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            startup = STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            # Parent stdio may be redirected: force the child onto ConPTY.
            startup.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
            startup.lpAttributeList = ptr
            cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            environment = None
            if env is not None:
                if any(not isinstance(k,str) or not k or "=" in k or "\0" in k
                       or not isinstance(v,str) or "\0" in v for k,v in env.items()):
                    raise ValueError("invalid child environment")
                environment = ctypes.create_unicode_buffer(
                    "\0".join(k+"="+v for k,v in sorted(env.items(),key=lambda item:item[0].upper()))+"\0\0")
            if not k.CreateProcessW(
                None, cmd, None, None, False, 0x00080000 | 0x00000400 | 0x00000004,
                environment, str(cwd), ctypes.byref(startup), ctypes.byref(info)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self._job.assign(info.hProcess)
            if k.ResumeThread(info.hThread)!=1:
                raise TerminalError("ConPTY child could not be resumed")
            k.CloseHandle(in_read); in_read = wintypes.HANDLE()
            k.CloseHandle(out_write); out_write = wintypes.HANDLE()
            self._input, self._output = in_write, out_read
            in_write, out_read = wintypes.HANDLE(), wintypes.HANDLE()
            self._process = info.hProcess
            self.pid = int(info.dwProcessId)
            success = True
        finally:
            if attribute_list is not None:
                # Initialized only if InitializeProcThreadAttributeList succeeded.
                if success:
                    k.DeleteProcThreadAttributeList(
                        ctypes.cast(attribute_list, ctypes.c_void_p))
                else:
                    try:
                        k.DeleteProcThreadAttributeList(
                            ctypes.cast(attribute_list, ctypes.c_void_p))
                    except OSError:
                        pass
            for h in (in_read, in_write, out_read, out_write, info.hThread):
                if h:
                    k.CloseHandle(h)
            if not success:
                self._job.close()
                if self._hpc:
                    k.ClosePseudoConsole(self._hpc)
                if info.hProcess:
                    k.TerminateProcess(info.hProcess,1)
                    k.CloseHandle(info.hProcess)

    def _read_loop(self) -> None:
        k = self._kernel
        try:
            buf = ctypes.create_string_buffer(8192)
            count = wintypes.DWORD()
            while k.ReadFile(self._output, buf, len(buf), ctypes.byref(count), None):
                if count.value and self._on_output:
                    self._on_output(bytes(buf.raw[:count.value]))
        finally:
            self._finished.set()

    def write(self, data: bytes) -> None:
        if len(data) > 16384:
            raise ValueError("input chunk too large")
        with self._lock:
            if self._closed or self.poll() is not None:
                raise TerminalError("terminal has exited")
            count = wintypes.DWORD()
            if not self._kernel.WriteFile(
                self._input, ctypes.c_char_p(data), len(data),
                ctypes.byref(count), None
            ) or count.value != len(data):
                raise TerminalError("could not write to pseudoterminal")

    def resize(self, cols: int, rows: int) -> None:
        if not 20 <= cols <= 500 or not 5 <= rows <= 200:
            raise ValueError("invalid PTY size")
        with self._lock:
            if self._closed:
                raise TerminalError("terminal closed")
            hr = self._kernel.ResizePseudoConsole(self._hpc, COORD(cols, rows))
            if hr < 0:
                raise TerminalError(f"ResizePseudoConsole HRESULT 0x{hr & 0xffffffff:08x}")

    def poll(self) -> int | None:
        if not self._process:
            return self._exit_code
        if self._kernel.WaitForSingleObject(self._process, 0) == 0:
            value = wintypes.DWORD()
            if self._kernel.GetExitCodeProcess(self._process, ctypes.byref(value)):
                self._exit_code = int(ctypes.c_int32(value.value).value)
                self._job.close()
                return self._exit_code
        return None

    def wait(self, timeout: float = 2) -> int | None:
        self._kernel.WaitForSingleObject(self._process, max(0, int(timeout * 1000)))
        return self.poll()

    def close(self, graceful_seconds: float = 2, *, exit_input: bytes = b"exit\r") -> None:
        with self._lock:
            if self._closed:
                return
            if self.poll() is None:
                try:
                    self.write(exit_input)
                except (OSError, TerminalError):
                    pass
                if self.wait(graceful_seconds) is None:
                    self._kernel.TerminateProcess(self._process, 1)
                    self.wait(2)
            self._closed = True
            self._job.close()
            if self._hpc:
                self._kernel.ClosePseudoConsole(self._hpc)
                self._hpc = wintypes.HANDLE()
            if self._input:
                self._kernel.CloseHandle(self._input)
                self._input = wintypes.HANDLE()
            if self._output:
                self._kernel.CloseHandle(self._output)
                self._output = wintypes.HANDLE()
            if self._process:
                self._kernel.CloseHandle(self._process)
                self._process = wintypes.HANDLE()
