"""Hash-linked audit proof tests, including negative tampering cases."""
import copy

import pytest

from sentra_runtime.audit_chain import AuditChain, AuditEntry, GENESIS


def test_append_and_verify_head_is_stable():
    log = AuditChain()
    assert log.head == GENESIS
    original = {"operation_id": "op-1", "decision": "allowed", "scope": {"pid": 1}}
    first = log.append(original)
    original["scope"]["pid"] = 999
    second = log.append({"operation_id": "op-1", "state": "SUCCEEDED"})
    assert first.seq == 1 and second.seq == 2
    assert first.event["scope"]["pid"] == 1
    assert AuditChain.verify(log.entries, expected_head=second.digest)


def test_edit_delete_or_reorder_detected_with_trusted_external_head():
    log = AuditChain()
    log.append({"op": "A"})
    log.append({"op": "B"})
    log.append({"op": "C"})
    checkpoint = log.head
    entry = log.entries[1]
    altered = list(log.entries)
    altered[1] = AuditEntry(entry.seq, {"op": "EVIL"}, entry.previous, entry.digest)
    assert not AuditChain.verify(altered, expected_head=checkpoint)
    assert not AuditChain.verify(log.entries[:-1], expected_head=checkpoint)
    assert not AuditChain.verify(tuple(reversed(log.entries)), expected_head=checkpoint)
    assert not AuditChain.verify(altered)


def test_rejects_unserializable_events_and_nan():
    log = AuditChain()
    with pytest.raises(ValueError):
        log.append({"secret": object()})
    with pytest.raises(ValueError):
        log.append({"invalid": float("nan")})
    assert log.entries == ()


def test_blank_chain_needs_external_checkpoint_to_detect_truncation():
    # A chain by itself does not reveal that it was entirely replaced.
    assert AuditChain.verify(())
    assert not AuditChain.verify((), expected_head="1" * 64)
