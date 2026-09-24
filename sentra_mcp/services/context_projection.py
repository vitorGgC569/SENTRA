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
        raw = f"{seat}|{task_id or 'global'}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"oma:{digest}"

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

        compiled = self.compiler.compile(
            pending,
            run_id=run_id,
            seat=seat,
            task_id=task_id,
            initial_seq=initial_seq,
            include=include,
            render=self._render_item,
        )
        return SharedContextBatch(
            text=compiled.text,
            last_seq=compiled.last_seq,
            count=compiled.count,
            consumer_id=consumer_id,
            epoch=compiled.epoch,
            estimated_tokens=compiled.estimated_tokens,
            truncated=compiled.truncated or more_pending,
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
                "project_id", "project_url", "model",
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
            project_id=safe_meta.get("project_id"),
            project_url=safe_meta.get("project_url"),
            task_id=task_id,
            metadata={"seat": seat, "source": "oma-fixed-conversation"},
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
