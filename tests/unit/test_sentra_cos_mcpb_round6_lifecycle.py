"""One real central WorkItem: stage -> OAuth PKCE -> MCP GET/DELETE -> Docker -> uninstall.

All external endpoints are local, ephemeral test fixtures; no ChatGPT account or
actual remote provider credentials are opened. Grant and consent are central.
"""
import asyncio
import http.client
import json
import shutil
import socket
import subprocess
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest

from test_sentra_cos_mcpb_offline import fixture as staged_package
from test_sentra_cos_mcpb_session_actions import SessionServer
from sentra_mcp.services.plugin_bundles import MCPBWorkItemLifecycle
from sentra_mcp.services.plugin_host import PluginWorkerHost
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.mcpb_http import MCPHttpRegistry
from sentra_mcp.services.mcpb_oauth import (
    OAuthDPAPIVault, MCPBOAuthPKCE, OAuthAdmissionError, win32crypt,
)

OWNER, RUN, WORK, AGENT = "owner", "run-round6", "WI-round6", "worker"
ALL_CAPS = ("mcp:launch", "mcp:oauth", "mcp:oauth-refresh", "mcp:oauth-revoke",
            "mcp:http-connect", "mcp:list",
            "mcp:echo", "mcp:events", "mcp:session-delete",
            "mcp:deps-install", "mcp:publish-schema", "mcp:manage")


class AuthSessionServer(SessionServer):
    authorization_headers = []
    def do_POST(self):
        type(self).authorization_headers.append(self.headers.get("Authorization"))
        super().do_POST()
    def do_GET(self):
        type(self).authorization_headers.append(self.headers.get("Authorization"))
        super().do_GET()
    def do_DELETE(self):
        type(self).authorization_headers.append(self.headers.get("Authorization"))
        super().do_DELETE()


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        conn.request("GET", path)
        res = conn.getresponse()
        return res.status, res.read()
    finally:
        conn.close()


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _setup(tmp_path):
    control, workspace, sha = staged_package(tmp_path)
    # The real worker host initializes its authoritative SQLite worker table.
    # Without its schema a physical purge correctly fails closed.
    PluginWorkerHost(tmp_path / "state", processes=object(),
                     governance=control.governance,
                     authorization=control.authorization, store=control.store)
    control.durable.create_run(OWNER, run_id=RUN, workspace=str(workspace))
    control.ensure_agent(RUN, OWNER, agent_id=AGENT, role="worker")
    control.create_work_item(RUN, OWNER, work_item_id=WORK,
                             objective="Full MCPB lifecycle in one WorkItem",
                             assignee_agent_id=AGENT,
                             required_capabilities=list(ALL_CAPS))
    control.transition_work_item(WORK, OWNER, "RUNNING")
    bound = MCPBWorkItemLifecycle(control, owner=OWNER, workspace=workspace,
                                  package_sha256=sha, run_id=RUN,
                                  work_item_id=WORK, agent_id=AGENT)
    return control, workspace, sha, bound


def _grant(control, cap):
    return control.authorization_grant(
        OWNER, principal_type="agent", principal_id=AGENT,
        capability=cap, scope_type="work_item", scope_id=WORK)


def _approval(owner, workspace, run, work, agent, sha, action, reference):
    return (owner == OWNER and run == RUN and work == WORK
            and agent == AGENT and len(sha) == 64
            and action in ("publish-schema", "uninstall", "disable",
                           "oauth-refresh", "oauth-revoke")
            and reference == "host-reviewed-ticket")


def _oauth_approval(owner, workspace, run, work, agent, sha, session, reference):
    return (owner == OWNER and run == RUN and work == WORK and agent == AGENT
            and len(sha) == 64 and session == "owner-session"
            and reference == "owner-oauth-ticket")


