from __future__ import annotations

import asyncio
import hashlib

import pytest

from orchestrator.models import Candidate, Task
from orchestrator.remote_candidate import RemoteCandidateProducer


class Gateway:
    def __init__(self, terminal):
        self.terminal = terminal
        self.calls = []

    def invoke(self, principal, device_id, tool, arguments, **kwargs):
        self.calls.append(("invoke", principal, device_id, tool, arguments, kwargs))
        if self.terminal.get("defer"):
            return {"state": "PENDING", "job_id": "job-1"}
        return dict(self.terminal)

    def result(self, principal, job_id):
        self.calls.append(("result", principal, job_id))
        return {k: v for k, v in self.terminal.items() if k != "defer"}


def _task():
    return Task(
        id="T-remote",
        run_id="run-central",
        objective="edit app",
        target_files=["app.py"],
        timeout_s=30,
    )


def _completed(root, *, digest=None, task_id="T-remote"):
    actual = hashlib.sha256((root / "app.py").read_bytes()).hexdigest()
    candidate = Candidate(
        candidate_id="cand-remote",
        task_id=task_id,
        run_id="remote-run-id-is-not-authority",
        patch="",
        summary="proposal",
    )
    return {
        "state": "COMPLETED",
        "job_id": "job-1",
        "result": {
            "ok": True,
            "data": {
                "status": "CANDIDATE_READY",
                "target_hashes": {"app.py": digest or actual},
                "candidate": candidate.to_dict(),
            },
        },
    }


def test_remote_candidate_roundtrip_uses_same_persisted_job(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    terminal = _completed(tmp_path)
    terminal["defer"] = True
    gateway = Gateway(terminal)
    producer = RemoteCandidateProducer(
        gateway,
        principal="user",
        device_id="dev-1",
        workspace="project",
        poll_interval_s=0.01,
    )
    candidate = asyncio.run(
        producer.produce_candidate(
            _task(),
            context_summary="ctx",
            workspace_path=tmp_path,
        )
    )
    assert candidate.task_id == "T-remote"
    assert candidate.run_id == "run-central"
    assert [call[0] for call in gateway.calls] == ["invoke", "result"]
    invoke = gateway.calls[0]
    assert invoke[3] == "sentra_oma_candidate_generate"
    assert invoke[5]["idempotency_key"].startswith(
        _task().idempotency_key + ":remote-candidate:"
    )


def test_remote_candidate_rejects_target_base_mismatch(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    gateway = Gateway(_completed(tmp_path, digest="0" * 64))
    producer = RemoteCandidateProducer(
        gateway, principal="user", device_id="dev-1"
    )
    with pytest.raises(RuntimeError, match="REMOTE_BASE_CHANGED"):
        asyncio.run(
            producer.produce_candidate(
                _task(), context_summary="", workspace_path=tmp_path
            )
        )


def test_remote_candidate_uncertain_is_never_treated_as_retryable_success(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    gateway = Gateway({
        "state": "UNCERTAIN",
        "job_id": "job-1",
        "error": "agent lost after execution may have started",
    })
    producer = RemoteCandidateProducer(
        gateway, principal="user", device_id="dev-1"
    )
    with pytest.raises(RuntimeError, match="REMOTE_CANDIDATE_UNCERTAIN"):
        asyncio.run(
            producer.produce_candidate(
                _task(), context_summary="", workspace_path=tmp_path
            )
        )


def test_remote_candidate_rejects_task_correlation_mismatch(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    gateway = Gateway(_completed(tmp_path, task_id="OTHER"))
    producer = RemoteCandidateProducer(
        gateway, principal="user", device_id="dev-1"
    )
    with pytest.raises(RuntimeError, match="REMOTE_CANDIDATE_TASK_MISMATCH"):
        asyncio.run(
            producer.produce_candidate(
                _task(), context_summary="", workspace_path=tmp_path
            )
        )
