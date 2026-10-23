"""Verify publisher-signed CABs and their Installer trust-table inscription.

Unsigned previews use only msi_media's integrity contract. These operations
never simulate signing or replace an independent VM installation acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from scripts.commander.msi_media import msi_distribution_files


def _media_table(msi: Path) -> list[tuple[int, int, str]]:
    if os.name != "nt":
        raise PermissionError("signed MSI media verification requires Windows Installer")
    import msilib

    db = msilib.OpenDatabase(str(msi), msilib.MSIDBOPEN_READONLY)
    view = db.OpenView("SELECT `DiskId`,`LastSequence`,`Cabinet` FROM `Media` ORDER BY `DiskId`")
    view.Execute(None)
    media = []
    previous = 0
    while (row := view.Fetch()) is not None:
        disk, last, name = row.GetInteger(1), row.GetInteger(2), row.GetString(3)
        if (disk != len(media) + 1 or last <= previous
                or name != f"{msi.stem}-{disk:04d}.cab"):
            raise PermissionError("MSI has unexpected external cabinet identity/sequence")
        media.append((disk, last, name))
        previous = last
    view.Close()
    if not media:
        raise PermissionError("MSI has no external cabinet media")
    return media


def require_inscribed_cabinets(msi: Path) -> None:
    """Require nonempty certificate/hash bindings for every external Media row.

    Actual publisher trust is checked separately by verify_authenticode; these
    table checks alone do not attest signatures. Insignia/WiX writes the CAB
    signature hashes which Windows Installer verifies during installation.
    """
    media = _media_table(msi)
    import msilib

    db = msilib.OpenDatabase(str(msi), msilib.MSIDBOPEN_READONLY)
    certs = db.OpenView("SELECT `DigitalCertificate` FROM `MsiDigitalCertificate` WHERE `CertData` IS NOT NULL")
    certs.Execute(None)
    present = set()
    while (row := certs.Fetch()) is not None:
        present.add(row.GetString(1))
    certs.Close()
    signatures = db.OpenView("SELECT `Table`,`SignObject`,`DigitalCertificate_` FROM `MsiDigitalSignature` WHERE `Hash` IS NOT NULL")
    signatures.Execute(None)
    bound = set()
    while (row := signatures.Fetch()) is not None:
        if row.GetString(1) == "Media" and row.GetString(3) in present:
            bound.add(row.GetString(2))
    signatures.Close()
    if bound != {str(disk) for disk, _, _ in media}:
        raise PermissionError("external CAB signatures must be inscribed into the MSI before signing it")


def verify_signed_msi_media(msi: Path, trusted_signer: str) -> list[Path]:
    from scripts.commander.release_signing import require_real_thumbprint
    from sentra_remote.updater import verify_authenticode

    signer = require_real_thumbprint(trusted_signer)
    files = msi_distribution_files(msi)
    verify_authenticode(msi, signer)
    for cabinet in files[2:]:
        verify_authenticode(cabinet, signer)
    require_inscribed_cabinets(msi)
    return files


def refresh_signed_msi_media(msi: Path, trusted_signer: str) -> Path:
    """Rebind the inventory only after real CAB+MSI signing and inscription."""
    from scripts.commander.release_signing import require_real_thumbprint
    from sentra_remote.updater import verify_authenticode

    signer = require_real_thumbprint(trusted_signer)
    inventory = msi.with_suffix(".media.json")
    if (not inventory.is_file() or inventory.is_symlink()
            or inventory.stat().st_size > 1024 * 1024 or msi.is_symlink()):
        raise ValueError("original MSI external-media inventory required before signing refresh")
    original = json.loads(inventory.read_text(encoding="utf-8"))
    if not isinstance(original, dict) or original.get("schema") != 1 or original.get("msi") != msi.name:
        raise ValueError("MSI signing inventory identity mismatch")
    verify_authenticode(msi, signer)
    require_inscribed_cabinets(msi)
    media = []
    for _, last, name in _media_table(msi):
        cabinet = msi.parent / name
        if not cabinet.is_file() or cabinet.is_symlink():
            raise ValueError("signed MSI external cabinet missing: " + name)
        verify_authenticode(cabinet, signer)
        with cabinet.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        media.append({"name": name, "bytes": cabinet.stat().st_size,
                      "sha256": digest, "last_sequence": last})
    with msi.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    record = {"schema": 1, "msi": msi.name, "sha256": digest, "media": media}
    temporary = inventory.with_suffix(".json.new")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, inventory)
    msi_distribution_files(msi)
    return inventory
