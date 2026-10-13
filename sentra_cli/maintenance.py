"""Vitra maintenance surface for the SENTRA CLI (read-only + fail-closed).

Wraps coordinated backup status, staged-update status, optional-provider
inventory and redacted diagnostics previews. Mutating operations
(backup/restore/update/install) are only staged through explicit
owner-authorized host calls; this module never fabricates authority and
fails closed when the local broker/host is unavailable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def backup_status(stage: str = "") -> dict[str, Any]:
    if not stage.strip():
        return {"schema": 1, "phase": "absent", "hint": "pass a backup stage directory"}
    try:
        from sentra_remote.coordinated_backup import backup_status as _status
        return _status(Path(stage))
    except (OSError, ValueError) as exc:
        return {"schema": 1, "phase": "unreadable", "reason": str(exc)[:160]}


def update_status(stage: str = "") -> dict[str, Any]:
    if not stage.strip():
        return {"schema": 1, "phase": "absent", "hint": "pass an update stage directory"}
    try:
        from sentra_remote.coordinated_upgrade import coordinated_status as _status
        return _status(Path(stage))
    except (OSError, ValueError) as exc:
        return {"schema": 1, "phase": "unreadable", "reason": str(exc)[:160]}


def provider_inventory() -> dict[str, Any]:
    from sentra_remote.optional_providers import transitive_inventory
    return transitive_inventory()


def provider_states(probes: dict[str, Any] | None = None) -> dict[str, Any]:
    from sentra_remote.install_doctor import inspect_provider_surface
    return inspect_provider_surface(probes)


def doctor_preview(free_text: dict[str, str] | None = None, *,
                   titles: list[str] | None = None,
                   projects: list[str] | None = None) -> dict[str, Any]:
    from sentra_remote.diagnostics import preview_export
    return preview_export({}, free_text or {}, titles=titles, projects=projects)


def setup_states(current_version: str = "", newest_version: str = "") -> dict[str, Any]:
    from sentra_remote.setup_states import describe_setup_states
    return describe_setup_states({}, current_version=current_version,
                                 newest_version=newest_version)
