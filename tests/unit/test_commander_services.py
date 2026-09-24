from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path

import pytest

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.services.browser import BrowserControlService
from sentra_mcp.services.documents import DocumentService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.filesystem import FilesystemService
from sentra_mcp.services.runtime_config import RuntimeConfigService
from sentra_mcp.services.search_sessions import SearchSessionService
from sentra_mcp.services.telemetry import TelemetryService
from sentra_mcp.services.workspace_ops import WorkspaceOpsService
from sentra_remote.agent import AgentConfig
from sentra_remote.updater import _safe_extract, download_verified, fetch_manifest


def _config(tmp_path: Path) -> MCPConfig:
    return MCPConfig(
        allowed_roots=(tmp_path,),
        audit_log=tmp_path / ".sentra" / "audit.jsonl",
        remote_store_path=tmp_path / ".sentra" / "remote.sqlite3",
    )


def test_persistent_search_pages_and_stops(tmp_path: Path) -> None:
    config = _config(tmp_path)
    audit = AuditLogger(config.audit_log)
    (tmp_path / "a.txt").write_text("alpha\nbeta\nalpha again\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("value = 'alpha'\n", encoding="utf-8")
    service = SearchSessionService(config, audit, db_path=tmp_path / ".sentra" / "search.sqlite3")
    try:
        started = service.start(
            ".",
            "alpha",
            owner="test-session",
            search_type="content",
            max_results=10,
        )
        sid = started["search_id"]
        deadline = time.monotonic() + 5
        page = {}
        while time.monotonic() < deadline:
            page = service.get_results(sid, "test-session", 0, 10)
            if page["state"] != "RUNNING":
                break
            time.sleep(0.02)
        assert page["state"] == "COMPLETED"
        assert page["matches"] == 3
        assert {item["path"] for item in page["results"]} == {"a.txt", "b.py"}
        assert service.list_searches("test-session")["searches"][0]["id"] == sid
    finally:
        service.close()


def test_runtime_config_safe_apply_and_privileged_offline_approval(tmp_path: Path) -> None:
    state = {"max_read_bytes": 1000}
    applied: list[dict] = []
    service = RuntimeConfigService(
        lambda: dict(state),
        lambda changes: applied.append(dict(changes)) or dict(changes),
        state_path=tmp_path / "config.json",
    )
    result = service.update({"max_read_bytes": 4096, "allowed_roots": [str(tmp_path)]})
    assert result["applied"]["max_read_bytes"] == 4096
    assert result["approval_required"]["request_id"]
    pending = service.list_pending()["pending"]
    request_id = result["approval_required"]["request_id"]
    assert pending[request_id]["status"] == "PENDING"
    approved = service.approve_local(request_id)
    assert approved["restart_required"] is False
    assert approved["reload_required"] is True
    assert service.approved_overrides()["allowed_roots"] == [str(tmp_path)]


def test_telemetry_and_pdf_writer(tmp_path: Path) -> None:
    config = _config(tmp_path)
    audit = AuditLogger(config.audit_log)
    fs = FilesystemService(config, audit)
    docs = DocumentService(fs, audit)
    audit.emit("process.start", "ok", {"bytes": 0})
    audit.emit("filesystem.read", "ok", {"bytes": 12})
    audit.emit("filesystem.write", "ok", {"bytes": 5})
    audit.emit("security.denied", "forbidden", {})

    result = docs.write_pdf("report.pdf", "hello\nworld", "Report")
    assert result["bytes"] > 100
    info = docs.document_info("report.pdf")
    assert info["type"] == "pdf"
    assert info["pdf_header"] is True
    assert info["pages_approx"] >= 1

    stats = TelemetryService(config).usage_stats()
    assert stats["calls_total"] >= 5
    assert stats["processes_started"] == 1
    assert stats["security_denials"] >= 1


def test_browser_blocks_private_and_loopback_targets(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = BrowserControlService(config, AuditLogger(config.audit_log))
    with pytest.raises(PermissionError):
        service._validate_url_sync("http://127.0.0.1/admin")
    with pytest.raises(PermissionError):
        service._validate_url_sync("http://localhost/")
    with pytest.raises(ValueError):
        service._validate_url_sync("file:///etc/passwd")


def test_workspace_sandbox_apply_evidence_and_rollback(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("old\n", encoding="utf-8", newline="\n")
    config = MCPConfig(
        allowed_roots=(tmp_path,),
        audit_log=tmp_path / ".sentra" / "audit.jsonl",
        remote_store_path=tmp_path / ".sentra" / "remote.sqlite3",
    )
    fs = FilesystemService(config, AuditLogger(config.audit_log))
    service = WorkspaceOpsService(fs, AuditLogger(config.audit_log))
    try:
        created = service.create_sandbox("repo", "owner")
        sid = created["sandbox_id"]
        patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        applied = service.apply_candidate(sid, "owner", patch)
        assert applied["apply_result"]["success"] is True
        evidence = service.get_evidence(sid, "owner")
        assert "new" in evidence["diff"]
        service.rollback(sid, "owner")
        assert service.get_evidence(sid, "owner")["diff"] == ""
        with pytest.raises(PermissionError):
            service.get_evidence(sid, "other")
    finally:
        service.shutdown()


def test_updater_requires_https_and_verifies_sha256(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("install.ps1", "Write-Host ok")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    class Response:
        status = 200
        def __init__(self, data: bytes):
            self.data = data
            self.offset = 0
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1):
            if size < 0:
                data, self.offset = self.data[self.offset:], len(self.data)
                return data
            data = self.data[self.offset:self.offset+size]
            self.offset += len(data)
            return data

    manifest = {"version": "3.0.0", "url": "https://example.test/bundle.zip", "sha256": digest}
    def fake_open(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("manifest.json"):
            return Response(json.dumps(manifest).encode())
        return Response(archive.read_bytes())

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    fetched = fetch_manifest("https://example.test/manifest.json")
    out = download_verified(fetched, tmp_path / "download.zip")
    assert out.read_bytes() == archive.read_bytes()
    with pytest.raises(ValueError):
        fetch_manifest("http://example.test/manifest.json")


def test_agent_config_protects_device_token_at_rest(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    token = "device-secret-" + "x" * 48
    config = AgentConfig(
        relay_url="https://relay.example.test",
        device_id="device-1",
        device_token=token,
        name="PC",
        allowed_roots=[str(tmp_path)],
        audit_log=str(tmp_path / "audit.jsonl"),
    )
    config.save(path)
    raw = path.read_text(encoding="utf-8")
    assert token not in raw
    loaded = AgentConfig.load(path)
    assert loaded.device_token == token
    assert loaded.device_id == "device-1"


def test_updater_rejects_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    target = tmp_path / "extract"
    target.mkdir()
    with pytest.raises(ValueError, match="unsafe path"):
        _safe_extract(archive, target)
    assert not (tmp_path / "outside.txt").exists()



def test_search_wait_screenshot_resource_and_tool_surfaces(tmp_path: Path) -> None:
    import asyncio
    from mcp import Client
    from sentra_mcp.server import SentraMCPServer

    async def probe() -> None:
        config = MCPConfig(
            allowed_roots=(tmp_path,),
            audit_log=tmp_path / ".sentra" / "audit.jsonl",
            remote_store_path=tmp_path / ".sentra" / "remote.sqlite3",
            tool_surfaces=("core", "developer"),
        )
        runtime = SentraMCPServer(config)
        (tmp_path / "needle.txt").write_text("search-wait-token\n", encoding="utf-8")
        async with Client(runtime.mcp) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert "sentra_search_wait" in tools
            assert "sentra_repo_status" in tools
            assert "sentra_browser_open" not in tools
            assert "sentra_list_devices" not in tools
            assert "sentra_usage_stats" not in tools
            assert "sentra_oma_health" not in tools
            assert "sentra_test_start" in tools
            assert "sentra_job_wait" in tools
            assert "sentra_request_workspace" in tools
            assert "sentra_read_document" in tools
            assert len(tools) <= 60

            started = await client.call_tool("sentra_start_search", {
                "path": ".",
                "pattern": "search-wait-token",
                "search_type": "content",
                "max_results": 10,
            })
            sid = started.structured_content["data"]["search_id"]
            waited = await client.call_tool("sentra_search_wait", {
                "search_id": sid,
                "timeout_s": 5,
                "length": 10,
            })
            page = waited.structured_content["data"]
            assert page["state"] == "COMPLETED"
            assert page["timed_out"] is False
            assert page["matches"] == 1
            assert page["next_poll_after_ms"] is None

            saved = runtime.browser._write_screenshot_bytes(
                "playwright:test",
                b"fake-png-bytes",
                ".png",
                "image/png",
                "https://example.com/",
                include_base64=False,
                full_page=True,
                backend="playwright",
            )
            assert "image_base64" not in saved
            assert saved["resource_uri"].startswith("sentra://screenshot/")
            resource = await client.read_resource(saved["resource_uri"])
            assert resource.contents
        await runtime.browser.shutdown()
        runtime.search.close()
        runtime.processes.shutdown()
        runtime.remote_store.close()

    asyncio.run(probe())


def test_default_surface_is_core_developer_browser_and_browser_owner_is_optional(tmp_path: Path) -> None:
    import asyncio
    from mcp import Client
    from sentra_mcp.server import SentraMCPServer

    async def probe() -> None:
        runtime = SentraMCPServer(_config(tmp_path))
        async with Client(runtime.mcp) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert "sentra_browser_open" in tools
            assert "sentra_research_start" in tools
            assert "sentra_usage_stats" not in tools
            assert "sentra_list_devices" not in tools
            assert "sentra_oma_health" not in tools
            assert len(tools) < 75
            schema = tools["sentra_browser_open"].input_schema
            assert "owner" in schema["properties"]
            assert "session_token" in schema["properties"]
            assert "owner" not in schema.get("required", [])
            assert "session_token" in tools["sentra_browser_tabs"].input_schema["properties"]
            assert "session_token" in tools["sentra_create_sandbox"].input_schema["properties"]
            backend = schema["properties"]["backend"]
            assert set(backend["enum"]) == {"auto", "playwright", "edge"}
            shot = tools["sentra_browser_screenshot"].input_schema["properties"]
            assert shot["include_base64"]["default"] is False
        await runtime.browser.shutdown()
        runtime.search.close()
        runtime.processes.shutdown()
        runtime.remote_store.close()

    asyncio.run(probe())



def test_allowed_root_request_is_additive_and_live_reload_requires_local_approval(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    effective = {"allowed_roots": [str(primary)]}
    applied: list[dict] = []

    def apply(changes: dict) -> dict:
        applied.append(dict(changes))
        effective.update(changes)
        return dict(changes)

    service = RuntimeConfigService(
        lambda: dict(effective),
        apply,
        state_path=primary / ".sentra" / "config.json",
    )

    requested = service.request_allowed_root(str(secondary))
    assert requested["already_allowed"] is False
    assert requested["approval_required"]["request_id"]
    assert effective["allowed_roots"] == [str(primary)]

    request_id = requested["approval_required"]["request_id"]
    approved = service.approve_local(request_id)
    assert approved["reload_required"] is True
    assert approved["restart_required"] is False
    assert effective["allowed_roots"] == [str(primary)]

    reloaded = service.reload_approved()
    assert reloaded["restart_required"] is False
    assert effective["allowed_roots"] == [
        str(primary.resolve()),
        str(secondary.resolve()),
    ]
    assert applied[-1]["allowed_roots"] == effective["allowed_roots"]

    duplicate = service.request_allowed_root(str(secondary))
    assert duplicate["already_allowed"] is True
    assert duplicate["approval_required"] is None


def test_allowed_root_request_rejects_relative_and_missing_paths(tmp_path: Path) -> None:
    service = RuntimeConfigService(
        lambda: {"allowed_roots": [str(tmp_path)]},
        lambda changes: dict(changes),
        state_path=tmp_path / "config.json",
    )
    with pytest.raises(ValueError, match="absolute"):
        service.request_allowed_root("relative/project")
    with pytest.raises(FileNotFoundError):
        service.request_allowed_root(str(tmp_path / "missing"))


def test_server_live_reload_approved_root_updates_filesystem_and_repository(tmp_path: Path) -> None:
    import asyncio
    from mcp import Client
    from sentra_mcp.server import SentraMCPServer

    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    (secondary / "outside-project.txt").write_text("secondary-root\n", encoding="utf-8")

    async def probe() -> None:
        runtime = SentraMCPServer(MCPConfig(
            allowed_roots=(primary,),
            audit_log=primary / ".sentra" / "audit.jsonl",
            remote_store_path=primary / ".sentra" / "remote.sqlite3",
        ))
        try:
            async with Client(runtime.mcp) as client:
                denied = await client.call_tool("sentra_read_file", {
                    "path": str(secondary / "outside-project.txt"),
                })
                assert denied.structured_content["ok"] is False

                request = await client.call_tool("sentra_request_allowed_root", {
                    "path": str(secondary),
                })
                request_data = request.structured_content["data"]
                request_id = request_data["approval_required"]["request_id"]

                approved = runtime.workspaces.approve_local(request_id)
                assert approved["status"] == "APPROVED"

                allowed = await client.call_tool("sentra_read_file", {
                    "path": str(secondary / "outside-project.txt"),
                })
                assert allowed.structured_content["ok"] is True
                assert "secondary-root" in allowed.structured_content["data"]["content"]

                listed = await client.call_tool("sentra_repo_workspaces", {})
                workspaces = listed.structured_content["data"]["workspaces"]
                assert [Path(item["path"]) for item in workspaces] == [
                    primary.resolve(),
                    secondary.resolve(),
                ]
                assert workspaces[1]["id"] == "root:1"
        finally:
            await runtime.browser.shutdown()
            runtime.search.close()
            runtime.processes.shutdown()
            runtime.remote_store.close()

    asyncio.run(probe())



def test_persistent_search_is_correlated_to_durable_operation_and_idempotent(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    audit = AuditLogger(config.audit_log)
    durable = DurableRunService(tmp_path / ".sentra")
    (tmp_path / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    service = SearchSessionService(
        config,
        audit,
        durable=durable,
        db_path=tmp_path / ".sentra" / "search-durable.sqlite3",
    )
    try:
        run = durable.create_run("test-session", workspace="root:0")
        first = service.start(
            ".",
            "alpha",
            owner="test-session",
            search_type="content",
            run_id=run["run_id"],
            idempotency_key="search-once",
        )
        assert first["run_id"] == run["run_id"]
        assert first["operation_id"]
        assert first["idempotency_key"] == "search-once"

        replay = service.start(
            ".",
            "alpha",
            owner="test-session",
            search_type="content",
            run_id=run["run_id"],
            idempotency_key="search-once",
        )
        assert replay["search_id"] == first["search_id"]
        assert replay["operation_id"] == first["operation_id"]
        assert replay["idempotent_replay"] is True

        deadline = time.monotonic() + 5
        page = {}
        while time.monotonic() < deadline:
            page = service.get_results(
                first["search_id"], "test-session", 0, 10
            )
            if page["state"] not in {"RUNNING", "CANCELLING"}:
                break
            time.sleep(0.02)

        assert page["run_id"] == run["run_id"]
        assert page["operation_id"] == first["operation_id"]
        operation = durable.operation_status(
            first["operation_id"], "test-session"
        )
        assert operation["state"] == "SUCCEEDED"
        assert operation["readiness"] == "PRODUCT_READY"
        assert operation["result"]["search_id"] == first["search_id"]
    finally:
        service.close()
        durable.close()
