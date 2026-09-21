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
        started = service.start(".", "alpha", search_type="content", max_results=10)
        sid = started["search_id"]
        deadline = time.monotonic() + 5
        page = {}
        while time.monotonic() < deadline:
            page = service.get_results(sid, 0, 10)
            if page["state"] != "RUNNING":
                break
            time.sleep(0.02)
        assert page["state"] == "COMPLETED"
        assert page["matches"] == 3
        assert {item["path"] for item in page["results"]} == {"a.txt", "b.py"}
        assert service.list_searches()["searches"][0]["id"] == sid
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
    assert approved["restart_required"] is True
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
