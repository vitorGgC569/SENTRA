"""Vitra integral shell tests — FOR FUTURE VALIDATION ONLY (do not run yet).

Covers, after ALL fronts finish and Codex liberates validation:
- shell_migration idempotent workspace->Space linkage (preserved IDs, repeatable)
- project_id/ws alias normalization and canonical envelope
- install_doctor shell surface pending/ready without breaking REQUIRED
- diagnostics shareable shell projection (no identifiers)
- onboarding shell stages
- coordinated_upgrade staged plan (app exit, ConPTY never interrupted)
- CLI shell_bridge allowlist (no owner/grant/path smuggling)
- release manifest shell_surface contract + release_doctor shell_contract
- shell_release_probe read-only behavior
"""
from __future__ import annotations


def test_future_shell_migration_is_idempotent(tmp_path):
    from sentra_remote.shell_migration import (
        normalize_project_id, plan_space_links, prepare_space_migration,
        commit_space_migration, migration_status,
    )
    assert normalize_project_id({"ws": "w1"}) == "w1"
    assert normalize_project_id({"project_id": "p", "ws": "w"}) == "p"
    plan = plan_space_links([{"workspace_id": "w1"}], {})
    assert plan[0]["effect"] == "link" and plan[0]["space_id"].startswith("space-")
    repeat = plan_space_links([{"workspace_id": "w1"}], {"w1": plan[0]["space_id"]})
    assert repeat[0]["effect"] == "already_linked"
    applied: list = []
    stage = prepare_space_migration(
        tmp_path, tmp_path.parent / "stage-shell-1", [{"workspace_id": "w1"}], {},
        installation_id="inst", owner_id="owner", operation_id="op-1",
        authorize=lambda *_: True, offline=lambda: True,
    )
    out = commit_space_migration(
        stage, tmp_path, installation_id="inst", owner_id="owner",
        operation_id="op-1", authorize=lambda *_: True, offline=lambda: True,
        apply_link=lambda ws, sp: applied.append((ws, sp)),
    )
    assert out["linked"] == 1 and applied == [("w1", plan[0]["space_id"])]
    assert migration_status(stage)["phase"] == "COMMITTED"


def test_future_doctor_shell_and_diagnostics_are_redacted(tmp_path):
    from sentra_remote.install_doctor import inspect_shell_surface, shareable_doctor, inspect_installation
    from sentra_remote.diagnostics import shareable_report
    shell = inspect_shell_surface(tmp_path)
    assert shell["status"] in {"shell_ready", "shell_pending"}
    plan = inspect_installation(tmp_path)
    report = shareable_doctor(plan)
    assert report["execution"] == "none" and report["credentials_inspected"] is False
    public = shareable_report({
        "config_exists": True, "python": "3.12.1",
        "platform": "Windows-10", "device": {"token_present": True},
        "relay": {"ok": True}, "audit_exists": True,
        "shell": {"status": "shell_pending", "missing": ["shell_bundle"]},
        "installation": {"doctor_phase": "files_present"},
    })
    assert public["shell"]["status"] == "shell_pending"
    assert "relay_url" not in str(public) and "hostname" not in str(public)


def test_future_cli_bridge_rejects_privilege_smuggling():
    from sentra_cli.shell_bridge import ShellBridge, ALLOWED_ACTIONS
    assert "home" in ALLOWED_ACTIONS and "coordinate" in ALLOWED_ACTIONS
    import pytest
    bridge = ShellBridge.__new__(ShellBridge)
    bridge.port, bridge._token, bridge.is_available = None, "", False
    with pytest.raises(RuntimeError):
        bridge._request({"action": "home"})
    with pytest.raises(ValueError):
        ShellBridge.dispatch(bridge, "rm -rf", project_id="p")
    with pytest.raises(ValueError):
        ShellBridge.dispatch(bridge, "home", project_id="p", extra={"grant": "x"})


def test_future_coordinated_upgrade_and_release_contract():
    from sentra_remote.coordinated_upgrade import plan_coordinated_upgrade
    from sentra_remote.onboarding import build_shell_onboarding
    plan = plan_coordinated_upgrade(
        {"version": "9.9.9", "sha256": "a" * 64,
         "shell_surface": {"bundle_sha256": "b" * 64}},
        installation_id="inst", operation_id="op",
    )
    assert plan["apply_on"] == "app_exit"
    assert plan["conpty_policy"] == "never_interrupt_live_sessions"
    assert "remain_on_functional_version" in plan["failure_policy"]
    pending = build_shell_onboarding({"shell": {"ready": False}, "shell_migration": {}})
    assert pending["stage"] == "SHELL_PENDING"
    ready = build_shell_onboarding({"shell": {"ready": True}, "shell_migration": {"linked": 2, "pending": 0}})
    assert ready["stage"] == "SHELL_READY"
