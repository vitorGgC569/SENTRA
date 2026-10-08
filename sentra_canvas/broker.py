"""Persistent local Canvas owner, independent of the native window lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from sentra_remote.secrets import protect_secret, unprotect_secret

from .instance_lock import InstanceLock


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


@dataclass(frozen=True)
class Endpoint:
    server_port: int
    secret: str = field(repr=False)
    runtime_id: str
    pid: int

    def request(self, path, body=None):
        if path not in {"/api/health", "/api/runtime/shutdown"}:
            raise ValueError("unsupported broker control endpoint")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server_port}{path}",
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.secret,
                     "Content-Type": "application/json"},
        )
        # A local authenticated request must never inherit environment proxies.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=1) as response:
            return json.loads(response.read(16384))


def _endpoint_file(state_dir):
    return Path(state_dir) / "broker.json"


def read_endpoint(state_dir):
    try:
        payload = json.loads(_endpoint_file(state_dir).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return None
        if payload.get("state_dir") != str(Path(state_dir).resolve()):
            return None
        port, pid = payload.get("port"), payload.get("pid")
        token = payload.get("protected_token", "")
        identity = payload.get("runtime_id", "")
        if (type(port) is not int or not 1 <= port <= 65535
                or type(pid) is not int or pid <= 0
                or not isinstance(identity, str) or len(identity) != 32
                or not isinstance(token, str) or not token.startswith(("dpapi:", "keyring:"))):
            return None
        endpoint = Endpoint(port, unprotect_secret(token), identity, pid)
        if len(endpoint.secret) < 32:
            return None
        health = endpoint.request("/api/health")
        if (isinstance(health, dict) and health.get("ok") and health.get("runtime_id") == endpoint.runtime_id
                and health.get("pid") == endpoint.pid
                and health.get("state_dir") == str(Path(state_dir).resolve())):
            return endpoint
    except (OSError, ValueError, TypeError, RuntimeError, urllib.error.URLError):
        return None
    return None


def publish_endpoint(server):
    state = server.canvas.state_dir
    protected = protect_secret(server.secret)
    if not protected.startswith(("dpapi:", "keyring:")):
        raise RuntimeError("Canvas broker requires OS protected credentials")
    payload = {"schema_version": 1, "port": server.server_port,
               "pid": os.getpid(), "runtime_id": server.runtime_id,
               "state_dir": str(state.resolve()), "protected_token": protected}
    fd, name = tempfile.mkstemp(prefix="broker.", suffix=".tmp", dir=state)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(_endpoint_file(state))
    finally:
        temporary.unlink(missing_ok=True)


def remove_endpoint(server):
    path = _endpoint_file(server.canvas.state_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("runtime_id") == server.runtime_id:
            path.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        pass


def broker_command(arguments):
    if getattr(sys,"frozen",False):
        executable=Path(sys.executable).resolve().parent/"sentra-canvas.exe"
        if not executable.is_file():raise FileNotFoundError("Canvas executable is not installed; repair SENTRA")
        return [str(executable),*arguments]
    return [sys.executable,"-m","sentra_canvas",*arguments]


def connect_or_start(root, state_dir=None, *, port=0, timeout=15):
    """Reuse the authenticated owner or start exactly one hidden local owner."""
    root = Path(root).resolve()
    state = Path(state_dir).resolve() if state_dir is not None else root / ".sentra" / "canvas"
    state.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        endpoint = read_endpoint(state)
        if endpoint:
            return endpoint
        try:
            lock = InstanceLock(state / "launch.lock")
        except RuntimeError:
            time.sleep(.1)
            continue
        try:
            # A concurrent launcher may have published while we took the lock.
            endpoint = read_endpoint(state)
            if endpoint:
                return endpoint
            arguments = ["--root", str(root), "--state-dir", str(state),
                         "--broker", "--port", str(port)]
            command = broker_command(arguments)
            process = subprocess.Popen(
                command, cwd=root if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            while time.monotonic() < deadline:
                endpoint = read_endpoint(state)
                if endpoint:
                    return endpoint
                if process.poll() is not None:
                    raise RuntimeError("Canvas broker could not start; inspect installation and state directory")
                time.sleep(.1)
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            raise RuntimeError("Canvas broker did not become ready")
        finally:
            lock.close()
    raise RuntimeError("Canvas broker startup is already in progress")
