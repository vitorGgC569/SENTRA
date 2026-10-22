from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .models import Candidate, Task


@dataclass
class WorkingMemory:
    """Immediate turn-level context for an active agent."""
    messages: List[Dict[str, str]] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def clear(self) -> None:
        self.messages.clear()
        self.variables.clear()


@dataclass
class TaskMemory:
    """History and intermediate candidate versions for a specific subtask."""
    task_id: str
    candidates: List[Candidate] = field(default_factory=list)
    findings_history: List[Dict[str, Any]] = field(default_factory=list)
    iterations: int = 0

    def add_candidate(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)
        self.iterations += 1

    def get_latest_candidate(self) -> Optional[Candidate]:
        return self.candidates[-1] if self.candidates else None


class ArtifactStore:
    """
    Stores bulky artifacts (code diffs, test logs, full file snapshots) on disk
    and provides lightweight IDs/URIs for agent context as specified in Section 42.
    """

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_artifact(self, artifact_type: str, content: str, extension: str = "txt") -> str:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        filename = f"{artifact_type}_{content_hash}.{extension}"
        filepath = self.storage_dir / filename
        filepath.write_text(content, encoding="utf-8", errors="replace")
        return str(filepath.resolve())

    def retrieve_artifact(self, filepath: str) -> str:
        p = Path(filepath)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        return ""


class SemanticCache:
    """Reusable candidate cache (Sections 43-44).

    HONESTY NOTE: this is a lexical near-duplicate cache (normalized hash +
    Jaccard overlap), NOT an embedding vector DB. Paraphrases with low lexical
    overlap are NOT matched. Threshold is conservative to avoid false-positive
    reuse; reused entries must still pass deterministic revalidation.
    """

    def __init__(self, similarity_threshold: float = 0.9):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._token_sets: Dict[str, Set[str]] = {}
        self.similarity_threshold = similarity_threshold

    def _normalize(self, objective: str) -> str:
        norm = re.sub(r"[^\w\s]", "", objective.lower())
        return " ".join(norm.split())

    def _hash_objective(self, objective: str) -> str:
        return hashlib.sha256(self._normalize(objective).encode("utf-8")).hexdigest()

    @staticmethod
    def _jaccard(a: Set[str], b: Set[str]) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def store(self, objective: str, candidate: Candidate) -> None:
        key = self._hash_objective(objective)
        self._cache[key] = {
            "candidate": candidate.to_dict(),
            "timestamp": time.time(),
            "objective": objective,
        }
        self._token_sets[key] = set(self._normalize(objective).split())

    def lookup(self, objective: str) -> Optional[Candidate]:
        key = self._hash_objective(objective)
        entry = self._cache.get(key)
        if entry:
            return Candidate.from_dict(entry["candidate"])
        # Near-duplicate fallback (conservative).
        cand_tokens = set(self._normalize(objective).split())
        best_key, best_sim = None, 0.0
        for k, toks in self._token_sets.items():
            sim = self._jaccard(cand_tokens, toks)
            if sim > best_sim:
                best_sim, best_key = sim, k
        if best_key is not None and best_sim >= self.similarity_threshold:
            return Candidate.from_dict(self._cache[best_key]["candidate"])
        return None

    def export_entries(self) -> List[Dict[str, Any]]:
        rows = []
        for entry in self._cache.values():
            rows.append({
                "objective": entry.get("objective", ""),
                "candidate": dict(entry.get("candidate") or {}),
            })
        rows.sort(key=lambda row: (
            str(row["objective"]),
            str((row["candidate"] or {}).get("candidate_id", "")),
        ))
        return rows

    def load_entries(self, rows: List[Dict[str, Any]]) -> None:
        if not isinstance(rows, list):
            raise ValueError("semantic cache rows must be a list")
        self._cache.clear()
        self._token_sets.clear()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("semantic cache row must be an object")
            objective = row.get("objective")
            if not isinstance(objective, str) or not objective.strip():
                raise ValueError("semantic cache objective is required")
            self.store(objective, Candidate.from_dict(row.get("candidate") or {}))


