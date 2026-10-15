"""Pure layout/probe tests and real central SQLite possession, not a Windows VM.

Probe JSON below is synthetic. PowerShell is parsed, never executed against the
host or guest. Passing these tests does not homologate OS or account isolation.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from sentra_executors.windows_dot_isolation import (
    CloneIdentity, GoldenImage, WindowsDotAccount, account_probe_script,
    assess_account_probe, assess_console_possession, console_resource_id,
    estimate_resources, validate_account_layout, validate_clone_layout,
)


VM = "11111111-1111-4111-8111-111111111111"
VM2 = "22222222-2222-4222-8222-222222222222"
DISK = "33333333-3333-4333-8333-333333333333"
SNAPSHOT = "44444444-4444-4444-8444-444444444444"
MACHINE = "55555555-5555-4555-8555-555555555555"
SID = "S-1-5-21-111-222-333-1001"
CANARY = r"C:\Users\dot_b\isolation-canary.txt"
GIB = 1024 ** 3


@pytest.fixture
def account():
    return WindowsDotAccount("owner-a", "dot-a", VM, "dot_a", SID,
                             r"C:\Users\dot_a", r"C:\Users\dot_a\work", "vault:dot-a")


@pytest.fixture
def probe(account):
    return {"schema": "sentra-windows-account-probe-v1", "nonce": "probe-1",
            "user_sid": account.user_sid, "machine_guid": MACHINE,
            "group_sids": ["S-1-5-32-545"], "privilege_names": ["SeChangeNotifyPrivilege"],
            "profile_path": account.profile_path, "session_id": 0,
            "interactive_console_verified": False,
            "directories": [{"path": path, "is_directory": True, "reparse_ancestor": False,
                             "owner_sid": SID, "protected": True,
                             "allow_sids": [SID, "S-1-5-18", "S-1-5-32-544"]}
                            for path in (account.profile_path, account.workspace_path)],
            "canaries": [{"path": CANARY, "state": "denied"}]}


def assess(account, probe):
    return assess_account_probe(account, probe, nonce="probe-1", expected_machine_guid=MACHINE,
                                peer_canaries=[CANARY])


def second_account(account, **changes):
    fields = dict(dot_id="dot-b", username="dot_b", user_sid="S-1-5-21-111-222-333-1002",
                  profile_path=r"C:\Users\dot_b", workspace_path=r"C:\Users\dot_b\work",
                  credential_ref="vault:dot-b")
    return replace(account, **(fields | changes))


def test_distinct_accounts_share_only_one_console_resource(account):
    other = second_account(account)
    validate_account_layout([account, other], strategy="shared_users")
    assert console_resource_id(account.vm_id) == console_resource_id(other.vm_id)
    from sentra_executors.input_control import resource_for_declaration
    declaration = SimpleNamespace(machine=SimpleNamespace(kind="virtualbox_vm"),
                                  adapter=SimpleNamespace(bindings={"guest": SimpleNamespace(vm_id=VM)}))
    assert console_resource_id(VM) == resource_for_declaration(declaration)
    assert "vault:dot-a" not in repr(account)


@pytest.mark.parametrize("changes,error", [
    ({"dot_id": "dot-a"}, "reused_dot"),
    ({"user_sid": SID}, "reused_sid"),
    ({"username": "DOT_A"}, "reused_username"),
    ({"credential_ref": "vault:dot-a"}, "reused_credential"),
    ({"workspace_path": r"C:\Users\DOT_A\other"}, "overlapping_private"),
    ({"profile_path": r"C:\Users\dot_a\nested"}, "overlapping_private"),
    ({"vm_id": VM2}, "one_shared_vm"),
])
def test_shared_layout_rejects_aliases_secret_reuse_and_private_tree_overlap(account, changes, error):
    with pytest.raises(ValueError, match=error):
        validate_account_layout([account, second_account(account, **changes)], strategy="shared_users")


@pytest.mark.parametrize("path", [r"\\server\share\user", r"\\?\C:\Users\dot_a", "C:\\",
    r"C:\Users\Public", r"C:\Users\Default\work", r"C:\Users\dot_a\..\dot_b",
    r"C:\Users\dot_a\CON.txt", r"C:\Users\dot_a\work:stream", "C:\\Users\\dot_a ",
    r"C:\Windows\work", "C:/Users/dot_a/work", r"C:\Users\dot_a\\work", None])
def test_private_paths_reject_ambiguity_and_shared_locations(account, path):
    with pytest.raises(ValueError):
        replace(account, workspace_path=path)


@pytest.mark.parametrize("changes", [
    {"username": "Administrator"}, {"username": "domain\\user"},
    {"user_sid": "S-1-5-18"}, {"user_sid": "S-1-5-21-111-222-333-500"},
    {"user_sid": "S-1-5-21-0111-222-333-1001"},
    {"vm_id": "friendly-VM-name"}, {"vm_id": "00000000-0000-0000-0000-000000000000"},
    {"credential_ref": "password with spaces"},
])
def test_binding_requires_real_dedicated_selectors(account, changes):
    with pytest.raises(ValueError):
        replace(account, **changes)


def golden():
    return GoldenImage(VM, SNAPSHOT, DISK, "a" * 64, True, True, True, True)


def clone():
    return CloneIdentity(VM2, "66666666-6666-4666-8666-666666666666", DISK,
                         "installation-dot-b", MACHINE, "080027010203")


def test_linked_clone_requires_distinct_runtime_and_storage_identity(account):
    validate_clone_layout(golden(), [clone()])
    validate_account_layout([account, second_account(account, vm_id=VM2)], strategy="linked_clones")
    with pytest.raises(ValueError, match="reused_vm"):
        validate_account_layout([account, second_account(account)], strategy="linked_clones")


@pytest.mark.parametrize("field", ["generalized", "credentials_absent", "sentra_identity_absent", "desktop_and_guestcontrol_verified"])
def test_uncommissioned_base_is_a_blocker_not_an_assumed_success(field):
    base = replace(golden(), **{field: False})
    assert base.blockers == (field,)
    with pytest.raises(ValueError, match="not_commissioned"):
        validate_clone_layout(base, [clone()])


@pytest.mark.parametrize("changes,error", [
    ({"vm_id": VM}, "distinct_vm"), ({"disk_id": DISK}, "distinct_vm"),
    ({"parent_disk_id": SNAPSHOT}, "pinned_base"),
])
def test_clones_cannot_reuse_original_vm_or_writable_base(changes, error):
    with pytest.raises(ValueError, match=error):
        validate_clone_layout(golden(), [replace(clone(), **changes)])


@pytest.mark.parametrize("field", ["vm_id", "disk_id", "installation_id", "machine_guid", "mac"])
def test_clones_reject_any_duplicated_runtime_identity(field):
    first = clone()
    other = CloneIdentity("77777777-7777-4777-8777-777777777777",
                          "88888888-8888-4888-8888-888888888888", DISK, "installation-dot-c",
                          "99999999-9999-4999-8999-999999999999", "080027040506")
    with pytest.raises(ValueError, match="reused_clone_" + field):
        validate_clone_layout(golden(), [first, replace(other, **{field: getattr(first, field)})])


def test_economical_estimate_caps_active_vms_without_claiming_measured_savings():
    result = estimate_resources(base_bytes=40 * GIB, dots=20, delta_bytes_per_dot=2 * GIB,
                                profile_bytes_per_dot=GIB, ram_per_vm_bytes=4 * GIB,
                                host_reserve_bytes=8 * GIB, host_ram_bytes=16 * GIB, max_running_clones=10)
    assert result["full_clone_base_disk_bytes"] == 800 * GIB
    assert result["linked_clone_disk_bytes"] == 80 * GIB
    assert result["shared_user_disk_bytes"] == 60 * GIB
    assert result["running_clone_limit"] == 2
    assert result["measured"] is result["licenses_included"] is False
    result = estimate_resources(base_bytes=GIB, dots=1, delta_bytes_per_dot=0,
                                profile_bytes_per_dot=0, ram_per_vm_bytes=8 * GIB,
                                host_reserve_bytes=8 * GIB, host_ram_bytes=8 * GIB)
    assert result["running_clone_limit"] == 0 and not result["one_shared_vm_fits_ram"]


@pytest.mark.parametrize("field,value", [("dots", 0), ("dots", 201), ("dots", True),
    ("delta_bytes_per_dot", -1), ("ram_per_vm_bytes", 0), ("max_running_clones", 3)])
def test_resource_budget_rejects_nonsense(field, value):
    args = dict(base_bytes=GIB, dots=2, delta_bytes_per_dot=GIB, profile_bytes_per_dot=GIB,
                ram_per_vm_bytes=GIB, host_reserve_bytes=GIB, host_ram_bytes=4 * GIB)
    with pytest.raises(ValueError):
        estimate_resources(**(args | {field: value}))


def test_headless_probe_can_pass_structure_without_becoming_gui_or_authority(account, probe):
    result = assess(account, probe)
    assert result.structural_checks_passed and not result.issues
    assert not result.gui_session_verified and not result.authorization_granted and not result.isolation_homologated


@pytest.mark.parametrize("field,value,issue", [
    ("nonce", "old-probe", "nonce"), ("user_sid", "S-1-5-18", "user_sid"),
    ("machine_guid", VM2, "machine_guid"), ("profile_path", r"C:\Users\dot_b", "profile"),
    ("group_sids", ["S-1-5-32-544"], "non_admin"),
    ("group_sids", None, "non_admin"),
    ("group_sids", [], "non_admin"),
    ("privilege_names", ["SeDebugPrivilege"], "limited_privileges"),
    ("privilege_names", [], "limited_privileges"),
    ("privilege_names", None, "limited_privileges"),
    ("directories", [], "directories_missing"),
    ("directories", [None], "directory_evidence"),
    ("canaries", [], "canary_evidence_missing"),
])
def test_probe_rejects_stale_identity_admin_and_incomplete_proof(account, probe, field, value, issue):
    probe[field] = value
    result = assess(account, probe)
    assert not result.structural_checks_passed
    assert any(issue in i for i in result.issues)


@pytest.mark.parametrize("field,value", [("protected", False), ("reparse_ancestor", True),
    ("owner_sid", "S-1-1-0"), ("is_directory", False),
    ("allow_sids", [SID, "S-1-1-0"]), ("allow_sids", ["S-1-5-11"]), ("allow_sids", [])])
def test_broad_acl_inheritance_reparse_and_unknown_owner_fail_closed(account, probe, field, value):
    probe["directories"][0][field] = value
    assert "private_acl_or_path_unproven" in assess(account, probe).issues


@pytest.mark.parametrize("state", ["readable", "missing", "error", "", None])
def test_missing_or_unknown_canary_never_counts_as_denied(account, probe, state):
    probe["canaries"][0]["state"] = state
    assert "peer_canary_access_not_denied" in assess(account, probe).issues


def test_probe_cannot_smuggle_duplicate_or_extra_records(account, probe):
    for key in ("directories", "canaries"):
        changed = copy.deepcopy(probe)
        changed[key].append(copy.deepcopy(changed[key][0]))
        assert not assess(account, changed).structural_checks_passed


def test_console_projection_requires_live_exact_physical_scope_and_epoch(account):
    status = {"resource_id": console_resource_id(VM), "machine_id": "machine-a", "principal_id": "agent-a",
              "work_item_id": "work-a", "holder": "agent", "epoch": 7, "live": True, "expires_at": 120.0}
    args = dict(machine_id="machine-a", principal_id="agent-a", work_item_id="work-a", expected_epoch=7, now=100.0)
    assert assess_console_possession(account, status, **args) == ()
    for key, value in [("resource_id", "dot:a"), ("holder", "human"), ("epoch", 8), ("principal_id", "agent-b"),
                       ("machine_id", "other-machine"), ("work_item_id", "work-b"), ("expires_at", 99),
                       ("expires_at", float("inf")), ("expires_at", float("nan")), ("live", False)]:
        assert assess_console_possession(account, status | {key: value}, **args)
    assert assess_console_possession(account, status, **(args | {"expected_epoch": True}))
    assert assess_console_possession(account, status, **(args | {"now": float("nan")}))
    assert assess_console_possession(account, None, **args)


def test_real_central_human_handoff_invalidates_old_projection_read(tmp_path, account):
    from sentra_executors.input_control import InputControl
    from sentra_mcp.services.context import ContextBusService
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_mcp.services.durable import DurableRunService
    from sentra_runtime.contracts import OperationRequest
    durable = DurableRunService(tmp_path / "central")
    control = ControlPlaneService(durable, ContextBusService(tmp_path / "central"))
    try:
        owner, agent, run, work, machine = account.owner, "agent-a", "run-a", "work-a", "machine-a"
        control.durable.create_run(owner, run_id=run, workspace=str(tmp_path))
        control.ensure_agent(run, owner, agent_id=agent, role="worker")
        control.create_work_item(run, owner, work_item_id=work, objective="Disposable commissioning",
                                 assignee_agent_id=agent, required_capabilities=["vm:input"],
                                 metadata={"workspace_id": "workspace-a", "machine_id": machine})
        control.transition_work_item(work, owner, "QUEUED")
        control.start_work_item_execution(work, owner, run_id=run, agent_id=agent)
        control.authorization.grant(owner, principal_type="agent", principal_id=agent,
                                     capability="vm:input", scope_type="work_item", scope_id=work)
        request = OperationRequest("op-a", agent, machine, "vm:input", work, "request-a", {"action": "input.key"})
        possession = InputControl(control, owner=owner, clock=lambda: 100.0)
        resource = console_resource_id(account.vm_id)
        handoff = dict(resource_id=resource, workspace_id="workspace-a", machine_id=machine)
        possession.handoff(**handoff, holder="agent", expected_epoch=0, request_key="acquire-a", request=request)
        check = dict(machine_id=machine, principal_id=agent, work_item_id=work, expected_epoch=1, now=100.0)
        fresh = lambda: possession.status(resource_id=resource, workspace_id="workspace-a")
        assert assess_console_possession(account, fresh(), **check) == ()
        possession.handoff(**handoff, holder="human", expected_epoch=1, request_key="human-a")
        assert assess_console_possession(account, fresh(), **check)
        with pytest.raises(PermissionError):
            possession.check(request, resource, expected_epoch=1)
        # No independent scheduler or permission store was created by our module.
    finally:
        durable.close()


def test_generated_probe_is_parseable_powershell_without_execution(tmp_path, account):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell parser unavailable; no guest effects allowed")
    path = tmp_path / "probe.ps1"
    # Apostrophes and metacharacters remain base64 JSON, never script source.
    tricky = r"C:\Users\dot_b\canary'$(Get-Date).txt"
    script = account_probe_script(account, nonce="probe-1", peer_canaries=[tricky])
    path.write_text(script, encoding="utf-8")
    assert tricky not in script
    parser = ("$tokens=$null;$errors=$null;"
              "[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)|Out-Null;"
              "if($errors.Count){$errors|ForEach-Object {$_.Message};exit 1};exit 0")
    # -Command arguments use $args inconsistently across PowerShell versions;
    # embed only a correctly quoted temporary path in this static parser call.
    parser = parser.replace("$args[0]", "'" + str(path).replace("'", "''") + "'")
    completed = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", parser],
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_probe_generator_bounds_paths_and_does_not_run(account):
    with pytest.raises(ValueError, match="unique_canaries"):
        account_probe_script(account, nonce="probe-1", peer_canaries=[CANARY, CANARY.upper()])
    with pytest.raises(ValueError):
        account_probe_script(account, nonce="';not-a-nonce", peer_canaries=[])
    # It returns inert source. No local VM API or process is called.
    assert isinstance(account_probe_script(account, nonce="probe-1"), str)
