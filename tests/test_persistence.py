from orchestrator.persistence import PersistenceStore
from orchestrator.models import Task, Candidate, ValidationReport
from orchestrator.events import EventEnvelope, EventType


def test_persistence_store_entities(tmp_path):
    store = PersistenceStore("run-persist-1", base_dir=tmp_path)

    # 1. Save and load tasks
    task = Task(id="T-99", run_id="run-persist-1", objective="Persistence test")
    store.save_tasks([task])
    loaded_tasks = store.load_tasks()
    assert len(loaded_tasks) == 1
    assert loaded_tasks[0].id == "T-99"

    # 2. Save and load candidates
    cand = Candidate(candidate_id="c-99", task_id="T-99", summary="Summary 99")
    store.save_candidate(cand)
    loaded_cands = store.load_candidates()
    assert len(loaded_cands) == 1
    assert loaded_cands[0].candidate_id == "c-99"

    # 3. Save and load events
    evt = EventEnvelope(event_type=EventType.TASK_CREATED, correlation_id="run-persist-1", task_id="T-99")
    store.append_event(evt)
    loaded_events = store.load_events()
    assert len(loaded_events) == 1
    assert loaded_events[0].task_id == "T-99"
