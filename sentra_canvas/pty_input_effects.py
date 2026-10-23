"""Exact, content-free selectors for owner-local daemon input observations.

These selectors confer no authority. Only the authenticated broker calls the
daemon; admission and permission checks remain in the central execution path.
"""
import hashlib
import re

REFERENCE_FIELDS = frozenset({"effect_key", "workspace_id", "terminal_id",
                             "runtime_id", "generation", "payload_sha256"})


def validate_reference(value):
    if not isinstance(value, dict) or set(value) != REFERENCE_FIELDS:
        raise ValueError("exact terminal input effect selector required")
    if any(not isinstance(v, str) for v in value.values()):
        raise ValueError("string terminal input effect identities required")
    if not 8 <= len(value["effect_key"]) <= 160 or any(
            not 1 <= len(value[name]) <= 128 for name in ("workspace_id", "terminal_id")):
        raise ValueError("bounded terminal input effect identities required")
    if any(not re.fullmatch(r"[0-9a-f]{32}", value[name]) for name in ("runtime_id", "generation")):
        raise ValueError("exact terminal runtime and generation required")
    if not re.fullmatch(r"[0-9a-f]{64}", value["payload_sha256"]):
        raise ValueError("terminal input payload digest required")
    return dict(value)


def validate_payload(reference, data):
    value = validate_reference(reference)
    if (not isinstance(data, bytes) or not 0 < len(data) <= 16384
            or hashlib.sha256(data).hexdigest() != value["payload_sha256"]):
        raise ValueError("terminal input differs from its exact effect selector")
    return value
