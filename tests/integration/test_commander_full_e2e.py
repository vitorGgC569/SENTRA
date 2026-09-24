from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from sentra_mcp.config import PROJECT_ROOT
from sentra_remote.agent import AgentConfig, AgentRuntime
from sentra_remote.relay import RemoteRelayServer
from sentra_remote.store import RemoteStore


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Introspection(BaseHTTPRequestHandler):
    resource = ""

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        data = urllib.parse.parse_qs(self.rfile.read(length).decode())
        token = (data.get("token") or [""])[0]
        if token == "sentra-full-e2e-token":
            payload = {
                "active": True,
                "client_id": "sentra-full-e2e",
                "sub": "full-e2e-user",
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
            raise AssertionError(f"cloud MCP exited early\nstdout={stdout}\nstderr={stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("cloud MCP did not open port")


def _pair_relay(relay_url: str, code: str, name: str) -> dict:
    body = json.dumps({"pairing_code": code, "name": name}).encode()
    request = urllib.request.Request(
        relay_url + "/v1/pair",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _data(result) -> dict:
    assert result.is_error is False, result
    assert result.structured_content is not None
    assert result.structured_content["ok"] is True
    return result.structured_content["data"]


def test_oauth_cloud_mcp_relay_agent_local_mcp_end_to_end(tmp_path: Path) -> None:
    db = tmp_path / "remote.sqlite3"
    relay_store = RemoteStore(db, online_window_s=10, lease_window_s=5)
    relay = RemoteRelayServer(relay_store, port=0)
    relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
    relay_thread.start()
    relay_url = f"http://127.0.0.1:{relay.server.server_port}"

    auth = ThreadingHTTPServer(("127.0.0.1", 0), _Introspection)
    auth_thread = threading.Thread(target=auth.serve_forever, daemon=True)
    auth_thread.start()
    issuer = f"http://127.0.0.1:{auth.server_port}"

    cloud_port = _free_port()
    resource = f"http://127.0.0.1:{cloud_port}/mcp"
    _Introspection.resource = resource
    cloud = subprocess.Popen(
        [
            sys.executable, "-B", "-m", "sentra_mcp",
            "--mode", "cloud",
            "--transport", "streamable-http",
            "--host", "127.0.0.1",
            "--port", str(cloud_port),
            "--allowed-root", str(tmp_path),
            "--audit-log", str(tmp_path / "cloud-audit.jsonl"),
            "--remote-store", str(db),
            "--oauth-issuer-url", issuer,
            "--oauth-resource-url", resource,
            "--oauth-introspection-url", issuer + "/introspect",
            "--oauth-required-scope", "sentra:mcp",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    runtime: AgentRuntime | None = None
    agent_task: asyncio.Task | None = None
    try:
        _wait_port(cloud_port, cloud)

        @asynccontextmanager
        async def transport():
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer sentra-full-e2e-token"}
            ) as http:
                async with streamable_http_client(resource, http_client=http) as streams:
                    yield streams

        async def scenario() -> None:
            nonlocal runtime, agent_task
            async with Client(transport()) as client:
                tools = {item.name for item in (await client.list_tools()).tools}
                assert "sentra_pair_device" in tools
                assert "sentra_remote_read_file" in tools
                assert "sentra_read_file" not in tools
                assert "sentra_start_process" not in tools

                pairing = _data(await client.call_tool(
                    "sentra_pair_device",
                    {
                        "name": "Full E2E PC",
                        "platform": "windows",
                        "allowed_tools": [
                            "sentra_read_file",
                            "sentra_write_file",
                            "sentra_start_process",
                            "sentra_read_process_output",
                            "system.shutdown_agent",
                        ],
                        "ttl_s": 300,
                    },
                ))
                paired = await asyncio.to_thread(
                    _pair_relay,
                    relay_url,
                    pairing["pairing_code"],
                    "Full E2E PC",
                )

                device_root = tmp_path / "device"
                device_root.mkdir()
                (device_root / "from-device.txt").write_text(
                    "through-all-layers\n", encoding="utf-8", newline="\n"
                )
                config = AgentConfig(
                    relay_url=relay_url,
                    device_id=paired["device_id"],
                    device_token=paired["device_token"],
                    name="Full E2E PC",
                    allowed_roots=[str(device_root)],
                    audit_log=str(tmp_path / "agent-audit.jsonl"),
                )
                runtime = AgentRuntime(config, tmp_path / "agent.json")
                agent_task = asyncio.create_task(runtime.run())

                deadline = time.monotonic() + 10
                device = None
                while time.monotonic() < deadline:
                    devices = _data(await client.call_tool("sentra_list_devices", {}))["devices"]
                    device = next((d for d in devices if d["device_id"] == paired["device_id"]), None)
                    if device and device["status"] == "ONLINE":
                        break
                    await asyncio.sleep(0.05)
                assert device and device["status"] == "ONLINE"

                read = _data(await client.call_tool(
                    "sentra_remote_read_file",
                    {"device_id": paired["device_id"], "path": "from-device.txt"},
                ))
                assert read["state"] == "COMPLETED"
                assert read["result"]["data"]["content"] == "through-all-layers\n"

                written = _data(await client.call_tool(
                    "sentra_remote_write_file",
                    {
                        "device_id": paired["device_id"],
                        "path": "from-cloud.txt",
                        "content": "cloud-wrote-this\n",
                    },
                ))
                assert written["state"] == "COMPLETED"
                assert (device_root / "from-cloud.txt").read_text(encoding="utf-8") == "cloud-wrote-this\n"

                shutdown = _data(await client.call_tool(
                    "sentra_shutdown_remote",
                    {"device_id": paired["device_id"], "timeout_s": 20},
                ))
                assert shutdown["state"] == "COMPLETED"
                assert agent_task is not None
                await asyncio.wait_for(agent_task, timeout=10)

        asyncio.run(scenario())
    finally:
        if runtime is not None:
            runtime.stop_event.set()
        if cloud.poll() is None:
            cloud.terminate()
            try:
                cloud.wait(timeout=8)
            except subprocess.TimeoutExpired:
                cloud.kill()
                cloud.wait(timeout=5)
        auth.shutdown()
        auth.server_close()
        auth_thread.join(timeout=5)
        relay.stop()
        relay_thread.join(timeout=5)
        relay_store.close()
