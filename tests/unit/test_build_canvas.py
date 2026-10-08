"""Native Canvas Windows build contract without invoking PyInstaller in unit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.commander import build_canvas as bc
from scripts.commander import build_windows as bw


def test_canvas_builder_includes_native_ui_and_webview(tmp_path, monkeypatch):
    ui = tmp_path / "sentra_canvas" / "static"
    ui.mkdir(parents=True)
    for name in ("native.html", "native.css", "native.js"):
        (ui / name).write_text(name, encoding="utf-8")
    import shutil
    shutil.copytree(bc.ROOT / "sentra_canvas" / "static" / "vendor", ui / "vendor")
    monkeypatch.setattr(bc, "ROOT", tmp_path)
    seen = []
    def fake_build(name, entry, dist, work, spec, **kwargs):
        seen.append((name, entry, kwargs))
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "sentra-canvas.exe").write_bytes(b"fake-packaged-exe")
    monkeypatch.setattr(bw, "_build", fake_build)
    bc.build_canvas(tmp_path / "dist", tmp_path / "work", tmp_path / "spec")
    assert len(seen) == 1
    name, entry, kwargs = seen[0]
    assert name == "sentra-canvas"
    assert entry == "canvas_entry.py"
    assert kwargs["windowed"] is True
    assert "webview" in kwargs["extra"]
    assert "sentra_canvas/static" in " ".join(kwargs["extra"])


def test_canvas_builder_fails_closed_without_ui_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="UI assets"):
        bc.build_canvas(tmp_path / "dist", tmp_path / "work", tmp_path / "spec")


def test_canvas_is_required_in_unified_windows_payload():
    from sentra_remote.installer import PRODUCTS
    assert "sentra-canvas.exe" in PRODUCTS
    assert "sentra-canvas.exe" in bw.PAYLOAD_NAMES
    assert "sentra-canvas.exe" in bw.EXPECTED


def test_modified_terminal_vendor_asset_is_rejected(tmp_path):
    import shutil
    from scripts.commander.vendor_canvas_terminal import validate
    target = tmp_path / "vendor"
    shutil.copytree(bc.ROOT / "sentra_canvas" / "static" / "vendor", target)
    validate(target)
    with (target / "xterm.js").open("ab") as stream:
        stream.write(b"modified")
    with pytest.raises(ValueError, match="integrity mismatch"):
        validate(target)


def test_build_provenance_rejects_source_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(bw, "ROOT", tmp_path)
    source = tmp_path / "sentra_version.py"
    source.write_text("VERSION = 'first'\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "sentra-canvas.exe").write_bytes(b"compiled")
    snapshot = bw._source_fingerprint()
    source.write_text("VERSION = 'changed'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="source changed during build"):
        bw._write_build_provenance(dist, "canvas", ("sentra-canvas.exe",), snapshot)
    assert not (dist / "build-provenance-canvas.json").exists()


def test_frozen_canvas_entry_resolves_runtime_authority(tmp_path, monkeypatch):
    from sentra_canvas import native_entry as entry
    from sentra_remote.product import ProductPaths
    install = tmp_path / "Commander"
    state = tmp_path / "user-state"
    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry.sys, "executable", str(install / "sentra-canvas.exe"))
    monkeypatch.setattr(ProductPaths, "default", lambda root: ProductPaths(install, state))
    seen = []
    monkeypatch.setattr(entry, "canvas_main", lambda args: seen.append(args) or 0)
    assert entry.main(["--no-open"]) == 0
    assert seen == [["--root", str(install), "--state-dir", str(state / "canvas"), "--no-open"]]
    assert entry.main(["--root=" + str(tmp_path / "test-install")]) == 0
    assert seen[-1] == ["--root=" + str(tmp_path / "test-install")]
