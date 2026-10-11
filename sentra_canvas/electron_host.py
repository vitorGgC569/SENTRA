"""Isolated Electron renderer using the existing authenticated SENTRA Canvas broker.

Electron for Windows has no reliable piped stdin. A single-use, time-limited
ticket file inside the current user's temp directory holds the credential
briefly; the process command line contains only the random ticket ID.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SURFACE = (Path(sys.executable).resolve().parent / "sentra-electron" if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parents[1] / "sentra_electron")


def electron_binary() -> Path | None:
    if os.name == "nt":
        candidates = (Path(sys.executable).resolve().parent / "sentra-electron" / "electron.exe",
                      SURFACE / "node_modules" / "electron" / "dist" / "electron.exe")
    else:
        candidates = (SURFACE / "node_modules" / "electron" / "dist" / "electron",)
    return next((path for path in candidates if path.is_file()), None)


def electron_status() -> dict[str, object]:
    return {"available": electron_binary() is not None,
            "renderer": "sentra_canvas", "authority": "existing_canvas_broker",
            "install_hint": "npm install --prefix sentra_electron"}


def launch_electron(endpoint, *, wait: bool = False) -> int:
    executable = electron_binary()
    entry = SURFACE / "main.cjs"
    if executable is None or not entry.is_file():
        raise FileNotFoundError("Electron surface unavailable; install sentra_electron dependencies")
    if not isinstance(endpoint.server_port, int) or not 1 <= endpoint.server_port <= 65535:
        raise ValueError("invalid local Canvas port")
    token = endpoint.secret
    if not isinstance(token, str) or len(token) < 32:
        raise PermissionError("missing authenticated Canvas broker credential")
    ticket = secrets.token_hex(16)
    path = Path(tempfile.gettempdir()) / ("sentra-electron-" + ticket + ".json")
    payload = {"schema": 1, "port": endpoint.server_port, "secret": token,
               "expires_at": int((time.time() + 20) * 1000)}
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(payload, stream, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    cleanup = threading.Timer(30, lambda: path.unlink(missing_ok=True))
    cleanup.daemon = True
    cleanup.start()
    try:
        process = subprocess.Popen(
            [str(executable), str(entry), "--sentra-ticket=" + ticket],
            cwd=SURFACE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if wait:
        return process.wait()
    return process.pid
