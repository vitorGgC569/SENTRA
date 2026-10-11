"""Chat 6: fail-closed update media and publisher tests (no system install)."""
from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from sentra_remote import updater


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.mark.parametrize("name", [
    "../escape.exe", "bad/../../escape", "/absolute.exe",
    "C:/Windows/System32/app.exe", "foo\\..\\escape.exe",
    "a/./b.exe", "bad:stream", "name. ", "a//b", "folder/CON:secret",
    "NUL", "AUX.txt", "com1.exe", "folder/LPT9.log",
])
def test_update_zip_refuses_unsafe_names(tmp_path: Path, name: str) -> None:
    archive = _zip(tmp_path / "update.zip", {name: b"attack"})
    target = tmp_path / "package"
    with pytest.raises(ValueError, match="unsafe path"):
        updater._safe_extract(archive, target)
    assert not (tmp_path / "escape.exe").exists()


def test_update_zip_rejects_casefold_duplicate_before_writing(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "update.zip", {"App.exe": b"A", "app.EXE": b"B"})
    with pytest.raises(ValueError, match="duplicate"):
        updater._safe_extract(archive, tmp_path / "package")
    assert not (tmp_path / "package" / "App.exe").exists()


def test_update_zip_rejects_directory_collision(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "update.zip", {"dir": b"x", "dir/file.exe": b"y"})
    with pytest.raises(ValueError, match="collision"):
        updater._safe_extract(archive, tmp_path / "package")


def test_update_zip_rejects_symlink(tmp_path: Path) -> None:
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as archive:
        member = zipfile.ZipInfo("fake")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "../../victim")
    with pytest.raises(ValueError, match="symlink"):
        updater._safe_extract(path, tmp_path / "package")


def test_update_zip_size_and_entry_limits(tmp_path: Path, monkeypatch) -> None:
    archive = _zip(tmp_path / "update.zip", {"app.exe": b"1234567890"})
    monkeypatch.setattr(updater, "MAX_UPDATE_UNPACKED_BYTES", 5)
    with pytest.raises(ValueError, match="expanded size"):
        updater._safe_extract(archive, tmp_path / "oversized")
    monkeypatch.setattr(updater, "MAX_UPDATE_ENTRIES", 0)
    with pytest.raises(ValueError, match="too many entries"):
        updater._safe_extract(archive, tmp_path / "too-many")


def test_update_zip_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "package"
    target.mkdir()
    (target / "app.exe").write_bytes(b"KEEP")
    archive = _zip(tmp_path / "update.zip", {"app.exe": b"REPLACE"})
    with pytest.raises(ValueError, match="existing"):
        updater._safe_extract(archive, target)
    assert (target / "app.exe").read_bytes() == b"KEEP"


def test_auto_update_refuses_manifest_declared_foreign_signer(tmp_path: Path, monkeypatch) -> None:
    package = _zip(tmp_path / "update.zip", {"SENTRA-Setup.exe": b"MZ", "sentra-update-helper.exe": b"MZ"})
    manifest = {"version": "1.2.3", "url": "https://releases.example.test/update.zip",
                "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                "signer_thumbprint": "B" * 40}
    monkeypatch.setattr(updater, "fetch_manifest", lambda _: manifest)
    monkeypatch.setattr(updater, "download_verified", lambda _, dest: package)
    monkeypatch.setattr(updater, "_installed_signer_thumbprint", lambda: "A" * 40)
    observed = []
    monkeypatch.setattr(updater, "verify_authenticode", lambda *_: observed.append(True))
    with pytest.raises(ValueError, match="installed publisher"):
        updater.prepare_update("https://releases.example.test/release-manifest.json", tmp_path / "stage",
                               require_signature=True)
    assert not observed


def test_auto_update_requires_valid_installed_signer(monkeypatch) -> None:
    monkeypatch.setattr(updater.sys, "frozen", False, raising=False)
    with pytest.raises(ValueError, match="installed Authenticode"):
        updater._installed_signer_thumbprint()
