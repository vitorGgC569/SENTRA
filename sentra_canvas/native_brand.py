"""Apply the official SENTRA icon to the Windows WebView2 HWND/taskbar.

pywebview creates a Windows Form; the EXE resource icon and the actual HWND
icon are separate. This callback only targets the current process' SENTRA
top-level window, never another running SENTRA Canvas instance.
"""
from __future__ import annotations

import os
from pathlib import Path

_ICON_HANDLES: list[int] = []  # Icon HICONs must stay alive until process exit.


def icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "SENTRA.ico"


def apply_native_icon() -> bool:
    if os.name != "nt":
        return False
    source = icon_path()
    if not source.is_file():
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                  wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM

    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
    big = user32.LoadImageW(None, str(source), IMAGE_ICON, 64, 64, LR_LOADFROMFILE)
    small = user32.LoadImageW(None, str(source), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
    if not big or not small:
        return False
    current_pid = os.getpid()
    applied = False
    ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @ENUM
    def visit(hwnd, _):
        nonlocal applied
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != current_pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if title.value != "SENTRA":
            return True
        user32.SendMessageW(hwnd, WM_SETICON, 1, int(big))
        user32.SendMessageW(hwnd, WM_SETICON, 0, int(small))
        applied = True
        return False

    user32.EnumWindows(visit, 0)
    if applied:
        _ICON_HANDLES.extend([int(big), int(small)])
    else:
        user32.DestroyIcon(big)
        user32.DestroyIcon(small)
    return applied
