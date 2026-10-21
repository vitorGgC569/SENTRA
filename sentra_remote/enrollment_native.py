"""Native Messaging transport. No commands, browsing data or secrets are logged."""
from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
import time
from pathlib import Path

from .enrollment_bridge import CHROMIUM_ID, FIREFOX_ID, PROTOCOL, descriptor_path, read_frame, write_frame


def caller_family(arguments: list[str], install_dir: Path) -> str:
    if arguments and arguments[0] == f"chrome-extension://{CHROMIUM_ID}/":
        return "chromium"
    if (len(arguments) == 2 and arguments[1] == FIREFOX_ID
            and Path(arguments[0]).resolve() == (install_dir / "browser-enrollment/native-firefox.json").resolve()):
        return "firefox"
    raise PermissionError("native_caller_not_allowed")


def is_native_invocation(arguments):
    return bool(arguments and (arguments[0].startswith("chrome-extension://")
                or arguments[0].lower().endswith("native-firefox.json")))


def run_native(arguments: list[str], *, install_dir: Path | None = None) -> int:
    root = install_dir or Path(sys.executable).resolve().parent
    try:
        family = caller_family(arguments, root)
        config = root / "browser-enrollment/native-config.json"
        if config.is_symlink() or config.stat().st_size > 8192 or not (root / ".sentra-install.json").is_file():
            return 2
        value = json.loads(config.read_text(encoding="utf-8"))
        if value.get("protocol") != PROTOCOL:
            return 2
        state = Path(value["state_dir"])
        if not state.is_absolute():
            return 2
        # Windows text translation must not modify the Native Messaging frames.
        if os.name == "nt":
            import msvcrt
            for stream in (sys.stdin, sys.stdout):
                msvcrt.setmode(stream.fileno(), os.O_BINARY)
        return transport(state, family, sys.stdin.buffer, sys.stdout.buffer)
    except Exception:
        return 2  # Exception strings can include confidential transport material.


def transport(state, family, source, destination, *, idle_timeout=1800):
    incoming = queue.Queue(maxsize=16)
    stopped = threading.Event()

    def receive():
        try:
            while not stopped.is_set():
                value = read_frame(source)
                if value is None:
                    return
                incoming.put(value, timeout=5)
        except Exception:
            pass
        finally:
            stopped.set()
    threading.Thread(target=receive, daemon=True).start()
    connection = None
    try:
        hello = incoming.get(timeout=10)
        if hello.get("protocol") != PROTOCOL:
            return 2
        write_frame(destination, {"status": "waiting_for_setup"})
        deadline = time.monotonic() + idle_timeout
        while not stopped.is_set() and time.monotonic() < deadline:
            try:
                from .secrets import unprotect_secret
                path = descriptor_path(state)
                if path.is_symlink() or path.stat().st_size > 16384:
                    raise ValueError("descriptor_invalid")
                protected = path.read_text(encoding="utf-8")
                if not protected.startswith("dpapi:"):
                    raise ValueError("descriptor_not_protected")
                session = json.loads(unprotect_secret(protected))
                if (session.get("protocol") != PROTOCOL or type(session.get("port")) is not int
                        or not 1 <= session["port"] <= 65535 or not isinstance(session.get("secret"), str)
                        or not time.time() < float(session["expires"]) <= time.time() + 1805):
                    raise ValueError("descriptor_expired")
                connection = socket.create_connection(("127.0.0.1", session["port"]), timeout=2)
                break
            except (OSError, ValueError, KeyError, RuntimeError):
                stopped.wait(1)
        if connection is None:
            return 0
        with connection, connection.makefile("rwb", buffering=0) as channel:
            connection.settimeout(None)
            write_frame(channel, {"protocol": PROTOCOL, "family": family,
                                  "platform_tab": hello.get("platform_tab") is True, "secret": session["secret"]})
            session.clear()
            write_frame(destination, {"status": "connected"})

            def forward():
                try:
                    while not stopped.is_set():
                        try:
                            value = incoming.get(timeout=0.5)
                        except queue.Empty:
                            continue
                        write_frame(channel, value)
                except Exception:
                    pass
                finally:
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            threading.Thread(target=forward, daemon=True).start()
            while not stopped.is_set():
                value = read_frame(channel)
                if value is None:
                    break
                write_frame(destination, value)
        return 0
    finally:
        stopped.set()
        if connection is not None:
            connection.close()
