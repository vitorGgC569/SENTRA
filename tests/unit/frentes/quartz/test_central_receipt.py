"""The audit reaches a central Run, WorkItem, Operation receipt and Grant by reading them."""
from __future__ import annotations

import pytest

from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceService
from sentra_quality.decision_receipt_audit import AuditRefusal, DecisionReceiptLedger
from tests.unit.frentes.quartz.helpers import (
    SHA_B,
    SHA_D,
    authorization,
    decision,
    execution,
)


def _central(tmp_path):
    state = tmp_path / "control"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    owner = "owner-a"
    durable.create_run(owner, run_id="run-1", workspace="ws-1")
    governance.create_work_item("run-1", owner, objective="import project", work_item_id="wi-1")
    grant = auth.grant(
        owner,
        principal_type="agent",
        principal_id="dot-a",
        capability="vm.import",
        scope_type="work_item",
        scope_id="wi-1",
    )
    reserved = durable.reserve_operation_intent(
        "run-1",
        owner,
        operation_id="op-import-1",
        idempotency_key="idem-import-1",
        intent_sha256=SHA_B,
        resource_key="resource-dot-a",
        operation_context={
            "work_item_id": "wi-1",
            "principal_id": "dot-a",
            "machine_id": "machine-1",
            "capability_id": "vm.import",
        },
    )
    return auth, durable, governance, grant, reserved


def _chain(tmp_path, grant_id):
    ledger = DecisionReceiptLedger(tmp_path / "audit")
    chain_id = ledger.open_chain(decision())["chain_id"]
    ledger.observe_tool(
        chain_id, owner="owner-a", dot_id="dot-a",
        tool_name="project.import", args_sha256=SHA_D,
    )
    ledger.observe_authorization(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=authorization(grant_id=grant_id),
    )
    ledger.observe_execution(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=execution(effect_started=False),
    )
    return ledger, chain_id


def test_audit_reads_central_run_work_item_operation_and_grant(tmp_path):
    auth, durable, governance, grant, reserved = _central(tmp_path)
    before = auth.list_grants("owner-a")["items"]
    ledger, chain_id = _chain(tmp_path, grant["grant_id"])
    assert ledger.read(chain_id, owner="owner-a", dot_id="dot-a")["central_receipt_reached"] is False
    sealed = ledger.bind_central_receipt(
        chain_id, owner="owner-a", dot_id="dot-a",
        durable=durable, governance=governance, authorization=auth,
    )
    assert sealed["authorizes_effect"] is False
    assert sealed["resend_allowed"] is False
    assert sealed["run_id"] == "run-1"
    assert sealed["work_item_id"] == "wi-1"
    assert sealed["operation_id"] == "op-import-1"
    assert sealed["grant_id"] == grant["grant_id"]
    assert sealed["intent_sha256"] == SHA_B
    assert sealed["central_state"] == "STARTING"
    assert sealed["fencing_token"] == reserved["fencing_token"]
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["central_receipt_reached"] is True
    assert view["authorizes_effect"] is False
    assert view["resend_allowed"] is False
    assert ledger.allows(chain_id, owner="owner-a", dot_id="dot-a", capability="vm.import") is False
    assert auth.list_grants("owner-a")["items"] == before
    assert durable.operation_status("op-import-1", "owner-a")["state"] == "STARTING"
    again = ledger.bind_central_receipt(
        chain_id, owner="owner-a", dot_id="dot-a",
        durable=durable, governance=governance, authorization=auth,
    )
    assert again == sealed
    with pytest.raises(AuditRefusal, match="does not dispatch"):
        ledger.request_resend(chain_id, owner="owner-a", dot_id="dot-a")


def test_missing_or_revoked_central_binding_is_refused(tmp_path):
    auth, durable, governance, grant, reserved = _central(tmp_path)
    ledger, chain_id = _chain(tmp_path, "grant-" + ("cd" * 16))
    with pytest.raises(AuditRefusal, match="central operation receipt unavailable"):
        ledger.bind_central_receipt(
            chain_id, owner="owner-a", dot_id="dot-a",
            durable=durable, governance=governance, authorization=auth,
        )
    assert ledger.read(chain_id, owner="owner-a", dot_id="dot-a")["central_receipt_reached"] is False
    auth.revoke(grant["grant_id"], "owner-a")
    other, other_id = _chain(tmp_path / "other", grant["grant_id"])
    with pytest.raises(AuditRefusal, match="Grant mismatch"):
        other.bind_central_receipt(
            other_id, owner="owner-a", dot_id="dot-a",
            durable=durable, governance=governance, authorization=auth,
        )
    durable.update_operation(
        "op-import-1", "owner-a", state="UNCERTAIN",
        resource_key="resource-dot-a", fencing_token=reserved["fencing_token"],
    )
    held_ledger, held_id = _chain(tmp_path / "held", grant["grant_id"])
    # The revoked grant still refuses before the UNCERTAIN state can be treated as success.
    with pytest.raises(AuditRefusal, match="Grant mismatch"):
        held_ledger.bind_central_receipt(
            held_id, owner="owner-a", dot_id="dot-a",
            durable=durable, governance=governance, authorization=auth,
        )


def test_uncertain_central_operation_is_bound_and_not_resent(tmp_path):
    auth, durable, governance, grant, reserved = _central(tmp_path)
    durable.update_operation(
        "op-import-1", "owner-a", state="UNCERTAIN",
        resource_key="resource-dot-a", fencing_token=reserved["fencing_token"],
    )
    ledger, chain_id = _chain(tmp_path, grant["grant_id"])
    sealed = ledger.bind_central_receipt(
        chain_id, owner="owner-a", dot_id="dot-a",
        durable=durable, governance=governance, authorization=auth,
    )
    assert sealed["central_state"] == "UNCERTAIN"
    assert sealed["resend_allowed"] is False
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["uncertain"] is True
    assert view["central_receipt_reached"] is True
    assert view["authorizes_effect"] is False
    with pytest.raises(AuditRefusal, match="UNCERTAIN operation is not resent"):
        ledger.request_resend(chain_id, owner="owner-a", dot_id="dot-a")
    assert durable.operation_status("op-import-1", "owner-a")["state"] == "UNCERTAIN"
