"""Decision-to-receipt audit. The chain observes; it does not admit an effect."""
from __future__ import annotations

import sqlite3

import pytest

from orchestrator.models import Candidate, Task
from orchestrator.quality_gate import QualityGate, gate_decision_observation
from sentra_quality.decision_receipt_audit import (
    AuditRefusal,
    ReceiptObservation,
    ReviewObservation,
    decision_from_gate,
)
from tests.unit.frentes.quartz.helpers import (
    SHA_B,
    SHA_C,
    open_through_result,
    receipt,
)


def test_chain_reaches_receipt_without_authorizing_effect(tmp_path):
    ledger, chain_id = open_through_result(tmp_path)
    sealed = ledger.observe_receipt(
        chain_id, owner="owner-a", dot_id="dot-a", observation=receipt(),
    )
    assert sealed["state"] == "SUCCEEDED"
    assert sealed["authorizes_effect"] is False
    assert sealed["resend_allowed"] is False
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["stages"] == [
        "decision", "tool", "authorization", "execution", "result", "receipt",
    ]
    assert view["authorizes_effect"] is False
    assert view["resend_allowed"] is False
    assert ledger.allows(chain_id, owner="owner-a", dot_id="dot-a", capability="vm.import") is False
    with pytest.raises(AuditRefusal, match="does not dispatch"):
        ledger.request_resend(chain_id, owner="owner-a", dot_id="dot-a")


def test_denial_blocks_execution_observation(tmp_path):
    from sentra_quality.decision_receipt_audit import DecisionReceiptLedger
    from tests.unit.frentes.quartz.helpers import SHA_D, authorization, decision, execution

    ledger = DecisionReceiptLedger(tmp_path / "audit")
    opened = ledger.open_chain(decision())
    chain_id = opened["chain_id"]
    ledger.observe_tool(
        chain_id, owner="owner-a", dot_id="dot-a",
        tool_name="project.import", args_sha256=SHA_D,
    )
    ledger.observe_authorization(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=authorization(allowed=False, source="policy", grant_id=None, reason="no matching active grant"),
    )
    with pytest.raises(AuditRefusal, match="denial is not an effect"):
        ledger.observe_execution(
            chain_id, owner="owner-a", dot_id="dot-a", observation=execution(),
        )
    assert ledger.read(chain_id, owner="owner-a", dot_id="dot-a")["stages"] == [
        "decision", "tool", "authorization",
    ]


def test_succeeded_requires_effect_and_observed_result(tmp_path):
    ledger, chain_id = open_through_result(tmp_path, effect_started=False, outcome="withheld")
    with pytest.raises(AuditRefusal, match="SUCCEEDED receipt requires effect_started"):
        ledger.observe_receipt(
            chain_id, owner="owner-a", dot_id="dot-a", observation=receipt(),
        )


def test_uncertain_receipt_is_not_resent_and_reconciliation_keeps_the_hold(tmp_path):
    from sentra_quality.decision_receipt_audit import ReconciliationObservation

    ledger, chain_id = open_through_result(tmp_path, effect_started=False, outcome="withheld")
    ledger.observe_receipt(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=receipt(state="UNCERTAIN", evidence_sha256=None),
    )
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["uncertain"] is True
    assert view["resend_allowed"] is False
    with pytest.raises(AuditRefusal, match="UNCERTAIN operation is not resent"):
        ledger.request_resend(chain_id, owner="owner-a", dot_id="dot-a")
    with pytest.raises(AuditRefusal, match="UNCERTAIN operation is not resent"):
        ledger.observe_reconciliation(
            chain_id, owner="owner-a", dot_id="dot-a",
            observation=ReconciliationObservation(
                operation_id="op-import-1", intent_sha256=SHA_B, state="SUCCEEDED", resend=True,
            ),
        )
    ledger.observe_reconciliation(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=ReconciliationObservation(
            operation_id="op-import-1", intent_sha256=SHA_B, state="SUCCEEDED", resend=False,
        ),
    )
    held = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert held["uncertain"] is True
    assert held["resend_allowed"] is False
    assert held["events"][-1]["resend"] is False
    with pytest.raises(AuditRefusal, match="does not grant"):
        ReviewObservation(reviewer_id="human-1", verdict="approved", note_sha256=SHA_C)


def test_tamper_breaks_the_hash_chain(tmp_path):
    ledger, chain_id = open_through_result(tmp_path)
    ledger.observe_receipt(
        chain_id, owner="owner-a", dot_id="dot-a", observation=receipt(),
    )
    db = sqlite3.connect(ledger.path)
    db.execute("UPDATE events SET body_json=? WHERE stage='decision'", ("{}",))
    db.commit()
    db.close()
    with pytest.raises(AuditRefusal, match="hash chain"):
        ledger.read(chain_id, owner="owner-a", dot_id="dot-a")


def test_quality_gate_stays_closed_and_its_observation_carries_no_grant():
    task = Task(id="task-1", run_id="run-1", objective="audit the decision")
    candidate = Candidate(candidate_id="cand-1", task_id="task-1", patch="diff")
    gate = QualityGate()
    assert gate.policy.validators_required == 3
    assert gate.policy.min_release_score == 9.5
    passed, reason, package = gate.evaluate(task, candidate, [])
    assert passed is False
    assert package is None
    assert "Quorum not met" in reason
    observation = gate_decision_observation(passed, reason, package)
    assert observation["authorizes_effect"] is False
    assert observation["grant_id"] is None
    advisory = decision_from_gate(
        observation,
        decision_id="dec-gate",
        owner="owner-a",
        dot_id="dot-a",
        workspace_id="ws-1",
        run_id="run-1",
        work_item_id="wi-1",
        model="quality-gate",
    )
    assert advisory.source == "quality_gate"
    assert advisory.choice == "fail"
    tainted = dict(observation)
    tainted["grant_id"] = "grant-" + ("ab" * 16)
    with pytest.raises(AuditRefusal, match="cannot carry a grant"):
        decision_from_gate(
            tainted,
            decision_id="dec-gate",
            owner="owner-a",
            dot_id="dot-a",
            workspace_id="ws-1",
            run_id="run-1",
            work_item_id="wi-1",
            model="quality-gate",
        )


def test_review_does_not_clear_uncertain(tmp_path):
    ledger, chain_id = open_through_result(tmp_path, effect_started=False, outcome="withheld")
    ledger.observe_receipt(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=ReceiptObservation(
            receipt_id="rcpt-1",
            operation_id="op-import-1",
            run_id="run-1",
            work_item_id="wi-1",
            intent_sha256=SHA_B,
            state="UNCERTAIN",
        ),
    )
    ledger.observe_review(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=ReviewObservation(reviewer_id="human-1", verdict="noted", note_sha256=SHA_C),
    )
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["uncertain"] is True
    assert view["resend_allowed"] is False
    assert view["authorizes_effect"] is False
