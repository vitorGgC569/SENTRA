"""The producer proof stays withheld until authority and auth are both present."""
from sentra_cli.producer_gate import assess_producer_proof

OBSERVED = {
    "codex_rc": 0,
    "codex_status": "Logged in using ChatGPT",
    "opencode_rc": 0,
    "opencode_status": "No authenticated integrations",
    "authority": None,
}


def test_observed_auth_does_not_open_a_producer_turn():
    report = assess_producer_proof(OBSERVED)
    assert report["producer_turn"] == "withheld"
    assert "opencode_unauthenticated" in report["blockers"]
    assert "authority_chain_absent" in report["blockers"]
    assert report["codex_login_is_receipt"] is False
    assert report["closes_trio"] is False
    assert report["product_success"] is False
    assert report["unit_gate_closes_trio"] is False
    assert report["process_exit_closes_trio"] is False


def test_a_complete_authority_chain_still_needs_opencode():
    ready = dict(OBSERVED)
    ready["opencode_status"] = "authenticated: opencode"
    ready["authority"] = {
        "run_state": "RUNNING",
        "work_item_state": "IN_REVIEW",
        "operation_state": "SUCCEEDED",
        "grant": "model:invoke",
        "receipt_verified": True,
        "execution_uncertain": False,
    }
    report = assess_producer_proof(ready)
    assert report["producer_turn"] == "ready"
    assert report["closes_trio"] is False
    assert report["product_success"] is False
