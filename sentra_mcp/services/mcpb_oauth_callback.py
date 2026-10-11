"""One-use OAuth loopback callback bound to an authenticated host session.

Owner, session and approval are verified by a trusted host callback, never by
the browser query, cookies or model-supplied booleans. The only network listener
binds to the exact approved literal loopback port; it does not log auth codes.
"""
from __future__ import annotations

import hmac
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .mcpb_oauth import OAuthAdmissionError, _loopback


class OAuthLoopbackReceiver:
    def __init__(self, broker, *, owner, workspace, server_id, host_session,
                 consent_ref, verify_host_consent, exchange):
        if not callable(verify_host_consent) or not callable(exchange):
            raise OAuthAdmissionError("trusted owner-session consent and exchange required")
        target = urlsplit(_loopback(broker.redirect_uri))
        if target.hostname != "127.0.0.1":
            raise OAuthAdmissionError("IPv4 literal loopback callback required")
        if not all(isinstance(x, str) and 1 <= len(x) <= 256
                   for x in (host_session, consent_ref)):
            raise OAuthAdmissionError("host session and approval reference required")
        self.broker, self.owner, self.workspace = broker, owner, workspace
        self.server_id, self.host_session, self.consent_ref = server_id, host_session, consent_ref
        self.verify_host_consent, self.exchange = verify_host_consent, exchange
        self._path, self._port = target.path, target.port
        self._lock = threading.RLock()
        self._active, self._attempted = False, False
        self._server, self._thread, self.authorization = None, None, None
        self._outcome = None

    def _authorize(self):
        try:
            return self.verify_host_consent(
                self.owner, self.workspace, self.server_id,
                self.host_session, self.consent_ref) is True
        except Exception:
            return False

    def start(self):
        with self._lock:
            if self._active or self._attempted or not self._authorize():
                raise OAuthAdmissionError("operator consent/session unavailable")
            owner = self

            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def do_GET(self):
                    owner._receive(self)

                def do_POST(self):
                    owner._deny(self)

            try:
                listener = ThreadingHTTPServer(("127.0.0.1", self._port), Callback)
                listener.daemon_threads = True
                listener.timeout = 2
                self._server = listener
                self.authorization = self.broker.begin(
                    self.owner, self.workspace, self.server_id, approved=True)
                self._active = True
                self._thread = threading.Thread(
                    target=listener.serve_forever, kwargs={"poll_interval": 0.05},
                    daemon=True, name="sentra-oauth-loopback")
                self._thread.start()
                return dict(self.authorization)
            except BaseException:
                self._attempted = True
                if self._server is not None:
                    self._server.server_close()
                    self._server = None
                raise

    def _deny(self, handler, status=403):
        handler.send_response(status)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Pragma", "no-cache")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("Content-Security-Policy", "default-src 'none'")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", "18")
        handler.end_headers()
        handler.wfile.write(b"Request not valid\n")

    def _receive(self, handler):
        remote = handler.client_address[0]
        host = handler.headers.get("Host", "")
        valid_host = f"127.0.0.1:{self._port}"
        if (remote != "127.0.0.1" or not hmac.compare_digest(host, valid_host)
                or handler.headers.get("Origin") is not None
                or handler.headers.get("Cookie") is not None
                or handler.headers.get("Referer") is not None
                or handler.headers.get("Transfer-Encoding") is not None
                or (handler.headers.get("Sec-Fetch-Mode") not in (None, "navigate"))
                or len(handler.path) > 4096
                or handler.path.split("?", 1)[0] != self._path):
            self._deny(handler)
            return
        try:
            query = urlsplit(handler.path)
            values = parse_qs(query.query, strict_parsing=True, keep_blank_values=True,
                              max_num_fields=3, errors="strict")
            if set(values) != {"state", "code"} or any(len(v) != 1 for v in values.values()):
                raise ValueError("ambiguous OAuth callback")
            state, code = values["state"][0], values["code"][0]
            with self._lock:
                if (not self._active or self._attempted or not self._authorize()
                        or not hmac.compare_digest(state, self.authorization["state"])):
                    raise OAuthAdmissionError("OAuth callback session/state denied")
                # Consume first, before transport: failure is UNCERTAIN, never replay.
                self._attempted = True
            self._outcome = self.broker.finish(
                self.owner, self.workspace, self.server_id,
                state=state, code=code, exchange=self.exchange, approved=True)
        except Exception:
            with self._lock:
                self._attempted = True
            self._deny(handler)
            return
        body = b"Authorization completed. Return to SENTRA.\n"
        handler.send_response(200)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("Content-Security-Policy", "default-src 'none'")
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def status(self):
        with self._lock:
            return {"active": self._active, "consumed": self._attempted,
                    "approved": self._outcome is not None, "credentials_exposed": False}

    def close(self):
        with self._lock:
            server, thread = self._server, self._thread
            self._active = False
            self._server, self._thread = None, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
