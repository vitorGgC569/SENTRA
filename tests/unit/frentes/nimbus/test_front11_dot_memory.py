"""Frente 11: Dot memory, plan, and context survive a new store and stay isolated."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from memory.dot_scope import DotScopedStore
from memory.protected_store import ProtectedMemoryStore
from orchestrator.memory import DotSessionMemory, MemoryManager
from orchestrator.models import Candidate
from orchestrator.program_memory import ProgramMemory


def _plan(objective: str, status: str = "active") -> dict:
    return {
        "objective": objective,
        "status": status,
        "steps": [{"id": "s1", "title": "first step", "status": "pending"}],
    }


def _context(summary: str, conversation_id: str) -> dict:
    return {
        "summary": summary,
        "variables": {"phase": summary},
        "conversation_ids": [conversation_id],
    }


def test_dot_store_survives_reopen_and_does_not_leak(tmp_path):
    store = DotScopedStore(tmp_path)
    plan = _plan("ship the alpha game")
    saved = store.put(
        "owner-a", dot_id="dot-alpha", kind="plan", key="current", body=plan,
        run_id="run-1", work_item_id="wi-1", operation_id="op-1",
    )
    store.put(
        "owner-a", dot_id="dot-bravo", kind="plan", key="current",
        body=_plan("bravo only", "draft"),
    )
    store.put(
        "owner-a", dot_id="dot-alpha", kind="context", key="current",
        body=_context("alpha context", "conv-alpha"),
    )
    store.put(
        "owner-a", dot_id="dot-alpha", kind="memory", key="note",
        body={"text": "alpha only"},
    )

    reloaded = DotScopedStore(tmp_path)
    got = reloaded.get("owner-a", dot_id="dot-alpha", kind="plan", key="current")
    assert got["body"] == plan
    assert got["revision"] == saved["revision"]
    assert got["run_id"] == "run-1"
    assert got["work_item_id"] == "wi-1"
    assert got["operation_id"] == "op-1"
    assert got["authorizes_effects"] is False
    assert reloaded.get("owner-a", dot_id="dot-alpha", kind="context", key="current")["body"]["summary"] == "alpha context"
    with pytest.raises(FileNotFoundError):
        reloaded.get("owner-a", dot_id="dot-bravo", kind="memory", key="note")
    with pytest.raises(FileNotFoundError):
        reloaded.get("owner-b", dot_id="dot-alpha", kind="plan", key="current")
    bravo = reloaded.get("owner-a", dot_id="dot-bravo", kind="plan", key="current")
    assert "alpha" not in json.dumps(bravo["body"])
    listed = json.dumps(reloaded.list_keys("owner-a", dot_id="dot-bravo", kind="memory"))
    assert "alpha only" not in listed
    assert reloaded.list_keys("owner-a", dot_id="dot-bravo", kind="memory")["total"] == 0


def test_dot_store_revision_and_rejected_ids(tmp_path):
    store = DotScopedStore(tmp_path)
    first = store.put(
        "owner-a", dot_id="dot-alpha", kind="memory", key="note", body={"text": "one"},
    )
    with pytest.raises(ValueError, match="revision"):
        store.put(
            "owner-a", dot_id="dot-alpha", kind="memory", key="note",
            body={"text": "two"}, expected_revision=0,
        )
    second = store.put(
        "owner-a", dot_id="dot-alpha", kind="memory", key="note",
        body={"text": "two"}, expected_revision=first["revision"],
    )
    assert second["revision"] == 2
    assert DotScopedStore(tmp_path).get(
        "owner-a", dot_id="dot-alpha", kind="memory", key="note",
    )["body"]["text"] == "two"
    with pytest.raises(ValueError):
        store.put("owner-a", dot_id="../dot-alpha", kind="memory", key="note", body={"text": "x"})
    with pytest.raises(ValueError):
        store.put(
            "owner-a", dot_id="dot-alpha", kind="plan", key="current",
            body={"objective": "x", "status": "active", "steps": [], "foreign": "dot-bravo"},
        )


def test_program_memory_is_scoped_per_dot(tmp_path):
    workspace = tmp_path / "ws"
    alpha = ProgramMemory(workspace, dot_id="dot-alpha")
    alpha.record_adr("Decisao do alpha", "motivo", {"run_id": "run-a", "task_id": "T-1"})
    alpha.record_lesson(
        "licao do alpha",
        "run-a ver orchestrator/memory.py:10",
    )
    bravo = ProgramMemory(workspace, dot_id="dot-bravo")
    assert bravo.list_adrs() == []
    assert bravo.list_lessons() == []
    assert bravo.recall("alpha") == []
    workspace_level = ProgramMemory(workspace)
    assert workspace_level.list_adrs() == []
    assert workspace_level.dot_id is None
    reloaded = ProgramMemory(workspace, dot_id="dot-alpha")
    assert [item["id"] for item in reloaded.list_adrs()] == ["ADR-0001"]
    assert reloaded.for_dot("dot-bravo").list_adrs() == []
    assert "dot-bravo" not in str(reloaded.memory_dir)
    with pytest.raises(ValueError):
        ProgramMemory(workspace, dot_id="..")
    with pytest.raises(ValueError):
        ProgramMemory(workspace, dot_id="dot/alpha")


def test_session_plan_and_context_survive_restart_without_leaking(tmp_path):
    root = tmp_path / "state"
    manager = MemoryManager("run-1", tmp_path / "runs-a")
    working = manager.get_working_memory("executor")
    working.add_message("user", "plano alpha")
    working.variables["step"] = "one"
    task = manager.get_task_memory("T-1")
    task.add_candidate(Candidate(candidate_id="c1", task_id="T-1", summary="alpha patch"))
    manager.record_run_insight("focus", "alpha")
    manager.semantic_cache.store(
        "build the alpha game",
        Candidate(candidate_id="cache-1", summary="alpha cache"),
    )
    session = DotSessionMemory(root, "owner-a", "dot-alpha")
    session.save_plan(
        _plan("ship the alpha game"),
        run_id="run-1", work_item_id="wi-1", operation_id="op-1",
    )
    session.save_context(
        _context("alpha context", "conv-alpha"),
        run_id="run-1", work_item_id="wi-1", operation_id="op-1",
    )
    saved = session.checkpoint(
        manager, run_id="run-1", work_item_id="wi-1", operation_id="op-1",
    )
    assert saved["authorizes_effects"] is False

    other = DotSessionMemory(root, "owner-a", "dot-bravo")
    other.save_plan(_plan("bravo only", "draft"))

    fresh = MemoryManager("run-2", tmp_path / "runs-b")
    loaded = DotSessionMemory(root, "owner-a", "dot-alpha")
    restored = loaded.restore(fresh)
    assert restored["authorizes_effects"] is False
    assert fresh.get_working_memory("executor").messages[0]["content"] == "plano alpha"
    assert fresh.get_working_memory("executor").variables["step"] == "one"
    assert fresh.get_task_memory("T-1").get_latest_candidate().summary == "alpha patch"
    assert fresh.get_run_insights()["focus"] == "alpha"
    hit = fresh.semantic_cache.lookup("build the alpha game")
    assert hit is not None and hit.candidate_id == "cache-1"
    assert loaded.load_plan()["body"]["objective"] == "ship the alpha game"
    assert loaded.load_context()["body"]["conversation_ids"] == ["conv-alpha"]

    bravo_manager = MemoryManager("run-9", tmp_path / "runs-c")
    with pytest.raises(FileNotFoundError):
        DotSessionMemory(root, "owner-a", "dot-bravo").restore(bravo_manager)
    assert bravo_manager.get_run_insights() == {}
    assert bravo_manager.get_working_memory("executor").messages == []
    assert "alpha" not in json.dumps(
        DotSessionMemory(root, "owner-a", "dot-bravo").load_plan()["body"]
    )


class _Request:
    work_item_id = "wi-shared"


class _Receipt:
    operation_id = "op-1"
    run_id = "run-1"


class _Context:
    request = _Request()
    receipt = _Receipt()


class _State:
    def __init__(self):
        self.rows = {}
        self.now = 1000.0

    def scoped(self, name):
        return self

    def clock(self):
        return self.now

    def put(self, key, value, expected_revision=None):
        current = 0 if key not in self.rows else self.rows[key]["revision"]
        if expected_revision is not None and expected_revision != current:
            raise ValueError("conflict")
        revision = current + 1
        self.rows[key] = {"value": value, "revision": revision}
        return revision

    def get(self, key):
        return self.rows.get(key)

    def records(self, prefix="", *, limit=10000):
        return [(key, value) for key, value in self.rows.items() if str(key).startswith(prefix)][:limit]

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            yield self

        return _tx()

    def delete(self, key, expected_revision=None):
        self.rows.pop(key, None)


def test_build_turn_memory_keeps_real_steps_and_long_objective_not_only_500_chars():
    from orchestrator.memory import build_turn_memory

    answer = "resultado " + ("etapa " * 120)
    assert len(answer) > 500
    memory = build_turn_memory(
        content=answer,
        conversation_id="conv-long-steps",
        journal=[{"seq": 1, "role": "user", "kind": "user_prompt", "content": "pedido real do turno"}],
        calls=[{"id": "call01", "kind": "tool", "operation": "WRITE", "state": "completed"}],
    )
    plan = memory["plan"]
    assert len(plan["objective"]) > 500
    assert plan["objective"] == answer.strip()
    titles = [step["title"] for step in plan["steps"]]
    assert "pedido real do turno" in titles
    assert "WRITE" in titles
    assert len(plan["steps"]) >= 2
    assert memory["context"]["summary"] == answer.strip()
    assert memory["provider_handoff"] is False


def test_turn_steps_survive_a_new_process_without_a_provider_handoff(tmp_path):
    from orchestrator.memory import LiveDotSession

    root = tmp_path / "state"
    root.mkdir()
    repo = Path(__file__).resolve().parents[4]
    answer = "resultado " + ("etapa " * 120)
    assert len(answer) > 500
    code = r"""
