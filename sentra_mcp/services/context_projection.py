"""Projection from SENTRA Control Plane context into OMA conversation seats."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from orchestrator.shared_context import SharedContextBatch

from .control_plane import ControlPlaneService


_KNOWLEDGE_TYPES = [
    "FACT", "HYPOTHESIS", "DECISION", "OBJECTION",
    "RESULT", "FAILURE", "ARTIFACT", "QUESTION",
    "CLAIM", "CHALLENGE", "CLAIM_RESOLUTION", "MESSAGE",
]


class ContextCompiler:
    """Compile ordered Context Bus knowledge into one bounded semantic epoch.

    The compiler never changes Run/Task authority and never performs protocol
    compaction. Cursor safety is strict: once a relevant event cannot fit, no
    later event may be considered consumed.
    """

    def __init__(self, *, max_chars: int, max_items: int) -> None:
        self.max_chars = max(1000, min(int(max_chars), 50000))
        self.max_items = max(1, min(int(max_items), 200))

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return (len(text or "") + 3) // 4

    def compile(
        self,
        items: list[dict[str, Any]],
        *,
        run_id: str,
        seat: str,
        task_id: str | None,
        initial_seq: int,
        include,
        render,
    ) -> SharedContextBatch:
        lines: list[str] = []
        consumed_seq = int(initial_seq)
        truncated = False
        for item in items:
            seq = int(item.get("seq") or consumed_seq)
            if not include(item):
                consumed_seq = max(consumed_seq, seq)
                continue
            if len(lines) >= self.max_items:
                truncated = True
                break
            line = render(item)
            prospective = line if not lines else "\n".join([*lines, line])
            if len(prospective) > self.max_chars:
                truncated = True
                break
            lines.append(line)
            consumed_seq = max(consumed_seq, seq)
        text = "\n".join(lines)
        digest = hashlib.sha256(
            ("|".join([
                str(run_id), str(seat), str(task_id or ""),
                str(consumed_seq), hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ])).encode("utf-8")
        ).hexdigest()[:24]
        return SharedContextBatch(
            text=text,
            last_seq=consumed_seq,
            count=len(lines),
            epoch="ctx-" + digest,
            estimated_tokens=self.estimate_tokens(text),
            truncated=truncated,
        )


class ControlPlaneContextBridge:
    """Bounded task-specific projection; never mutates authoritative run state."""

    def __init__(
        self,
        control_plane: ControlPlaneService,
        owner: str,
        *,
        max_chars: int = 12000,
        max_items: int = 80,
    ) -> None:
        self.control_plane = control_plane
        self.owner = str(owner)
        self.max_chars = max(1000, min(int(max_chars), 50000))
        self.max_items = max(1, min(int(max_items), 200))
        self.compiler = ContextCompiler(
            max_chars=self.max_chars,
            max_items=self.max_items,
        )

    @staticmethod
    def _agent_id(seat: str) -> str:
        digest = hashlib.sha256(str(seat).encode("utf-8")).hexdigest()[:24]
        return f"agent-oma-{digest}"

    @staticmethod
    def _chat_id(seat: str) -> str:
        digest = hashlib.sha256(str(seat).encode("utf-8")).hexdigest()[:24]
        return f"chat-oma-{digest}"

    @staticmethod
    def _consumer_id(seat: str, task_id: str | None) -> str:
        # Consumer progress belongs to the persistent logical Agent/seat.
        # task_id changes every round; including it would replay old Context Bus
        # history and eventually strand recent messages behind historical backlog.
        del task_id
        digest = hashlib.sha256(str(seat).encode("utf-8")).hexdigest()[:24]
        return f"oma:{digest}"

    @staticmethod
    def _render_goal(item: dict[str, Any]) -> str:
        payload = {
            "authority": "control_plane_goal",
            "goal_id": item.get("goal_id"),
            "parent_goal_id": item.get("parent_goal_id"),
            "state": item.get("state"),
            "priority": item.get("priority"),
            "objective": str(item.get("objective") or "")[:5000],
            "acceptance_criteria": list(item.get("acceptance_criteria") or [])[:30],
            "constraints": list(item.get("constraints") or [])[:30],
            "budget": item.get("budget") or {},
            "deadline": item.get("deadline"),
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return text[:7000] + ("...[goal truncated]" if len(text) > 7000 else "")

    @staticmethod
    def _render_item(item: dict[str, Any]) -> str:
        payload = {
            "event_id": item.get("event_id"),
            "seq": item.get("seq"),
            "type": item.get("type"),
            "subject": item.get("subject"),
            "task_id": item.get("task_id"),
            "agent_id": item.get("agent_id"),
            "payload": item.get("payload"),
            "evidence": item.get("evidence"),
            "confidence": item.get("confidence"),
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(text) > 1800:
            text = text[:1760] + "...[item truncated]"
        return text

    @staticmethod
    def _rehydration_memory(content: str, *, role: str, task_id: str | None) -> dict[str, Any]:
        import re
        text = str(content or "").strip()
        sections: dict[str, str] = {}
        heading = re.compile(
            r"(?im)^\s*(CONFIRMED|REJECTED|NEEDS_TEST|IMPLEMENTATION|QUALITY_GATE|ANSWERS)\s*:?[ \t]*$"
        )
        matches = list(heading.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            value = " ".join(text[match.end():end].strip().split())
            if value:
                sections[match.group(1).upper()] = value[:1200]
        questions = [
            " ".join(line.strip().split())[:800]
            for line in text.splitlines()
            if line.strip().startswith("Q->")
        ][:8]
        return {
            "role": str(role),
            "last_task_id": task_id,
            "last_response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "last_response_excerpt": text[:4000],
            "sections": sections,
            "open_peer_questions": questions,
        }

    @staticmethod
    def _render_memory(memory: Any) -> str:
        if not isinstance(memory, dict) or not memory:
            return ""
        payload = {
            key: memory.get(key)
            for key in (
                "role", "last_task_id", "last_response_sha256",
                "sections", "open_peer_questions", "last_response_excerpt",
            )
            if memory.get(key)
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(text) > 5000:
            text = text[:4970] + "...[memory truncated]"
        return "[AGENT_REHYDRATION_MEMORY] " + text

    def prepare(
        self, *, run_id: str, role: str, task_id: str | None, seat: str
    ) -> SharedContextBatch:
        consumer_id = self._consumer_id(seat, task_id)
        agent_id = self._agent_id(seat)
        self.control_plane.ensure_agent(
            run_id,
            self.owner,
            agent_id=agent_id,
            role=role,
            task_id=task_id,
            metadata={"seat": seat, "source": "oma-fixed-conversation"},
        )
        snapshot = self.control_plane.durable.run_status(run_id, self.owner)
        agent_record = next(
            (item for item in snapshot.get("agents", []) if item.get("agent_id") == agent_id),
            None,
        )
        memory_text = self._render_memory(
            ((agent_record or {}).get("metadata") or {}).get("rehydration_memory")
        )
        skill_projection = self.control_plane.agent_skills(
            run_id,
            self.owner,
            agent_id=agent_id,
            max_chars=min(5000, max(1000, self.max_chars // 3)),
        )
        skill_text = str(skill_projection.get("text") or "")
        goal_items = self.control_plane.list_goals(
            run_id, self.owner, states=["ACTIVE", "BLOCKED"]
        ).get("items", [])
        goal_budget = min(
            6000,
            self.max_chars // 2,
            max(0, self.max_chars - 1000),
        )
        goal_lines: list[str] = []
        goals_truncated = False
        for item in goal_items[:8]:
            line = self._render_goal(item)
            candidate = line if not goal_lines else "\n".join([*goal_lines, line])
            if len(candidate) <= goal_budget:
                goal_lines.append(line)
                continue
            if not goal_lines and goal_budget > 32:
                goal_lines.append(line[: goal_budget - 24] + "...[goal truncated]")
            goals_truncated = True
            break
        if len(goal_items) > len(goal_lines):
            goals_truncated = True
        goal_text = "\n".join(goal_lines)
        prefix_parts = [part for part in (goal_text, skill_text, memory_text) if part]
        prefix_text = "\n".join(prefix_parts)
        if len(prefix_text) > self.max_chars - 1000:
            prefix_text = (
                prefix_text[: max(0, self.max_chars - 1030)]
                + "...[prefix truncated]"
            )

        pending: list[dict[str, Any]] = []
        after_seq: int | None = None
        initial_seq = 0
        more_pending = False

        for page in range(3):
            delta = self.control_plane.read_context(
                run_id,
                self.owner,
                consumer_id=consumer_id,
                after_seq=after_seq,
                types=_KNOWLEDGE_TYPES,
                limit=200,
            )
            if page == 0:
                initial_seq = int(delta.get("after_seq") or 0)
            items = list(delta.get("items") or [])
            pending.extend(items)
            if len(items) < 200:
                more_pending = False
                break
            next_seq = int(delta.get("last_seq") or 0)
            if next_seq <= int(after_seq or initial_seq):
                break
            after_seq = next_seq
            more_pending = page == 2

        def include(item: dict[str, Any]) -> bool:
            if item.get("type") == "MESSAGE":
                recipient = (item.get("payload") or {}).get("to_agent_id")
                return recipient in {agent_id, "*"}
            return item.get("task_id") in {None, task_id}

        separator_chars = 1 if prefix_text else 0
        context_budget = max(1000, self.max_chars - len(prefix_text) - separator_chars)
        context_compiler = ContextCompiler(
            max_chars=context_budget,
            max_items=self.max_items,
        )
        compiled = context_compiler.compile(
            pending,
            run_id=run_id,
            seat=seat,
            task_id=task_id,
            initial_seq=initial_seq,
            include=include,
            render=self._render_item,
        )
        combined = prefix_text
        if compiled.text:
            combined = compiled.text if not combined else combined + "\n" + compiled.text
        epoch = "ctx-" + hashlib.sha256(
            (compiled.epoch + "|" + combined).encode("utf-8")
        ).hexdigest()[:24]
        return SharedContextBatch(
            text=combined,
            last_seq=compiled.last_seq,
            count=(
                compiled.count
                + len(goal_lines)
                + len(skill_projection.get("items") or [])
                + (1 if memory_text else 0)
            ),
            consumer_id=consumer_id,
            epoch=epoch,
            estimated_tokens=context_compiler.estimate_tokens(combined),
            truncated=(
                goals_truncated
                or bool(skill_projection.get("truncated"))
                or compiled.truncated
                or more_pending
            ),
        )

    def acknowledge(
        self, *, run_id: str, role: str, task_id: str | None, seat: str,
        consumer_id: str, last_seq: int
    ) -> None:
        if int(last_seq) <= 0:
            return
        self.control_plane.acknowledge(
            run_id,
            self.owner,
            consumer_id,
            int(last_seq),
        )

    def publish_response(
        self, *, run_id: str, role: str, task_id: str | None, seat: str,
        content: str, metadata: dict[str, Any], request_sha256: str
    ) -> None:
        text = str(content or "")
        if len(text) > 20000:
            text = text[:19950] + "\n[response truncated]"
        stable = "|".join([
            str(run_id), str(seat), str(task_id or ""),
            str(request_sha256 or ""), hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ])
        key = "oma-response-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:40]
        safe_meta = {
            key_name: metadata.get(key_name)
            for key_name in (
                "conversation_id", "conversation_url", "worker",
                "project_id", "project_url", "model", "provider", "web_model",
            )
            if metadata.get(key_name) is not None
        }
        agent_id = self._agent_id(seat)
        self.control_plane.bind_agent_chat(
            run_id,
            self.owner,
            agent_id=agent_id,
            chat_id=self._chat_id(seat),
            role=role,
            conversation_id=safe_meta.get("conversation_id"),
            conversation_url=safe_meta.get("conversation_url"),
            provider=safe_meta.get("provider"),
            project_id=safe_meta.get("project_id"),
            project_url=safe_meta.get("project_url"),
            task_id=task_id,
            metadata={
                "seat": seat,
                "source": "oma-fixed-conversation",
                **{
                    key_name: safe_meta[key_name]
                    for key_name in ("provider", "web_model", "model", "worker")
                    if key_name in safe_meta
                },
            },
        )
        self.control_plane.durable.update_agent(
            agent_id,
            self.owner,
            task_id=task_id,
            metadata={
                "rehydration_memory": self._rehydration_memory(
                    text, role=role, task_id=task_id
                )
            },
            event_type="AGENT_MEMORY_UPDATED",
        )
        self.control_plane.publish_context(
            run_id,
            self.owner,
            event_type="RESULT",
            subject=f"oma.response.{role}.{task_id or 'global'}",
            payload={
                "role": role,
                "seat": seat,
                "task_id": task_id,
                "text": text,
                "response_meta": safe_meta,
                "request_sha256": request_sha256,
            },
            evidence=[],
            confidence=None,
            supersedes=[],
            task_id=task_id,
            agent_id=agent_id,
            idempotency_key=key,
        )
