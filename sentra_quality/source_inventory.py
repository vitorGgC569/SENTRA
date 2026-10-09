"""Deterministic, offline provenance + top-level license-evidence inventory.

This output is NOT an SPDX SBOM, security approval or legal license opinion:
transitive dependencies, CVEs, vendored packages and exceptions are out of scope.
It never executes cloned code or installs packages. Every source is verified
against a trusted pin lock *before* tracked files are inspected.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from .source_gate import GateFailure, SourceGate, _contained, _git

_LICENSE = {"LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE"}
_SUFFIX = {".TXT", ".MD", ".RST", ""}


def _is_license(name: str) -> bool:
    if "/" in name or "\\" in name:
        return False
    p = Path(name)
    return p.stem.upper() in _LICENSE and p.suffix.upper() in _SUFFIX


def generate_source_inventory(gate: SourceGate, *,
                              require_license: bool = False) -> dict:
    """All-or-nothing inventory; missing evidence can block release explicitly."""
    packages: list[dict] = []
    for name in sorted(gate.pins):
        info = gate.verify(name)
        repo = gate.root / name
        candidates = [
            p.decode("utf-8", "surrogateescape")
            for p in _git(repo, "ls-files", "-z").split(b"\0")
            if p and _is_license(p.decode("utf-8", "surrogateescape"))
        ]
        license_evidence = []
        for candidate in sorted(candidates):
            file = _contained(repo, repo / candidate)
            if not file.is_file():
                raise GateFailure("tracked license evidence is not a readable file")
            license_evidence.append({
                "path": candidate,
                "sha256": sha256(file.read_bytes()).hexdigest(),
            })
        if require_license and not license_evidence:
            raise GateFailure(f"manual license review required: {name}")
        packages.append({
            "name": name,
            "upstream": info.upstream,
            "revision": info.revision,
            "tracked_files": info.tracked_files,
            "license_files": license_evidence,
            # Presence of a LICENSE file does not establish relicensing rights.
            "release_license_review": "REQUIRED" if license_evidence else "MISSING_EVIDENCE",
        })
    canonical = json.dumps(packages, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        "schema": "sentra.source-inventory/v1",
        "count": len(packages),
        "inventory_sha256": sha256(canonical).hexdigest(),
        "verified_git_revisions": True,
        "sbom_complete": False,
        "cve_scanned": False,
        "license_cleared": False,
        "packages": packages,
    }
