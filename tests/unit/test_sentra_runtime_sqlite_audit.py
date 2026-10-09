"""Durable audit evidence: SQLite transactions, restarts, replay and tampering."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from sentra_runtime.audit_chain import GENESIS
from sentra_runtime.sqlite_audit import (
    AuditHeadConflict, AuditIntegrityError, SQLiteAuditLedger,
)


def test_append_across_restarts_and_verify_independent_checkpoint(tmp_path):
    path = tmp_path / "local-ledger.db"
    first = SQLiteAuditLedger(path)
    e1 = first.append({"operation": "op-1", "kind": "authorized"})
    assert e1.previous == GENESIS
    second = SQLiteAuditLedger(path)
    e2 = second.append({"operation": "op-1", "kind": "observed"},
                       expected_head=e1.digest)
    assert e2.seq == 2
    assert len(SQLiteAuditLedger(path).entries(expected_head=e2.digest)) == 2
    assert SQLiteAuditLedger(path).verify(expected_head=e2.digest)
    assert not SQLiteAuditLedger(path).verify(expected_head=e1.digest)


def test_persisted_event_is_frozen_against_input_mutation(tmp_path):
    ledger = SQLiteAuditLedger(tmp_path / "state.db")
    obj = {"a": {"x": [1, 2]}}
    ledger.append(obj)
    obj["a"]["x"].append(999)
    read = ledger.entries()[0]
    assert read.event == {"a": {"x": [1, 2]}}
    assert ledger.verify(expected_head=read.digest)


def test_head_compare_and_swap_is_atomic_across_independent_connections(tmp_path):
    path = tmp_path / "audit.db"
    ledger = SQLiteAuditLedger(path)
    first_head = ledger.head

    def compete(label):
        try:
            entry = SQLiteAuditLedger(path).append({"writer": label},
                                                  expected_head=first_head)
            return entry.digest
        except AuditHeadConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ("alpha", "beta")))
    assert sum(item is not None for item in results) == 1
    assert len(SQLiteAuditLedger(path).entries()) == 1


@pytest.mark.parametrize("column,value", [
    ("event_json", '{"fake":true}'),
    ("previous", "0" * 63 + "1"),
    ("digest", "f" * 64),
    ("seq", 7),
])
def test_detects_row_tamper_before_adding_more_evidence(tmp_path, column, value):
    path = tmp_path / "audit.db"
    ledger = SQLiteAuditLedger(path)
    ledger.append({"before": True})
    checkpoint = ledger.head
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE audit_events SET {column}=? WHERE seq=1", (value,))
    assert not ledger.verify(expected_head=checkpoint)
    with pytest.raises(AuditIntegrityError):
        ledger.append({"later": True})


def test_truncation_detected_only_when_trusted_head_provided(tmp_path):
    path = tmp_path / "audit.db"
    ledger = SQLiteAuditLedger(path)
    ledger.append({"seq": 1})
    checkpoint = ledger.append({"seq": 2}).digest
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM audit_events WHERE seq=2")
    assert ledger.verify()  # Local chain alone cannot detect truncation.
    assert not ledger.verify(expected_head=checkpoint)


def test_bad_values_and_unbounded_events_rejected_without_writes(tmp_path):
    ledger = SQLiteAuditLedger(tmp_path / "audit.db")
    for bad in ({"x": float("nan")}, {"x": object()}, {"x": "x" * 65536}):
        with pytest.raises((ValueError, TypeError)):
            ledger.append(bad)
    assert ledger.entries() == ()


def test_noncanonical_sqlite_json_rejected_even_if_hash_matches(tmp_path):
    path = tmp_path / "audit.db"
    ledger = SQLiteAuditLedger(path)
    entry = ledger.append({"b": 2, "a": 1})
    with sqlite3.connect(path) as db:
        db.execute("UPDATE audit_events SET event_json=? WHERE seq=1",
                   ('{"b":2,"a":1}',))
    assert not ledger.verify(expected_head=entry.digest)


def test_empty_ledger_has_genesis_head(tmp_path):
    ledger = SQLiteAuditLedger(tmp_path / "audit.db")
    assert ledger.head == GENESIS
    assert ledger.verify(expected_head=GENESIS)
