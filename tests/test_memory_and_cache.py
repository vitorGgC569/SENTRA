from orchestrator.memory import (
    MemoryManager,
    WorkingMemory,
    TaskMemory,
    ArtifactStore,
    SemanticCache,
)
from orchestrator.models import Candidate


def test_working_and_task_memory(tmp_path):
    mgr = MemoryManager("run-mem-1", tmp_path)

    wm = mgr.get_working_memory("executor")
    wm.add_message("user", "Implement feature")
    assert len(wm.messages) == 1

    tm = mgr.get_task_memory("T-01")
    cand = Candidate(candidate_id="c1", task_id="T-01", version=1)
    tm.add_candidate(cand)
    assert tm.get_latest_candidate().candidate_id == "c1"


def test_artifact_store(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    content = "Unified diff hunk line 1\nline 2"
    path = store.store_artifact("patch", content, extension="diff")

    retrieved = store.retrieve_artifact(path)
    assert retrieved == content


def test_semantic_cache():
    cache = SemanticCache()
    cand = Candidate(candidate_id="c_cached", summary="Reusable solution")

    cache.store("Sort a list of numbers in ascending order", cand)

    # Lookup with minor whitespace / casing variations
    hit = cache.lookup("sort a list of numbers in ascending order!")
    assert hit is not None
    assert hit.candidate_id == "c_cached"

    # Miss
    miss = cache.lookup("Write a fast binary search")
    assert miss is None
