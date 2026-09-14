from copy import deepcopy
import json

import pytest

from orchestrator.master_queue import MasterQueue
from orchestrator.scale_gates import evaluate_scale


def manifest():
    return {"schema_version": 1, "limits": {"total_tokens": 500000, "total_seconds": 1800},
            "jobs": [{"id": "one", "objective": "fix value", "agents": 6,
                      "budget": {"master": 20000, "secondary": 200000, "task": 150000, "seconds": 900}}]}


def test_atomic_idempotent_import_and_no_automatic_replay(tmp_path):
    q = MasterQueue(tmp_path)
    q.ingest(manifest(), {})
    q.ingest(manifest(), {})
    assert len(q.status()["jobs"]) == 1
    assert q.claim()[0]["id"] == "one"
    restarted = MasterQueue(tmp_path)
    with pytest.raises(ValueError, match="requires operator"):
        restarted.claim()
    restarted.abandon("one", "External delivery checked by operator")
    assert restarted.claim() is None
    q.ingest(manifest(), {})
    assert q.status()["jobs"][0]["state"] == "FAILED"


@pytest.mark.parametrize("field,value", [("id", "../escape"), ("agents", True), ("agents", 200), ("priority", -1), ("depends_on", ["missing"])])
def test_bad_manifest_is_atomic(tmp_path, field, value):
    q = MasterQueue(tmp_path)
    data = manifest()
    data["jobs"][0][field] = value
    with pytest.raises((ValueError, TypeError)):
        q.ingest(data, {})
    assert q.status()["jobs"] == []


def test_budget_and_id_cannot_be_redefined(tmp_path):
    q = MasterQueue(tmp_path)
    data = manifest()
    q.ingest(data, {})
    data["limits"]["total_tokens"] += 1
    with pytest.raises(ValueError, match="immutable"):
        q.ingest(data, {})
    data = manifest()
    data["jobs"][0]["objective"] = "different task"
    with pytest.raises(ValueError, match="immutable"):
        q.ingest(data, {})
    data = manifest()
    data["jobs"] += [{**deepcopy(data["jobs"][0]), "id": "two"}, {**deepcopy(data["jobs"][0]), "id": "three"}]
    with pytest.raises(ValueError, match="allocation"):
        q.ingest(data, {})
    assert len(q.status()["jobs"]) == 1


def test_dependencies_require_code_promotion_not_central_receipt(tmp_path):
    q = MasterQueue(tmp_path)
    data = manifest()
    data["jobs"] += [{**deepcopy(data["jobs"][0]), "id": "two", "priority": 100, "depends_on": ["one"]}]
    q.ingest(data, {})
    assert q.claim()[0]["id"] == "one"
    q._finish("one", "CANDIDATE_READY", {}, None)
    assert q.claim() is None
    path = tmp_path / "runs" / "mq-one"
    path.mkdir(parents=True)
    (path / "handoff.json").write_text(json.dumps({"status": "APPLIED"}))
    assert q.claim()[0]["id"] == "two"


def test_cycle_rejected_before_any_import(tmp_path):
    data = manifest()
    data["jobs"][0]["depends_on"] = ["two"]
    data["jobs"] += [{**deepcopy(data["jobs"][0]), "id": "two", "depends_on": ["one"]}]
    with pytest.raises(ValueError, match="cycle"):
        MasterQueue(tmp_path).ingest(data, {})


def test_scale_requires_recent_unique_live_evidence():
    assert evaluate_scale(6, [], "p")["allowed"]
    assert not evaluate_scale(7, [], "p")["allowed"]
    sample = {"run_id": "a", "live": True, "policy_hash": "p", "created_at": 100,
              "seats_observed": 6, "elapsed_s": 800, "success": True,
              "uncertain": 0, "budget_overrun": False, "identity_complete": True}
    assert not evaluate_scale(7, [sample] * 3, "p", 101)["allowed"]
    samples = [{**sample, "run_id": str(i)} for i in range(3)]
    assert evaluate_scale(7, samples, "p", 101)["allowed"]
    for key, value in (("live", False), ("policy_hash", "stale"), ("uncertain", 1), ("elapsed_s", 1900), ("identity_complete", False)):
        assert not evaluate_scale(7, [{**s, key: value} for s in samples], "p", 101)["allowed"]
    assert not evaluate_scale(8, samples, "p", 101)["allowed"]


async def test_missing_docker_authority_blocks_without_model_calls(tmp_path, monkeypatch):
    q = MasterQueue(tmp_path)
    q.ingest(manifest(), {})
    monkeypatch.setattr("orchestrator.configuration.build_router", lambda _: pytest.fail("must not call provider"))
    result = await q.run_next()
    assert result["status"] == "BLOCKED" and "Docker" in result["error"]


def test_unread_context_cannot_be_acknowledged(tmp_path):
    q = MasterQueue(tmp_path)
    with pytest.raises(ValueError, match="exact imported"):
        q.acknowledge("one", "invented", "central")