class MemoryManager:
    """
    Central Memory Architecture coordinating Working, Task, Run, and Long-Term Memory.
    """

    def __init__(self, run_id: str, storage_root: Path):
        self.run_id = run_id
        self.storage_root = Path(storage_root) / "memory" / run_id
        self.storage_root.mkdir(parents=True, exist_ok=True)

        self.working_memories: Dict[str, WorkingMemory] = {}
        self.task_memories: Dict[str, TaskMemory] = {}
        self.artifact_store = ArtifactStore(self.storage_root / "artifacts")
        self.semantic_cache = SemanticCache()
        self.run_knowledge: Dict[str, Any] = {}

    def get_working_memory(self, agent_id: str) -> WorkingMemory:
        if agent_id not in self.working_memories:
            self.working_memories[agent_id] = WorkingMemory()
        return self.working_memories[agent_id]

    def get_task_memory(self, task_id: str) -> TaskMemory:
        if task_id not in self.task_memories:
            self.task_memories[task_id] = TaskMemory(task_id=task_id)
        return self.task_memories[task_id]

    def record_run_insight(self, key: str, value: Any) -> None:
        self.run_knowledge[key] = value

    def get_run_insights(self) -> Dict[str, Any]:
        return dict(self.run_knowledge)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def _json_copy(value: Any, *, what: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} is not JSON-serializable") from exc


def _session_body(manager: MemoryManager) -> Dict[str, Any]:
    """Bounded snapshot of one run's working state. Bulky patches stay out."""
    working: Dict[str, Any] = {}
    for agent_id in sorted(manager.working_memories):
        mem = manager.working_memories[agent_id]
        messages = []
        for message in mem.messages[-20:]:
            messages.append({
                "role": _clip(str(message.get("role", "")), 40),
                "content": _clip(str(message.get("content", "")), 1000),
            })
        variables = {}
        for key, value in mem.variables.items():
            copied = _json_copy(value, what="working variable")
            if len(json.dumps(copied, ensure_ascii=False)) > 500:
                raise ValueError("working variable exceeds 500 chars")
            variables[str(key)[:80]] = copied
        working[str(agent_id)] = {"messages": messages, "variables": variables}
    tasks: Dict[str, Any] = {}
    for task_id in sorted(manager.task_memories):
        task_mem = manager.task_memories[task_id]
        candidates = []
        for candidate in task_mem.candidates[-10:]:
            data = candidate.to_dict()
            candidates.append({
                "candidate_id": data.get("candidate_id"),
                "task_id": data.get("task_id"),
                "version": data.get("version"),
                "summary": _clip(str(data.get("summary") or ""), 500),
                "status": data.get("status"),
                "created_by": data.get("created_by"),
            })
        findings = []
        for item in task_mem.findings_history[-20:]:
            encoded = json.dumps(_json_copy(item, what="finding"), ensure_ascii=False)
            if len(encoded) > 1000:
                raise ValueError("finding exceeds 1000 chars")
            findings.append(json.loads(encoded))
        tasks[str(task_id)] = {
            "iterations": task_mem.iterations,
            "candidates": candidates,
            "findings_history": findings,
        }
    cache_rows = []
    for row in manager.semantic_cache.export_entries()[-20:]:
        cached_candidate = row.get("candidate") or {}
        cache_rows.append({
            "objective": _clip(str(row.get("objective") or ""), 500),
            "candidate": {
                "candidate_id": cached_candidate.get("candidate_id"),
                "task_id": cached_candidate.get("task_id"),
                "summary": _clip(str(cached_candidate.get("summary") or ""), 500),
                "status": cached_candidate.get("status", "CREATED"),
            },
        })
    return {
        "source_run_id": manager.run_id,
        "working": working,
        "tasks": tasks,
        "run_knowledge": _json_copy(manager.run_knowledge, what="run knowledge"),
        "semantic_cache": cache_rows,
    }


_STEP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_TURN_CALL_STATUS = {
    "completed": "done",
    "received": "done",
    "started": "active",
    "submitted": "active",
    "uncertain": "blocked",
    "not_executed": "pending",
    "rejected": "blocked",
}


def _bounded_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _turn_title(value: str) -> str:
    return _bounded_text(" ".join(value.split()), 400)


