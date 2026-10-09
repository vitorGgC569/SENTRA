"""No-publication safety tests for Edge Add-ons release packaging."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.commander import edge_store_assistant as edge


def _source(tmp_path: Path, *, ready: bool) -> Path:
    src = tmp_path / "edge"
    src.mkdir(parents=True)
    manifest = {
        "manifest_version": 3, "name": "SENTRA Browser",
        "version": "1.0.0", "host_permissions": ["https://chatgpt.com/*"],
    }
    (src / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (src / "service-worker.js").write_text("void 0;", encoding="utf-8")
    (src / "README.md").write_text("documentation", encoding="utf-8")
    if not ready:
        (src / "sentra-bootstrap.json").write_text('{"proof":"local"}', encoding="utf-8")
    return src


def test_repo_extension_has_store_publishing_blockers():
    report = edge.store_preflight()
    assert not report["ready_for_store"]
    assert any("pairing proof" in text for text in report["blockers"])


def test_package_offline_deterministic_and_excludes_markdown(tmp_path):
    source = _source(tmp_path, ready=True)
    first = edge.package(source, tmp_path / "one.zip")
    second = edge.package(source, tmp_path / "two.zip")
    assert first["ready_for_store"] and first["candidate_only"]
    assert first["sha256"] == second["sha256"]
    with zipfile.ZipFile(tmp_path / "one.zip") as archive:
        assert sorted(archive.namelist()) == ["manifest.json", "service-worker.js"]


def test_store_archive_rejects_proof_or_stale_changes(tmp_path):
    local = _source(tmp_path / "local", ready=False)
    bad = tmp_path / "local.zip"
    local_package = edge.package(local, bad)
    assert "sentra-bootstrap.json" not in local_package["files"]
    with zipfile.ZipFile(bad) as archive:
        assert "sentra-bootstrap.json" not in archive.namelist()
    with pytest.raises(ValueError, match="pairing proof"):
        edge.validate_store_archive(local, bad)

    publishable = _source(tmp_path / "ready", ready=True)
    good = tmp_path / "ready.zip"
    edge.package(publishable, good)
    edge.validate_store_archive(publishable, good)
    (publishable / "service-worker.js").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        edge.validate_store_archive(publishable, good)


def test_store_archive_rejects_unexpected_members(tmp_path):
    ready = _source(tmp_path / "ready", ready=True)
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", (ready / "manifest.json").read_bytes())
        z.writestr("service-worker.js", (ready / "service-worker.js").read_bytes())
        z.writestr("../malicious.js", "test")
    with pytest.raises(ValueError, match="differs"):
        edge.validate_store_archive(ready, path)


def test_store_upload_denies_unapproved_and_not_ready(tmp_path, monkeypatch):
    source = _source(tmp_path, ready=False)
    archive = tmp_path / "candidate.zip"
    edge.package(source, archive)
    monkeypatch.setattr(edge, "_request", lambda *_a, **_kw: pytest.fail("network must not run"))
    with pytest.raises(PermissionError):
        edge.upload(source, archive, approved=False)
    report = edge.upload(source, archive, approved=True)
    assert report["ok"] is False
    assert report["blockers"]


def test_store_publish_requires_approval_and_confirmed_upload(tmp_path, monkeypatch):
    source = _source(tmp_path, ready=True)
    monkeypatch.setattr(edge, "operation_status", lambda *_a: {"ok": False})
    monkeypatch.setattr(edge, "_request", lambda *_a, **_kw: pytest.fail("network must not run"))
    with pytest.raises(PermissionError):
        edge.publish(source, uploaded_operation="identifier", approved=False)
    outcome = edge.publish(source, uploaded_operation="identifier", approved=True)
    assert outcome["reason"] == "package_upload_not_confirmed"


def test_status_does_not_accept_untrusted_operation_ids():
    with pytest.raises(ValueError):
        edge.operation_status("../../other")
    with pytest.raises(ValueError):
        edge.operation_status("ok", kind="unsupported")
