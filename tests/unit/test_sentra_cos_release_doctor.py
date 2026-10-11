"""Offline release media Doctor: all fixtures stay inside pytest tmp_path."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.commander.release_doctor import audit_release


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, version: str = "1.2.3") -> tuple[Path, dict[str, str]]:
    release = root / "release"
    release.mkdir()
    setup = f"SENTRA-Setup-{version}.exe"
    msi = f"SENTRA-Desktop-{version}-x64.msi"
    update = f"SENTRA-Desktop-{version}-update.zip"
    sbom = f"SENTRA-Desktop-{version}.cdx.json"
    (release / setup).write_bytes(b"MZ-SETUP-QA")
    (release / msi).write_bytes(b"MSI-QA")
    with zipfile.ZipFile(release / update, "w") as archive:
        archive.writestr("SENTRA-Setup.exe", (release / setup).read_bytes())
        archive.writestr("sentra-update-helper.exe", b"MZ-HELPER-QA")
        archive.writestr("tunnel-client-v0.0.14-windows-amd64.zip", b"TUNNEL-QA")
    components = [{"type": "library", "name": "pypdfium2", "version": "4.30.0"}] + [
        {"type": "file", "name": name, "hashes": [{"alg": "SHA-256", "content": _sha(release / name)}]}
        for name in (setup, msi, update)
    ]
    (release / sbom).write_text(json.dumps({
        "bomFormat": "CycloneDX", "specVersion": "1.5",
        "metadata": {"component": {"name": "SENTRA Desktop", "version": version}},
        "components": components,
    }))
    names = (setup, msi, update, sbom)
    (release / "SHA256SUMS.txt").write_text("".join(
        f"{_sha(release / name)}  {name}\n" for name in names
    ), encoding="ascii")
    manifest = {
        "version": version,
        "url": f"https://github.com/company/SENTRA/releases/download/v{version}/{update}",
        "sha256": _sha(release / update),
        "signer_thumbprint": "",
        "setup": setup, "msi": msi, "sbom": sbom, "checksums": "SHA256SUMS.txt",
    }
    (release / "release-manifest.json").write_text(json.dumps(manifest))
    return release, {"setup": setup, "msi": msi, "update": update, "sbom": sbom}


def test_release_doctor_checks_all_assets_without_claiming_signed(tmp_path: Path) -> None:
    release, _ = _fixture(tmp_path)
    result = audit_release(release, version="1.2.3")
    assert result["result"] == "pass"
    assert result["artifacts_verified"] == 4
    assert result["update_zip_components"] == 3
    assert result["authenticode"] == "not_verified_unsigned_qa_only"
    assert result["ready_for_install_smoke"] is False
    assert result["homologated"] is False


@pytest.mark.parametrize("corrupt", ["setup", "msi", "update", "sbom"])
def test_release_doctor_detects_tampered_checksum_assets(tmp_path: Path, corrupt: str) -> None:
    release, names = _fixture(tmp_path)
    with (release / names[corrupt]).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        audit_release(release, version="1.2.3")


def test_release_doctor_checks_inner_setup_independently(tmp_path: Path) -> None:
    release, names = _fixture(tmp_path)
    update = release / names["update"]
    with zipfile.ZipFile(update, "w") as archive:
        archive.writestr("SENTRA-Setup.exe", b"MZ-ANOTHER-SETUP")
        archive.writestr("sentra-update-helper.exe", b"MZ-HELPER")
        archive.writestr("tunnel-client-v0.0.14-windows-amd64.zip", b"TUNNEL")
    # Re-signing checksums/SBOM does not make a different inner Setup acceptable.
    data = json.loads((release / names["sbom"]).read_text())
    for entry in data["components"]:
        if entry["name"] == names["update"]:
            entry["hashes"][0]["content"] = _sha(update)
    (release / names["sbom"]).write_text(json.dumps(data))
    (release / "SHA256SUMS.txt").write_text("".join(
        f"{_sha(release / name)}  {name}\n" for name in names.values()
    ))
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"] = _sha(update)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differs"):
        audit_release(release, version="1.2.3")


def test_release_doctor_rejects_unverified_claimed_signer(tmp_path: Path) -> None:
    release, _ = _fixture(tmp_path)
    path = release / "release-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["signer_thumbprint"] = "A" * 40
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="independent signer"):
        audit_release(release, version="1.2.3")


def test_release_doctor_rejects_missing_sbom_digest(tmp_path: Path) -> None:
    release, names = _fixture(tmp_path)
    data = json.loads((release / names["sbom"]).read_text())
    data["components"] = data["components"][:-1]
    (release / names["sbom"]).write_text(json.dumps(data))
    checksums = release / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{_sha(release / n)}  {n}\n" for n in names.values()))
    with pytest.raises(ValueError, match="SBOM file digest"):
        audit_release(release, version="1.2.3")
