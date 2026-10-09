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


def test_pre_send_not_ready_is_proven_not_sent():
    result = classify_failure("PRE_SEND_NOT_READY: TAB_ERROR tab=1")
    assert result["delivery_state"] == "NOT_SENT"
    assert result["retry_safe"] is True
    assert result["error_kind"] == "PRE_SEND_NOT_READY"


def test_gemini_model_selection_failure_is_proven_pre_send():
    result = classify_failure("MODEL_SELECTION_FAILED: Gemini model selector not found")
    assert result["delivery_state"] == "NOT_SENT"
    assert result["retry_safe"] is True
    assert result["error_kind"] == "PRE_SEND_MODEL_SELECTION"
