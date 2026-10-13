"""Durable, owned program-tree backup before executing external Setup.

Never removes the previous rollback point, never retries an interrupted Setup,
and never grants itself permission to restart or stop an executable.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from .windows_paths import filesystem_path

INSTALL_MARKER = ".sentra-install.json"
TERMINAL = frozenset({"COMMITTED", "RESTORED"})


def _checkpoint():
    from sentra_runtime.effect_boundary import current_effect_context
    context = current_effect_context.get()
    if context is not None:
        context.checkpoint()


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    _checkpoint()
    with Path(filesystem_path(tmp)).open("x", encoding="utf-8") as out:
        json.dump(data, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    _checkpoint(); os.replace(filesystem_path(tmp), filesystem_path(path))


def _load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise PermissionError("unsafe or oversized program stage journal")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("schema") != 1:
        raise ValueError("invalid program stage journal")
    return obj


def require_no_interrupted_stage(namespace: Path) -> None:
    if namespace.is_symlink() or namespace.parent.is_symlink():
        raise PermissionError("rollback namespace cannot be a symlink")
    if not namespace.is_dir():
        return
    for path in namespace.glob("txn-*.json"):
        if _load(path).get("phase") not in TERMINAL:
            raise PermissionError("previous Setup effect uncertain; manual owner-authorized recovery required")


def stage_program_backup(install: Path, namespace: Path, installation_id: str) -> tuple[Path, Path]:
    """Journal first, then enable Setup; incomplete copy never becomes rollback."""
    install = install.resolve(strict=True)
    if namespace.is_symlink() or namespace.parent.is_symlink():
        raise PermissionError("unsafe rollback namespace")
    namespace = namespace.resolve()
    if namespace.is_relative_to(install) or install.is_relative_to(namespace):
        raise ValueError("backup may not nest in installation directory")
    require_no_interrupted_stage(namespace)
    marker = install / INSTALL_MARKER
    if marker.is_symlink() or not marker.is_file():
        raise PermissionError("unowned installation")
    observed = json.loads(marker.read_text(encoding="utf-8"))
    if observed.get("product") != "SENTRA Desktop" or observed.get("installation_id") != installation_id:
        raise PermissionError("backup installation identity mismatch")
    if any(child.is_symlink() for child in install.rglob("*")):
        raise PermissionError("symlinks in installation cannot be backed up safely")
    _checkpoint(); namespace.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    original_backup = namespace / "previous"
    backup = original_backup if not original_backup.exists() else namespace / ("previous-" + transaction_id)
    pending = namespace / (".staging-" + transaction_id)
    journal = namespace / ("txn-" + transaction_id + ".json")
    try:
        _checkpoint(); shutil.copytree(filesystem_path(install), filesystem_path(pending))
        new_marker = json.loads(Path(filesystem_path(pending / INSTALL_MARKER)).read_text(encoding="utf-8"))
        if new_marker.get("installation_id") != installation_id:
            raise PermissionError("staged ownership changed")
        _checkpoint(); os.replace(filesystem_path(pending), filesystem_path(backup))
        _write(journal, {
            "schema": 1, "phase": "PREPARED",
            "installation_binding": hashlib.sha256(installation_id.encode()).hexdigest(),
            "backup_name": backup.name, "transaction_id": transaction_id,
        })
        return backup, journal
    finally:
        if pending.exists():
            shutil.rmtree(filesystem_path(pending))


def mark_program_stage(journal: Path, phase: str, installation_id: str) -> None:
    if phase not in {"APPLYING", "RECOVERY_REQUIRED", "COMMITTED", "RESTORED"}:
        raise ValueError("invalid program stage transition")
    record = _load(journal)
    if record.get("installation_binding") != hashlib.sha256(installation_id.encode()).hexdigest():
        raise PermissionError("program stage installation mismatch")
    transitions = {
        "PREPARED": {"APPLYING", "RECOVERY_REQUIRED"},
        "APPLYING": {"RECOVERY_REQUIRED", "COMMITTED"},
        "RECOVERY_REQUIRED": {"RESTORED"},
    }
    if phase not in transitions.get(record.get("phase"), set()):
        raise PermissionError("program stage phase cannot be replayed or downgraded")
    record["phase"] = phase
    # Journal persistence cannot safely be rolled back to older transaction state.
    temp = journal.with_name(journal.name + ".phase.tmp")
    _checkpoint()
    with Path(filesystem_path(temp)).open("x", encoding="utf-8") as out:
        json.dump(record, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    _checkpoint(); os.replace(filesystem_path(temp), filesystem_path(journal))


def restore_failed_program_tree(install: Path, backup: Path, installation_id: str) -> Path:
    """Restore owned media while quarantining the failed tree, not deleting it.

    The caller already holds the installation lock and the product's own
    process-stop gate. Return the quarantine for independent owner inspection.
    """
    install = Path(install).resolve()
    backup = Path(backup).resolve(strict=True)
    if backup.is_symlink() or install == backup or backup.is_relative_to(install):
        raise PermissionError("unsafe program rollback roots")
    old_marker = json.loads(Path(filesystem_path(backup / INSTALL_MARKER)).read_text(encoding="utf-8"))
    if old_marker.get("product") != "SENTRA Desktop" or old_marker.get("installation_id") != installation_id:
        raise PermissionError("rollback backup identity mismatch")
    if not install.is_dir() or install.is_symlink():
        raise PermissionError("incomplete install requires manual recovery")
    # New files might have been written by another actor after Setup started.
    # Never erase them: move the entire suspect tree into an owned quarantine.
    quarantine = backup.parent / ("failed-current-" + uuid.uuid4().hex)
    _checkpoint(); os.replace(filesystem_path(install), filesystem_path(quarantine))
    try:
        shutil.copytree(filesystem_path(backup), filesystem_path(install))
        # Retain only unknown new files, without overwriting restored media.
        owned: set[str] = set(old_marker.get("owned_files") or [])
        newer_marker = quarantine / INSTALL_MARKER
        if newer_marker.is_file() and not newer_marker.is_symlink():
            try:
                updated = json.loads(Path(filesystem_path(newer_marker)).read_text(encoding="utf-8"))
                if updated.get("product") == "SENTRA Desktop" and updated.get("installation_id") == installation_id:
                    owned.update(updated.get("owned_files") or [])
            except (OSError, ValueError, TypeError):
                pass
        owned.add(INSTALL_MARKER)
        long_quarantine = Path(filesystem_path(quarantine))
        for candidate in long_quarantine.rglob("*"):
            if candidate.is_symlink():
                raise PermissionError("symlink in failed Setup requires manual review")
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(long_quarantine)
            if relative.as_posix() in owned:
                continue
            target = install / relative
            if target.exists():
                continue
            parent = Path(filesystem_path(target.parent))
            parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filesystem_path(candidate), filesystem_path(target))
        return quarantine
    except BaseException:
        # The quarantined original must remain untouched if restoration failed.
        # Revert only the new copy; never delete quarantined owner data.
        if install.exists():
            shutil.rmtree(filesystem_path(install))
        os.replace(filesystem_path(quarantine), filesystem_path(install))
        raise
