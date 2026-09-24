"""Bridge contract between the OMA conversation pool and shared context.

The bridge carries knowledge only. It has no methods for changing task/run state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SharedContextBatch:
    text: str = ""
    last_seq: int = 0
    count: int = 0
    consumer_id: str = ""
    epoch: str = ""
    estimated_tokens: int = 0
    truncated: bool = False


class SharedContextBridge(Protocol):
    def prepare(
        self, *, run_id: str, role: str, task_id: str | None, seat: str
    ) -> SharedContextBatch: ...

    def acknowledge(
        self, *, run_id: str, role: str, task_id: str | None, seat: str,
        consumer_id: str, last_seq: int
    ) -> None: ...

    def publish_response(
        self, *, run_id: str, role: str, task_id: str | None, seat: str,
        content: str, metadata: dict[str, Any], request_sha256: str
    ) -> None: ...


class NullSharedContextBridge:
    def prepare(self, **kwargs) -> SharedContextBatch:
        return SharedContextBatch()

    def acknowledge(self, **kwargs) -> None:
        return None

    def publish_response(self, **kwargs) -> None:
        return None



class ContextBusSharedContextBridge:
    """Bounded adapter from the durable Context Bus to fixed chat seats.

    Knowledge delivery is cursor-based and non-authoritative. The bridge cannot
    change Task/Run state; it can only read/ack context and publish responses.
    """

    def __init__(
        self,
        bus: Any,
        *,
        owner: str,
        max_events: int = 48,
        max_chars: int = 10000,
    ) -> None:
        self.bus = bus
        self.owner = str(owner or "").strip()
        if not self.owner:
            raise ValueError("shared context bridge owner is required")
        self.max_events = max(1, min(int(max_events), 200))
        self.max_chars = max(1000, min(int(max_chars), 12000))

    @staticmethod
    def _consumer_id(run_id: str, role: str, task_id: str | None, seat: str) -> str:
        import hashlib
        raw = "|".join([
            str(run_id or ""),
            str(seat or ""),
            str(role or ""),
            str(task_id or ""),
        ])
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
        return f"oma:{str(seat or role or 'agent')[:48]}:{digest}"

    @staticmethod
    def _compact_payload(payload: Any, maximum: int = 1200) -> str:
        import json
        try:
            text = json.dumps(
                payload if payload is not None else {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            text = repr(payload)
        text = " ".join(str(text).split())
        if len(text) > maximum:
            return text[: maximum - 18] + "...[truncated]"
        return text

    def _format_event(self, item: dict[str, Any]) -> str:
        event_type = str(item.get("type") or "EVENT")
        subject = str(item.get("subject") or "")
        payload = item.get("payload") or {}
        evidence = [str(ref) for ref in (item.get("evidence") or [])][:12]

        if event_type == "MESSAGE":
            sender = str(payload.get("from_agent_id") or "agent")
            body = str(payload.get("body") or "")
            body = " ".join(body.split())
            if len(body) > 1600:
                body = body[:1582] + "...[truncated]"
            text = f"[{item.get('seq')} MESSAGE from={sender}] {body}"
        else:
            text = (
                f"[{item.get('seq')} {event_type}] {subject}: "
                f"{self._compact_payload(payload)}"
            )
        if evidence:
            text += " evidence=" + ",".join(evidence)
        return text

    def prepare(
        self, *, run_id: str, role: str, task_id: str | None, seat: str
    ) -> SharedContextBatch:
        consumer_id = self._consumer_id(run_id, role, task_id, seat)
        delta = self.bus.read_delta(
            run_id,
            self.owner,
            consumer_id=consumer_id,
            limit=min(500, max(self.max_events * 4, self.max_events)),
        )

        lines: list[str] = []
        count = 0
        consumed_seq = int(delta.get("after_seq") or 0)
        for item in delta.get("items", []):
            seq = int(item.get("seq") or consumed_seq)
            if item.get("type") == "MESSAGE":
                recipient = str((item.get("payload") or {}).get("to_agent_id") or "")
                if recipient not in {"*", str(seat), str(role)}:
                    consumed_seq = seq
                    continue

            rendered = self._format_event(item)
            candidate = rendered if not lines else "\n".join([*lines, rendered])
            if count >= self.max_events or len(candidate) > self.max_chars:
                break
            lines.append(rendered)
            count += 1
            consumed_seq = seq

        return SharedContextBatch(
            text="\n".join(lines),
            last_seq=consumed_seq,
            count=count,
            consumer_id=consumer_id,
        )

    def acknowledge(
        self, *, run_id: str, role: str, task_id: str | None, seat: str,
        consumer_id: str, last_seq: int
    ) -> None:
        if int(last_seq or 0) <= 0:
            return
        self.bus.acknowledge(
            run_id,
            self.owner,
            str(consumer_id),
            int(last_seq),
        )

    def publish_response(
        self, *, run_id: str, role: str, task_id: str | None, seat: str,
        content: str, metadata: dict[str, Any], request_sha256: str
    ) -> None:
        import hashlib
        body = str(content or "")
        if len(body) > 12000:
            body = body[:11970] + "\n...[response truncated]"
        stable = "|".join([
            str(request_sha256 or ""),
            str(run_id or ""),
            str(seat or ""),
            str(role or ""),
            str(task_id or ""),
        ])
        key = "oma-response:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()
        scalar_metadata = {
            str(k): v
            for k, v in dict(metadata or {}).items()
            if isinstance(v, (str, int, float, bool)) or v is None
        }
        self.bus.publish(
            run_id,
            self.owner,
            event_type="RESULT",
            subject=f"agent.response.{role}.{seat}",
            payload={
                "role": str(role),
                "seat": str(seat),
                "task_id": task_id,
                "content": body,
                "metadata": scalar_metadata,
                "request_sha256": str(request_sha256 or ""),
            },
            evidence=[],
            confidence=None,
            supersedes=[],
            task_id=task_id,
            agent_id=str(seat or role or ""),
            idempotency_key=key,
        )