def _docker_image():
    exe = shutil.which("docker")
    if not exe:
        return None
    try:
        info = subprocess.run([exe, "info", "--format", "{{.OSType}}"],
                              capture_output=True, text=True, timeout=6)
        image = subprocess.run([exe, "image", "inspect", "oma-sandbox:local",
                                "--format", "{{.Id}}"],
                               capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return image.stdout.strip() if (
        info.returncode == 0 and info.stdout.strip() == "linux"
        and image.returncode == 0 and
        image.stdout.strip().startswith("sha256:")) else None


def test_one_workitem_oauth_http_schema_offline_docker_uninstall(
        tmp_path, monkeypatch):
    if win32crypt is None:
        pytest.skip("Real Windows DPAPI unavailable")
    image = _docker_image()
    if not image:
        pytest.skip("Pinned real Docker Linux image unavailable")
    monkeypatch.setenv("SENTRA_MCPB_SANDBOX_IMAGE_ID", image)
    cp, ws, sha, lifecycle = _setup(tmp_path)
    AuthSessionServer.seen = []
    AuthSessionServer.authorization_headers = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), AuthSessionServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    vault = OAuthDPAPIVault(cp.store)
    registry = MCPHttpRegistry(cp)
    receiver = None
    try:
        inspected = lifecycle.inspect()
        assert inspected["registration"] == "REGISTERED"
        assert inspected["server_id"] == "mcpb-" + sha[:32]
        assert inspected["remote_account_verified"] is False

        # Single owner/Run/WorkItem, real authorization, no launch without grant.
        with pytest.raises(PermissionError, match="authorization"):
            cp.bundle_activation_plan(OWNER, str(ws), sha,
                run_id=RUN, work_item_id=WORK, agent_id=AGENT)
        _grant(cp, "mcp:launch")
        launch = cp.bundle_activation_plan(OWNER, str(ws), sha,
            run_id=RUN, work_item_id=WORK, agent_id=AGENT)
        assert launch["grant_checked"] and not launch["worker_started"]

        _grant(cp, "mcp:oauth")
        port = _port()
        broker = MCPBOAuthPKCE(
            authorize_url="https://accounts.example.test/authorize",
            token_url="https://accounts.example.test/token",
            client_id="sentra-round6",
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            scopes=("tools.read",), vault=vault)
        exchanges = []
        def exchange(url, client_id, code, verifier, redirect_uri):
            exchanges.append(code)
            return {"token_type": "Bearer", "access_token": "offline-local-bearer",
                    "refresh_token": "offline-local-refresh", "expires_in": 3600}
        receiver = lifecycle.oauth_callback(
            broker, host_session="owner-session",
            consent_ref="owner-oauth-ticket",
            verify_host_consent=_oauth_approval, exchange=exchange)
        authorized = receiver.start()
        status, body = _get(port, "/callback?" + urlencode(
            {"state": authorized["state"], "code": "single-use-code"}))
        assert status == 200 and b"single-use-code" not in body
        assert receiver.status()["approved"] and len(exchanges) == 1
        assert b"offline-local-bearer" not in cp.store.path_for("plugin_bundle").read_bytes()
        receiver.close()

        registry.register(OWNER, ws, lifecycle.server_id,
                          f"http://127.0.0.1:{server.server_address[1]}/mcp",
                          approved=True, streamable=True)
        _grant(cp, "mcp:http-connect")
        _grant(cp, "mcp:list")
        # Tool must have its own grant, despite registered OAuth credentials.
        with pytest.raises(PermissionError, match="authorization"):
            asyncio.run(lifecycle.call_http_tool(
                registry, vault, name="echo", arguments={},
                operation_id="op-full-tool", idempotency_key="idem-full-tool"))
        assert not AuthSessionServer.seen
        _grant(cp, "mcp:echo")
        call = asyncio.run(lifecycle.call_http_tool(
            registry, vault, name="echo", arguments={},
            operation_id="op-full-tool", idempotency_key="idem-full-tool"))
        assert call.operation.state == "SUCCEEDED", call
        assert call.payload["content"][0]["text"] == "OK"
        assert "Bearer offline-local-bearer" in AuthSessionServer.authorization_headers
        assert cp.durable.operation_status("op-full-tool", OWNER)["state"] == "SUCCEEDED"

        _grant(cp, "mcp:events")
        received = asyncio.run(lifecycle.session_action(
            registry, vault, source_operation_id="op-full-tool",
            operation_id="op-full-events", idempotency_key="idem-full-events",
            action="events"))
        assert received.operation.state == "SUCCEEDED", received
        assert received.payload["last_event_id"] == "cursor_1"
        _grant(cp, "mcp:session-delete")
        deleted = asyncio.run(lifecycle.session_action(
            registry, vault, source_operation_id="op-full-tool",
            operation_id="op-full-delete", idempotency_key="idem-full-delete",
            action="delete"))
        assert deleted.operation.state == "SUCCEEDED"
        assert sum(x[0] == "DELETE" for x in AuthSessionServer.seen) == 1
        assert len(AuthSessionServer.authorization_headers) == len(AuthSessionServer.seen)
        assert all(x == "Bearer offline-local-bearer"
                   for x in AuthSessionServer.authorization_headers)

        _grant(cp, "mcp:publish-schema")
        with pytest.raises(PermissionError, match="approval"):
            lifecycle.publish_verified_tool(
                source_operation_id="op-full-tool", tool_name="echo",
                descriptor={"name": "echo", "inputSchema": {"type": "object"}},
                approval_ref="wrong", verify_host_approval=_approval)
        exposed = lifecycle.publish_verified_tool(
            source_operation_id="op-full-tool", tool_name="echo",
            descriptor={"name": "echo", "inputSchema": {"type": "object"}},
            approval_ref="host-reviewed-ticket",
            verify_host_approval=_approval)
        assert exposed["enabled"] and exposed["external_account_verified"] is False
        publication = cp.tool_exposure.publication_snapshot(
            [exposed["provider_id"]], allowed_names=["echo"])
        assert publication["tool_count"] == 1
        assert publication["external_account_verified"] is False

        # Same central WorkItem + grants for a REAL, no-egress Docker job.
        with pytest.raises(PermissionError, match="authorization"):
            asyncio.run(lifecycle.install_offline_in_owned_docker(
                operation_id="op-full-wheels", idempotency_key="idem-full-wheels"))
        _grant(cp, "mcp:deps-install")
        wheels = asyncio.run(lifecycle.install_offline_in_owned_docker(
            operation_id="op-full-wheels", idempotency_key="idem-full-wheels"))
        assert wheels.operation.state == "SUCCEEDED", wheels
        assert wheels.payload["installed_imports"] == ["demo"]
        assert wheels.payload["network"] == "none"
        with cp.store.connect("plugin_bundle") as db:
            docker_claim = db.execute(
                "SELECT state,run_id,work_item_id,container_id FROM mcpb_docker_ownership "
                "WHERE operation_id='op-full-wheels'").fetchone()
        assert docker_claim["state"] == "CLEANED"
        assert docker_claim["run_id"] == RUN and docker_claim["work_item_id"] == WORK
        assert len(docker_claim["container_id"]) == 64
        replay = asyncio.run(lifecycle.install_offline_in_owned_docker(
            operation_id="op-full-wheels", idempotency_key="idem-full-wheels"))
        assert replay.duplicate and replay.operation.state == "SUCCEEDED"

        _grant(cp, "mcp:manage")
        with pytest.raises(PermissionError, match="approval"):
            lifecycle.retire(registry, vault, approval_ref="wrong",
                             verify_host_approval=_approval)
        retired = lifecycle.retire(
            registry, vault, approval_ref="host-reviewed-ticket",
            verify_host_approval=_approval, uninstall=True, purge=True)
        assert retired["registration"] == "DISABLED"
        assert retired["uninstall"]["status"] == "REMOVED"
        assert retired["purge"]["extracted_removed"]
        assert cp.tool_exposure.publication_snapshot(
            [exposed["provider_id"]])["tool_count"] == 0
        assert vault.status(OWNER, ws, lifecycle.server_id)["status"] == "REVOKED"
        assert registry.get(OWNER, ws, lifecycle.server_id)["enabled"] == 0
        assert not (cp.bundle_catalog.target / sha).exists()
        assert (cp.bundle_catalog.target / ".archives" / (sha + ".mcpb")).exists()
        with pytest.raises((PermissionError, FileNotFoundError, ValueError)):
            asyncio.run(lifecycle.call_http_tool(
                registry, vault, name="echo", arguments={},
                operation_id="op-after-retire", idempotency_key="idem-after-retire"))
        assert len(exchanges) == 1
        assert sum(x[0] == "DELETE" for x in AuthSessionServer.seen) == 1
    finally:
        if receiver is not None:
            receiver.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        cp.durable.close()


