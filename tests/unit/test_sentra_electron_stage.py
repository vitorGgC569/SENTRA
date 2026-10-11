"""Optional Electron release payload checks never execute npm or upstream code."""
import json
from pathlib import Path
import pytest
from scripts.commander.stage_electron import stage_electron_surface, validate_electron_payload


def _fixture(root: Path) -> Path:
    binary = root / "node_modules" / "electron" / "dist"
    binary.mkdir(parents=True)
    for folder in ("resources", "locales"):
        (binary / folder).mkdir()
    for name in ("electron.exe", "LICENSE", "LICENSES.chromium.html"):
        (binary / name).write_bytes(b"isolated-fixture")
    for name in ("main.cjs", "policy.cjs", "SENTRA.ico", "THIRD_PARTY_NOTICES.md"):
        (root / name).write_bytes(b"fixture")
    (root / "package.json").write_text(
        json.dumps({"devDependencies": {"electron": "44.0.0"}}), encoding="utf-8")
    return root


def test_stage_and_validate_electron_display(tmp_path):
    src = _fixture(tmp_path / "source")
    dest = tmp_path / "installed" / "sentra-electron"
    result = stage_electron_surface(src, dest)
    assert result["authority"] == "sentra_canvas"
    assert validate_electron_payload(dest) == result
    (dest / "policy.cjs").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="tampered"):
        validate_electron_payload(dest)


def test_incomplete_bundle_refused_before_publish(tmp_path):
    src = _fixture(tmp_path / "source")
    (src / "node_modules" / "electron" / "dist" / "LICENSE").unlink()
    with pytest.raises(FileNotFoundError, match="runtime"):
        stage_electron_surface(src, tmp_path / "dest")
