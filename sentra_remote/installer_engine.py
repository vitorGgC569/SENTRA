"""Translate internal update calls for native Inno media and legacy workers."""
from __future__ import annotations

import os
from pathlib import Path


def original_filename(path: Path) -> str:
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    ignored = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not size or size > 1024 * 1024:
        return ""
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        return ""
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(data, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        return ""
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
    translations = [(words[i], words[i + 1]) for i in range(0, length.value // 2 - 1, 2)]
    for language, codepage in translations:
        key = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\OriginalFilename"
        if version.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length)) and 0 < length.value < 512:
            # Inno's version-resource slot is padded with spaces, not only NULs.
            return ctypes.wstring_at(pointer, length.value).rstrip("\0 ")
    return ""


def install_command(installer: Path, arguments: list[str]) -> list[str]:
    # This is format dispatch only. Signature, admission and offline handoff
    # checks remain the caller's authority, before any installer is executed.
    if original_filename(installer) != "SENTRA-Inno-Setup.exe":
        return [str(installer), *arguments]
    values = {"--install-dir": "DIR", "--state-dir": "SENTRA-STATE-DIR",
              "--offline-handoff": "SENTRA-HANDOFF", "--mcp-port": "SENTRA-MCP-PORT",
              "--relay-port": "SENTRA-RELAY-PORT", "--tunnel-archive": "SENTRA-TUNNEL-ARCHIVE"}
    flags = {"--no-launch": "NO-LAUNCH", "--no-system-registration": "SENTRA-NO-REGISTRATION",
             "--stop-after-doctor": "SENTRA-STOP-AFTER-DOCTOR"}
    result = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    args = iter(arguments)
    for argument in args:
        if argument in values:
            value = next(args, None)
            if value is None or '"' in value or "\0" in value:
                raise ValueError("invalid native installer argument")
            result.append("/" + values[argument] + "=" + value)
        elif argument in flags:
            result.append("/" + flags[argument])
        elif argument not in {"--silent", "--upgrade", "--no-git", "--local-only"}:
            raise ValueError("unsupported native installer argument")
    return result