def test_lifecycle_rejects_foreign_workitem_and_broken_consent(tmp_path):
    cp, ws, sha, bind = _setup(tmp_path)
    try:
        with pytest.raises((PermissionError, FileNotFoundError)):
            MCPBWorkItemLifecycle(cp, owner="other", workspace=ws,
                package_sha256=sha, run_id=RUN, work_item_id=WORK, agent_id=AGENT)
        with pytest.raises(PermissionError):
            MCPBWorkItemLifecycle(cp, owner=OWNER, workspace=ws,
                package_sha256=sha, run_id=RUN, work_item_id=WORK,
                agent_id="other-agent")
        assert bind.inspect()["registration"] == "REGISTERED"
        with pytest.raises(PermissionError, match="authorization"):
            bind._binding("mcp:manage")
        with pytest.raises(PermissionError, match="approval"):
            bind._host_approval("disable", "host-reviewed-ticket", lambda *args: False)
        with pytest.raises(PermissionError):
            bind._host_approval("disable", "", _approval)
    finally:
        cp.durable.close()


def test_same_workitem_oauth_refresh_revoke_durable_no_duplicate(tmp_path):
    if win32crypt is None:
        pytest.skip("Windows DPAPI unavailable")
    cp, ws, sha, bind = _setup(tmp_path)
    registry = MCPHttpRegistry(cp)
    vault = OAuthDPAPIVault(cp.store)
    vault.put(OWNER, ws, bind.server_id,
              {"token_type": "Bearer", "access_token": "initial-fixture",
               "refresh_token": "initial-refresh", "expires_in": 3600},
              approved=True)
    seen = []
    args = dict(approval_ref="host-reviewed-ticket",
                verify_host_approval=_approval)
    try:
        with pytest.raises(PermissionError, match="authorization"):
            asyncio.run(bind.oauth_effect(
                vault, action="refresh", operation_id="op-r6-refresh",
                idempotency_key="idem-r6-refresh", exchange=lambda x: {},
                **args))
        _grant(cp, "mcp:oauth-refresh")
        with pytest.raises(PermissionError, match="approval"):
            asyncio.run(bind.oauth_effect(
                vault, action="refresh", operation_id="op-r6-refresh",
                idempotency_key="idem-r6-refresh",
                exchange=lambda x: {}, approval_ref="invalid",
                verify_host_approval=_approval))
        def exchange(refresh):
            seen.append(("refresh", refresh))
            assert refresh == "initial-refresh"
            return {"token_type": "Bearer", "access_token": "rotated-fixture",
                    "refresh_token": "rotated-refresh", "expires_in": 3600}
        fresh = asyncio.run(bind.oauth_effect(
            vault, action="refresh", operation_id="op-r6-refresh",
            idempotency_key="idem-r6-refresh", exchange=exchange, **args))
        assert fresh.operation.state == "SUCCEEDED", fresh
        assert vault.access(OWNER, ws, bind.server_id) == "rotated-fixture"
        duplicate = asyncio.run(bind.oauth_effect(
            vault, action="refresh", operation_id="op-r6-refresh",
            idempotency_key="idem-r6-refresh", exchange=exchange, **args))
        assert duplicate.duplicate and duplicate.operation.state == "SUCCEEDED"
        assert seen == [("refresh", "initial-refresh")]
        _grant(cp, "mcp:oauth-revoke")
        def revoke(refresh):
            seen.append(("revoke", refresh))
            assert refresh == "rotated-refresh"
            with pytest.raises(OAuthAdmissionError):
                vault.access(OWNER, ws, bind.server_id)
            return True
        result = asyncio.run(bind.oauth_effect(
            vault, action="revoke", operation_id="op-r6-revoke",
            idempotency_key="idem-r6-revoke", revoke=revoke, **args))
        assert result.operation.state == "SUCCEEDED", result
        assert result.payload["remote_confirmed"] is True
        assert vault.status(OWNER, ws, bind.server_id)["status"] == "REVOKED"
        again = asyncio.run(bind.oauth_effect(
            vault, action="revoke", operation_id="op-r6-revoke",
            idempotency_key="idem-r6-revoke", revoke=revoke, **args))
        assert again.duplicate
        assert seen == [("refresh", "initial-refresh"),
                        ("revoke", "rotated-refresh")]
        # Retirement preserves the recorded remote revocation status.
        _grant(cp, "mcp:manage")
        retired = bind.retire(registry, vault, approval_ref="host-reviewed-ticket",
                              verify_host_approval=_approval)
        assert retired["registration"] == "DISABLED"
        assert vault.status(OWNER, ws, bind.server_id)["status"] == "REVOKED"
        assert cp.durable.operation_status("op-r6-refresh", OWNER)["state"] == "SUCCEEDED"
        assert cp.durable.operation_status("op-r6-revoke", OWNER)["state"] == "SUCCEEDED"
    finally:
        cp.durable.close()


