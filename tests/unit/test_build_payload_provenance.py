import hashlib
import json
import pytest
from scripts.commander import build_windows as build

def test_installer_rejects_payload_without_current_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "stamp_extension_identity", lambda *_: None)
    monkeypatch.setattr(build, "PAYLOAD_NAMES", ("sentra-mcp.exe",))
    monkeypatch.setattr(build, "_source_fingerprint", lambda: {"product.py": "current"})
    binary = tmp_path / "sentra-mcp.exe"; binary.write_bytes(b"actual")
    with pytest.raises(RuntimeError, match="stale or unverified"):
        build.build_installer(tmp_path, tmp_path / "work", tmp_path / "spec")
    proof = {"sources": {"product.py": "old"}, "executables": {binary.name:{"sha256":hashlib.sha256(binary.read_bytes()).hexdigest()}}}
    (tmp_path / "build-provenance-payload.json").write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match="stale or unverified"):
        build.build_installer(tmp_path, tmp_path / "work", tmp_path / "spec")
    proof["sources"] = {"product.py": "current"}
    (tmp_path / "build-provenance-payload.json").write_text(json.dumps(proof))
    binary.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="stale or unverified"):
        build.build_installer(tmp_path, tmp_path / "work", tmp_path / "spec")
    binary.write_bytes(b"actual")
    with pytest.raises(RuntimeError, match="Electron Web Models payload"):
        build.build_installer(tmp_path, tmp_path / "work", tmp_path / "spec")

def test_full_build_never_certifies_sources_changed_during_payload(tmp_path, monkeypatch):
    sources={"product.py":"initial"}
    current=dict(sources)
    monkeypatch.setattr(build, "_source_fingerprint", lambda:dict(current))
    monkeypatch.setattr(build, "build_web_models", lambda *_: None)
    monkeypatch.setattr(build, "PAYLOAD_NAMES", ("sentra-mcp.exe",))
    def compile_then_change(dist, *_):
        (dist / "sentra-mcp.exe").write_bytes(b"initial binary")
        current["product.py"]="changed"
    monkeypatch.setattr(build, "build_payload", compile_then_change)
    with pytest.raises(RuntimeError, match="source changed during build"):
        build.build(tmp_path, tmp_path / "work", tmp_path / "spec", sources)
    assert not (tmp_path / "build-provenance-payload.json").exists()
