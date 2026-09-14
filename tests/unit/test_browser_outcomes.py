import pytest

from browser.outcomes import classify_failure, classify_probe


@pytest.mark.parametrize("code", ["STALE_CONVERSATION", "TAB_STALE", "DOM_NOT_READY",
                                 "DEPENDENCY_ERROR", "SUBMIT_FAILED", "TIMEOUT"])
def test_phase_ambiguous_browser_error_never_authorizes_replay(code):
    result = classify_failure(code)
    assert result["delivery_state"] == "UNCERTAIN" and result["retry_safe"] is False


@pytest.mark.parametrize("code", ["FILL_FAILED", "CLEAR_FAILED", "PROMPT_MISMATCH", "STALE_DRAFT"])
def test_prompt_preparation_failure_is_not_sent(code):
    assert classify_failure(code)["delivery_state"] == "NOT_SENT"


def test_missing_button_is_not_proof_of_account_limit():
    assert classify_probe({"composer_found": True, "send_available": False, "finished": True}) == "UNKNOWN"
    assert classify_probe({"cap_banner": "limit reached"}) == "ACCOUNT_LIMIT"
