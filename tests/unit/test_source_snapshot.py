import hashlib
import json
from pathlib import Path

import pytest

from scripts.commander import build_windows as build
from scripts.commander import source_snapshot as snapshot


def _source(tmp_path):
    root = tmp_path / "checkout"
    for name, data in {
        "sentra_code_mode/guest/sentra_quickjs_guest.c": b"guest-v1",
        "sentra_canvas/static/chat.woff2": b"font-v1",
        "sentra_canvas/desktop_ui/src/assets/opendots/LICENSE": b"license-v1",
        "docs/video.mp4": b"video-v1",
        "main.py": b"print('product')",
        "sentra_executors/remote_rustdesk_gate.rs": b"fn gate() {}",
        "sentra_canvas/desktop_ui/scripts/materialize.mjs": b"export {};",
        ".sentra/token.json": b"PRIVATE",
        "sentra_canvas/desktop_ui/node_modules/dependency/index.js": b"CACHE",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def test_seal_copies_product_bytes_without_private_state_and_survives_checkout_edits(tmp_path):
    root = _source(tmp_path)
    destination = tmp_path / "candidate"
    proof = snapshot.create_source_snapshot(destination, root)
    assert proof["files"] == 7
    assert not (destination / ".sentra").exists()
    assert not (destination / "sentra_canvas/desktop_ui/node_modules").exists()
    assert build._source_fingerprint(destination) == proof["sources"]
    (root / "main.py").write_bytes(b"later checkout work")
    assert snapshot.verify_source_snapshot(destination) == proof
    assert (destination / "main.py").read_bytes() == b"print('product')"


def test_terminal_packaged_engine_is_sealed_without_copying_unrelated_dist_outputs(tmp_path):
    root = _source(tmp_path)
    names = ("integrations/orca-terminal/dist/engine.cjs",
             "integrations/orca-terminal/dist/manifest.json")
    for name in (*names, "integrations/orca-terminal/dist/build-cache.json"):
        source = root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"sealed terminal output")
    candidate = tmp_path / "terminal-candidate"
    proof = snapshot.create_source_snapshot(candidate, root)
    assert all(name in proof["sources"] and (candidate / name).is_file() for name in names)
    assert "integrations/orca-terminal/dist/build-cache.json" not in proof["sources"]
    (candidate / names[0]).write_bytes(b"tampered engine")
    with pytest.raises(RuntimeError, match="source snapshot changed"):
        snapshot.verify_source_snapshot(candidate)


def test_desktop_source_seal_includes_vendor_licenses_and_public_font_formats(tmp_path):
    root = _source(tmp_path)
    names = ("sentra_canvas/desktop_ui/src/vendor/coucou/LICENSE",
             "sentra_canvas/desktop_ui/public/fonts/regular.woff2")
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"required desktop seal input")
    candidate = tmp_path / "desktop-candidate"
    proof = snapshot.create_source_snapshot(candidate, root)
    assert all((candidate / name).read_bytes() == (root / name).read_bytes() for name in names)
    assert all(name in proof["sources"] for name in names)
    (candidate / names[0]).write_bytes(b"changed license")
    with pytest.raises(RuntimeError, match="source snapshot changed"):
        snapshot.verify_source_snapshot(candidate)


def test_repository_snapshot_covers_desktop_and_terminal_sealed_inputs():
    from scripts.commander.build_canvas import desktop_source_inputs

    root = Path(__file__).resolve().parents[2]
    sources = build._source_fingerprint(root)
    for name, digest in desktop_source_inputs(root / "sentra_canvas/desktop_ui").items():
        assert sources.get("sentra_canvas/desktop_ui/" + name) == digest, name
    engine = root / "integrations/orca-terminal/dist/manifest.json"
    if not engine.is_file():
        # A clean checkout builds this generated input before making a snapshot.
        return
    terminal = json.loads(engine.read_text(encoding="utf-8"))
    for name, digest in terminal["sources"].items():
        assert sources.get("integrations/orca-terminal/" + name) == digest, name
    assert sources["integrations/orca-terminal/dist/engine.cjs"] == terminal["output"]


