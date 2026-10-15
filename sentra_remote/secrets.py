"""OS-local secret protection for SENTRA Commander agent credentials."""
from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes


_PREFIX_DPAPI = "dpapi:"
_PREFIX_KEYRING = "keyring:"
_PREFIX_PORTABLE = "portable:"  # legacy migration only; never written by current code


if os.name == "nt":
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    value = _DATA_BLOB(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return value, buffer


def protect_secret(value: str) -> str:
    if not value:
        return value
    if os.name != "nt":
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("non-Windows agent requires keyring for secure credential storage") from exc
        import secrets
        entry_id = secrets.token_urlsafe(24)
        keyring.set_password("SENTRA Commander", entry_id, value)
        return _PREFIX_KEYRING + entry_id

    raw = value.encode("utf-8")
    in_blob, _buffer = _blob(raw)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "SENTRA Commander Device Token",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
    return _PREFIX_DPAPI + base64.b64encode(protected).decode("ascii")


def unprotect_secret(value: str) -> str:
    if not value:
        return value
    if value.startswith(_PREFIX_KEYRING):
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("keyring is required to read this agent credential") from exc
        entry_id = value[len(_PREFIX_KEYRING):]
        secret = keyring.get_password("SENTRA Commander", entry_id)
        if secret is None:
            raise RuntimeError("agent credential is missing from the OS keyring")
        return secret
    if value.startswith(_PREFIX_PORTABLE):
        # Legacy migration only. Loading succeeds so the next save can move it into DPAPI/keyring.
        return base64.b64decode(value[len(_PREFIX_PORTABLE):], validate=True).decode("utf-8")
    if not value.startswith(_PREFIX_DPAPI):
        # Migration path for pre-DPAPI configs. The next save upgrades it.
        return value
    if os.name != "nt":
        raise RuntimeError("DPAPI-protected credential can only be opened on Windows")

    protected = base64.b64decode(value[len(_PREFIX_DPAPI):], validate=True)
    in_blob, _buffer = _blob(protected)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
    return raw.decode("utf-8")
