"""Readiness for one producer CLI proof. This module does not send a prompt.

A Codex login and an exit code are not receipts. ``unit_gate`` and
``process_exit`` do not close the coordinator trio. The gate withholds the
turn until OpenCode has an authenticated integration and an authority chain
is already present. It never creates that chain.
"""
from __future__ import annotations


def assess_producer_proof(observation: dict) -> dict:
    blockers: list[str] = []
    if observation.get("codex_rc") != 0:
        blockers.append("codex_session_absent")
    opencode = str(observation.get("opencode_status") or "")
    if observation.get("opencode_rc") != 0 or "No authenticated integrations" in opencode:
        blockers.append("opencode_unauthenticated")
    if not _authority_ready(observation.get("authority")):
        blockers.append("authority_chain_absent")
    return {
        "producer_turn": "withheld" if blockers else "ready",
        "blockers": blockers,
        "codex_login_is_receipt": False,
        "closes_trio": False,
        "product_success": False,
        "unit_gate_closes_trio": False,
        "process_exit_closes_trio": False,
    }


def _authority_ready(authority: object) -> bool:
    if not isinstance(authority, dict):
        return False
    if authority.get("run_state") != "RUNNING":
        return False
    if authority.get("work_item_state") != "IN_REVIEW":
        return False
    if authority.get("operation_state") != "SUCCEEDED":
        return False
    if authority.get("receipt_verified") is not True:
        return False
    if authority.get("execution_uncertain") is not False:
        return False
    grant = authority.get("grant")
    return isinstance(grant, str) and bool(grant.strip())
