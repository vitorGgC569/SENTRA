"""Real central receipts with synthetic guest payloads; no Windows/VM effects."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from test_windows_dot_isolation import account, probe, MACHINE, CANARY
from sentra_core.conversations import _encode, _decode
from sentra_executors.windows_dot_isolation import (
    collect_windows_probe, prepare_windows_probe, recover_windows_probe,
)
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import OperationResult
from sentra_runtime.executor import _request_snapshot


@pytest.fixture
def prepared(tmp_path, account):
    state = tmp_path / "state"
    durable = DurableRunService(state)
    control = ControlPlaneService(durable, ContextBusService(state))
    owner, agent, run, work = account.owner, "agent-a", "run-a", "work-a"
    control.durable.create_run(owner, run_id=run, workspace=str(tmp_path))
    control.ensure_agent(run, owner, agent_id=agent, role="worker")
    control.create_work_item(run, owner, work_item_id=work, objective="Synthetic probe contract",
                            assignee_agent_id=agent, required_capabilities=["vm:guest"],
                            metadata={"workspace_id": "workspace-a", "machine_id": "machine-a",
                                      "conversation_id": "conversation-a", "root_dot_id": account.dot_id})
    control.transition_work_item(work, owner, "QUEUED")
    control.start_work_item_execution(work, owner, run_id=run, agent_id=agent)
    grant = control.authorization.grant(owner, principal_type="agent", principal_id=agent,
                                        capability="vm:guest", scope_type="work_item", scope_id=work)["grant_id"]
    cfg = {"vm_id": account.vm_id, "root_dot_id": account.dot_id, "os_family": "windows",
           "username": account.username, "machine_id": "machine-a", "agent_id": agent,
           "work_items": {"conversation-a": work}, "password": "synthetic-never-exported"}
    with control.store.connect("shell") as db:
        db.execute("CREATE TABLE shell_dot_vms(owner TEXT,project TEXT,root TEXT,body TEXT)")
        db.execute("INSERT INTO shell_dot_vms VALUES(?,?,?,?)", (owner, "workspace-a", account.dot_id, _encode(cfg)))
    plan = prepare_windows_probe(control, account, workspace_id="workspace-a", conversation_id="conversation-a",
                                  expected_machine_guid=MACHINE, nonce="probe-1", operation_id="op-probe-a",
                                  idempotency_key="request-probe-a", peer_canaries=(CANARY,))
    try:
        yield control, plan, grant
    finally:
        durable.close()


def persist(control, plan, probe, *, state="SUCCEEDED", evidence_changes=None):
    authority = CentralDurableIntentAuthority(control.durable, release_on_terminal=True)
    receipt = authority.reserve_intent(run_id=plan.run_id, owner=plan.account.owner,
                                       request=plan.request, intent_sha256=_request_snapshot(plan.request)[1])
    assert authority.fence_active(receipt)
    authority.begin_effect(receipt)
    evidence = {"vm_id": plan.account.vm_id, "execution_surface": "guest", "guest_process_confirmed": True,
                "claims_guest_execution": True, "host_subprocess": False, "execution_uncertain": False,
                "stdout": json.dumps(probe) if not isinstance(probe, str) else probe}
    evidence.update(evidence_changes or {})
    assert authority.record_result(receipt, OperationResult(plan.request.operation_id, state, evidence))
    return authority


def test_canonical_protected_result_is_recovered_without_arbitrary_stdout_parameter(prepared, probe):
    control, plan, _ = prepared
    persist(control, plan, probe)
    observed = recover_windows_probe(control, plan)
    assert observed.central_receipt_verified and observed.guest_execution_receipt_verified
    assert observed.assessment.structural_checks_passed
    assert observed.automatic_retry is observed.isolation_homologated is False
    assert not observed.assessment.authorization_granted and not observed.assessment.gui_session_verified
    assert "synthetic-never-exported" not in repr(plan)


def test_prepare_does_not_create_operation_or_grant(prepared):
    control, plan, _ = prepared
    assert control.durable.list_operations(plan.run_id, plan.account.owner)["items"] == []
    with pytest.raises(FileNotFoundError):
        recover_windows_probe(control, plan)
    with pytest.raises(PermissionError, match="owning_machine_host"):
        collect_windows_probe(SimpleNamespace(owner=plan.account.owner, control=control), plan)


@pytest.mark.parametrize("changes", [
    {"execution_surface": "host"}, {"host_subprocess": True}, {"guest_process_confirmed": False},
    {"execution_uncertain": True}, {"claims_guest_execution": False}, {"vm_id": MACHINE},
])
def test_canonical_success_without_guest_proof_is_rejected(prepared, probe, changes):
    control, plan, _ = prepared
    persist(control, plan, probe, evidence_changes=changes)
    with pytest.raises(PermissionError, match="does_not_prove_guest"):
        recover_windows_probe(control, plan)


@pytest.mark.parametrize("state", ["UNCERTAIN", "FAILED", "CANCELLED"])
def test_non_success_never_promotes_probe_even_when_payload_looks_valid(prepared, probe, state):
    control, plan, _ = prepared
    persist(control, plan, probe, state=state)
    observed = recover_windows_probe(control, plan)
    assert observed.state == state and observed.assessment is None
    assert not observed.guest_execution_receipt_verified and not observed.automatic_retry


def test_stored_result_cannot_be_rebound_to_different_probe_intent(prepared, probe):
    control, plan, _ = prepared
    persist(control, plan, probe)
    from sentra_executors.windows_dot_isolation import account_probe_script
    changed = replace(plan, nonce="other-probe")
    changed = replace(changed, request=replace(changed.request, arguments={
        "action": "guest.run", "timeout_seconds": 60,
        "command": account_probe_script(changed.account, nonce=changed.nonce, peer_canaries=changed.peer_canaries)}))
    with pytest.raises(PermissionError, match="intent_mismatch"):
        recover_windows_probe(control, changed)


def test_mutating_prepared_request_does_not_change_approved_probe_command(prepared):
    control, plan, _ = prepared
    plan.request.arguments["command"] = "Write-Output forged"
    with pytest.raises(PermissionError, match="command_changed"):
        recover_windows_probe(control, plan)


def test_revoke_prevents_publishing_even_valid_canonical_probe(prepared, probe):
    control, plan, grant = prepared
    persist(control, plan, probe)
    control.authorization.revoke(grant, plan.account.owner)
    with pytest.raises(PermissionError, match="live_vm_guest_grant"):
        recover_windows_probe(control, plan)


@pytest.mark.parametrize("field,value", [("username", "dot_b"), ("vm_id", MACHINE), ("agent_id", "other-agent")])
def test_trusted_registry_change_invalidates_prepared_binding(prepared, probe, field, value):
    control, plan, _ = prepared
    persist(control, plan, probe)
    with control.store.connect("shell") as db:
        cfg = _decode(db.execute("SELECT body FROM shell_dot_vms").fetchone()["body"])
        cfg[field] = value
        db.execute("UPDATE shell_dot_vms SET body=?", (_encode(cfg),))
    with pytest.raises(PermissionError):
        recover_windows_probe(control, plan)


def test_unbound_conversation_cannot_prepare_guest_effect(prepared):
    control, plan, _ = prepared
    with pytest.raises(PermissionError, match="owning_conversation"):
        prepare_windows_probe(control, plan.account, workspace_id=plan.workspace_id,
                              conversation_id="conversation-other", expected_machine_guid=MACHINE,
                              nonce="probe-2", operation_id="op-probe-b", idempotency_key="request-b")


def test_modified_protected_artifact_is_not_accepted_as_receipt(prepared, probe):
    control, plan, _ = prepared
    persist(control, plan, probe)
    row = control.durable.operation_status(plan.request.operation_id, plan.account.owner)
    artifact = control.durable.artifact_info(row["result"]["evidence_artifact_id"], plan.account.owner)
    Path(artifact["path"]).write_bytes(b"forged-json-does-not-have-a-valid-digest")
    with pytest.raises(RuntimeError, match="artifact content hash changed"):
        recover_windows_probe(control, plan)


@pytest.mark.parametrize("stdout", ['{"nonce":"one","nonce":"two"}', '{"x":NaN}', "not JSON"])
def test_even_canonical_stdout_requires_unambiguous_json(prepared, stdout):
    control, plan, _ = prepared
    persist(control, plan, stdout)
    with pytest.raises(ValueError):
        recover_windows_probe(control, plan)


def test_old_probe_is_historical_evidence_not_current_account_validation(prepared, probe):
    control, plan, _ = prepared
    persist(control, plan, probe)
    with control.durable.lock:
        control.durable.db.execute("UPDATE operations SET updated_at=updated_at-1000 WHERE operation_id=?",
                                   (plan.request.operation_id,))
        control.durable.db.commit()
    with pytest.raises(PermissionError, match="stale_or_time"):
        recover_windows_probe(control, plan)


def test_real_machine_host_recovery_never_repeats_dispatch(prepared, probe, monkeypatch):
    from sentra_runtime.machine_host import MachineHost
    control, plan, _ = prepared
    persist(control, plan, probe)
    host = MachineHost(control, owner=plan.account.owner)
    try:
        monkeypatch.setattr(host, "dispatch", lambda **_: pytest.fail("recovery repeated a physical request"))
        assert collect_windows_probe(host, plan).assessment.structural_checks_passed
    finally:
        host.close()


def test_new_collection_requires_registered_real_virtualbox_machine(prepared, monkeypatch):
    from sentra_runtime.machine_host import MachineHost
    control, plan, _ = prepared
    host = MachineHost(control, owner=plan.account.owner)
    try:
        monkeypatch.setattr(host, "dispatch", lambda **_: pytest.fail("unconfigured physical request"))
        with pytest.raises(PermissionError, match="configured_virtualbox_machine_host"):
            collect_windows_probe(host, plan)
    finally:
        host.close()
