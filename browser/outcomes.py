"""Delivery uncertainty is not a retry policy or a provider quota estimate."""


def classify_failure(error):
    text = str(error or "UNKNOWN_ERROR")
    if any(code in text for code in ("ACCOUNT_LIMIT", "RATE_LIMIT", "QUOTA_EXCEEDED")):
        return {"delivery_state": "BLOCKED", "error_kind": "ACCOUNT_LIMIT", "retry_safe": False}
    # Only failures raised by prompt preparation establish NOT_SENT. Generic
    # browser/identity errors may occur after SEND_MESSAGE (e.g. stale chat
    # detected after WAIT_RESPONSE), so they must not authorize replay.
    if any(code in text for code in ("PROMPT_MISMATCH", "FILL_FAILED", "CLEAR_FAILED", "STALE_DRAFT")):
        return {"delivery_state": "NOT_SENT", "error_kind": "PROMPT_INTEGRITY", "retry_safe": True}
    return {"delivery_state": "UNCERTAIN", "error_kind": "DELIVERY_UNCERTAIN", "retry_safe": False}


def classify_probe(result):
    if result.get("cap_banner"):
        return "ACCOUNT_LIMIT"
    if result.get("finished") is False:
        return "GENERATING"
    if result.get("composer_found") is False:
        return "UI_UNAVAILABLE"
    if result.get("send_available") is True:
        return "UI_READY"  # Button presence is not proof of quota or delivery.
    return "UNKNOWN"