import json, sys
from orchestrator.memory import LiveDotSession, build_turn_memory
root, owner, dot, session_id = sys.argv[1:5]
answer = sys.argv[5]
memory = build_turn_memory(
    content=answer,
    conversation_id=session_id,
    journal=[{"seq": 1, "role": "user", "kind": "user_prompt", "content": "pedido real do turno"}],
    calls=[{"id": "callread01", "kind": "tool", "operation": "READ", "state": "completed"}],
)
assert memory["provider_handoff"] is False
assert "handoff" not in json.dumps(memory["plan"]).lower()
LiveDotSession(root, owner, dot, session_id).save_dot(
    plan=memory["plan"], context=memory["context"],
    run_id="run-live", work_item_id="wi-live", operation_id="op-live",
)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", code, str(root), "owner-a", "dot-alpha", "sess-live", answer],
        check=False, cwd=str(repo), env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    loaded = LiveDotSession.reopen(root, "owner-a", "dot-alpha", "sess-live").load_dot()
    plan = loaded["plan"]["body"]
    assert plan["objective"] == answer.strip()
    assert len(plan["objective"]) > 500
    titles = [step["title"] for step in plan["steps"]]
    assert "pedido real do turno" in titles
    assert "READ" in titles
    assert plan["steps"]
    assert "handoff" not in json.dumps(plan).lower()
    assert loaded["context"]["body"]["summary"] == answer.strip()
    assert loaded["context"]["body"]["conversation_ids"] == ["sess-live"]
    assert loaded["authorizes_effects"] is False


