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

# OpenDots shell surface: existing installs remain valid without it, but a
# shell-first install must carry the shell bundle proof and the bridge
# contract note. Checked separately so REQUIRED stays backward compatible.
SHELL_COMPONENTS = {
    "shell_bundle": "sentra_canvas/static/desktop-assets/manifest.json",
    "shell_bridge_contract": "docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md",
    "shell_migration_plan": "docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md",
}


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


def shareable_doctor(plan: RepairPlan, *, shell: dict | None = None,
                     providers: dict | None = None) -> dict:
    public = {
        "schema": 1,
        "status": plan.status,
        "missing_components": list(plan.missing),
        "repair_action": plan.action,
        "execution": "none",
        "identity_disclosed": False,
        "credentials_inspected": False,
        "shell_surface": "unchecked",
    }
    if isinstance(shell, dict):
        status = shell.get("status")
        if status in {"shell_ready", "shell_pending", "unowned"}:
            public["shell_surface"] = status
            missing = shell.get("missing")
            if isinstance(missing, list):
                public["shell_missing_count"] = min(len(missing), 64)
    if isinstance(providers, dict):
        states = providers.get("providers") if isinstance(providers.get("providers"), dict) else None
        if isinstance(states, dict):
            counts: dict[str, int] = {}
            for entry in states.values():
                state = entry.get("state") if isinstance(entry, dict) else None
                if state in {"absent", "installable", "installing", "ready",
                             "degraded", "unavailable", "removed"}:
                    counts[state] = min(counts.get(state, 0) + 1, 64)
            public["providers"] = {"states": counts, "total": min(len(states), 64)}
    return public


def inspect_shell_surface(root: Path) -> dict:
    """Read-only shell linkage check. Never inspects credentials or tokens."""
    base = Path(root).expanduser().absolute()
    if base.is_symlink():
        return {"schema": 1, "status": "unowned", "missing": ["root"]}
    missing = []
    for label, relative in SHELL_COMPONENTS.items():
        target = base / relative
        if not target.is_file() or target.is_symlink():
            missing.append(label)
    # The installed shell bundle manifest is optional until Prisma ships the
    # shell; its absence is reported, never treated as a damaged install.
    return {
        "schema": 1,
        "status": "shell_ready" if not missing else "shell_pending",
        "missing": sorted(missing),
        "repair_action": "none" if not missing else "install_shell_bundle_or_keep_canvas",
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


def inspect_provider_surface(probes: dict | None = None) -> dict:
    """Read-only optional-provider projection for Doctor surfaces.

    Never installs, repairs or removes anything. Each provider reports
    ready/degraded/installable/unavailable from verified probes only.
    """
    from .optional_providers import PROVIDERS, describe_provider
    probes = probes if isinstance(probes, dict) else {}
    states = {}
    for name in sorted(PROVIDERS):
        probe = probes.get(name)
        states[name] = describe_provider(
            name, probe if isinstance(probe, dict) else None
        ).to_dict()
    return {"schema": 1, "providers": states}
