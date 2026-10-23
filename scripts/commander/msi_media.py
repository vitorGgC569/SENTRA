"""Portable integrity contract for the complete external-CAB MSI distribution.

No installation, signing, execution, or publisher trust is implied by hashes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def msi_distribution_files(msi: Path) -> list[Path]:
    """Verify and enumerate a complete external-media MSI distribution.

    Callers must copy/publish this entire list, not just the .msi database.
    A missing or substituted CAB fails before distribution. This inventory is
    not a substitute for Authenticode or independent installation acceptance.
    """
    msi = Path(msi)
    inventory = msi.with_suffix(".media.json")
    if (not msi.is_file() or msi.is_symlink() or not inventory.is_file()
            or inventory.is_symlink() or inventory.stat().st_size > 1024 * 1024):
        raise ValueError("MSI external-media inventory or database is missing/invalid")
    manifest = json.loads(inventory.read_text(encoding="utf-8"))
    with msi.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1
            or manifest.get("msi") != msi.name or manifest.get("sha256") != digest
            or not isinstance(manifest.get("media"), list) or not manifest["media"]):
        raise ValueError("MSI external-media inventory does not match database")
    files = [msi, inventory]
    previous = 0
    for disk, record in enumerate(manifest["media"], 1):
        expected_name = f"{msi.stem}-{disk:04d}.cab"
        if (not isinstance(record, dict) or record.get("name") != expected_name
                or type(record.get("bytes")) is not int or record["bytes"] < 36
                or type(record.get("last_sequence")) is not int
                or record["last_sequence"] <= previous):
            raise ValueError("MSI external-media inventory contains invalid cabinet")
        path = msi.parent / expected_name
        if not path.is_file() or path.is_symlink() or path.stat().st_size != record["bytes"]:
            raise ValueError("MSI external cabinet missing/invalid: " + expected_name)
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if record.get("sha256") != actual:
            raise ValueError("MSI external cabinet checksum mismatch: " + expected_name)
        previous = record["last_sequence"]
        files.append(path)
    return files


def msi_manifest_entry(msi: Path) -> dict:
    files = msi_distribution_files(msi)
    inventory = json.loads(files[1].read_text(encoding="utf-8"))
    return {"schema": 1, "inventory": files[1].name,
            "sha256": hashlib.sha256(files[1].read_bytes()).hexdigest(),
            "files": [{key: item[key] for key in ("name", "bytes", "sha256")}
                      for item in inventory["media"]],
            "installation": "Keep the MSI and every CAB together in the same directory."}


def verify_msi_manifest(msi: Path, entry: object) -> list[Path]:
    if not isinstance(entry, dict) or entry != msi_manifest_entry(msi):
        raise ValueError("release MSI external-media manifest mismatch")
    return msi_distribution_files(msi)
