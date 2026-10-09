"""Lifecycle of the owned Hocuspocus sidecar; no inherited authority environment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading

from .owned_process import TaskProcess


class CollaborationProcess:
    def __init__(self, *, port: int, secret: str, node_executable=None, timeout_seconds=8):
        node = node_executable or shutil.which("node")
        folder = Path(__file__).resolve().parent.parent / "sentra_collab"
        if not node or not (folder / "node_modules/@hocuspocus/server").is_dir():
            raise RuntimeError("Install Node.js 24 and run npm ci in sentra_collab")
        if not (Path(__file__).parent / "static/vendor/sentra-collab-runtime.js").is_file():
            raise RuntimeError("Build the collaboration browser runtime with npm run build:browser in sentra_collab")
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
                                          "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA"}}
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.child = TaskProcess([str(node), str(folder / "central_sidecar.mjs")],
            cwd=str(folder), env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **options)
        self._lock = threading.RLock()
        self._closed = False
        ready = queue.Queue(maxsize=1)
        def stdout():
            try:
                line = self.child.process.stdout.readline(4097)
                ready.put_nowait(line if len(line) <= 4096 else b"")
                # Drain unexpected diagnostics without retaining or displaying credentials.
                while self.child.process.stdout.read(4096):
                    pass
            except (OSError, ValueError, queue.Full):
                pass
        def stderr():
            try:
                while self.child.process.stderr.read(4096):
                    pass
            except (OSError, ValueError):
                pass
        self._readers = [threading.Thread(target=fn, daemon=True, name="sentra-collab-output")
                         for fn in (stdout, stderr)]
        for thread in self._readers:
            thread.start()
        try:
            config = {"url": f"http://127.0.0.1:{port}/api/collab/host", "token": secret,
                      "allowedOrigins": [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]}
            self.child.process.stdin.write((json.dumps(config) + "\n").encode())
            self.child.process.stdin.flush()
            value = json.loads(ready.get(timeout=timeout_seconds))
            if value.get("ready") is not True or not re.fullmatch(r"ws://127\.0\.0\.1:[0-9]{1,5}", value.get("url", "")):
                raise RuntimeError("invalid collaboration process readiness")
            self.url = value["url"]
        except BaseException as exc:
            self.close()
            raise RuntimeError("collaboration sidecar could not start") from exc

    def status(self):
        with self._lock:
            active = not self._closed and self.child.poll() is None
            return {"available": active, "url": self.url if active else None}

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.child.terminate_tree()
                self.child.process.wait(timeout=5)
            finally:
                for stream in (self.child.process.stdin, self.child.process.stdout, self.child.process.stderr):
                    if stream:
                        stream.close()
