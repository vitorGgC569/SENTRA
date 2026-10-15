"""The same sealed body replays. A different body conflicts. UNCERTAIN is not rewritten."""
from __future__ import annotations

import pytest

from sentra_quality.decision_receipt_audit import AuditConflict
from tests.unit.frentes.quartz.helpers import (
    SHA_B,
    SHA_D,
    decision,
    execution,
    open_through_result,
    receipt,
)


def test_same_decision_replays_and_a_different_body_conflicts(tmp_path):
    ledger, chain_id = open_through_result(tmp_path, effect_started=False, outcome="withheld")
    again = ledger.open_chain(decision())
    assert again["chain_id"] == chain_id
    assert again["stages"] == ["decision", "tool", "authorization", "execution", "result"]
    with pytest.raises(AuditConflict, match="different body"):
        ledger.open_chain(decision(choice="pass"))
    ledger.observe_tool(
        chain_id, owner="owner-a", dot_id="dot-a",
        tool_name="project.import", args_sha256=SHA_D,
    )
    with pytest.raises(AuditConflict, match="tool"):
        ledger.observe_tool(
            chain_id, owner="owner-a", dot_id="dot-a",
            tool_name="project.import", args_sha256="e" * 64,
        )


def test_fence_and_receipt_bodies_are_idempotent(tmp_path):
    ledger, chain_id = open_through_result(tmp_path, effect_started=False, outcome="withheld")
    first = ledger.observe_execution(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=execution(effect_started=False),
    )
    second = ledger.observe_execution(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=execution(effect_started=False),
    )
    assert first == second
    with pytest.raises(AuditConflict, match="execution"):
        ledger.observe_execution(
            chain_id, owner="owner-a", dot_id="dot-a",
            observation=execution(effect_started=False, fence_token="fence-002"),
        )
    sealed = receipt(state="UNCERTAIN", evidence_sha256=None)
    assert ledger.observe_receipt(
        chain_id, owner="owner-a", dot_id="dot-a", observation=sealed,
    )["state"] == "UNCERTAIN"
    assert ledger.observe_receipt(
        chain_id, owner="owner-a", dot_id="dot-a", observation=sealed,
    )["resend_allowed"] is False
    with pytest.raises(AuditConflict, match="receipt"):
        ledger.observe_receipt(
            chain_id, owner="owner-a", dot_id="dot-a",
            observation=receipt(state="SUCCEEDED"),
        )
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["uncertain"] is True
    assert view["resend_allowed"] is False
    assert view["events"][-1]["intent_sha256"] == SHA_B
