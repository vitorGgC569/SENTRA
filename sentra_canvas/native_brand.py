"""Apply the Dot desktop identity to the Windows WebView2 HWND/taskbar.

pywebview creates a Windows Form; the EXE resource icon and the actual HWND
icon are separate. This callback only targets the current process' SENTRA
top-level window, never another running SENTRA Canvas instance.
"""
from __future__ import annotations

import os
from pathlib import Path

_ICON_HANDLES: list[int] = []  # Icon HICONs must stay alive until process exit.
APP_USER_MODEL_ID = "SENTRA.Desktop"


def icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "SENTRA-DOT.ico"


def configure_taskbar_identity() -> bool:
    """Set identity before creating the HWND so Windows separates it from Python."""
    if os.name != "nt":
        return False
    import ctypes
    setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_long
    return setter(APP_USER_MODEL_ID) == 0


def _window_taskbar_properties(hwnd, source, *, app_id=APP_USER_MODEL_ID,
                               display_name="SENTRA", relaunch_command=None):
    """Override the packaged Python identity on this HWND, including pin artwork.

    A process AppUserModelID alone does not replace the Windows Store Python
    window properties. Explorer also needs the relaunch command/name/icon.
    """
    import ctypes
    import subprocess
    import sys
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]
    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]
    class VALUE(ctypes.Union):
        _fields_ = [("pointer", ctypes.c_void_p), ("padding", ctypes.c_ubyte * (16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8))]
    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("value", VALUE)]
    def guid(value):
        return GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))
    store = ctypes.c_void_p()
    initialized = ctypes.windll.ole32.CoInitializeEx(None, 2) in (0, 1)
    getter = ctypes.windll.shell32.SHGetPropertyStoreForWindow
    getter.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    getter.restype = ctypes.c_long
    iid = guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
    if getter(hwnd, ctypes.byref(iid), ctypes.byref(store)) != 0:
        if initialized:
            ctypes.windll.ole32.CoUninitialize()
        return False
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    setter = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    root = Path(__file__).resolve().parents[1]
    arguments = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-B", "-m", "sentra_canvas"]
    command = relaunch_command or subprocess.list2cmdline([*arguments, "--ui", "auto"] if getattr(sys, "frozen", False)
                 else [*arguments, "--root", str(root), "--ui", "native", "--surface", "shell-home"])
    fmtid = guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")
    try:
        # All three relaunch properties must accompany a custom icon resource.
        for pid, text in ((2, command), (3, str(source) + ",0"), (4, display_name), (5, app_id)):
            key = PROPERTYKEY(fmtid, pid)
            buffer = ctypes.create_unicode_buffer(text)
            value = PROPVARIANT()
            value.vt = 31  # VT_LPWSTR; SetValue copies the string.
            value.value.pointer = ctypes.cast(buffer, ctypes.c_void_p).value
            if setter(store, ctypes.byref(key), ctypes.byref(value)) != 0:
                return False
        return commit(store) == 0
    finally:
        release(store)
        if initialized:
            ctypes.windll.ole32.CoUninitialize()


def apply_native_icon() -> bool:
    if os.name != "nt":
        return False
    source = icon_path()
    if not source.is_file():
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                  wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    class_icon = getattr(user32, "SetClassLongPtrW", user32.SetClassLongW)
    class_icon.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    class_icon.restype = ctypes.c_void_p

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
        taskbar_applied = _window_taskbar_properties(hwnd, source)
        import logging
        logging.getLogger(__name__).info("Windows taskbar identity applied: %s", taskbar_applied)
        user32.SendMessageW(hwnd, WM_SETICON, 1, int(big))
        user32.SendMessageW(hwnd, WM_SETICON, 0, int(small))
        class_icon(hwnd, -14, big)   # GCLP_HICON: Explorer's fallback class artwork.
        class_icon(hwnd, -34, small) # GCLP_HICONSM.
        applied = True
        return False

    user32.EnumWindows(visit, 0)
    if applied:
        _ICON_HANDLES.extend([int(big), int(small)])
    else:
        user32.DestroyIcon(big)
        user32.DestroyIcon(small)
    return applied