def test_ambiguous_refresh_stays_uncertain_on_retry_and_wrong_store_denied(tmp_path):
    if win32crypt is None:
        pytest.skip("Windows DPAPI unavailable")
    from sentra_mcp.services.control_store import SQLiteControlPlaneStore
    cp, ws, sha, bind = _setup(tmp_path)
    vault = OAuthDPAPIVault(cp.store)
    vault.put(OWNER, ws, bind.server_id,
              {"token_type": "Bearer", "access_token": "fixture-access",
               "refresh_token": "fixture-refresh", "expires_in": 3600},
              approved=True)
    _grant(cp, "mcp:oauth-refresh")
    args = dict(action="refresh", operation_id="op-r6-refresh-uncertain",
                idempotency_key="idem-r6-refresh-uncertain",
                approval_ref="host-reviewed-ticket",
                verify_host_approval=_approval)
    sends = []
    def uncertain(secret):
        sends.append(secret)
        raise TimeoutError("synthetic ambiguous provider response")
    try:
        wrong_store = OAuthDPAPIVault(SQLiteControlPlaneStore(tmp_path / "other-state"))
        with pytest.raises(PermissionError, match="Pacto local authority differs"):
            asyncio.run(bind.oauth_effect(wrong_store, exchange=uncertain, **args))
        assert not sends
        result = asyncio.run(bind.oauth_effect(vault, exchange=uncertain, **args))
        assert result.operation.state == "UNCERTAIN", result
        assert vault.status(OWNER, ws, bind.server_id)["status"] == "UNCERTAIN"
        replay = asyncio.run(bind.oauth_effect(vault, exchange=uncertain, **args))
        assert replay.duplicate and replay.operation.state == "UNCERTAIN"
        assert sends == ["fixture-refresh"]
        with pytest.raises(OAuthAdmissionError):
            vault.access(OWNER, ws, bind.server_id)
    finally:
        cp.durable.close()