def test_live_session_survives_a_new_process(tmp_path):
    from orchestrator.memory import LiveDotSession

    root = tmp_path / "state"
    root.mkdir()
    repo = Path(__file__).resolve().parents[4]
    code = r"""
import sys
from orchestrator.memory import LiveDotSession, MemoryManager
from orchestrator.models import Candidate
root, owner, dot, session_id = sys.argv[1:5]
manager = MemoryManager("run-live", root + "/runs")
manager.get_working_memory("executor").add_message("user", "plano vivo")
manager.record_run_insight("focus", "alpha")
manager.get_task_memory("T-1").add_candidate(
    Candidate(candidate_id="c-live", task_id="T-1", summary="vivo")
)
session = LiveDotSession(root, owner, dot, session_id)
session.save(
    manager,
    {"objective": "plano vivo", "status": "active", "steps": [
        {"id": "s1", "title": "persistir", "status": "active"}
    ]},
    {"summary": "contexto vivo", "variables": {"phase": "live"}, "conversation_ids": ["conv-live"]},
    run_id="run-live", work_item_id="wi-live", operation_id="op-live",
)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", code, str(root), "owner-a", "dot-alpha", "sess-live"],
        check=False, cwd=str(repo), env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    restored = MemoryManager("run-after", tmp_path / "runs-after")
    loaded = LiveDotSession.reopen(root, "owner-a", "dot-alpha", "sess-live").load(restored)
    assert loaded["plan"]["body"]["objective"] == "plano vivo"
    assert loaded["context"]["body"]["conversation_ids"] == ["conv-live"]
    assert restored.get_working_memory("executor").messages[0]["content"] == "plano vivo"
    assert restored.get_run_insights()["focus"] == "alpha"
    assert restored.get_task_memory("T-1").get_latest_candidate().summary == "vivo"
    other = MemoryManager("run-other", tmp_path / "runs-other")
    with pytest.raises(FileNotFoundError):
        LiveDotSession.reopen(root, "owner-a", "dot-bravo", "sess-live").load(other)
    assert other.get_run_insights() == {}
    with pytest.raises(ValueError, match="session id"):
        LiveDotSession.reopen(root, "owner-a", "dot-alpha", "sess-other").load(restored)


def test_protected_memory_isolates_dots_that_share_a_work_item():
    store = ProtectedMemoryStore(_State())
    context = _Context()
    store.put(
        namespace="notes", key="plan", body={"text": "alpha"},
        expected_revision=None, context=context, dot_id="dot-alpha",
    )
    store.put(
        namespace="notes", key="plan", body={"text": "bravo"},
        expected_revision=None, context=context, dot_id="dot-bravo",
    )
    alpha = store.list(namespace="notes", context=context, dot_id="dot-alpha")
    assert alpha["total"] == 1
    assert alpha["authorizes_effects"] is False
    assert alpha["items"][0]["body"]["text"] == "alpha"
    assert store.get(
        namespace="notes", key="plan", context=context, dot_id="dot-bravo",
    )["body"]["text"] == "bravo"
    assert store.list(namespace="notes", context=context)["total"] == 0
    with pytest.raises(ValueError):
        store.put(
            namespace="notes", key="plan", body={"text": "nope"},
            expected_revision=None, context=context, dot_id="../dot",
        )


def test_protected_memory_without_dot_keeps_the_work_item_key():
    store = ProtectedMemoryStore(_State())
    context = _Context()
    store.put(
        namespace="notes", key="plan", body={"text": "shared-work"},
        expected_revision=None, context=context,
    )
    listed = store.list(namespace="notes", context=context)
    assert listed["total"] == 1
    assert listed["items"][0]["body"]["text"] == "shared-work"
    assert "dot_id" not in listed["items"][0]
