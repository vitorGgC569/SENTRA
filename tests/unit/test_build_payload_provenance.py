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


def test_release_provenance_tracks_packaged_brand_pngs(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    original = tmp_path / "sentra_canvas" / "assets" / "SENTRA-LOGO.png"
    favicon = tmp_path / "sentra_canvas" / "static" / "sentra-logo.png"
    original.parent.mkdir(parents=True)
    favicon.parent.mkdir(parents=True)
    original.write_bytes(b"original-brand")
    favicon.write_bytes(b"favicon-v1")
    initial = build._source_fingerprint()
    assert initial["sentra_canvas/assets/SENTRA-LOGO.png"] == hashlib.sha256(b"original-brand").hexdigest()
    assert initial["sentra_canvas/static/sentra-logo.png"] == hashlib.sha256(b"favicon-v1").hexdigest()
    favicon.write_bytes(b"favicon-v2")
    changed = build._source_fingerprint()
    assert changed["sentra_canvas/static/sentra-logo.png"] != initial["sentra_canvas/static/sentra-logo.png"]


def test_release_provenance_tracks_react_jsx_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    source = tmp_path / "sentra_canvas" / "desktop_ui" / "src" / "main.jsx"
    source.parent.mkdir(parents=True)
    source.write_text("export const version = 1;\n", encoding="utf-8")
    first = build._source_fingerprint()
    key = "sentra_canvas/desktop_ui/src/main.jsx"
    assert first[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("export const version = 2;\n", encoding="utf-8")
    assert build._source_fingerprint()[key] != first[key]


def test_release_provenance_tracks_web_models_builder_and_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    builder = tmp_path / "scripts" / "integrations" / "Build-CodexChatGPTWebRuntime.ps1"
    patch = tmp_path / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch"
    builder.parent.mkdir(parents=True)
    patch.parent.mkdir(parents=True)
    builder.write_text("Write-Output 'first'\n", encoding="utf-8")
    patch.write_text("initial patch\n", encoding="utf-8")
    original = build._source_fingerprint()
    builder_key = "scripts/integrations/Build-CodexChatGPTWebRuntime.ps1"
    patch_key = "integrations/codex_chatgpt_web/sentra-upstream.patch"
    assert original[builder_key] == hashlib.sha256(builder.read_bytes()).hexdigest()
    assert original[patch_key] == hashlib.sha256(patch.read_bytes()).hexdigest()
    builder.write_text("Write-Output 'second'\n", encoding="utf-8")
    patch.write_text("updated patch\n", encoding="utf-8")
    current = build._source_fingerprint()
    assert current[builder_key] != original[builder_key]
    assert current[patch_key] != original[patch_key]


def test_release_provenance_tracks_packaged_notices_licenses_and_onboarding(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    paths = (
        "edge_extension/COS-NOTICE.txt",
        "sentra_canvas/static/desktop-assets/THIRD_PARTY_NOTICES.txt",
        "sentra_electron/THIRD_PARTY_NOTICES.md",
        "sentra_canvas/static/vendor/xterm-LICENSE",
        "sentra_canvas/static/vendor/addon-fit-LICENSE",
        "docs/SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md",
    )
    for key in paths:
        file = tmp_path / key
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("version 1\n", encoding="utf-8")
    first = build._source_fingerprint()
    assert all(first[key] == hashlib.sha256((tmp_path / key).read_bytes()).hexdigest() for key in paths)
    for key in paths:
        file = tmp_path / key
        file.write_text("version 2\n", encoding="utf-8")
        assert build._source_fingerprint()[key] != first[key]


def test_release_provenance_tracks_entire_packaged_docs_tree(tmp_path, monkeypatch):
    """--add-data docs must not ship untracked media or non-onboarding docs."""
    monkeypatch.setattr(build, "ROOT", tmp_path)
    paths = (
        "docs/RELEASE.md",
        "docs/MASTER_QUEUE.example.json",
        "docs/onboarding_media/mcp-create-tunnel.mp4",
        "docs/onboarding_media/screenshots/01-installer-start.png",
    )
    for key in paths:
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original " + key.encode("utf-8"))
    initial = build._source_fingerprint()
    for key in paths:
        path = tmp_path / key
        assert initial[key] == hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_bytes(path.read_bytes() + b" changed")
        assert build._source_fingerprint()[key] != initial[key]