def build_turn_memory(
    *,
    content: str,
    conversation_id: str,
    journal: Optional[List[Dict[str, Any]]] = None,
    calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Plan and context from the turn that was actually recorded.

    Objective and summary keep the answer up to the store limit. Steps are
    the journal messages and calls of this turn. A provider handoff is not
    added unless that journal already names one.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("turn content required")
    if not isinstance(conversation_id, str) or not _STEP_ID.fullmatch(conversation_id):
        raise ValueError("invalid conversation_id")
    objective = _bounded_text(content, 4000)
    steps: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def add(step_id: Any, title: Any, status: str) -> None:
        if len(steps) >= 100 or not isinstance(title, str):
            return
        if not isinstance(step_id, str) or not _STEP_ID.fullmatch(step_id) or step_id in seen:
            return
        cleaned = _turn_title(title)
        if not cleaned or status not in {"pending", "active", "blocked", "done"}:
            return
        seen.add(step_id)
        steps.append({"id": step_id, "title": cleaned, "status": status})

    for entry in journal or []:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind") if isinstance(entry.get("kind"), str) else "message"
        seq = entry.get("seq")
        step_id = f"m{seq}" if isinstance(seq, int) and seq >= 0 else None
        text = str(entry.get("content")) if isinstance(entry.get("content"), str) else ""
        if kind == "handoff" and not text.strip():
            text = "handoff"
        add(step_id, text, "blocked" if kind == "provider_error" else "done")
    for index, call in enumerate(calls or []):
        if not isinstance(call, dict):
            continue
        operation = str(call.get("operation")) if isinstance(call.get("operation"), str) else ""
        kind = call.get("kind") if isinstance(call.get("kind"), str) else "call"
        title = operation.strip() or kind
        raw_id = call.get("id")
        step_id = raw_id if isinstance(raw_id, str) and _STEP_ID.fullmatch(raw_id) else f"c{index}"
        add(step_id, title, _TURN_CALL_STATUS.get(str(call.get("state")), "blocked"))
    if not steps:
        add("answer", objective, "done")
    return {
        "plan": {"objective": objective, "status": "active", "steps": steps},
        "context": {
            "summary": objective,
            "variables": {},
            "conversation_ids": [conversation_id],
        },
        "provider_handoff": False,
    }


def _apply_session(manager: MemoryManager, body: Dict[str, Any]) -> None:
    if not isinstance(body, dict):
        raise ValueError("session body must be an object")
    manager.working_memories.clear()
    for agent_id, raw in (body.get("working") or {}).items():
        if not isinstance(raw, dict):
            raise ValueError("working memory entry must be an object")
        mem = manager.get_working_memory(str(agent_id))
        for message in raw.get("messages") or []:
            mem.add_message(str(message.get("role", "user")), str(message.get("content", "")))
        variables = raw.get("variables") or {}
        if not isinstance(variables, dict):
            raise ValueError("working variables must be an object")
        mem.variables.update(variables)
    manager.task_memories.clear()
    for task_id, raw in (body.get("tasks") or {}).items():
        if not isinstance(raw, dict):
            raise ValueError("task memory entry must be an object")
        task_mem = manager.get_task_memory(str(task_id))
        task_mem.iterations = 0
        for candidate in raw.get("candidates") or []:
            task_mem.add_candidate(Candidate.from_dict(candidate))
        stored = raw.get("iterations")
        if type(stored) is int and stored >= 0:
            task_mem.iterations = stored
        task_mem.findings_history = list(raw.get("findings_history") or [])
    knowledge = body.get("run_knowledge") or {}
    if not isinstance(knowledge, dict):
        raise ValueError("run knowledge must be an object")
    manager.run_knowledge.clear()
    manager.run_knowledge.update(knowledge)
    manager.semantic_cache.load_entries(body.get("semantic_cache") or [])


class DotSessionMemory:
    """Plan, context, and session snapshot for one Dot.

    A new ``DotSessionMemory`` on the same root reloads the rows. Reads are
    scoped to ``owner`` and ``dot_id``. Nothing returned here authorizes an
    effect, a Grant, or a send.
    """

    def __init__(self, root: Path | str, owner: str, dot_id: str):
        from memory.dot_scope import DotScopedStore

        self.store = DotScopedStore(root)
        self.owner = owner
        self.dot_id = dot_id

    def _put(self, kind: str, key: str, body: Dict[str, Any], *, expected_revision: Optional[int],
             run_id: Optional[str], work_item_id: Optional[str], operation_id: Optional[str]) -> Dict[str, Any]:
        return self.store.put(
            self.owner,
            dot_id=self.dot_id,
            kind=kind,
            key=key,
            body=body,
            expected_revision=expected_revision,
            run_id=run_id,
            work_item_id=work_item_id,
            operation_id=operation_id,
        )

    def save_plan(self, plan: Dict[str, Any], *, expected_revision: Optional[int] = None,
                  run_id: Optional[str] = None, work_item_id: Optional[str] = None,
                  operation_id: Optional[str] = None) -> Dict[str, Any]:
        return self._put("plan", "current", plan, expected_revision=expected_revision,
                         run_id=run_id, work_item_id=work_item_id, operation_id=operation_id)

    def load_plan(self) -> Dict[str, Any]:
        return self.store.get(self.owner, dot_id=self.dot_id, kind="plan", key="current")

    def save_context(self, context: Dict[str, Any], *, expected_revision: Optional[int] = None,
                     run_id: Optional[str] = None, work_item_id: Optional[str] = None,
                     operation_id: Optional[str] = None) -> Dict[str, Any]:
        return self._put("context", "current", context, expected_revision=expected_revision,
                         run_id=run_id, work_item_id=work_item_id, operation_id=operation_id)

    def load_context(self) -> Dict[str, Any]:
        return self.store.get(self.owner, dot_id=self.dot_id, kind="context", key="current")

    def remember(self, key: str, body: Dict[str, Any], *, expected_revision: Optional[int] = None,
                 run_id: Optional[str] = None, work_item_id: Optional[str] = None,
                 operation_id: Optional[str] = None) -> Dict[str, Any]:
        return self._put("memory", key, body, expected_revision=expected_revision,
                         run_id=run_id, work_item_id=work_item_id, operation_id=operation_id)

    def recall(self, key: str) -> Dict[str, Any]:
        return self.store.get(self.owner, dot_id=self.dot_id, kind="memory", key=key)

    def checkpoint(self, manager: MemoryManager, *, expected_revision: Optional[int] = None,
                   run_id: Optional[str] = None, work_item_id: Optional[str] = None,
                   operation_id: Optional[str] = None) -> Dict[str, Any]:
        return self.remember(
            "session",
            _session_body(manager),
            expected_revision=expected_revision,
            run_id=run_id,
            work_item_id=work_item_id,
            operation_id=operation_id,
        )

    def restore(self, manager: MemoryManager) -> Dict[str, Any]:
        row = self.recall("session")
        _apply_session(manager, row["body"])
        row["authorizes_effects"] = False
        return row


class LiveDotSession:
    """Load and save one Dot's plan, context, and working session.

    ``reopen`` is a new object on the same directory. The previous process
    does not need to stay alive. A session id from another Dot is refused.
    """

    def __init__(self, root: Path | str, owner: str, dot_id: str, session_id: str):
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
            raise ValueError("invalid session_id")
        self.memory = DotSessionMemory(root, owner, dot_id)
        self.owner = owner
        self.dot_id = dot_id
        self.session_id = session_id

    @classmethod
    def reopen(cls, root: Path | str, owner: str, dot_id: str, session_id: str) -> "LiveDotSession":
        return cls(root, owner, dot_id, session_id)

    def save_dot(
        self,
        *,
        plan: Dict[str, Any],
        context: Dict[str, Any],
        run_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        manager: Optional[MemoryManager] = None,
    ) -> Dict[str, Any]:
        """Shell call site. Plan and context are enough; the manager is optional."""
        plan_row = self.memory.save_plan(
            plan, run_id=run_id, work_item_id=work_item_id, operation_id=operation_id,
        )
        context_row = self.memory.save_context(
            context, run_id=run_id, work_item_id=work_item_id, operation_id=operation_id,
        )
        session_revision = None
        if manager is not None:
            session_revision = self.memory.checkpoint(
                manager, run_id=run_id, work_item_id=work_item_id, operation_id=operation_id,
            )["revision"]
        index = self.memory.remember(
            "live-session",
            {
                "session_id": self.session_id,
                "dot_id": self.dot_id,
                "owner": self.owner,
            },
            run_id=run_id, work_item_id=work_item_id, operation_id=operation_id,
        )
        return {
            "session_id": self.session_id,
            "dot_id": self.dot_id,
            "owner": self.owner,
            "plan_revision": plan_row["revision"],
            "context_revision": context_row["revision"],
            "session_revision": session_revision,
            "index_revision": index["revision"],
            "authorizes_effects": False,
        }

    def save(
        self,
        manager: MemoryManager,
        plan: Dict[str, Any],
        context: Dict[str, Any],
        *,
        run_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.save_dot(
            plan=plan, context=context, manager=manager,
            run_id=run_id, work_item_id=work_item_id, operation_id=operation_id,
        )

    def load_dot(self, manager: Optional[MemoryManager] = None) -> Dict[str, Any]:
        index = self.memory.recall("live-session")
        body = index["body"]
        if body.get("dot_id") != self.dot_id or body.get("owner") != self.owner:
            raise ValueError("live session belongs to another dot")
        if body.get("session_id") != self.session_id:
            raise ValueError("live session id does not match")
        if manager is not None:
            self.memory.restore(manager)
        return {
            "session_id": self.session_id,
            "plan": self.memory.load_plan(),
            "context": self.memory.load_context(),
            "authorizes_effects": False,
        }

    def load(self, manager: MemoryManager) -> Dict[str, Any]:
        return self.load_dot(manager)
