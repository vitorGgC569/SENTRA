"""One native SENTRA Dot window per Windows interactive session.

DOT_WINDOW_MUTEX is the Dot window identity. It is not an installation id
and it is not a frontend code reload. A second launch focuses the existing
SENTRA window instead of opening another one. The Canvas broker remains
independently managed by connect_or_start.
"""
from __future__ import annotations
from contextlib import contextmanager
import os

DOT_WINDOW_MUTEX = "Local\\SENTRA.Dot.Native.Window"
WINDOW_OWNER_PROPERTY = "SENTRA.Dot.Window.OwnerPID"


def mark_native_window(window) -> bool:
    """Identify this display for reactivation without an optional psutil import."""
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    user = ctypes.windll.user32
    user.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
    user.SetPropW.restype = wintypes.BOOL
    return bool(user.SetPropW(window.native.Handle.ToInt64(), WINDOW_OWNER_PROPERTY, os.getpid()))


def unmark_native_window(window) -> None:
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        user.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        user.RemovePropW.restype = wintypes.HANDLE
        user.RemovePropW(window.native.Handle.ToInt64(), WINDOW_OWNER_PROPERTY)


def dot_window_identity() -> dict:
    return {"kind": "dot_identity", "mutex": DOT_WINDOW_MUTEX,
            "installation_id": None, "code_reload": False}


def focus_existing_window() -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    user = ctypes.windll.user32
    user.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user.GetPropW.restype = wintypes.HANDLE
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd):
            return True
        length = user.GetWindowTextLengthW(hwnd)
        if length != len("SENTRA"):
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user.GetWindowTextW(hwnd, title, length + 1)
        if title.value != "SENTRA":
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        owned = user.GetPropW(hwnd, WINDOW_OWNER_PROPERTY) == pid.value
        if not owned:
            # Compatibility for older displays that predate the window marker.
            try:
                import psutil
            except ImportError:
                owned = False
            else:
                try:
                    process = psutil.Process(pid.value)
                    arguments = " ".join(process.cmdline()).casefold()
                    image_name = process.name().casefold()
                    owned = ("sentra_canvas" in arguments or
                             image_name in {"sentra-canvas.exe", "sentra-desktop.exe"})
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    owned = False
        if owned:
            found.append(hwnd)
            return False
        return True

    user.EnumWindows(visit, 0)
    if not found:
        return False
    user.ShowWindow(found[0], 9)  # SW_RESTORE
    user.SetForegroundWindow(found[0])
    return True


@contextmanager
def single_native_window():
    if os.name != "nt":
        yield True
        return
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.GetLastError.restype = ctypes.c_ulong
    kernel.SetLastError(0)
    mutex = kernel.CreateMutexW(None, True, DOT_WINDOW_MUTEX)
    if not mutex:
        raise OSError("Não foi possível reservar a janela nativa do SENTRA")
    if kernel.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle(mutex)
        focus_existing_window()
        yield False
        return
    try:
        yield True
    finally:
        kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)
