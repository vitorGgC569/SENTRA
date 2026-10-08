"""Loopback HTTP relay: bearer authentication, durable leases, bounded requests."""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .bootstrap import bootstrap_proof, extension_identity, write_extension_bootstrap
from .protocol import ChatJob, ChatResult
from .job_store import JobStore


class RelayState(JobStore):
    WORKER_ONLINE_WINDOW_S = 45.0
    EXTENSION_ONLINE_WINDOW_S = 90.0
    POOL_LEASE_WINDOW_S = 45.0

    def __init__(self, extension_dir=None, db_path=":memory:"):
        super().__init__(db_path)
        self.extension_dir = extension_dir
        self._last_poll = {}
        self._worker_status = {}
        self._extension_seen = 0.0
        self._extension_status = {}
        self._pool_owner = None
        self._pool_seen = 0.0
        self._bootstrap_successes = 0
        self._bootstrap_failures = 0
        self._bootstrap_last_seen = None
        self.started_at = time.time()

    def extension_version(self):
        root = Path(self.extension_dir) if self.extension_dir else None
        if not root:
            return {"version": None}
        try:
            return extension_identity(root)
        except (OSError, ValueError, KeyError):
            return {"version": None, "error": "extension manifest unavailable or stale"}

    def note_bootstrap(self, success: bool) -> None:
        with self.lock:
            self._bootstrap_last_seen = time.time()
            if success:
                self._bootstrap_successes += 1
            else:
                self._bootstrap_failures += 1

    def bootstrap_status(self) -> dict:
        with self.lock:
            return {
                "successes": self._bootstrap_successes,
                "failures": self._bootstrap_failures,
                "last_seen": self._bootstrap_last_seen,
            }

    def mark_extension(self, status=None):
        if status is not None and not isinstance(status, dict):
            raise ValueError("extension status must be an object")
        with self.lock:
            self._extension_seen = time.time()
            if isinstance(status, dict):
                self._extension_status = dict(status)

    def extension_status(self):
        with self.lock:
            last_seen = float(self._extension_seen or 0.0)
            status = dict(self._extension_status or {})
        age_s = (time.time() - last_seen) if last_seen else None
        return {
            "online": bool(last_seen and age_s is not None and age_s <= self.EXTENSION_ONLINE_WINDOW_S),
            "last_seen": last_seen or None,
            "age_s": round(age_s, 3) if age_s is not None else None,
            "status": status,
        }

    def mark_worker(self, worker="", status=None):
        if not isinstance(worker, str) or not worker.startswith("TAB-"):
            raise ValueError("invalid worker identity")
        if status is not None and not isinstance(status, dict):
            raise ValueError("worker status must be an object")
        with self.lock:
            self._last_poll[worker] = time.time()
            if isinstance(status, dict):
                self._worker_status[worker] = status

    def worker_status(self, worker):
        if not isinstance(worker, str) or not worker.startswith("TAB-"):
            raise ValueError("invalid worker identity")
        with self.lock:
            last_seen = self._last_poll.get(worker)
            status = dict(self._worker_status.get(worker) or {})
        online = bool(
            last_seen is not None
            and time.time() - last_seen <= self.WORKER_ONLINE_WINDOW_S
        )
        return {
            "worker": worker,
            "online": online,
            "last_seen": last_seen,
            "status": status,
        }

    def poll(self, worker=""):
        job = super().poll(worker)
        if worker:
            self.mark_worker(worker)
        return job

    def workers_online(self):
        with self.lock:
            return [
                w for w, t in self._last_poll.items()
                if time.time() - t <= self.WORKER_ONLINE_WINDOW_S
            ]

    def release_worker(self, worker=""):
        if not isinstance(worker, str) or not worker.startswith("TAB-"):
            raise ValueError("invalid worker identity")
        with self.lock:
            # Keep the key so workers_ever_seen remains monotonic for diagnostics,
            # but make the worker immediately offline and clear cached UI status.
            self._last_poll[worker] = 0.0
            self._worker_status.pop(worker, None)

    def workers_ever_seen(self):
        with self.lock:
            return len(self._last_poll)

    def claim_pool(self, instance_id: str) -> dict:
        if not isinstance(instance_id, str) or not instance_id.startswith("POOL-") or len(instance_id) > 120:
            raise ValueError("invalid pool instance identity")
        now = time.time()
        with self.lock:
            expired = (
                self._pool_owner is None
                or now - self._pool_seen > self.POOL_LEASE_WINDOW_S
            )
            if expired or self._pool_owner == instance_id:
                self._pool_owner = instance_id
                self._pool_seen = now
                leader = True
            else:
                leader = False
            return {
                "leader": leader,
                "owner": self._pool_owner,
                "lease_window_s": self.POOL_LEASE_WINDOW_S,
            }

    def pool_status(self) -> dict:
        now = time.time()
        with self.lock:
            active = (
                self._pool_owner is not None
                and now - self._pool_seen <= self.POOL_LEASE_WINDOW_S
            )
            return {
                "active": active,
                "owner": self._pool_owner if active else None,
                "lease_window_s": self.POOL_LEASE_WINDOW_S,
            }

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

        def _read_json(self, maximum=1048576):
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= int(maximum):
                self._send({"error": f"body must be 1..{int(maximum)} bytes"}, 413)
                return None
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            return data

        def _bootstrap(self, data):
            origin = self.headers.get("Origin", "")
            extension_id = (
                origin.removeprefix("chrome-extension://")
                if origin.startswith("chrome-extension://")
                else ""
            )
            if (
                len(extension_id) != 32
                or any(ch < "a" or ch > "p" for ch in extension_id)
            ):
                state.note_bootstrap(False)
                return self._send({"error": "forbidden extension origin"}, 403)
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",
                                                 f"localhost:{self.server.server_port}"}:
                state.note_bootstrap(False)
                return self._send({"error": "invalid host"}, 403)
            identity = state.extension_version()
            if not identity.get("version"):
                state.note_bootstrap(False)
                return self._send({"error": "extension identity unavailable"}, 503)
            supplied = {
                "schema_version": data.get("schema_version"),
                "extension_version": data.get("extension_version"),
                "build_id": data.get("build_id"),
                "source_hash": data.get("source_hash"),
            }
            expected_identity = {
                "schema_version": 1,
                "extension_version": identity.get("version"),
                "build_id": identity.get("build_id"),
                "source_hash": identity.get("source_hash"),
            }
            if supplied != expected_identity:
                state.note_bootstrap(False)
                return self._send({"error": "extension identity mismatch",
                                   "expected": expected_identity}, 409)
            proof = str(data.get("proof") or "")
            expected_proof = bootstrap_proof(token, identity)
            if not proof or not secrets.compare_digest(proof, expected_proof):
                state.note_bootstrap(False)
                return self._send({"error": "extension bootstrap proof required"}, 401)
            state.note_bootstrap(True)
            return self._send({"ok": True, "token": token, **expected_identity})

        def do_POST(self):
            try:
                if self.path == "/auth/bootstrap":
                    data = self._read_json(8192)
                    if data is None:
                        return
                    return self._bootstrap(data)
                if not self._authorized():
                    return
                data = self._read_json()
                if data is None:
                    return
                if self.path == "/extension/heartbeat":
                    state.mark_extension(data.get("status"))
                    return self._send({"ok": True, "extension": state.extension_status()})
                if self.path == "/workers/heartbeat":
                    worker = str(data.get("worker") or "")
                    status = data.get("status")
                    state.mark_worker(worker, status)
                    return self._send({"ok": True})
                if self.path == "/workers/pool-claim":
                    instance_id = str(data.get("instance_id") or "")
                    return self._send({"ok": True, **state.claim_pool(instance_id)})
                if self.path == "/workers/release":
                    worker = str(data.get("worker") or "")
                    state.release_worker(worker)
                    return self._send({"ok": True, "released": True})
                if self.path == "/jobs/submit":
                    allowed = {
                        "task_id", "prompt", "timeout_s", "new_chat",
                        "conversation_url", "kind", "images", "target_worker",
                        "browser_action", "browser_args", "project_id",
                        "project_url", "chat_title", "provider", "model",
                    }
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
                                   "extension": state.extension_status(),
                                   "pool": state.pool_status(),
                                   "bootstrap": state.bootstrap_status(),
                                   "uptime_s": round(time.time()-state.started_at, 1)})
            if parsed.path == "/extension/version":
                identity = state.extension_version()
                bootstrap_refreshed = None
                if state.extension_dir:
                    try:
                        write_extension_bootstrap(Path(state.extension_dir), token)
                        bootstrap_refreshed = True
                    except (OSError, ValueError, KeyError):
                        bootstrap_refreshed = False
                return self._send({
                    **identity,
                    "bootstrap_refreshed": bootstrap_refreshed,
                })
            if not self._authorized():
                return
            qs = parse_qs(parsed.query)
            try:
                if parsed.path == "/auth/check":
                    return self._send({"ok": True})
                if parsed.path == "/workers/status":
                    worker = (qs.get("worker") or [""])[0]
                    return self._send(state.worker_status(worker))
                if parsed.path == "/jobs/poll":
                    return self._send({"job": state.poll((qs.get("worker") or [""])[0])})
                if parsed.path == "/jobs/wait":
                    jid = (qs.get("job_id") or [""])[0]
                    timeout = float((qs.get("timeout_s") or ["20"])[0])
                    result = state.wait(jid, timeout)
                    if result is not None:
                        return self._send(result)
                    status = state.pending_status(jid)
                    return self._send({"pending": True, **status})
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
        if extension_dir is not None:
            write_extension_bootstrap(Path(extension_dir), self.token)
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
