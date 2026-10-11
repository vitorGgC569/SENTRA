"""Read-only installed media Doctor; repair is delegated to an owner-authorized host.

This module does not inspect credentials, stop services, issue grants or run Setup.
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .installer import INSTALL_MARKER, PRODUCTS

REQUIRED = {
    "canvas": "sentra-canvas.exe",
    "cli": "sentra-cli.exe",
    "mcp": "sentra-mcp.exe",
    "setup": "sentra-installer.exe",
    "edge": "edge_extension/manifest.json",
    "web_models": "web-models/win-unpacked/Codex Web GPT.exe",
    "web_models_proof": "web-models/integration-build.json",
    "electron": "sentra-electron/electron.exe",
    "electron_proof": "sentra-electron/sentra-surface-build.json",
    "guide": "docs/START_HERE.md",
}
REQUIRED.update({f"component_{i}": name for i, name in enumerate(PRODUCTS)})


@dataclass(frozen=True)
class RepairPlan:
    status: str
    missing: tuple[str, ...]
    action: str
    install_identity: str = ""  # host-only, never exported


def inspect_installation(root: Path, *, deep: bool = False) -> RepairPlan:
    """No secrets, account labels, URLs or arbitrary errors leave this function."""
    supplied_root = Path(root).expanduser().absolute()
    if supplied_root.is_symlink() or any(p.is_symlink() for p in supplied_root.parents):
        return RepairPlan("unowned", (), "deny")
    root = supplied_root.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        return RepairPlan("unowned", (), "deny")
    marker = root / INSTALL_MARKER
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 1024 * 1024:
        return RepairPlan("unowned", (), "deny")
    try:
        record = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return RepairPlan("unowned", (), "deny")
    if not isinstance(record, dict) or record.get("product") != "SENTRA Desktop":
        return RepairPlan("unowned", (), "deny")
    identity = record.get("installation_id")
    owned = record.get("owned_files")
    if not isinstance(identity, str) or not identity or not isinstance(owned, list):
        return RepairPlan("unowned", (), "deny")
    if any(not isinstance(x, str) or not x or
           Path(x).is_absolute() or ".." in Path(x).parts or ":" in x
           for x in owned):
        return RepairPlan("invalid_manifest", (), "deny")
    missing = []
    for label, relative in REQUIRED.items():
        target = root / relative
        cursor = root
        valid = True
        for part in Path(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                valid = False
                break
        if not valid or not target.is_file() or not target.resolve().is_relative_to(root):
            missing.append(label)
    if deep and "electron" not in missing and "electron_proof" not in missing:
        try:
            from scripts.commander.stage_electron import validate_electron_payload
            validate_electron_payload(root / "sentra-electron")
        except (ValueError, OSError, KeyError, TypeError):
            missing.append("electron_integrity")
    return RepairPlan(
        "repair_needed" if missing else "files_present",
        tuple(sorted(set(missing))),
        "owner_approval_required" if missing else "none",
        identity,
    )


def shareable_doctor(plan: RepairPlan) -> dict:
    return {
        "schema": 1,
        "status": plan.status,
        "missing_components": list(plan.missing),
        "repair_action": plan.action,
        "execution": "none",
        "identity_disclosed": False,
        "credentials_inspected": False,
    }


def request_owner_repair(
    root: Path,
    *,
    owner_id: str,
    operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    dispatch: Callable[[Path, str], object] | None,
) -> object:
    """Host extension point. No model-provided approval or owner identity suffices.

    The central host must bind owner_id to its authenticated session, make an
    independent durable single-use grant decision for operation_id, and supply
    the repair dispatcher. Neither callback is exposed via the web/model API.
    """
    plan = inspect_installation(root)
    if plan.status != "repair_needed":
        raise PermissionError("repair requires a verified damaged SENTRA install")
    if not owner_id or not operation_id or authorize is None or dispatch is None:
        raise PermissionError("owner-authorized repair host unavailable")
    candidate = Path(root).expanduser().absolute()
    marker = candidate / INSTALL_MARKER
    if candidate.is_symlink() or marker.is_symlink() or not marker.is_file():
        raise PermissionError("installation marker cannot be a symlink")
    before = hashlib.sha256(marker.read_bytes()).digest()
    if authorize(owner_id, operation_id, plan.install_identity) is not True:
        raise PermissionError("repair authorization denied")
    # Reinspect immediately before the host-owned action to reject marker swap.
    current = inspect_installation(root)
    if (current != plan or candidate.is_symlink() or marker.is_symlink() or
        not marker.is_file() or hashlib.sha256(marker.read_bytes()).digest() != before):
        raise PermissionError("installation changed during repair admission")
    return dispatch(candidate.resolve(), operation_id)
