"""Loopback HTTP relay: bearer authentication, durable leases, bounded requests."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .protocol import ChatJob, ChatResult
from .job_store import JobStore


class RelayState(JobStore):
    WORKER_ONLINE_WINDOW_S = 15.0

    def __init__(self, extension_dir=None, db_path=":memory:"):
        super().__init__(db_path)
        self.extension_dir = extension_dir
        self._last_poll = {}
        self.started_at = time.time()

    def extension_version(self):
        root = Path(self.extension_dir) if self.extension_dir else None
        if not root:
            return {"version": None}
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            files = {name: {"sha": hashlib.sha256((root/name).read_bytes()).hexdigest()[:12]}
                     for name in ("service-worker.js", "content-script.js", "selectors.js", "observer.js")}
            return {"version": manifest["version"], "files": files}
        except (OSError, ValueError):
            return {"version": None, "error": "extension manifest unavailable"}

    def poll(self, worker=""):
        job = super().poll(worker)
        with self.lock:
            self._last_poll[worker] = time.time()
        return job

    def workers_online(self):
        with self.lock:
            return [w for w, t in self._last_poll.items() if time.time()-t <= self.WORKER_ONLINE_WINDOW_S]

    def workers_ever_seen(self):
        with self.lock:
            return len(self._last_poll)

    def wait(self, job_id, timeout_s):
        deadline = time.monotonic() + max(0, min(timeout_s, 25))
        while True:
            result = self.result(job_id)
            if result is not None or time.monotonic() >= deadline:
                return result
            time.sleep(.1)


def make_handler(state, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def _send(self, payload, code=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (OSError, TimeoutError):
                pass

        def log_message(self, *args):
            pass

        def _authorized(self):
            origin = self.headers.get("Origin", "")
            # A website, including chatgpt.com content scripts, cannot call the relay.
            if origin and not origin.startswith("chrome-extension://"):
                self._send({"error": "forbidden origin"}, 403)
                return False
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",
                                                 f"localhost:{self.server.server_port}"}:
                self._send({"error": "invalid host"}, 403)
                return False
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self._send({"error": "pairing token required"}, 401)
                return False
            return True

        def do_POST(self):
            if not self._authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 1048576:
                    return self._send({"error": "body must be 1..1048576 bytes"}, 413)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("JSON object required")
                if self.path == "/jobs/submit":
                    allowed = {"task_id", "prompt", "timeout_s", "new_chat", "conversation_url", "kind", "images"}
                    if set(data) - allowed:
                        raise ValueError("unknown job fields")
                    return self._send({"job_id": state.submit(ChatJob(**data))})
                if self.path == "/jobs/result":
                    lease_token = data.pop("lease_token", "")
                    state.store_result(ChatResult(**data), lease_token)
                elif self.path == "/jobs/progress":
                    info = state.progress(data["job_id"], data["worker"], data["lease_token"], data["phase"])
                    return self._send({"ok": True, **info})
                elif self.path == "/jobs/lease":
                    state.lease(data["job_id"], data["worker"], data["lease_token"])
                elif self.path == "/jobs/ack":
                    state.acknowledge(data["job_id"])
                elif self.path == "/jobs/cancel":
                    state.cancel(data["job_id"])
                else:
                    return self._send({"error": "not found"}, 404)
                return self._send({"ok": True})
            except (ValueError, TypeError, KeyError) as exc:
                return self._send({"error": str(exc)}, 400)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                return self._send({"ok": True, "authentication": "bearer",
                                   **state.counts(), "workers_online": state.workers_online(),
                                   "workers_ever_seen": state.workers_ever_seen(),
                                   "uptime_s": round(time.time()-state.started_at, 1)})
            if parsed.path == "/extension/version":
                return self._send(state.extension_version())
            if not self._authorized():
                return
            qs = parse_qs(parsed.query)
            try:
                if parsed.path == "/auth/check":
                    return self._send({"ok": True})
                if parsed.path == "/jobs/poll":
                    return self._send({"job": state.poll((qs.get("worker") or [""])[0])})
                if parsed.path == "/jobs/wait":
                    jid = (qs.get("job_id") or [""])[0]
                    timeout = float((qs.get("timeout_s") or ["20"])[0])
                    return self._send(state.wait(jid, timeout) or {"pending": True})
                return self._send({"error": "not found"}, 404)
            except ValueError as exc:
                return self._send({"error": str(exc)}, 400)

    return Handler


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound concurrent HTTP handler threads; slow local clients cannot spawn unbounded workers."""
    daemon_threads = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class RelayServer:
    def __init__(self, host="127.0.0.1", port=8765, extension_dir=None, token=None, db_path=":memory:"):
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("relay must bind loopback only")
        self.token = token or secrets.token_urlsafe(32)
        if len(self.token) < 32:
            raise ValueError("relay token must contain at least 32 characters")
        self.state = RelayState(extension_dir, db_path)
        try:
            self.server = BoundedHTTPServer((host, port), make_handler(self.state, self.token))
        except OSError:
            self.state.close()
            raise
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)
        self.state.close()
