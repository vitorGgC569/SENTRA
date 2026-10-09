from __future__ import annotations

import http.client
import asyncio
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import zstandard as zstd

from sentra_model_gateway.gateway import GatewayConfig, GatewayServer, LauncherSupervisor, _extract_codex_goal_context, _extract_codex_goal_signal, _extract_codex_task_text, _extract_codex_subagent_notifications, _upstream_version_from_ref
from orchestrator.providers.model_provider import ChatGPTWebModelProvider
from orchestrator.providers.codex_web_provider import CodexChatGPTWebProvider
from orchestrator.providers.base import AgentRequest


UPSTREAM_MANIFEST = json.loads(
    (Path(__file__).resolve().parents[2] / "integrations" / "codex_chatgpt_web" / "upstream.json")
    .read_text(encoding="utf-8")
)
UPSTREAM_VERSION = _upstream_version_from_ref(str(UPSTREAM_MANIFEST["ref"]))


class UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, status, value):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, {
                "status": "ok",
                "service": "codex-chatgpt-web",
                "version": UPSTREAM_VERSION,
                "accepting_turns": True,
                "active_http_turns": int(
                    getattr(self.server, "active_http_turns", 0)
                ),
                "active_browser_turns": int(
                    getattr(self.server, "active_browser_turns", 0)
                ),
            })
        if self.path == "/v1/models":
            self.server.received = {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            }
            return self._send(200, {"models": [
                {"slug": "gpt-6-sol"},
                {"slug": "chatgpt-web/high", "display_name": "Web"},
                {"slug": "gemini-web/flash", "display_name": "Gemini Flash"},
            ]})
        self._send(404, {})

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        raw = self.rfile.read(size)
        body = (
            raw
            if self.path in {"/v1/images/edits"}
            else (json.loads(raw) if raw else {})
        )
        self.server.received = {"path": self.path, "body": body, "metadata": self.headers.get("x-codex-turn-metadata"), "authorization": self.headers.get("Authorization"), "content_type": self.headers.get("Content-Type"), "content_encoding": self.headers.get("Content-Encoding")}
        if self.path == "/admin/cancel-turns":
            if self.headers.get("Authorization") != "Bearer upstream-secret":
                return self._send(401, {"error": "unauthorized"})
            cancelled_http = int(
                getattr(self.server, "active_http_turns", 0)
            )
            cancelled_browser = int(
                getattr(self.server, "active_browser_turns", 0)
            )
            self.server.active_http_turns = 0
            self.server.active_browser_turns = 0
            return self._send(200, {
                "status": "ok",
                "cancelled_http_turns": cancelled_http,
                "cancelled_browser_turns": cancelled_browser,
                "active_http_turns": 0,
                "active_browser_turns": 0,
            })
        if self.path in {"/v1/alpha/search", "/v1/images/edits", "/admin/interrupt-turn"}:
            return self._send(200, {"ok": True})
        if self.path == "/v1/responses/compact":
            return self._send(200, {"output": [{"type": "compaction", "encrypted_content": "summary"}]})
        if body.get("input") == "terminal-keepalive":
            terminal = b'event: response.completed\ndata: {"response":{"status":"completed","model":"chatgpt-web/high"}}\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(f"{len(terminal):X}\r\n".encode("ascii") + terminal + b"\r\n")
            self.wfile.flush()
            time.sleep(1.5)
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                pass
            return
        if body.get("input") == "slow-chunked":
            first = b'event: response.heartbeat\ndata: {"type":"response.heartbeat"}\n\n'
            second = b'event: response.completed\ndata: {"response":{"status":"completed","model":"chatgpt-web/high"}}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk, delay in ((first, 0.8), (second, 0)):
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        if body.get("stream"):
            data = b'event: response.output_text.delta\ndata: {"delta":"ola"}\n\nevent: response.completed\ndata: {"response":{"status":"completed","model":"chatgpt-web/high"}}\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(200, {"status": "completed", "model": body["model"]})


@pytest.fixture
def servers(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        admin_token="test-secret",
        upstream_control_token="upstream-secret",
        state_root=tmp_path / "durable",
        browser_descriptor=tmp_path / "browser.json",
        launcher_executable=tmp_path / "missing-launcher.exe",
    ))
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, gateway)]
    for thread in threads:
        thread.start()
    yield upstream, gateway
    for server in (gateway, upstream):
        server.shutdown()
        server.server_close()
    for thread in threads:
        thread.join(timeout=2)


