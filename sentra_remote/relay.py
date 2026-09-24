"""Hosted/outbound relay HTTP surface for SENTRA Commander agents."""
from __future__ import annotations

import base64
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import RemoteStore


def _read_json(handler: BaseHTTPRequestHandler, *, limit: int = 2 * 1024 * 1024) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > limit:
        raise ValueError("invalid request body length")
    payload = json.loads(handler.rfile.read(length))
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def make_handler(store: RemoteStore):
    pairing_attempts: dict[str, list[float]] = {}
    pairing_lock = threading.Lock()

    def pairing_allowed(address: str) -> bool:
        now = time.monotonic()
        with pairing_lock:
            recent = [stamp for stamp in pairing_attempts.get(address, []) if now - stamp < 60.0]
            if len(recent) >= 12:
                pairing_attempts[address] = recent
                return False
            recent.append(now)
            pairing_attempts[address] = recent
            return True

    class Handler(BaseHTTPRequestHandler):
        server_version = "SentraRelay/1.0"

        def log_message(self, *args):
            return

        def _send(self, payload: dict, code: int = 200):
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _device_auth(self) -> tuple[str, str]:
            device_id = self.headers.get("X-Sentra-Device", "").strip()
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Device "):
                raise PermissionError("device credential required")
            token = auth[7:].strip()
            store.authenticate_device(device_id, token)
            return device_id, token

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                return self._send({"ok": True, "service": "sentra-relay"})
            try:
                device_id, token = self._device_auth()
                if parsed.path == "/v1/agent/jobs/poll":
                    job = store.poll_job(device_id, token)
                    return self._send({"job": None if job is None else {
                        "job_id": job.job_id,
                        "tool": job.tool,
                        "arguments": job.arguments,
                        "lease_token": job.lease_token,
                        "deadline": job.deadline,
                    }})
                return self._send({"error": "not found"}, 404)
            except PermissionError as exc:
                return self._send({"error": str(exc)}, 401)
            except Exception as exc:
                return self._send({"error": str(exc)}, 400)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/v1/pair":
                    if not pairing_allowed(str(self.client_address[0])):
                        return self._send({"error": "pairing rate limit exceeded"}, 429)
                    data = _read_json(self)
                    result = store.pair_device(str(data.get("pairing_code", "")), agent_name=data.get("name"))
                    return self._send(result, 201)

                device_id, token = self._device_auth()
                if parsed.path == "/v1/agent/heartbeat":
                    data = _read_json(self)
                    return self._send(store.heartbeat(device_id, token, data.get("capabilities") or {}))

                if parsed.path == "/v1/agent/token/rotate":
                    _read_json(self)
                    return self._send(store.rotate_device_token(device_id, token))

                if parsed.path == "/v1/agent/jobs/progress":
                    data = _read_json(self)
                    return self._send(store.progress(
                        device_id,
                        token,
                        str(data["job_id"]),
                        str(data["lease_token"]),
                        str(data["phase"]),
                    ))

                if parsed.path == "/v1/agent/jobs/result":
                    data = _read_json(self, limit=4 * 1024 * 1024)
                    store.complete_job(
                        device_id,
                        token,
                        str(data["job_id"]),
                        str(data["lease_token"]),
                        dict(data.get("result") or {}),
                        failed=bool(data.get("failed", False)),
                    )
                    return self._send({"ok": True})

                if parsed.path == "/v1/agent/jobs/chunk":
                    data = _read_json(self, limit=2 * 1024 * 1024)
                    raw = base64.b64decode(str(data["data_b64"]), validate=True)
                    store.put_result_chunk(
                        device_id,
                        token,
                        str(data["job_id"]),
                        str(data["lease_token"]),
                        int(data["index"]),
                        raw,
                        str(data["sha256"]),
                    )
                    return self._send({"ok": True})

                if parsed.path == "/v1/agent/jobs/finalize":
                    data = _read_json(self)
                    store.finalize_chunks(
                        device_id,
                        token,
                        str(data["job_id"]),
                        str(data["lease_token"]),
                        int(data["chunks"]),
                        str(data["sha256"]),
                        failed=bool(data.get("failed", False)),
                    )
                    return self._send({"ok": True})

                return self._send({"error": "not found"}, 404)
            except PermissionError as exc:
                return self._send({"error": str(exc)}, 401)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return self._send({"error": str(exc)}, 400)
            except Exception:
                return self._send({"error": "internal relay error"}, 500)

    return Handler


class BoundedRelayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, max_handlers: int = 64, **kwargs):
        self._slots = threading.BoundedSemaphore(max_handlers)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class RemoteRelayServer:
    """Threaded relay. Non-loopback binding requires TLS cert/key."""

    def __init__(
        self,
        store: RemoteStore,
        *,
        host: str = "127.0.0.1",
        port: int = 8787,
        tls_cert: str | Path | None = None,
        tls_key: str | Path | None = None,
    ) -> None:
        local = host in {"127.0.0.1", "::1", "localhost"}
        if not (1 <= int(port) <= 65535 or (int(port) == 0 and local)):
            raise ValueError("invalid relay port")
        if not local and not (tls_cert and tls_key):
            raise ValueError("non-loopback relay requires TLS certificate and key")
        self.store = store
        self.server = BoundedRelayHTTPServer((host, int(port)), make_handler(store))
        if tls_cert or tls_key:
            if not (tls_cert and tls_key):
                raise ValueError("both TLS certificate and key are required")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(tls_cert), str(tls_key))
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)

    def serve_forever(self) -> None:
        self.server.serve_forever(poll_interval=0.5)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
