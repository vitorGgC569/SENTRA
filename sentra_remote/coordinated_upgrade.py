"""Coordinated staged upgrade: app + extension + Web Models + MCP schema.

The updater downloads and verifies a package; this coordinator stages the
full product switch so it is applied when the user closes the app, never
by killing live ConPTY sessions. On any failure the installed version
keeps running and rollback restores the previous live set.

No service is stopped here, no secret is inspected, and no grant is
issued. The central host supplies owner admission and the offline proof.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
JOURNAL = "coordinated-upgrade.json"


def _write_journal(stage: Path, record: dict[str, Any]) -> None:
    target = stage / JOURNAL
    tmp = stage / (JOURNAL + ".tmp")
    with tmp.open("x", encoding="utf-8") as out:
        json.dump(record, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, target)


def plan_coordinated_upgrade(
    manifest: dict[str, Any], *, installation_id: str, operation_id: str,
) -> dict[str, Any]:
    """Pure planner from a verified release manifest.

    Requires the release manifest fields produced by
    ``scripts/commander/release_assets.py`` plus the shell surface proof:
    version, update sha256, shell bundle digest and MCP schema version.
    """
    if not isinstance(manifest, dict):
        raise ValueError("release manifest must be an object")
    version = str(manifest.get("version") or "").strip()
    digest = str(manifest.get("sha256") or "").lower()
    if not version or len(digest) != 64:
        raise ValueError("release manifest lacks version/sha256")
    shell = manifest.get("shell_surface") or {}
    if not isinstance(shell, dict):
        raise ValueError("release manifest lacks shell surface proof")
    bundle = str(shell.get("bundle_sha256") or "").strip().lower()
    shell_status = "shell_ready" if len(bundle) == 64 else "shell_pending"
    schema = manifest.get("mcp_schema_version", 1)
    try:
        schema_version = int(schema)
    except (TypeError, ValueError):
        raise ValueError("invalid MCP schema version")
    if not installation_id or not operation_id:
        raise ValueError("installation and operation identity required")
    return {
        "schema": SCHEMA,
        "version": version,
        "update_sha256": digest,
        "shell_bundle_sha256": bundle,
        "shell_status": shell_status,
        "shell_bridge_contract": str(shell.get("bridge_contract") or "POST /api/shell/bridge"),
        "mcp_schema_version": schema_version,
        "installation_binding": hashlib.sha256(installation_id.encode()).hexdigest(),
        "operation_id": operation_id,
        "apply_on": "app_exit",
        "conpty_policy": "never_interrupt_live_sessions",
        "failure_policy": "remain_on_functional_version_and_allow_rollback",
    }


def stage_coordinated_upgrade(
    state_root: Path, stage_dir: Path, manifest: dict[str, Any], *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> Path:
    """Persist the coordinated plan. The package itself stays verified by updater."""
    if not owner_id or authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline gate required")
    if offline() is not True or authorize(owner_id, operation_id, installation_id) is not True:
        raise PermissionError("coordinated upgrade denied")
    root = Path(state_root).resolve(strict=True)
    raw = Path(stage_dir).absolute()
    if raw.is_symlink() or raw.parent.resolve() != root.parent.resolve() or raw.exists():
        raise PermissionError("upgrade stage must be a new private sibling of state root")
    plan = plan_coordinated_upgrade(manifest, installation_id=installation_id, operation_id=operation_id)
    raw.mkdir(parents=True, exist_ok=False)
    try:
        _write_journal(raw, {**plan, "phase": "STAGED"})
        return raw
    except BaseException:
        try:
            (raw / JOURNAL).unlink(missing_ok=True)
            (raw / (JOURNAL + ".tmp")).unlink(missing_ok=True)
            raw.rmdir()
        except OSError:
            pass
        raise


def coordinated_status(stage_dir: Path) -> dict[str, Any]:
    stage = Path(stage_dir).resolve(strict=True)
    journal = stage / JOURNAL
    if not journal.is_file():
        return {"schema": SCHEMA, "phase": "absent"}
    record = json.loads(journal.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        return {"schema": SCHEMA, "phase": "invalid"}
    return {
        "schema": SCHEMA,
        "phase": str(record.get("phase") or "unknown"),
        "version": str(record.get("version") or ""),
        "apply_on": str(record.get("apply_on") or "app_exit"),
        "failure_policy": str(record.get("failure_policy") or ""),
        "extension_version": str(record.get("extension_version") or ""),
        "gateway_version": str(record.get("gateway_version") or ""),
        "conpty_policy": str(record.get("conpty_policy") or "never_interrupt_live_sessions"),
    }


def verify_mcp_schema_compatibility(current: int, target: int) -> None:
    """Staged MCP schema switches must be monotonic and explicitly reviewed."""
    if not isinstance(current, int) or not isinstance(target, int):
        raise ValueError("MCP schema versions must be integers")
    if target < current:
        raise ValueError("MCP schema downgrade requires explicit rollback, not staged update")
    if target > current + 1:
        raise ValueError("MCP schema jump requires stepped migration review")


def check_conpty_guard(alive_handles: list[str] | None) -> dict[str, Any]:
    """Defer physical update application while any ConPTY session is alive.

    Pure gate: returns defer/apply without touching sessions. The Pulso-owned
    terminal registry remains the authority over handles; Vitra only refuses
    to interrupt them.
    """
    handles = list(alive_handles or [])
    if any(not isinstance(h, str) or not h for h in handles):
        raise ValueError("ConPTY handle list must contain non-empty strings")
    if handles:
        return {"decision": "defer", "reason": "live_conpty_sessions",
                "alive": len(handles), "apply_on": "app_exit_after_sessions_close"}
    return {"decision": "apply", "reason": "no_live_conpty_sessions", "apply_on": "app_exit"}


def plan_staged_product_update(
    manifest: dict[str, Any], *, installation_id: str, operation_id: str,
    current_mcp_schema: int = 1,
) -> dict[str, Any]:
    """Extended planner: app + extension + MCP schema + gateway + sidecars.

    Builds on plan_coordinated_upgrade and adds the expansion axes. The
    update still applies only on app exit and never interrupts live ConPTY.
    """
    base = plan_coordinated_upgrade(
        manifest, installation_id=installation_id, operation_id=operation_id
    )
    extension = manifest.get("extension") if isinstance(manifest.get("extension"), dict) else {}
    gateway = manifest.get("gateway") if isinstance(manifest.get("gateway"), dict) else {}
    sidecars = manifest.get("sidecars") if isinstance(manifest.get("sidecars"), dict) else {}
    verify_mcp_schema_compatibility(current_mcp_schema, base["mcp_schema_version"])
    return {
        **base,
        "extension_version": str(extension.get("version") or ""),
        "extension_digest": str(extension.get("sha256") or "").lower(),
        "gateway_version": str(gateway.get("version") or ""),
        "gateway_digest": str(gateway.get("sha256") or "").lower(),
        "sidecars_combined_sha256": str(manifest.get("sidecars_combined_sha256") or ""),
        "sidecar_kinds": sorted(sidecars.keys()) if sidecars else [],
        "update_kind": "staged_product_update",
    }


def plan_extension_update(installed_manifest: dict[str, Any],
                          release_manifest: dict[str, Any]) -> dict[str, Any]:
    """Pure extension coordination: installed (edge_extension/manifest.json)
    vs release manifest `extension` block (C194: 1.7.0 vs older bootstrap).

    Returns current/target/stale flag without touching files. The physical
    file staging happens in stage_product_update; the browser rebuild itself
    stays out of this phase (no build executed here).
    """
    if not isinstance(installed_manifest, dict) or not isinstance(release_manifest, dict):
        raise ValueError("extension manifests must be objects")
    current = str(installed_manifest.get("version") or "").strip()
    target_block = release_manifest.get("extension")
    target_block = target_block if isinstance(target_block, dict) else {}
    target = str(target_block.get("version") or "").strip()
    if not current or not target:
        raise ValueError("extension current/target versions required")
    return {"schema": SCHEMA, "current": current, "target": target,
            "stale": current != target,
            "target_sha256": str(target_block.get("sha256") or "").lower(),
            "apply_on": "app_exit", "note": "extension files stage with the product update"}


def stage_product_update(
    state_root: Path, stage_dir: Path, manifest: dict[str, Any], *,
    installation_id: str, owner_id: str, operation_id: str,
    current_mcp_schema: int,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> Path:
    """Persist the extended staged-product plan (apply on app exit).

    The verified package itself stays owned by updater; this journal only
    records WHAT was staged and the ConPTY-safe apply policy.
    """
    if not owner_id or authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline gate required")
    if offline() is not True or authorize(owner_id, operation_id, installation_id) is not True:
        raise PermissionError("staged product update denied")
    root = Path(state_root).resolve(strict=True)
    raw = Path(stage_dir).absolute()
    if raw.is_symlink() or raw.parent.resolve() != root.parent.resolve() or raw.exists():
        raise PermissionError("update stage must be a new private sibling of state root")
    plan = plan_staged_product_update(manifest, installation_id=installation_id,
                                      operation_id=operation_id,
                                      current_mcp_schema=current_mcp_schema)
    raw.mkdir(parents=True, exist_ok=False)
    try:
        _write_journal(raw, {**plan, "phase": "STAGED"})
        return raw
    except BaseException:
        try:
            (raw / JOURNAL).unlink(missing_ok=True)
            (raw / (JOURNAL + ".tmp")).unlink(missing_ok=True)
            raw.rmdir()
        except OSError:
            pass
        raise


def commit_product_update(
    stage_dir: Path, *, installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    alive_conpty_handles: list[str] | None = None,
) -> dict[str, Any]:
    """Seal the staged plan for application on app exit.

    Refuses to mark APPLY while any ConPTY session is alive (defer); on any
    failure the installed version keeps running and the journal stays STAGED
    for explicit rollback. This seal never applies bytes itself — the host's
    update helper applies them after the app exits.
    """
    if not owner_id or authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline gate required")
    if offline() is not True or authorize(owner_id, operation_id, installation_id) is not True:
        raise PermissionError("product update commit denied")
    stage = Path(stage_dir).resolve(strict=True)
    journal = stage / JOURNAL
    if journal.is_symlink() or not journal.is_file() or journal.stat().st_size > 16384:
        raise ValueError("staged product journal missing or unsafe")
    record = json.loads(journal.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("phase") != "STAGED"
            or record.get("operation_id") != operation_id
            or record.get("installation_binding") != hashlib.sha256(
                installation_id.encode()).hexdigest()):
        raise PermissionError("product update stage binding/phase mismatch")
    gate = check_conpty_guard(alive_conpty_handles)
    if gate["decision"] == "defer":
        return {"operation_id": operation_id, "phase": "STAGED",
                "decision": "defer", "reason": "live_conpty_sessions",
                "alive": gate["alive"], "apply_on": gate["apply_on"]}
    record["phase"] = "APPLY_ON_EXIT"
    _write_journal(stage, record)
    return {"operation_id": operation_id, "phase": "APPLY_ON_EXIT",
            "version": record.get("version"), "apply_on": "app_exit",
            "failure_policy": record.get("failure_policy")}