def call(port, method, path, value=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(value).encode() if value is not None else None
    connection.request(method, path, data, {"Content-Type": "application/json", **(headers or {})})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def test_gateway_listener_is_exclusive(tmp_path):
    first = GatewayServer(GatewayConfig(
        upstream="http://127.0.0.1:9",
        port=0,
        state_root=tmp_path / "first",
        browser_descriptor=tmp_path / "first-browser.json",
    ))
    try:
        with pytest.raises(OSError):
            GatewayServer(GatewayConfig(
                upstream="http://127.0.0.1:9",
                port=first.server_port,
                state_root=tmp_path / "second",
                browser_descriptor=tmp_path / "second-browser.json",
            ))
    finally:
        first.server_close()


def _packaged_gateway_config(
    tmp_path: Path,
    *,
    patch_hash: str | None = None,
    built_files: list[str] | None = None,
) -> GatewayConfig:
    repo = tmp_path / "repo"
    checkout = repo / "third_party" / "codex-chatgpt-web"
    integration = repo / "integrations" / "codex_chatgpt_web"
    payload = repo / "dist" / "web-models"
    launcher = payload / "win-unpacked" / "Codex Web GPT.exe"
    runtime_manifest = launcher.parent / "resources" / "runtime" / "manifest.json"

    checkout.mkdir(parents=True)
    integration.mkdir(parents=True)
    runtime_manifest.parent.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    runtime_manifest.write_text("{}", encoding="utf-8")

    patch = integration / "sentra-upstream.patch"
    patch.write_text("gateway-patch\n", encoding="utf-8")
    expected_files = ["launcher/electron/main.cjs", "src/config.ts"]
    commit = "757942251222ee0f71953c35636679c6d92dd636"
    (integration / "upstream.json").write_text(
        json.dumps({"patch_files": expected_files, "commit": commit, "ref": UPSTREAM_MANIFEST["ref"]}),
        encoding="utf-8",
    )
    (payload / "integration-build.json").write_text(
        json.dumps(
            {
                "patch_sha256": patch_hash or hashlib.sha256(patch.read_bytes()).hexdigest(),
                "patch_files": expected_files if built_files is None else built_files,
                "commit": commit,
            }
        ),
        encoding="utf-8",
    )
    return GatewayConfig(
        checkout=checkout,
        launcher_executable=launcher,
        state_root=tmp_path / "state",
        browser_descriptor=tmp_path / "browser.json",
    )


def test_launcher_payload_validation_accepts_current_build(tmp_path: Path) -> None:
    supervisor = LauncherSupervisor(_packaged_gateway_config(tmp_path))
    result = supervisor.validate_payload()
    assert result["packaged"] is True
    assert result["commit"] == "757942251222ee0f71953c35636679c6d92dd636"


def test_launcher_auto_detects_development_packaged_payload(tmp_path: Path) -> None:
    explicit = _packaged_gateway_config(tmp_path)
    config = GatewayConfig(
        checkout=explicit.checkout,
        state_root=tmp_path / "state-auto",
    )
    supervisor = LauncherSupervisor(config)
    assert supervisor._packaged_launcher_path() == explicit.launcher_executable.resolve()
    assert supervisor.validate_payload()["packaged"] is True
    assert supervisor._browser_descriptor_path().parent.parent.name == ".codex-chatgpt-web"


def test_gateway_authority_uses_same_auto_detected_browser_descriptor_as_launcher(tmp_path: Path) -> None:
    explicit = _packaged_gateway_config(tmp_path)
    gateway = GatewayServer(GatewayConfig(
        upstream="http://127.0.0.1:9",
        port=0,
        checkout=explicit.checkout,
        state_root=tmp_path / "state-authority-descriptor",
    ))
    try:
        assert gateway.turn_authority.descriptor == gateway.launcher._browser_descriptor_path()
        assert gateway.turn_authority.descriptor.parent.parent.name == ".codex-chatgpt-web"
    finally:
        gateway.server_close()
        gateway.turn_authority.durable.close()


def test_upstream_watchdog_restarts_live_launcher_when_upstream_is_dead(tmp_path: Path, monkeypatch) -> None:
    gateway = GatewayServer(GatewayConfig(
        upstream="http://127.0.0.1:9",
        port=0,
        state_root=tmp_path / "state-watchdog",
        browser_descriptor=tmp_path / "browser-watchdog.json",
    ))
    calls: list[str] = []
    monkeypatch.setattr(gateway, "_upstream_health", lambda: (False, {}))
    monkeypatch.setattr(
        gateway.launcher,
        "status",
        lambda: {"running": True, "pid": 1234, "source": "owned"},
    )
    monkeypatch.setattr(
        gateway.launcher,
        "stop",
        lambda: calls.append("stop") or {"running": False, "pid": None, "source": "none"},
    )
    monkeypatch.setattr(
        gateway.launcher,
        "start",
        lambda hidden=False: calls.append(f"start:{hidden}") or {
            "running": True,
            "pid": 5678,
            "source": "owned",
        },
    )
    try:
        first = gateway.supervise_upstream_once(now=100.0)
        assert first["state"] == "DEGRADED"
        assert calls == []

        recovered = gateway.supervise_upstream_once(now=106.1)
        assert recovered["state"] == "RECOVERING"
        assert recovered["action"] == "restart_launcher"
        assert calls == ["stop", "start:True"]

        recovering = gateway.supervise_upstream_once(now=106.2)
        assert recovering["state"] == "RECOVERING"
        assert calls == ["stop", "start:True"]
    finally:
        gateway.server_close()
        gateway.turn_authority.durable.close()


def test_launcher_payload_validation_rejects_stale_build(tmp_path: Path) -> None:
    supervisor = LauncherSupervisor(_packaged_gateway_config(tmp_path, patch_hash="0" * 64))
    with pytest.raises(RuntimeError, match="payload is stale"):
        supervisor.validate_payload()


def test_launcher_environment_fences_payload_identity(tmp_path: Path) -> None:
    config = _packaged_gateway_config(tmp_path)
    relay_token = Path(config.state_root) / "browser" / "relay-token"
    relay_token.parent.mkdir(parents=True, exist_ok=True)
    relay_token.write_text("relay-secret\n", encoding="utf-8")

    supervisor = LauncherSupervisor(config)
    payload = supervisor.validate_payload()
    environment = supervisor._environment()
    assert environment["SENTRA_MANAGED_TUNNEL"] == "1"
    assert environment["SENTRA_MANAGED_TUNNEL"] == "1"
    assert environment["SENTRA_INTEGRATION_PATCH_SHA256"] == payload["patch_sha256"]
    assert environment["SENTRA_UPSTREAM_COMMIT"] == payload["commit"]
    assert environment["SENTRA_GEMINI_WEB_ENABLED"] == "1"
    assert environment["SENTRA_BROWSER_RELAY_TOKEN_FILE"] == str(relay_token)


def test_launcher_refuses_to_adopt_stale_live_descriptor(tmp_path: Path) -> None:
    supervisor = LauncherSupervisor(_packaged_gateway_config(tmp_path))
    descriptor_path = supervisor._browser_descriptor_path()
    descriptor_path.write_text(
        json.dumps(
            {
                "version": 3,
                "kind": "codex-web-gpt-launcher",
                "sentraManaged": True,
                "sentraIntegrationPatchSha256": "0" * 64,
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )
    supervisor._pid_alive = lambda _pid: True  # type: ignore[method-assign]
    status = supervisor.status()
    assert status["source"] == "stale"
    assert status["stale_pid"] == 12345
    with pytest.raises(RuntimeError, match="stale Web Models launcher is still running"):
        supervisor.start(hidden=True)


def test_catalog_namespace_health_and_admin(servers):
    upstream, gateway = servers

    status, cached_payload, _ = call(
        gateway.server_port,
        "GET",
        "/sentra/model-catalog",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert status == 200
    assert json.loads(cached_payload)["status"] == "awaiting_codex_catalog"

    status, payload, _ = call(
        gateway.server_port,
        "GET",
        "/v1/models",
        headers={"Authorization": "Bearer codex-token"},
    )
    assert status == 200
    assert upstream.received["authorization"] == "Bearer codex-token"
    assert [item["slug"] for item in json.loads(payload)["models"]] == [
        "gpt-6-sol",
        "sentra/chatgpt-web/high",
        "sentra/gemini-web/flash",
    ]

    assert call(gateway.server_port, "GET", "/sentra/model-catalog")[0] == 401
    status, cached_payload, _ = call(
        gateway.server_port,
        "GET",
        "/sentra/model-catalog",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert status == 200
    cached = json.loads(cached_payload)
    assert cached["status"] == "ready"
    assert [item["slug"] for item in cached["models"]] == [
        "sentra/chatgpt-web/high",
        "sentra/gemini-web/flash",
    ]

    assert call(gateway.server_port, "GET", "/healthz")[0] == 200
    _, resource_payload, _ = call(gateway.server_port, "GET", "/sentra/resources", headers={"Authorization": "Bearer test-secret"})
    resource = json.loads(resource_payload)["resources"][0]
    assert resource["resource_id"] == "model:chatgpt-web:primary"
    assert resource["state"] == "READY"
    assert call(gateway.server_port, "GET", "/sentra/status")[0] == 401
    assert call(gateway.server_port, "GET", "/sentra/status", headers={"Authorization": "Bearer test-secret"})[0] == 200



def test_sentra_doctor_requires_internal_or_admin_auth(servers):
    _, gateway = servers
    gateway.sentra_doctor = lambda **_: {
        "ok": True,
        "mode": "sentra",
        "checks": [{"id": "sentra-gateway", "status": "ok", "message": "ready"}],
    }

    assert call(gateway.server_port, "GET", "/sentra/doctor")[0] == 401

    status, payload, _ = call(
        gateway.server_port,
        "GET",
        "/sentra/doctor",
        headers={"Authorization": "Bearer " + gateway.turn_authority_token},
    )
    assert status == 200
    assert json.loads(payload)["ok"] is True

    assert call(
        gateway.server_port,
        "GET",
        "/sentra/doctor",
        headers={"Authorization": "Bearer test-secret"},
    )[0] == 200



def test_sentra_doctor_actively_verifies_sentra_connector(monkeypatch, tmp_path):
    import sentra_model_gateway.gateway as gateway_module

    gateway = GatewayServer(GatewayConfig(
        upstream="http://127.0.0.1:17841",
        port=0,
        admin_token="doctor-secret",
        state_root=tmp_path / "state",
        browser_descriptor=tmp_path / "browser.json",
        connector_name="SENTRA tunnel",
    ))
    seen = {}
    try:
        monkeypatch.setattr(gateway_module, "collect_product_status", lambda *_: {
            "mcp": {"ok": True},
            "relay": {"ok": True},
            "tunnel": {"configured": True, "ok": True},
            "edge": {"workers": []},
            "remote_agent": {"configured": False, "ok": False},
        })
        gateway.launcher.route = lambda action="status": (
            {"checks": []}
            if action == "doctor"
            else {"installed": True, "active": True, "points_to_sentra": True}
        )

        def verify(action, payload=None):
            seen["action"] = action
            seen["payload"] = payload
            return {"ok": True, "verified": True, "connectorName": "SENTRA tunnel"}

        gateway.launcher.runtime_control = verify
        report = gateway.sentra_doctor(verify_connector=True)
        connector = next(item for item in report["checks"] if item["id"] == "connector")
        assert connector["status"] == "ok"
        assert seen == {
            "action": "verify-connector",
            "payload": {"connectorName": "SENTRA tunnel"},
        }
    finally:
        gateway.server_close()


def test_sentra_doctor_http_query_requests_active_connector_check(servers):
    _, gateway = servers
    seen = {}

    def doctor(*, verify_connector=False):
        seen["verify_connector"] = verify_connector
        return {
            "ok": True,
            "mode": "sentra",
            "checks": [{"id": "connector", "status": "ok", "message": "ready"}],
        }

    gateway.sentra_doctor = doctor
    status, _, _ = call(
        gateway.server_port,
        "GET",
        "/sentra/doctor?verify_connector=1",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert status == 200
    assert seen["verify_connector"] is True


def test_responses_sse_and_compaction_preserve_turn_header(servers):
    upstream, gateway = servers
    turn_metadata = json.dumps({
        "thread_id": "thread-123",
        "turn_id": "turn-123",
        "request_kind": "turn",
    })
    status, payload, headers = call(
        gateway.server_port, "POST", "/v1/responses",
        {"model": "sentra/chatgpt-web/high", "stream": True, "input": "oi"},
        {"x-codex-turn-metadata": turn_metadata},
    )
    assert status == 200 and "response.output_text.delta" in payload.decode()
    assert headers["Content-Type"] == "text/event-stream"
    assert upstream.received["path"] == "/v1/responses"
    assert {key: upstream.received["body"][key] for key in ("model", "stream", "input")} == {
        "model": "chatgpt-web/high", "stream": True, "input": "oi"}
    assert upstream.received["body"]["client_metadata"]["sentra_managed"] is True
    assert upstream.received["body"]["client_metadata"]["sentra_turn_capability"].startswith("stc_")
    assert upstream.received["body"]["client_metadata"]["x-codex-turn-metadata"] == turn_metadata
    assert upstream.received["metadata"] == turn_metadata
    status, payload, _ = call(gateway.server_port, "POST", "/v1/responses/compact", {"model": "sentra/chatgpt-web/high", "input": []})
    assert status == 200 and json.loads(payload)["output"][0]["type"] == "compaction"
    assert upstream.received["body"]["model"] == "chatgpt-web/high"
    assert call(gateway.server_port, "POST", "/v1/responses", {"model": "sentra/unknown", "input": []})[0] == 400
    assert call(gateway.server_port, "POST", "/v1/responses", {"model": "chatgpt-web/", "input": []})[0] == 400
    assert call(gateway.server_port, "POST", "/v1/responses", {"model": "gemini-web/", "input": []})[0] == 400
    assert call(gateway.server_port, "POST", "/v1/responses", {"model": "sentra/gemini-web/", "input": []})[0] == 400


def test_gemini_web_routes_stay_under_sentra_turn_authority(servers):
    upstream, gateway = servers
    for requested in ("sentra/gemini-web/flash", "gemini-web/flash"):
        status, payload, _ = call(
            gateway.server_port,
            "POST",
            "/v1/responses",
            {"model": requested, "stream": False, "input": "gemini-selection"},
        )
        assert status == 200
        assert json.loads(payload)["model"] == "sentra/gemini-web/flash"
        assert upstream.received["body"]["model"] == "gemini-web/flash"
        metadata = upstream.received["body"]["client_metadata"]
        assert metadata["sentra_managed"] is True
        assert metadata["sentra_turn_capability"].startswith("stc_")


def test_legacy_web_model_alias_stays_under_sentra_turn_authority(servers):
    upstream, gateway = servers
    status, payload, _ = call(
        gateway.server_port,
        "POST",
        "/v1/responses",
        {"model": "chatgpt-web/high", "stream": False, "input": "legacy-selection"},
    )
    assert status == 200
    assert json.loads(payload)["model"] == "sentra/chatgpt-web/high"
    assert upstream.received["body"]["model"] == "chatgpt-web/high"
    metadata = upstream.received["body"]["client_metadata"]
    assert metadata["sentra_managed"] is True
    assert metadata["sentra_turn_capability"].startswith("stc_")


def test_gateway_http11_and_chunked_codex_request(servers):
    upstream, gateway = servers
    payload = json.dumps({
        "model": "sentra/chatgpt-web/high",
        "stream": False,
        "input": "chunked",
    }).encode()

    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    connection.request(
        "POST",
        "/v1/responses",
        body=[payload[:11], payload[11:]],
        headers={"Content-Type": "application/json"},
        encode_chunked=True,
    )
    response = connection.getresponse()
    assert response.version == 11
    assert response.status == 200
    response.read()
    connection.close()
    assert upstream.received["body"]["model"] == "chatgpt-web/high"
    assert upstream.received["body"]["input"] == "chunked"

    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    connection.request(
        "GET",
        "/v1/responses",
        headers={
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGVzdC13ZWJzb2NrZXQta2V5",
        },
    )
    response = connection.getresponse()
    assert response.version == 11
    response.read()
    connection.close()


def test_gateway_rechunks_streaming_upstream_without_buffering(servers):
    _, gateway = servers
    request = {
        "model": "sentra/chatgpt-web/high",
        "stream": True,
        "input": "slow-chunked",
    }
    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    connection.request(
        "POST",
        "/v1/responses",
        body=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    assert response.version == 11
    assert response.status == 200
    assert response.getheader("Transfer-Encoding") == "chunked"
    started = time.monotonic()
    first = response.read1(4096)
    elapsed = time.monotonic() - started
    assert b"response.heartbeat" in first
    assert elapsed < 0.6
    rest = response.read()
    connection.close()
    assert b"response.completed" in rest
    assert b"[DONE]" in rest


def test_gateway_closes_sse_on_terminal_event_without_waiting_for_upstream_eof(servers):
    _, gateway = servers
    request = {
        "model": "sentra/chatgpt-web/high",
        "stream": True,
        "input": "terminal-keepalive",
    }
    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    started = time.monotonic()
    connection.request(
        "POST",
        "/v1/responses",
        body=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    body = response.read()
    elapsed = time.monotonic() - started
    connection.close()

    assert response.status == 200
    assert b"response.completed" in body
    assert elapsed < 1.0


def test_gateway_decodes_codex_zstd_request_and_strips_encoding(servers):
    upstream, gateway = servers
    payload = json.dumps({
        "model": "sentra/chatgpt-web/high",
        "stream": False,
        "input": "compressed",
    }).encode()
    compressed = zstd.ZstdCompressor().compress(payload)

    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    connection.request(
        "POST",
        "/v1/responses",
        body=compressed,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "zstd",
        },
    )
    response = connection.getresponse()
    assert response.version == 11
    assert response.status == 200
    response.read()
    connection.close()

    assert upstream.received["body"]["model"] == "chatgpt-web/high"
    assert upstream.received["body"]["input"] == "compressed"
    assert upstream.received["content_encoding"] is None


def test_native_model_passthrough(servers):
    upstream, gateway = servers
    assert call(gateway.server_port, "POST", "/v1/responses", {"model": "gpt-6-sol", "input": []})[0] == 200
    assert upstream.received["body"]["model"] == "gpt-6-sol"
    status, _, _ = call(gateway.server_port, "POST", "/v1/alpha/search", {"query": "x"}, {"Authorization": "Bearer codex-token"})
    assert status == 200
    assert upstream.received["authorization"] == "Bearer codex-token"


def test_image_edit_body_is_forwarded_without_json_rewrite(servers):
    upstream, gateway = servers
    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    connection.request("POST", "/v1/images/edits", b"raw-image", {"Content-Type": "multipart/form-data; boundary=test", "Authorization": "Bearer codex-token"})
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    assert upstream.received["body"] == b"raw-image"
    assert upstream.received["content_type"] == "multipart/form-data; boundary=test"


def test_model_provider_uses_redacted_admin_catalog_without_codex_bearer(servers):
    upstream, gateway = servers
    gateway.cache_model_catalog({
        "models": [
            {"slug": "gpt-6-sol"},
            {"slug": "chatgpt-web/high", "display_name": "Web"},
            {"slug": "gemini-web/flash", "display_name": "Gemini Flash"},
        ]
    })

    async def exercise():
        provider = ChatGPTWebModelProvider(
            f"http://127.0.0.1:{gateway.server_port}/v1",
            api_key="not-a-codex-bearer",
            gateway_admin_token="test-secret",
        )
        try:
            catalog = await provider.list_models()
            assert [item["slug"] for item in catalog] == [
                "sentra/chatgpt-web/high",
                "sentra/gemini-web/flash",
            ]
        finally:
            await provider.close()

    asyncio.run(exercise())
    assert not hasattr(upstream, "received") or upstream.received.get("path") != "/v1/models"


def test_codex_web_provider_accepts_sentra_gemini_namespace():
    provider = CodexChatGPTWebProvider(
        base_url="http://127.0.0.1:17842/v1",
        model_name="sentra/gemini-web/flash",
        gateway_admin_token="admin",
    )
    try:
        assert provider.model_name == "sentra/gemini-web/flash"
    finally:
        asyncio.run(provider.close())


def test_async_model_provider_keeps_native_events(servers):
    _, gateway = servers

    async def exercise():
        provider = ChatGPTWebModelProvider(f"http://127.0.0.1:{gateway.server_port}/v1")
        try:
            catalog = await provider.list_models()
            assert catalog[1]["slug"] == "sentra/chatgpt-web/high"
            events = [event async for event in provider.create_response({"model": "sentra/chatgpt-web/high", "input": "oi"})]
            assert [event.type for event in events] == ["response.output_text.delta", "response.completed"]
            assert events[0].data["delta"] == "ola"
        finally:
            await provider.close()

    asyncio.run(exercise())


def test_cancel_uses_two_control_tokens(servers):
    upstream, gateway = servers

    async def exercise():
        provider = ChatGPTWebModelProvider(f"http://127.0.0.1:{gateway.server_port}/v1", gateway_admin_token="test-secret")
        try:
            assert (await provider.cancel("thread-123", "turn-123"))["ok"] is True
        finally:
            await provider.close()

    asyncio.run(exercise())
    assert upstream.received["path"] == "/admin/interrupt-turn"
    assert upstream.received["authorization"] == "Bearer upstream-secret"


def test_oma_buffered_adapter_only_confirms_terminal_response(servers):
    _, gateway = servers

    async def exercise():
        provider = CodexChatGPTWebProvider(
            base_url=f"http://127.0.0.1:{gateway.server_port}/v1",
            model_name="sentra/chatgpt-web/high",
        )
        try:
            result = await provider.execute(AgentRequest(system_prompt="", user_prompt="oi"))
            assert result.success is True
            assert result.content == "ola"
            assert result.metadata["delivery_state"] == "CONFIRMED"
        finally:
            await provider.close()

    asyncio.run(exercise())


def test_internal_turn_authority_requires_private_bearer(servers):
    _, gateway = servers
    capability = gateway.turn_authority.issue()
    payload = {"capability": capability, "traceId": "trace-auth", "allowedTools": []}
    assert call(gateway.server_port, "POST", "/internal/turn/register", payload)[0] == 401
    status, _, _ = call(
        gateway.server_port,
        "POST",
        "/internal/turn/register",
        payload,
        {"Authorization": "Bearer " + gateway.turn_authority_token},
    )
    assert status == 200
    environment = gateway.launcher._environment()
    assert environment["SENTRA_TURN_AUTHORITY_TOKEN"] == gateway.turn_authority_token
    gateway.turn_authority.retire(capability, failed=True)


def test_browser_audit_links_native_turn_without_logging_capability(servers):
    from sentra_core.telemetry import EventJournal

    _, gateway = servers
    capability = gateway.turn_authority.issue(request_identity=json.dumps({
        "thread_id": "thread-audit", "turn_id": "native-audit-turn",
    }))
    try:
        status, _, _ = call(
            gateway.server_port, "POST", "/internal/turn/register",
            {"capability": capability, "traceId": "trace-audit", "allowedTools": []},
            {"Authorization": "Bearer " + gateway.turn_authority_token},
        )
        assert status == 200
        journal = EventJournal(gateway.audit.path.parent)
        page = journal.query(correlation_id="native-audit-turn")
        assert len(page["items"]) == 1
        evidence = page["items"][0]["details"]
        assert evidence["trace_id"] == "trace-audit"
        assert evidence["operation_state"] == "RUNNING"
        assert evidence["completion_verified"] is False
        assert capability not in json.dumps(page)
    finally:
        gateway.turn_authority.retire(capability, failed=True)


def test_generated_admin_token_authorizes_admin_routes(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    gateway = GatewayServer(
        GatewayConfig(
            upstream=f"http://127.0.0.1:{upstream.server_port}",
            port=0,
            admin_token="",
            state_root=tmp_path / "durable",
            browser_descriptor=tmp_path / "browser.json",
        )
    )
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, gateway)]
    for thread in threads:
        thread.start()
    try:
        assert gateway.admin_token
        assert call(gateway.server_port, "GET", "/sentra/status")[0] == 401
        status, _, _ = call(
            gateway.server_port,
            "GET",
            "/sentra/status",
            headers={"Authorization": "Bearer " + gateway.admin_token},
        )
        assert status == 200
    finally:
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_duplicate_codex_turn_identity_is_not_replayed(servers):
    _, gateway = servers
    turn_metadata = json.dumps({
        "thread_id": "thread-dedupe",
        "turn_id": "turn-dedupe",
        "request_kind": "turn",
    })
    request = {"model": "sentra/chatgpt-web/high", "input": "oi"}
    headers = {"x-codex-turn-metadata": turn_metadata}

    assert call(gateway.server_port, "POST", "/v1/responses", request, headers)[0] == 200
    status, payload, _ = call(gateway.server_port, "POST", "/v1/responses", request, headers)
    assert status == 409
    error = json.loads(payload)["error"]
    assert error["type"] == "duplicate_turn"
    assert "automatic replay is disabled" in error["message"]


def test_oma_web_provider_maps_logical_conversation_to_codex_thread_metadata():
    request = AgentRequest(
        system_prompt="system",
        user_prompt="hello",
        role="executor",
        metadata={
            "conversation_uri": "conversation://builder-primary",
            "task_id": "T-123",
            "idempotency_key": "idem-123",
        },
    )
    first, first_turn = CodexChatGPTWebProvider._turn_metadata(request)
    second, second_turn = CodexChatGPTWebProvider._turn_metadata(request)

    assert first == second
    assert first_turn == second_turn
    assert first["prompt_cache_key"].startswith("sentra-thread-")
    encoded = json.loads(first["client_metadata"]["x-codex-turn-metadata"])
    assert encoded["thread_id"] == first["prompt_cache_key"]
    assert encoded["turn_id"] == first_turn
    assert encoded["request_kind"] == "turn"
    assert first["client_metadata"]["sentra_conversation_uri"] == "conversation://builder-primary"


def test_oma_web_provider_sends_canonical_thread_metadata(servers):
    upstream, gateway = servers

    async def exercise():
        provider = CodexChatGPTWebProvider(
            base_url=f"http://127.0.0.1:{gateway.server_port}/v1",
            model_name="sentra/chatgpt-web/high",
        )
        try:
            result = await provider.execute(AgentRequest(
                system_prompt="",
                user_prompt="oi",
                role="executor",
                metadata={
                    "conversation_uri": "conversation://builder-primary",
                    "task_id": "T-456",
                    "idempotency_key": "idem-456",
                },
            ))
            assert result.success is True
        finally:
            await provider.close()

    asyncio.run(exercise())
    body = upstream.received["body"]
    metadata = body["client_metadata"]
    turn = json.loads(metadata["x-codex-turn-metadata"])
    assert body["prompt_cache_key"] == turn["thread_id"]
    assert turn["thread_id"].startswith("sentra-thread-")
    assert turn["turn_id"].startswith("sentra-turn-")
    assert metadata["sentra_conversation_uri"] == "conversation://builder-primary"


class LauncherRuntimeControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        self.server.received = {
            "path": self.path,
            "body": body,
            "authorization": self.headers.get("Authorization"),
        }
        if self.path != "/v1/sentra/runtime-control":
            status, value = 404, {"error": "not_found"}
        elif self.headers.get("Authorization") != "Bearer launcher-private-token-0123456789abcdefgh":
            status, value = 401, {"error": "unauthorized"}
        else:
            status, value = 200, {"status": "ok", "action": body["action"]}
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_gateway_uses_launcher_private_control_without_daemon_token(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    launcher = ThreadingHTTPServer(("127.0.0.1", 0), LauncherRuntimeControlHandler)
    descriptor = tmp_path / "launcher-browser.json"
    descriptor.write_text(json.dumps({
        "version": 3,
        "kind": "codex-web-gpt-launcher",
        "sentraManaged": True,
        "pid": 1234,
        "control": {
            "endpoint": f"http://127.0.0.1:{launcher.server_port}",
            "token": "launcher-private-token-0123456789abcdefgh",
        },
    }), encoding="utf-8")
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        admin_token="admin-secret",
        upstream_control_token="",
        state_root=tmp_path / "durable",
        browser_descriptor=descriptor,
    ))
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (upstream, launcher, gateway)
    ]
    for thread in threads:
        thread.start()
    try:
        headers = {"Authorization": "Bearer admin-secret"}
        status, payload, _ = call(
            gateway.server_port,
            "POST",
            "/sentra/upstream/interrupt-turn",
            {"threadId": "thread-1", "turnId": "turn-1"},
            headers,
        )
        assert status == 200
        assert json.loads(payload)["action"] == "interrupt-turn"
        assert launcher.received["body"] == {
            "action": "interrupt-turn",
            "threadId": "thread-1",
            "turnId": "turn-1",
        }
        assert launcher.received["authorization"] == "Bearer launcher-private-token-0123456789abcdefgh"

        status, payload, _ = call(
            gateway.server_port,
            "POST",
            "/sentra/upstream/drain",
            headers=headers,
        )
        assert status == 200
        assert json.loads(payload)["action"] == "drain"
        assert launcher.received["body"] == {"action": "drain"}
    finally:
        for server in (gateway, launcher, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_gateway_fallback_uses_loaded_private_upstream_control_token(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    state_root = tmp_path / "durable"
    token_dir = state_root / "web-models"
    token_dir.mkdir(parents=True)
    loaded_token = "upstream-control-token-loaded-from-private-state-0123456789"
    (token_dir / "upstream-control.token").write_text(
        loaded_token + "\n", encoding="utf-8"
    )
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        admin_token="admin-secret",
        upstream_control_token="",
        state_root=state_root,
        browser_descriptor=tmp_path / "missing-launcher-browser.json",
    ))
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (upstream, gateway)
    ]
    for thread in threads:
        thread.start()
    try:
        status, payload, _ = call(
            gateway.server_port,
            "POST",
            "/sentra/upstream/interrupt-turn",
            {"threadId": "thread-fallback", "turnId": "turn-fallback"},
            {"Authorization": "Bearer admin-secret"},
        )
        assert status == 200
        assert json.loads(payload)["ok"] is True
        assert upstream.received["path"] == "/admin/interrupt-turn"
        assert upstream.received["authorization"] == "Bearer " + loaded_token
        assert upstream.received["body"] == {
            "threadId": "thread-fallback",
            "turnId": "turn-fallback",
        }
    finally:
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_launcher_supervisor_adopts_only_live_sentra_managed_descriptor(tmp_path):
    descriptor = tmp_path / "launcher-browser.json"
    supervisor = LauncherSupervisor(GatewayConfig(
        port=0,
        browser_descriptor=descriptor,
        launcher_executable=tmp_path / "missing-launcher.exe",
    ))
    payload = supervisor.validate_payload()
    descriptor.write_text(json.dumps({
        "version": 3,
        "kind": "codex-web-gpt-launcher",
        "sentraManaged": True,
        "sentraIntegrationPatchSha256": payload.get("patch_sha256"),
        "pid": os.getpid(),
    }), encoding="utf-8")
    status = supervisor.status()
    assert status == {"running": True, "pid": os.getpid(), "source": "adopted"}
    assert supervisor.process is None

    descriptor.write_text(json.dumps({
        "version": 3,
        "kind": "codex-web-gpt-launcher",
        "sentraManaged": False,
        "pid": os.getpid(),
    }), encoding="utf-8")
    assert supervisor.status() == {"running": False, "pid": None, "source": "none"}


def test_extracts_codex_native_goal_context() -> None:
    body = [
        {"role": "developer", "content": [
            {"type": "input_text", "text": "<goal_context>Ship only when all gates are green.</goal_context>"}
        ]}
    ]
    assert _extract_codex_goal_context(body) == "Ship only when all gates are green."
    internal = {
        "content": '<codex_internal_context source="goal">Keep fixing concrete blockers.</codex_internal_context>'
    }
    assert _extract_codex_goal_context(internal) == "Keep fixing concrete blockers."
    assert _extract_codex_goal_signal("<goal_context></goal_context>") == (True, None)
    assert _extract_codex_goal_signal({"content": "ordinary user text"}) == (False, None)
    assert _extract_codex_goal_context({"content": "ordinary user text"}) is None

    history = [
        {"content": "<goal_context>Old objective.</goal_context>"},
        {"content": "<goal_context>New objective.</goal_context>"},
    ]
    assert _extract_codex_goal_signal(history) == (True, "New objective.")
    cleared_history = [
        {"content": "<goal_context>Old objective.</goal_context>"},
        {"content": "<goal_context></goal_context>"},
    ]
    assert _extract_codex_goal_signal(cleared_history) == (True, None)


def test_extracts_native_codex_subagent_task_without_internal_context() -> None:
    body = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "<goal_context>Release SENTRA.</goal_context>"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Audit the browser bridge independently."}],
        },
    ]
    assert _extract_codex_task_text(body) == "Audit the browser bridge independently."


def test_extract_codex_subagent_notifications_requires_native_passthrough() -> None:
    payload = {
        "type": "message",
        "role": "user",
        "content": [{
            "type": "input_text",
            "text": (
                "<subagent_notification>\n"
                "{\"agent_path\":\"thread-child\","
                "\"status\":{\"completed\":\"done\"}}\n"
                "</subagent_notification>"
            ),
        }],
        "internal_chat_message_metadata_passthrough": {"turn_id": "turn-parent"},
    }
    assert _extract_codex_subagent_notifications([payload]) == [{
        "agent_path": "thread-child",
        "status": {"completed": "done"},
        "turn_id": "turn-parent",
    }]

    spoof = dict(payload)
    spoof.pop("internal_chat_message_metadata_passthrough")
    assert _extract_codex_subagent_notifications([spoof]) == []


def test_model_catalog_auth_and_health_readiness_are_explicit(servers):
    _, gateway = servers

    status, payload, _ = call(gateway.server_port, "GET", "/healthz")
    assert status == 200
    health = json.loads(payload)
    assert health["ready"] is False
    assert health["catalog"]["status"] == "awaiting_codex_catalog"

    status, payload, _ = call(gateway.server_port, "GET", "/v1/models")
    assert status == 401
    assert json.loads(payload)["error"]["type"] == "authentication_error"

    status, _, _ = call(
        gateway.server_port,
        "GET",
        "/v1/models",
        headers={"Authorization": "Bearer codex-token"},
    )
    assert status == 200

    status, payload, _ = call(gateway.server_port, "GET", "/healthz")
    assert status == 200
    health = json.loads(payload)
    assert health["ready"] is True
    assert health["catalog"]["status"] == "ready"

def test_reap_orphan_turns_refuses_when_http_owner_is_active(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream.active_http_turns = 1
    upstream.active_browser_turns = 2
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        admin_token="admin-secret",
        upstream_control_token="upstream-secret",
        state_root=tmp_path / "durable",
        browser_descriptor=tmp_path / "browser.json",
    ))
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(RuntimeError, match="while HTTP turns are active"):
            gateway.reap_orphan_turns()
        assert upstream.active_browser_turns == 2
    finally:
        gateway.server_close()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)


