"""Vitra expansion tests — CREATED FOR FUTURE EXECUTION ONLY (not run).

Covers the expansion order: coordinated backup/restore, staged product
update with ConPTY guard, optional providers lifecycle, setup-state axes,
redacted diagnostics preview, sidecar manifests, real-signing refusal of
simulation, and CLI maintenance projections.

DO NOT EXECUTE in this phase (implementation-integral-first order).
"""
from __future__ import annotations


def test_plan_backup_empty_scope_rejected_future():
    from sentra_remote.coordinated_backup import plan_coordinated_backup
    try:
        plan_coordinated_backup({})
    except ValueError:
        return
    raise AssertionError("empty backup scope must be rejected")


def test_conpty_guard_defers_while_alive_future():
    from sentra_remote.coordinated_upgrade import check_conpty_guard
    assert check_conpty_guard(["handle-1"])["decision"] == "defer"
    assert check_conpty_guard([])["decision"] == "apply"


def test_mcp_schema_downgrade_refused_future():
    from sentra_remote.coordinated_upgrade import verify_mcp_schema_compatibility
    try:
        verify_mcp_schema_compatibility(3, 2)
    except ValueError:
        return
    raise AssertionError("schema downgrade must be refused")


def test_provider_install_requires_approval_future():
    from sentra_remote.optional_providers import provider_install
    try:
        provider_install("git", approved=False, runner=lambda a, p: {})
    except PermissionError:
        return
    raise AssertionError("unapproved provider install must be denied")


def test_provider_unconfigured_runner_is_unavailable_future():
    from sentra_remote.optional_providers import provider_health
    try:
        provider_health("git", runner=None)
    except ValueError:
        return
    raise AssertionError("missing runner must fail explicitly")


def test_setup_states_axes_independent_future():
    from sentra_remote.setup_states import describe_setup_states
    view = describe_setup_states({"mcp": {"ok": True}})
    assert view["local"] == {"ready": True}
    assert view["tunnel"]["online"] is False
    assert view["extension"]["state"] in {
        "absent", "installed", "paired", "login", "revoked"}


def test_diagnostics_preview_redacts_ip_url_path_email_future():
    from sentra_remote.diagnostics import redact_text_preview
    out = redact_text_preview("ip 10.0.0.1 url https://example.com/x "
                              "path C:\\Users\\ana\\doc.txt mail ana@example.com",
                              titles=["Secret Project"], projects=["SENTRA"])
    assert "[redacted-ip]" in out["redacted"] and "[redacted-url]" in out["redacted"]
    assert "[redacted-path]" in out["redacted"] and "[redacted-email]" in out["redacted"]


def test_sidecar_manifest_without_signer_rejected_future():
    from sentra_remote.sidecar_manifests import validate_sidecar_manifest
    try:
        validate_sidecar_manifest("interop", {"name": "x", "version": "1",
                                              "schema_version": 1, "sha256": "a" * 64,
                                              "files": [], "license": "MIT"})
    except ValueError:
        return
    raise AssertionError("unsigned sidecar manifest must be rejected")


def test_signing_refuses_simulation_future():
    from scripts.commander.release_signing import require_real_thumbprint
    for fake in ("", "SIMULATED", "00"):
        try:
            require_real_thumbprint(fake)
        except ValueError:
            continue
        raise AssertionError("simulated signer must be refused")


def test_cli_maintenance_fail_closed_future():
    from sentra_cli.maintenance import backup_status, update_status
    assert backup_status("")["phase"] == "absent"
    assert update_status("")["phase"] == "absent"


def test_provider_renew_requires_approval_future():
    from sentra_remote.optional_providers import provider_renew
    try:
        provider_renew("git", approved=False, runner=lambda a, p: {})
    except PermissionError:
        return
    raise AssertionError("unapproved provider renew must be denied")


def test_provider_notices_exist_per_file_future():
    from pathlib import Path
    from sentra_remote.optional_providers import PROVIDERS
    base = Path(__file__).resolve().parents[2]
    for name, spec in PROVIDERS.items():
        target = base / str(spec["notice"])
        assert target.is_file(), f"missing NOTICE for {name}"


def test_postgres_plan_requires_monotonic_future():
    from sentra_remote.postgres_migration import plan_postgres_migration
    try:
        plan_postgres_migration(database="sentra", current_version=3,
                                target_version=3, statements_digest="a" * 64)
    except ValueError:
        return
    raise AssertionError("non-monotonic postgres migration must be refused")


def test_postgres_needs_runners_future():
    from sentra_remote.postgres_migration import prepare_postgres_migration
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "state"
        root.mkdir()
        try:
            prepare_postgres_migration(
                root, Path(tmp) / "stage", database="sentra",
                current_version=1, target_version=2,
                statements_digest="b" * 64, installation_id="i",
                owner_id="o", operation_id="p",
                authorize=lambda a, b, c: True, offline=lambda: True,
                dump_runner=None, dsn="")
        except ValueError:
            return
    raise AssertionError("postgres migration without dump runner must be unavailable")


def test_extension_plan_detects_stale_future():
    from sentra_remote.coordinated_upgrade import plan_extension_update
    view = plan_extension_update({"version": "1.6.52"},
                                 {"extension": {"version": "1.7.0", "sha256": "c" * 64}})
    assert view["stale"] is True and view["target"] == "1.7.0"


def test_sidecar_registry_marks_unsigned_future():
    import json
    from pathlib import Path
    registry = json.loads(
        (Path(__file__).resolve().parents[2] / "sentra_remote" / "sidecar_registry.json")
        .read_text(encoding="utf-8"))
    assert registry["sidecars"]["interop"]["state"] == "absent-awaiting-owner"
    for kind in ("workflows", "quality"):
        assert registry["sidecars"][kind]["signature"] == "unverified-pending-host"


def test_shareable_doctor_defaults_unchanged_future():
    from sentra_remote.install_doctor import RepairPlan, shareable_doctor
    plan = RepairPlan("files_present", (), "none")
    assert shareable_doctor(plan)["shell_surface"] == "unchecked"
    assert "providers" not in shareable_doctor(plan)


def test_opendots_notice_and_provenance_present_future():
    import json
    from pathlib import Path
    base = Path(__file__).resolve().parents[2]
    assets = base / "sentra_canvas" / "desktop_ui" / "src" / "assets" / "opendots"
    assert (assets / "LICENSE").is_file()
    provenance = json.loads((assets / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert provenance.get("license") == "MIT" and "Atai Barkai" in str(provenance.get("copyright"))
    assert isinstance(provenance.get("files"), dict) and len(provenance["files"]) == 4
    notice = base / "sentra_remote" / "provider_notices" / "opendots-mascots-NOTICE.txt"
    assert notice.is_file()


def test_guacamole_legal_and_provenance_present_future():
    import json
    from pathlib import Path
    base = Path(__file__).resolve().parents[2]
    assets = base / "sentra_canvas" / "desktop_ui" / "src" / "assets" / "guacamole"
    assert (assets / "LICENSE").is_file()
    assert (assets / "NOTICE").is_file()
    provenance = json.loads((assets / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert provenance.get("package") == "guacamole-common-js"
    assert str(provenance.get("version")) == "1.5.0"
    assert provenance.get("license") == "Apache-2.0"
    assert provenance.get("is_apache_clone") is False
    assert str(provenance.get("integrity") or "").startswith("sha512-")
    notice = base / "sentra_remote" / "provider_notices" / "guacamole-common-js-NOTICE.txt"
    assert notice.is_file()