@pytest.mark.parametrize("name", [
    "sentra_code_mode/guest/sentra_quickjs_guest.c",
    "sentra_canvas/static/chat.woff2",
    "sentra_canvas/desktop_ui/src/assets/opendots/LICENSE",
    "sentra_executors/remote_rustdesk_gate.rs",
    "sentra_canvas/desktop_ui/scripts/materialize.mjs",
])
def test_packaged_native_sources_media_and_legal_changes_invalidate_proof(tmp_path, name):
    root = _source(tmp_path)
    initial = build._source_fingerprint(root)
    (root / name).write_bytes(b"changed")
    assert build._source_fingerprint(root)[name] != initial[name]


def test_build_refuses_modified_sealed_candidate_before_issuing_binary_proof(tmp_path, monkeypatch):
    root = _source(tmp_path)
    candidate = tmp_path / "candidate"
    proof = snapshot.create_source_snapshot(candidate, root)
    monkeypatch.setattr(build, "ROOT", candidate)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "sentra-canvas.exe").write_bytes(b"MZ-binary")
    build._write_build_provenance(dist, "canvas", ("sentra-canvas.exe",), proof["sources"])
    receipt = json.loads((dist / "build-provenance-canvas.json").read_text())
    assert receipt["source_snapshot_sha256"] == hashlib.sha256((candidate / snapshot.MANIFEST).read_bytes()).hexdigest()
    (candidate / "main.py").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="source snapshot changed"):
        build._write_build_provenance(dist, "other", ("sentra-canvas.exe",), build._source_fingerprint())
    assert not (dist / "build-provenance-other.json").exists()


def test_concurrent_checkout_edit_never_gets_a_seal(tmp_path, monkeypatch):
    root = _source(tmp_path)
    destination = tmp_path / "candidate"
    real_fingerprint = snapshot._source_fingerprint
    calls = 0

    def changed(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "main.py").write_bytes(b"concurrent edit")
        return real_fingerprint(path)

    monkeypatch.setattr(snapshot, "_source_fingerprint", changed)
    with pytest.raises(RuntimeError, match="source changed during snapshot"):
        snapshot.create_source_snapshot(destination, root)
    assert not (destination / snapshot.MANIFEST).exists()


def test_refuse_merge_into_existing_or_nested_directory(tmp_path):
    root = _source(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        snapshot.create_source_snapshot(root / "candidate", root)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        snapshot.create_source_snapshot(existing, root)
    assert list(existing.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "C:/escape.py", "dir\\file.py", "./main.py"])
def test_manifest_cannot_escape_snapshot(tmp_path, name):
    root = _source(tmp_path)
    destination = tmp_path / "candidate"
    proof = snapshot.create_source_snapshot(destination, root)
    proof["sources"][name] = "0" * 64
    (destination / snapshot.MANIFEST).write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="invalid snapshot input path"):
        snapshot.verify_source_snapshot(destination)


def test_added_product_input_is_not_silently_accepted(tmp_path):
    root = _source(tmp_path)
    destination = tmp_path / "candidate"
    snapshot.create_source_snapshot(destination, root)
    (destination / "sentra_code_mode/new.py").write_text("new input")
    with pytest.raises(RuntimeError, match="input set changed"):
        snapshot.verify_source_snapshot(destination)


def test_snapshot_preserves_standalone_runtime_legal_inputs_and_release_docs(tmp_path):
    root = _source(tmp_path)
    names = ("vendor/orca/LICENSE", "integrations/orca-terminal/vendor/orca/LICENSE",
             "README.md", "SECURITY.md", "CHANGELOG.md")
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"reviewed packaged notice")
    destination = tmp_path / "candidate"
    proof = snapshot.create_source_snapshot(destination, root)
    for name in names:
        assert (destination / name).read_bytes() == b"reviewed packaged notice"
        assert name in proof["sources"]
    (destination / "vendor/orca/LICENSE").write_bytes(b"changed license")
    with pytest.raises(RuntimeError, match="source snapshot changed"):
        snapshot.verify_source_snapshot(destination)


def test_snapshot_includes_connector_registration_and_detects_later_change(tmp_path):
    root = _source(tmp_path)
    connector = root / "sentra_connectors/registration.py"
    connector.parent.mkdir()
    connector.write_bytes(b"def restore(): return 'central-authority'")
    destination = tmp_path / "candidate"
    snapshot.create_source_snapshot(destination, root)
    assert (destination / "sentra_connectors/registration.py").read_bytes() == connector.read_bytes()
    (destination / "sentra_connectors/registration.py").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="source snapshot changed"):
        snapshot.verify_source_snapshot(destination)
