"""Persistence safety — interrupted writes, corruption, duplicates."""
import json

import pytest

from orchestrator.persistence import PersistenceCorruptionError, PersistenceStore
from orchestrator.models import Candidate, Task, ValidationReport


def test_corrupted_tasks_file_quarantined_not_silent(tmp_path):
    store = PersistenceStore("corr-run", base_dir=tmp_path)
    store.save_tasks([Task(id="T-1", run_id="corr-run", objective="ok")])
    # Corrupt the file mid-write style
    (store.tasks_file).write_text("{ not valid json [[[", encoding="utf-8")
    with pytest.raises(PersistenceCorruptionError):
        store.load_tasks()
    # Quarantine backup exists; original gone (never silently used)
    assert list(store.run_dir.glob("tasks.json.corrupt-*.bak")) != []


def test_torn_event_line_skipped_gracefully(tmp_path):
    store = PersistenceStore("torn-run", base_dir=tmp_path)
    from orchestrator.events import EventEnvelope, EventType
    store.append_event(EventEnvelope(event_type=EventType.TASK_CREATED, correlation_id="r",
                                     task_id="T-1", producer="t"))
    with open(store.events_file, "a", encoding="utf-8") as f:
        f.write("{ torn partial line without newline")
    # Loader must not crash; torn line skipped
    events = store.load_events()
    assert len(events) == 1


def test_duplicate_event_ids_ignored_on_load(tmp_path):
    from orchestrator.events import EventEnvelope, EventType
    store = PersistenceStore("dup-run", base_dir=tmp_path)
    e = EventEnvelope(event_type=EventType.TASK_CREATED, correlation_id="r",
                      task_id="T-1", producer="t")
    store.append_event(e)
    store.append_event(e)  # duplicate delivery
    assert len(store.load_events()) == 1


def test_candidate_duplicate_idempotent(tmp_path):
    store = PersistenceStore("cand-run", base_dir=tmp_path)
    c = Candidate(candidate_id="C-1", task_id="T-1", solution="v1")
    store.save_candidate(c)
    store.save_candidate(c)
    assert len(store.load_candidates()) == 1


def test_atomic_write_no_partial_file(tmp_path):
    store = PersistenceStore("atomic-run", base_dir=tmp_path)
    tasks = [Task(id=f"T-{i}", run_id="atomic-run", objective=f"obj {i}") for i in range(20)]
    store.save_tasks(tasks)
    data = json.loads(store.tasks_file.read_text(encoding="utf-8"))
    assert len(data) == 20
    assert not list(store.run_dir.glob("tasks.json.tmp.*"))  # no tmp leftovers