def test_schema_receipt_foreign_workitem_and_foreign_retire_authority_denied(tmp_path):
    cp, ws, sha, binding = _setup(tmp_path)
    vault = OAuthDPAPIVault(cp.store) if win32crypt is not None else None
    other = None
    try:
        _grant(cp, "mcp:publish-schema")
        kwargs = dict(tool_name="echo",
                      descriptor={"name": "echo", "inputSchema": {"type": "object"}},
                      approval_ref="host-reviewed-ticket",
                      verify_host_approval=_approval)
        with pytest.raises(FileNotFoundError):
            binding.publish_verified_tool(source_operation_id="op-not-present", **kwargs)
        cp.durable.create_run(OWNER, run_id="run-other", workspace=str(ws))
        cp.ensure_agent("run-other", OWNER, agent_id="other-worker", role="worker")
        cp.create_work_item("run-other", OWNER, work_item_id="WI-other",
                            objective="different WorkItem",
                            assignee_agent_id="other-worker")
        cp.transition_work_item("WI-other", OWNER, "RUNNING")
        cp.durable.create_operation("run-other", OWNER, kind="mcp:test-receipt",
                                    operation_id="op-other", idempotency_key="idem-other")
        cp.durable.update_operation(
            "op-other", OWNER, state="RUNNING",
            progress={"work_item_id": "WI-other", "principal_id": "other-worker"})
        cp.durable.update_operation("op-other", OWNER, state="SUCCEEDED")
        with pytest.raises(PermissionError, match="same|receipt|match|central"):
            binding.publish_verified_tool(source_operation_id="op-other", **kwargs)
        provider = cp.bundle_catalog.registration(OWNER, ws, sha)["plugin_id"]
        assert cp.tool_exposure.publication_snapshot([provider])["tool_count"] == 0
        _grant(cp, "mcp:manage")
        other = ControlPlaneService(
            DurableRunService(tmp_path / "other-state"),
            ContextBusService(tmp_path / "other-state"))
        wrong_registry = MCPHttpRegistry(other)
        if vault is not None:
            with pytest.raises(PermissionError, match="central"):
                binding.retire(wrong_registry, vault,
                               approval_ref="host-reviewed-ticket",
                               verify_host_approval=_approval)
            assert cp.bundle_catalog.registration(OWNER, ws, sha)["status"] == "REGISTERED"
    finally:
        if other is not None:
            other.durable.close()
        cp.durable.close()
