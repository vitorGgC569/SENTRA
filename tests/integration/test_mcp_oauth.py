from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from sentra_mcp.config import PROJECT_ROOT


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _IntrospectionHandler(BaseHTTPRequestHandler):
    resource = ""

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = urllib.parse.parse_qs(self.rfile.read(length).decode())
        token = (data.get("token") or [""])[0]
        if token == "sentra-e2e-good-token":
            payload = {
                "active": True,
                "client_id": "sentra-e2e-client",
                "sub": "oauth-user",
                "scope": "sentra:mcp sentra:devices:read sentra:devices:write sentra:execute",
                "exp": int(time.time()) + 3600,
                "aud": self.resource,
            }
        else:
            payload = {"active": False}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _wait_port(port: int, process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(f"MCP exited early\nstdout={stdout}\nstderr={stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("MCP OAuth server did not open port")


def test_oauth_http_and_protected_resource_metadata(tmp_path: Path) -> None:
    auth_server = ThreadingHTTPServer(("127.0.0.1", 0), _IntrospectionHandler)
    auth_port = auth_server.server_port
    auth_thread = threading.Thread(target=auth_server.serve_forever, daemon=True)
    auth_thread.start()

    mcp_port = _free_port()
    resource = f"http://127.0.0.1:{mcp_port}/mcp"
    _IntrospectionHandler.resource = resource
    issuer = f"http://127.0.0.1:{auth_port}"
    process = subprocess.Popen(
        [
            sys.executable, "-B", "-m", "sentra_mcp",
            "--transport", "streamable-http",
            "--mode", "cloud",
            "--host", "127.0.0.1",
            "--port", str(mcp_port),
            "--allowed-root", str(tmp_path),
            "--audit-log", str(tmp_path / ".sentra" / "oauth-audit.jsonl"),
            "--remote-store", str(tmp_path / ".sentra" / "remote.sqlite3"),
            "--oauth-issuer-url", issuer,
            "--oauth-resource-url", resource,
            "--oauth-introspection-url", f"{issuer}/introspect",
            "--oauth-required-scope", "sentra:mcp",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_port(mcp_port, process)

        metadata = None
        for path in (
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource",
        ):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{mcp_port}{path}", timeout=3) as response:
                    if response.status == 200:
                        metadata = json.loads(response.read())
                        break
            except urllib.error.HTTPError:
                pass
        assert metadata is not None
        assert issuer.rstrip("/") in {item.rstrip("/") for item in metadata["authorization_servers"]}
        assert metadata["resource"].rstrip("/") == resource.rstrip("/")

        unauth = urllib.request.Request(resource, method="GET")
        try:
            urllib.request.urlopen(unauth, timeout=3)
            raise AssertionError("unauthenticated MCP request unexpectedly succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            challenge = exc.headers.get("WWW-Authenticate", "")
            assert "Bearer" in challenge
            assert "oauth-protected-resource" in challenge

        @asynccontextmanager
        async def transport():
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer sentra-e2e-good-token"}
            ) as http:
                async with streamable_http_client(resource, http_client=http) as streams:
                    yield streams

        async def probe() -> None:
            async with Client(transport()) as client:
                tools = {tool.name for tool in (await client.list_tools()).tools}
                assert "sentra_remote_call" in tools
                assert "sentra_list_devices" in tools
                assert "sentra_read_file" not in tools
                assert "sentra_start_process" not in tools
                health = await client.call_tool("sentra_health", {})
                assert health.is_error is False
                who = await client.call_tool("sentra_who_am_i", {})
                assert who.is_error is False
                assert who.structured_content["data"]["subject"] == "oauth-user"
                assert "sentra:execute" in who.structured_content["data"]["scopes"]

        asyncio.run(probe())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        auth_server.shutdown()
        auth_server.server_close()
        auth_thread.join(timeout=5)
