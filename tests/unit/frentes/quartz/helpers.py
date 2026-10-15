"""Shared fixtures for the Quartz front. Not a test module."""
from __future__ import annotations

from sentra_quality.decision_receipt_audit import (
    AuthorizationObservation,
    DecisionObservation,
    DecisionReceiptLedger,
    ExecutionObservation,
    ReceiptObservation,
    ResultObservation,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
GRANT_ID = "grant-" + ("ab" * 16)


def decision(**overrides) -> DecisionObservation:
    base = dict(
        decision_id="dec-1",
        owner="owner-a",
        dot_id="dot-a",
        workspace_id="ws-1",
        run_id="run-1",
        work_item_id="wi-1",
        model="grok-4.7",
        choice="hold",
        confidence=0.9,
        prompt_sha256=SHA_A,
        source="model",
    )
    base.update(overrides)
    return DecisionObservation(**base)


def authorization(**overrides) -> AuthorizationObservation:
    base = dict(
        owner="owner-a",
        principal_type="agent",
        principal_id="dot-a",
        capability="vm.import",
        scope_type="work_item",
        scope_id="wi-1",
        allowed=True,
        source="grant",
        grant_id=GRANT_ID,
        reason="grant observed",
    )
    base.update(overrides)
    return AuthorizationObservation(**base)


def execution(**overrides) -> ExecutionObservation:
    base = dict(
        operation_id="op-import-1",
        run_id="run-1",
        work_item_id="wi-1",
        lease_id="lease-001",
        fence_token="fence-001",
        effect_started=True,
    )
    base.update(overrides)
    return ExecutionObservation(**base)


def result(**overrides) -> ResultObservation:
    base = dict(outcome="observed", evidence_sha256=SHA_C)
    base.update(overrides)
    return ResultObservation(**base)


def receipt(**overrides) -> ReceiptObservation:
    base = dict(
        receipt_id="rcpt-1",
        operation_id="op-import-1",
        run_id="run-1",
        work_item_id="wi-1",
        intent_sha256=SHA_B,
        state="SUCCEEDED",
        evidence_sha256=SHA_C,
    )
    base.update(overrides)
    return ReceiptObservation(**base)


def open_through_result(tmp_path, *, effect_started=True, outcome="observed", content=None, recorder=None):
    ledger = DecisionReceiptLedger(
        tmp_path / "audit",
        on_event=None if recorder is None else recorder.record,
    )
    opened = ledger.open_chain(decision(), untrusted_content=content)
    chain_id = opened["chain_id"]
    ledger.observe_tool(
        chain_id, owner="owner-a", dot_id="dot-a",
        tool_name="project.import", args_sha256=SHA_D,
    )
    ledger.observe_authorization(
        chain_id, owner="owner-a", dot_id="dot-a", observation=authorization(),
    )
    ledger.observe_execution(
        chain_id, owner="owner-a", dot_id="dot-a",
        observation=execution(effect_started=effect_started),
    )
    ledger.observe_result(
        chain_id, owner="owner-a", dot_id="dot-a", observation=result(outcome=outcome),
    )
    return ledger, chain_id
