"""Recoverable Canvas workspace -> Space linkage for the OpenDots shell.

The shell (Home/Dots/Spaces/conversations) is a projection of the
authoritative Canvas/Control Plane state. This module never creates Runs,
WorkItems, Grants or Operations: it records an idempotent, repeatable
linkage between a preserved Canvas workspace ID and its Space, so existing
projects migrate without copying or renaming.

The central host (Nexo/Codex) supplies the authoritative store callbacks.
All filesystem effects are confined to a private sibling stage directory
and a small JSON journal. Browser/model input never supplies ownership.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
JOURNAL = "shell-migration.json"
MIGRATION_VERSION = 1

READ_ACTIONS = frozenset({
    "home", "space_list", "space_get", "dot_list",
    "conversation_list", "message_list", "events",
})
WRITE_ACTIONS = frozenset({
    "space_create", "dot_create", "dot_update", "conversation_create",
    "message_send", "coordinate",
    "document_list", "document_get", "document_create", "document_save",
    "document_history", "document_restore", "document_delete",
})


def normalize_project_id(body: dict[str, Any]) -> str:
    """Normalize the legacy ``ws`` alias to canonical ``project_id``.

    The bridge accepts ``ws`` on input for migration compatibility and
    always emits ``project_id``. No identity is inferred from directories,
    conversation names, browsers or terminals.
    """
    if not isinstance(body, dict):
        raise ValueError("shell bridge body must be a JSON object")
    project_id = body.get("project_id", "")
    legacy = body.get("ws", "")
    if isinstance(project_id, str) and project_id.strip():
        canonical = project_id.strip()
    elif isinstance(legacy, str) and legacy.strip():
        canonical = legacy.strip()
    else:
        raise ValueError("project_id (or legacy ws) is required")
    if len(canonical) > 128 or any(ord(c) < 32 for c in canonical):
        raise ValueError("invalid project_id")
    return canonical


def canonical_response(value: dict[str, Any], request_key: str) -> dict[str, Any]:
    """Envelope shared with the central bridge handler (Codex-owned)."""
    if not isinstance(value, dict):
        raise ValueError("shell value must be an object")
    if "project_id" not in value:
        raise ValueError("canonical shell value must carry project_id")
    return {"ok": True, "value": value, "request_key": request_key}


def validate_request_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        raise ValueError("request_key is required (UUID or dedupe key, max 128)")
    try:
        uuid.UUID(text)
        return text
    except ValueError:
        if any(ord(c) < 32 for c in text):
            raise ValueError("invalid request_key")
        return text


def _bind(installation_id: str) -> str:
    if not installation_id or len(installation_id) > 128:
        raise ValueError("installation_id is required")
    return hashlib.sha256(installation_id.encode("utf-8")).hexdigest()


def _stage_paths(state_root: Path, stage_dir: Path) -> tuple[Path, Path]:
    root = Path(state_root).resolve(strict=True)
    raw = Path(stage_dir).absolute()
    if raw.is_symlink() or raw.parent.resolve() != root.parent.resolve():
        raise PermissionError("migration stage must be a private sibling of state root")
    stage = raw.resolve() if raw.exists() else raw
    if stage.exists() and (stage.is_symlink() or not stage.is_dir()):
        raise PermissionError("unsafe migration stage")
    return root, raw


def _write_journal(stage: Path, record: dict[str, Any]) -> None:
    target = stage / JOURNAL
    tmp = stage / (JOURNAL + ".tmp")
    with tmp.open("x", encoding="utf-8") as out:
        json.dump(record, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, target)


def plan_space_links(
    workspaces: list[dict[str, Any]],
    existing: dict[str, str],
) -> list[dict[str, Any]]:
    """Pure planner: preserved workspace IDs to Space links.

    No copy or rename: each workspace keeps its ID and receives one linked
    Space. Already-linked workspaces are reported as ``already_linked`` so
    the migration is repeatable and idempotent.
    """
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in workspaces:
        workspace_id = str((item or {}).get("workspace_id") or (item or {}).get("id") or "").strip()
        if not workspace_id or workspace_id in seen:
            continue
        seen.add(workspace_id)
        if existing.get(workspace_id):
            plan.append({
                "workspace_id": workspace_id,
                "space_id": existing[workspace_id],
                "effect": "already_linked",
            })
        else:
            plan.append({
                "workspace_id": workspace_id,
                "space_id": "space-" + hashlib.sha256(workspace_id.encode()).hexdigest()[:16],
                "effect": "link",
            })
    return plan


def prepare_space_migration(
    state_root: Path, stage_dir: Path, workspaces: list[dict[str, Any]],
    existing: dict[str, str], *, installation_id: str, owner_id: str,
    operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> Path:
    """Stage a linkage plan offline. No live store is mutated here."""
    if not owner_id or not operation_id or authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline gate required")
    if offline() is not True or authorize(owner_id, operation_id, installation_id) is not True:
        raise PermissionError("space migration denied")
    root, raw_stage = _stage_paths(state_root, stage_dir)
    if raw_stage.exists():
        raise ValueError("migration stage already exists; recover or commit first")
    plan = plan_space_links(workspaces, existing or {})
    raw_stage.mkdir(parents=True, exist_ok=False)
    try:
        _write_journal(raw_stage, {
            "schema": SCHEMA,
            "migration_version": MIGRATION_VERSION,
            "phase": "STAGED",
            "install_binding": _bind(installation_id),
            "state_binding": hashlib.sha256(str(root).encode()).hexdigest(),
            "operation_id": operation_id,
            "plan": plan,
        })
        return raw_stage
    except BaseException:
        try:
            (raw_stage / JOURNAL).unlink(missing_ok=True)
            (raw_stage / (JOURNAL + ".tmp")).unlink(missing_ok=True)
            raw_stage.rmdir()
        except OSError:
            pass
        raise


def commit_space_migration(
    stage_dir: Path, state_root: Path, *, installation_id: str, owner_id: str,
    operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    apply_link: Callable[[str, str], None] | None,
) -> dict[str, Any]:
    """Apply staged links via the central host callback, then seal the journal.

    ``apply_link(workspace_id, space_id)`` must persist the explicit
    ``project_id`` association in the authoritative store (Nexo-owned) and
    confer it on every call. This module only drives the callback in plan
    order and records the outcome.
    """
    if not owner_id or not operation_id or authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline gate required")
    if offline() is not True or authorize(owner_id, operation_id, installation_id) is not True:
        raise PermissionError("space migration commit denied")
    if apply_link is None or not callable(apply_link):
        raise ValueError("central apply_link callback is required")
    root = Path(state_root).resolve(strict=True)
    stage = Path(stage_dir).resolve(strict=True)
    journal_file = stage / JOURNAL
    if journal_file.is_symlink() or not journal_file.is_file() or journal_file.stat().st_size > 65536:
        raise ValueError("migration journal missing or unsafe")
    record = json.loads(journal_file.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("schema") != SCHEMA
            or record.get("phase") != "STAGED"
            or record.get("operation_id") != operation_id
            or record.get("install_binding") != _bind(installation_id)
            or record.get("state_binding") != hashlib.sha256(str(root).encode()).hexdigest()):
        raise PermissionError("migration stage binding/phase mismatch")
    applied: list[dict[str, Any]] = []
    for item in record.get("plan", []):
        if not isinstance(item, dict):
            raise ValueError("invalid migration plan entry")
        if item.get("effect") == "already_linked":
            applied.append(item)
            continue
        apply_link(str(item["workspace_id"]), str(item["space_id"]))
        applied.append({**item, "effect": "linked"})
    record["phase"] = "COMMITTED"
    record["applied"] = applied
    _write_journal(stage, record)
    return {"operation_id": operation_id, "linked": len(applied)}


def migration_status(stage_dir: Path) -> dict[str, Any]:
    """Read-only projection of a staged migration (no secrets)."""
    stage = Path(stage_dir).resolve(strict=True)
    journal_file = stage / JOURNAL
    if not journal_file.is_file():
        return {"schema": SCHEMA, "phase": "absent"}
    record = json.loads(journal_file.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        return {"schema": SCHEMA, "phase": "invalid"}
    return {
        "schema": SCHEMA,
        "phase": str(record.get("phase") or "unknown"),
        "migration_version": record.get("migration_version"),
        "operations": 1 if record.get("operation_id") else 0,
        "entries": len(record.get("plan") or []),
    }
