"""Files the Next installer must copy. This module does not edit the installer.

Copying the license and these modules does not close front 16 and does not add a
paywall. ``production_audit`` imports ``decision_receipt_audit``; that module is
part of the copy list. The rest of ``sentra_quality`` is not.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PACKAGE_FILES = (
    "LICENSE",
    "docs/frentes-18/comercial/README.md",
    "docs/frentes-18/comercial/LICENCA.md",
    "docs/frentes-18/comercial/USUARIO.md",
    "docs/frentes-18/comercial/SUPORTE.md",
    "docs/frentes-18/comercial/PACOTE_LATCH.md",
    "sentra_quality/local_use_policy.py",
    "sentra_quality/production_audit.py",
    "sentra_quality/distribution_diagnosis.py",
    "sentra_quality/decision_receipt_audit.py",
)


def diagnose_installer_text(script: str, *, product_version: str) -> dict[str, Any]:
    """Report whether an installer script packages the license and the diagnosis."""
    if not isinstance(script, str) or not script.strip():
        raise ValueError("installer script required")
    if not isinstance(product_version, str) or not product_version.strip():
        raise ValueError("product version required")
    executable = '\n'.join(line for line in script.splitlines() if not line.lstrip().startswith('#'))
    if 'SENTRA-Setup.exe' in executable and re.search(r'\bStart-Process\b', executable, re.I):
        # A launcher is not a package manifest. Its comments cannot establish
        # what a setup contains or which version was selected at runtime.
        return {'defect': 'installer_payload_not_inspected', 'missing': None,
            'copies_license': None, 'copies_comercial': None, 'copies_sentra_quality': None,
            'marker_version': None, 'product_version': product_version, 'version_matches': None,
            'installer_role': 'setup_wrapper', 'paywall': False, 'local_use_blocked': False,
            'commercial_homologated': False, 'physical_proof': False, 'closes_front_16': False}
    missing = [rel for rel in PACKAGE_FILES if rel not in executable]
    marker = re.search(r'product_version\s*=\s*"([^"]+)"', executable)
    marker_version = marker.group(1) if marker else ""
    return {
        "defect": "installer_omits_license_docs_and_diagnosis" if missing else None,
        "missing": missing,
        "copies_license": "LICENSE" in executable,
        "copies_comercial": "docs/frentes-18/comercial" in executable,
        "copies_sentra_quality": "sentra_quality" in executable,
        "marker_version": marker_version,
        "product_version": product_version,
        "version_matches": marker_version == product_version,
        "paywall": False,
        "local_use_blocked": False,
        "commercial_homologated": False,
        "physical_proof": False,
        "closes_front_16": False,
    }


def diagnose_installer(path: Path | str, *, product_version: str) -> dict[str, Any]:
    script_path = Path(path)
    return diagnose_installer_text(
        script_path.read_text(encoding="utf-8"),
        product_version=product_version,
    )


def diagnose_tree(root: Path | str) -> dict[str, Any]:
    """Say which package files are present in a tree. Absence is a defect, not a lock."""
    base = Path(root)
    present = [rel for rel in PACKAGE_FILES if (base / rel).is_file()]
    missing = [rel for rel in PACKAGE_FILES if rel not in present]
    return {
        "present": present,
        "missing": missing,
        "defect": "package_missing_license_docs_or_diagnosis" if missing else None,
        "paywall": False,
        "local_use_blocked": False,
        "commercial_homologated": False,
        "physical_proof": False,
        "closes_front_16": False,
    }