def test_reap_orphan_turns_cancels_browser_leases_with_zero_http_owners(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream.active_http_turns = 0
    upstream.active_browser_turns = 3
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        admin_token="admin-secret",
        upstream_control_token="upstream-secret",
        state_root=tmp_path / "durable",
        browser_descriptor=tmp_path / "browser.json",
    ))
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        result = gateway.reap_orphan_turns()
        assert result["reaped"] is True
        assert result["cancelled_browser_turns"] == 3
        assert result["active_http_turns"] == 0
        assert result["active_browser_turns"] == 0
        assert upstream.active_browser_turns == 0
        assert upstream.received["path"] == "/admin/cancel-turns"
        assert upstream.received["authorization"] == "Bearer upstream-secret"
    finally:
        gateway.server_close()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

def test_gateway_fallback_uses_loaded_upstream_control_token(tmp_path, monkeypatch):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    state_root = tmp_path / "durable"
    token_dir = state_root / "web-models"
    token_dir.mkdir(parents=True)
    (token_dir / "upstream-control.token").write_text(
        "upstream-secret-0123456789-abcdef\n", encoding="utf-8"
    )
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        admin_token="admin-secret",
        upstream_control_token="",
        state_root=state_root,
        browser_descriptor=tmp_path / "browser.json",
    ))

    def fail_runtime_control(*_args, **_kwargs):
        raise RuntimeError("launcher unavailable")

    monkeypatch.setattr(gateway.launcher, "runtime_control", fail_runtime_control)
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (upstream, gateway)
    ]
    for thread in threads:
        thread.start()
    try:
        status, payload, _ = call(
            gateway.server_port,
            "POST",
            "/sentra/upstream/interrupt-turn",
            {"threadId": "thread-fallback", "turnId": "turn-fallback"},
            {"Authorization": "Bearer admin-secret"},
        )
        assert status == 200
        assert json.loads(payload)["ok"] is True
        assert upstream.received["path"] == "/admin/interrupt-turn"
        assert upstream.received["authorization"] == "Bearer upstream-secret-0123456789-abcdef"
    finally:
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
