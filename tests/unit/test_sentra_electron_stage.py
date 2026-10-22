"""Optional Electron release payload checks never execute npm or upstream code."""
import json
import hashlib
from pathlib import Path
import pytest
from scripts.commander.stage_electron import stage_electron_surface, validate_electron_payload, SURFACE_REQUIRED


def _fixture(root: Path) -> Path:
    binary = root / "node_modules" / "electron" / "dist"
    binary.mkdir(parents=True)
    for folder in ("resources", "locales"):
        (binary / folder).mkdir()
    for name in ("electron.exe", "LICENSE", "LICENSES.chromium.html"):
        (binary / name).write_bytes(b"isolated-fixture")
    for name in SURFACE_REQUIRED:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"fixture-" + name.encode("ascii"))
    inputs = {"src/main.jsx": "a" * 64}
    desktop = root.parent / 'sentra_canvas/static/desktop-assets/manifest.json'
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(json.dumps({'source_inputs': inputs}), encoding='utf-8')
    (root / 'island/source-manifest.json').write_text(json.dumps({
        'schema': 1, 'source_inputs': inputs, 'files': {
            name: hashlib.sha256((root / 'island' / name).read_bytes()).hexdigest()
            for name in ('island.html', 'island.js', 'island.css')
        }}), encoding='utf-8')
    (root / "package.json").write_text(
        json.dumps({"devDependencies": {"electron": "44.0.0"}}), encoding="utf-8")
    return root


def test_stage_and_validate_electron_display(tmp_path):
    src = _fixture(tmp_path / "source")
    dest = tmp_path / "installed" / "sentra-electron"
    result = stage_electron_surface(src, dest)
    assert result["authority"] == "sentra_canvas"
    assert (dest / "SENTRA-DOT.ico").read_bytes() == b"fixture-SENTRA-DOT.ico"
    assert "SENTRA-DOT.ico" in result["files"]
    assert validate_electron_payload(dest) == result
    (dest / "policy.cjs").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="tampered"):
        validate_electron_payload(dest)


def test_dot_icon_required_before_publish(tmp_path):
    src = _fixture(tmp_path / "source")
    (src / "SENTRA-DOT.ico").unlink()
    with pytest.raises(FileNotFoundError, match="SENTRA-DOT.ico"):
        stage_electron_surface(src, tmp_path / "dest")


def test_incomplete_bundle_refused_before_publish(tmp_path):
    src = _fixture(tmp_path / "source")
    (src / "node_modules" / "electron" / "dist" / "LICENSE").unlink()
    with pytest.raises(FileNotFoundError, match="runtime"):
        stage_electron_surface(src, tmp_path / "dest")


def test_island_seal_must_match_desktop(tmp_path):
    src = _fixture(tmp_path / 'source')
    manifest = src / 'island/source-manifest.json'
    value = json.loads(manifest.read_text(encoding='utf-8'))
    value['source_inputs'] = {}
    manifest.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='source seals differ'):
        stage_electron_surface(src, tmp_path / 'dest')


def test_changed_island_output_refused(tmp_path):
    src = _fixture(tmp_path / 'source')
    (src / 'island/island.js').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='build seal'):
        stage_electron_surface(src, tmp_path / 'dest')
