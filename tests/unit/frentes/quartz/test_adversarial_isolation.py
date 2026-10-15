"""A Dot cannot read or attach to another Dot or owner through the audit ledger."""
from __future__ import annotations

import pytest

from sentra_quality.decision_receipt_audit import AuditRefusal, DecisionReceiptLedger
from tests.unit.frentes.quartz.helpers import SHA_D, authorization, decision


def test_other_dot_and_other_owner_cannot_read(tmp_path):
    ledger = DecisionReceiptLedger(tmp_path / "audit")
    opened = ledger.open_chain(decision())
    chain_id = opened["chain_id"]
    with pytest.raises(AuditRefusal, match="not visible"):
        ledger.read(chain_id, owner="owner-a", dot_id="dot-b")
    with pytest.raises(AuditRefusal, match="not visible"):
        ledger.read(chain_id, owner="owner-b", dot_id="dot-a")
    with pytest.raises(AuditRefusal, match="not visible"):
        ledger.read("audit-" + ("0" * 32), owner="owner-a", dot_id="dot-a")
    visible = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert visible["dot_id"] == "dot-a"
    assert visible["events"][0]["prompt_sha256"]


def test_other_principal_cannot_attach_and_chain_stays_unchanged(tmp_path):
    ledger = DecisionReceiptLedger(tmp_path / "audit")
    chain_id = ledger.open_chain(decision())["chain_id"]
    ledger.observe_tool(
        chain_id, owner="owner-a", dot_id="dot-a",
        tool_name="project.import", args_sha256=SHA_D,
    )
    with pytest.raises(AuditRefusal, match="principal is outside"):
        ledger.observe_authorization(
            chain_id, owner="owner-a", dot_id="dot-a",
            observation=authorization(principal_id="dot-b"),
        )
    with pytest.raises(AuditRefusal, match="not visible"):
        ledger.observe_tool(
            chain_id, owner="owner-b", dot_id="dot-b",
            tool_name="project.import", args_sha256=SHA_D,
        )
    view = ledger.read(chain_id, owner="owner-a", dot_id="dot-a")
    assert view["stages"] == ["decision", "tool"]
    assert ledger.allows(chain_id, owner="owner-a", dot_id="dot-a", capability="vm.delete") is False
