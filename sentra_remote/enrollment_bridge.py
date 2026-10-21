"""A short-lived, Windows-user-protected bridge to installed WebExtensions.

The browser owns authentication. Only installer-owned tabs are controllable;
cookies, profile databases and arbitrary JavaScript are outside the protocol.
"""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Any

PROTOCOL = 1
MAX_MESSAGE = 262144
HOST_NAME = "com.sentra.enrollment"
CHROMIUM_ID = "adjhmomkohbombfkfgngjbdfdehoiglg"
FIREFOX_ID = "enrollment@sentra.local"


def read_frame(stream) -> dict | None:
    def exact(size, allow_eof=False):
        chunks = bytearray()
        while len(chunks) < size:
            data = stream.read(size - len(chunks))
            if not data:
                if not chunks and allow_eof:
                    return None
                raise ValueError("bridge_truncated_message")
            chunks.extend(data)
        return bytes(chunks)
    header = exact(4, allow_eof=True)
    if header is None:
        return None
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("bridge_invalid_message_size")
    value = json.loads(exact(size).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bridge_invalid_message")
    return value


def write_frame(stream, value: dict) -> None:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not 0 < len(data) <= MAX_MESSAGE:
        raise ValueError("bridge_invalid_message_size")
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


def descriptor_path(state: Path) -> Path:
    return Path(state) / "browser-enrollment" / "active.dpapi"


class BridgeClient:
    def __init__(self, stream, hello):
        self.stream = stream
        self.browser_name = "firefox" if hello.get("family") == "firefox" else "chromium"
        self.preferred = hello.get("platform_tab") is True
        self.pending: dict[int, queue.Queue] = {}
        self.lock = threading.Lock()
        self.counter = 0
        self.closed = threading.Event()

    def request(self, operation: str, *, timeout=30, **payload):
        response = queue.Queue(maxsize=1)
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError("browser_bridge_disconnected")
            self.counter += 1
            request_id = self.counter
            self.pending[request_id] = response
            try:
                write_frame(self.stream, {"id": request_id, "operation": operation, **payload})
            except BaseException:
                self.pending.pop(request_id, None)
                raise
        try:
            result = response.get(timeout=timeout)
            if result.get("ok") is not True:
                reason = result.get("error")
                allowed = {"browser_closed", "bridge_origin_changed", "bridge_selector_ambiguous",
                           "bridge_element_missing", "bridge_element_disabled", "bridge_navigation_failed",
                           "browser_bridge_disconnected", "browser_account_selection_required"}
                raise ValueError(reason if reason in allowed else "browser_dom_needs_attention")
            return result.get("result")
        except queue.Empty:
            raise TimeoutError("browser_bridge_timeout") from None
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def receive(self, value):
        request_id = value.get("id")
        if type(request_id) is not int:
            raise ValueError("bridge_invalid_response")
        with self.lock:
            target = self.pending.get(request_id)
            if target is not None and target.empty():
                target.put_nowait(value)

    def disconnect(self):
        self.closed.set()
        with self.lock:
            for target in self.pending.values():
                if target.empty():
                    target.put_nowait({"ok": False, "error": "browser_bridge_disconnected"})


class EnrollmentBridge:
    def __init__(self, paths):
        self.paths = paths
        self.secret = secrets.token_urlsafe(32)
        self.clients: list[BridgeClient] = []
        self.connections: set[socket.socket] = set()
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.closed = threading.Event()
        self.server = None
        self.thread = None
        self.protected_descriptor = None

    def __enter__(self):
        from .secrets import protect_secret
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.server.settimeout(0.5)
        value = {"protocol": PROTOCOL, "port": self.server.getsockname()[1],
                 "secret": self.secret, "expires": time.time() + 1800}
        target = descriptor_path(self.paths.state_dir)
        # Protect first; failure must never publish a plaintext capability.
        try:
            protected = protect_secret(json.dumps(value))
            if not protected.startswith("dpapi:"):
                raise RuntimeError("credential_protection_unavailable")
            target.parent.mkdir(parents=True, exist_ok=True)
            # An active setup owns this name exclusively, including after crash.
            # A stale lease may only be replaced after its bounded expiry.
            if target.exists():
                from .secrets import unprotect_secret
                old = json.loads(unprotect_secret(target.read_text(encoding="utf-8")))
                if float(old.get("expires", 0)) >= time.time():
                    # A crash leaves a protected lease but no listener. Never
                    # replace a live listener, including an unrelated reused port.
                    try:
                        port = int(old["port"])
                        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                            pass
                    except ConnectionRefusedError:
                        pass
                    else:
                        raise RuntimeError("browser_enrollment_already_running")
                target.unlink()
            with target.open("x", encoding="utf-8") as stream:
                stream.write(protected)
            self.protected_descriptor = protected
            self.thread = threading.Thread(target=self._accept, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.server.close()
            raise

    def _accept(self):
        while not self.closed.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.lock:
                if len(self.connections) >= 16:
                    connection.close()
                    continue
                self.connections.add(connection)
            threading.Thread(target=self._serve, args=(connection,), daemon=True).start()

    def _serve(self, connection):
        client = None
        try:
            connection.settimeout(5)
            with connection, connection.makefile("rwb", buffering=0) as stream:
                hello = read_frame(stream)
                supplied = hello.get("secret") if isinstance(hello, dict) else None
                if (not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.secret)
                        or hello.get("protocol") != PROTOCOL or hello.get("family") not in {"firefox", "chromium"}):
                    return
                client = BridgeClient(stream, hello)
                connection.settimeout(None)
                with self.changed:
                    self.clients.append(client)
                    self.changed.notify_all()
                while not self.closed.is_set():
                    value = read_frame(stream)
                    if value is None:
                        return
                    client.receive(value)
        except Exception:
            pass  # Never log messages, responses or enrollment capabilities.
        finally:
            if client:
                client.disconnect()
            with self.changed:
                self.connections.discard(connection)
                self.changed.notify_all()

    def context(self, timeout=75):
        deadline = time.monotonic() + timeout
        with self.changed:
            while not any(not c.closed.is_set() for c in self.clients) and not self.closed.is_set():
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.changed.wait(left)
            # Allow other already-open profiles to finish the same discovery pass.
            self.changed.wait(min(0.5, max(0, deadline - time.monotonic())))
            clients = [c for c in self.clients if not c.closed.is_set()]
        preferred = [c for c in clients if c.preferred]
        selected = preferred or clients
        if len(selected) > 1:
            raise ValueError("browser_account_selection_required")
        return ExtensionEnrollmentContext(selected[0]) if selected else None

    def __exit__(self, *_):
        self.closed.set()
        if self.server:
            self.server.close()
        with self.lock:
            for connection in list(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        if self.thread:
            self.thread.join(timeout=2)
        target = descriptor_path(self.paths.state_dir)
        try:
            if self.protected_descriptor and target.read_text(encoding="utf-8") == self.protected_descriptor:
                target.unlink()
        except FileNotFoundError:
            pass
        self.secret = ""


class ExtensionEnrollmentContext:
    def __init__(self, client):
        self.client = client
        self.browser_name = client.browser_name
        self.pages = []

    def new_page(self):
        from .onboarding import OPENAI_TUNNELS_URL
        page = ExtensionPage(self.client, self.client.request("open"), initial_url=OPENAI_TUNNELS_URL)
        self.pages.append(page)
        return page

    def close(self):
        for page in self.pages:
            try:
                page.close()
            except (OSError, ValueError, RuntimeError, TimeoutError):
                pass
        self.pages.clear()


def _name(value):
    import re
    if isinstance(value, re.Pattern):
        return {"source": value.pattern, "flags": "i" if value.flags & re.I else ""}
    return {"literal": str(value)}


class ExtensionLocator:
    def __init__(self, page, steps=()):
        self.page, self.steps = page, list(steps)

    def _append(self, step):
        return ExtensionLocator(self.page, [*self.steps, step])

    def locator(self, selector):
        return self._append({"kind": "css", "selector": selector})

    def get_by_role(self, role, *, name=None):
        return self._append({"kind": "role", "role": role, "name": _name(name) if name is not None else None})

    def get_by_text(self, name):
        return self._append({"kind": "text", "name": _name(name)})

    def filter(self, *, visible):
        return self._append({"kind": "visible", "value": visible})

    def nth(self, index):
        return self._append({"kind": "nth", "index": index})

    @property
    def first(self):
        return self.nth(0)

    def _call(self, action, **options):
        return self.page.client.request("dom", tab=self.page.tab, steps=self.steps, action=action, **options)

    def count(self): return self._call("count")
    def is_visible(self): return self._call("visible")
    def is_enabled(self): return self._call("enabled")
    def is_checked(self): return self._call("checked")
    def get_attribute(self, name): return self._call("attribute", name=name)
    def inner_text(self): return self._call("text")
    def select_option(self, *, label, timeout=5000):
        return self._call("select_label", label=label)
    def click(self, *, timeout=5000): self._call("click")
    def pointer_click(self, *, timeout=5000): self._call("pointer_click")
    def fill(self, value, *, timeout=5000): self._call("fill", value=value)
    def press(self, value, *, timeout=5000): self._call("press", value=value)


class ExtensionPage(ExtensionLocator):
    def __init__(self, client, tab, *, initial_url=None):
        self.client, self.tab, self.closed = client, tab, False
        self._initial_url = initial_url
        super().__init__(self)

    @property
    def url(self): return self.client.request("url", tab=self.tab)

    def goto(self, url, *, wait_until="domcontentloaded", timeout=30000):
        initial_url, self._initial_url = self._initial_url, None
        if url == initial_url:
            # The extension's open operation already starts this navigation.
            # A second tabs.update can cancel it in Chromium. The enrollment
            # worker waits for the official URL and hydrated controls itself.
            return None
        return self.client.request("navigate", tab=self.tab, url=url, timeout=max(1, timeout / 1000 + 2))

    def evaluate(self, source):
        from .openai_browser_enrollment import _TUNNEL_DOM, _KEY_DOM
        operation = {_TUNNEL_DOM: "tunnels", _KEY_DOM: "new_key"}.get(source)
        if not operation:
            raise ValueError("bridge_arbitrary_script_forbidden")
        return self.client.request("extract", tab=self.tab, kind=operation)

    def is_closed(self):
        return self.closed or self.client.closed.is_set() or self.client.request("closed", tab=self.tab)

    def close(self):
        if not self.closed:
            self.client.request("close", tab=self.tab)
            self.closed = True

    def wait_for_timeout(self, milliseconds):
        time.sleep(min(max(milliseconds / 1000, 0), 1))
