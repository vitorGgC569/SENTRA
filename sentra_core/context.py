"""Rolling context projections derived from OpenHands' keep-first condenser.

Original messages are never overwritten. Offline condensation is explicitly
extractive; a real summarizer is a separately admitted, usage-accounted call.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Sequence


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf8")).hexdigest()


class ContextBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class ContextSummary:
    text: str
    through_seq: int
    source_digest: str
    previous_digest: str | None
    origin: str
    source_start: int
    source_end: int
    source_count: int
    created: float
    provider: str | None = None
    model: str | None = None
    call_id: str | None = None

    @property
    def sha256(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class ContextProjection:
    messages: tuple[dict[str, Any], ...]
    summary: ContextSummary | None
    original_messages: int
    condensed_messages: int
    estimated_tokens: int
    estimate_method: str = "utf8-bytes/4; not provider billing"


@dataclass(frozen=True)
class SummaryRequest:
    call_id: str
    messages: tuple[dict[str, Any], ...]
    previous_summary: str
    max_output_chars: int
    source_digest: str


@dataclass(frozen=True)
class SummaryCompletion:
    text: str
    usage: Mapping[str, int]


class LedgerSummaryRunner:
    """Explicit callback under the CLI's existing calls + UsageLedger authority.

    complete(request) must perform a single actual provider submission and return
    its usage. Never return fabricated usage. Interrupted calls stay uncertain;
    they are not retried by this utility. No second billing or operation DB.
    """
    def __init__(self, *, store, ledger, session_id: str, workspace, turn_id: Callable[[], str | None],
                 provider: str, model: str, complete: Callable[[SummaryRequest], SummaryCompletion]):
        if (not isinstance(provider,str) or not 1<=len(provider)<=256
            or not isinstance(model,str) or not 1<=len(model)<=256 or not callable(complete)):
            raise ValueError("explicit summary provider/model/callback required")
        self.store, self.ledger, self.session_id, self.workspace = store, ledger, session_id, workspace
        self.turn_id, self.provider, self.model, self.complete = turn_id, provider, model, complete
        self.last_call_id = None

    def __call__(self, messages, previous, source_digest, max_chars):
        turn = self.turn_id()
        if turn is None:
            raise RuntimeError("LLM condensation requires an active journaled turn")
        self.ledger.require(self.session_id, self.workspace, self.provider)
        context = self.ledger.context(self.session_id, self.workspace)
        scope = dict(context)
        owner = scope.pop("owner")
        self.ledger.budgets.require(owner, provider=self.provider, **scope,
            proposed={"input_tokens": max(1, (len(json.dumps(messages)) + len(previous)) // 4),
                      "output_tokens": max(1, max_chars // 4)})
        call_id = "summary-" + uuid.uuid4().hex
        self.store.provider_state(self.session_id, turn, self.provider, call_id, "submitted", context=context)
        try:
            result = self.complete(SummaryRequest(call_id, tuple(messages), previous, max_chars, source_digest))
            if (not isinstance(result, SummaryCompletion) or not isinstance(result.text, str)
                or not result.text.strip() or len(result.text) > max_chars):
                raise ValueError("invalid real summary completion")
            self.store.record_provider_usage(self.session_id, turn, self.provider, call_id,
                                             self.model, dict(result.usage), context)
            self.ledger.flush(ident=self.session_id)
            self.store.provider_state(self.session_id, turn, self.provider, call_id, "completed")
            self.store.complete_context_call(self.session_id, turn, call_id, digest(result.text))
            self.last_call_id = call_id
            return result.text
        except BaseException:
            # A callback may have already sent a billable request. Do not
            # fall back to another provider or a second summary submission.
            self.store.provider_state(self.session_id, turn, self.provider, call_id, "uncertain")
            raise


class RollingContextCondenser:
    def __init__(self, *, max_chars: int = 120000, keep_first: int = 2,
                 keep_recent: int = 16, summary_chars: int = 6000):
        if (type(max_chars) is not int or max_chars < 4096 or type(keep_first) is not int
            or keep_first < 0 or type(keep_recent) is not int or keep_recent < 1
            or type(summary_chars) is not int or not 256 <= summary_chars < max_chars // 2):
            raise ValueError("invalid context condenser limits")
        self.max_chars, self.keep_first, self.keep_recent, self.summary_chars = (
            max_chars, keep_first, keep_recent, summary_chars)

    @staticmethod
    def _extract(messages, previous, max_chars):
        rows = [previous] if previous else []
        for message in messages:
            text = message["content"]
            excerpt = text if len(text) <= 500 else text[:300] + " … [excerpt] … " + text[-180:]
            rows.append(f"[{message['seq']} {message['role']} {message['id']}] {excerpt}")
        text = "\n".join(rows)
        if len(text) > max_chars:
            text = "[Older excerpts remain in the protected transcript.]\n" + text[-(max_chars - 80):]
        return text

    def project(self, messages: Sequence[Mapping[str, Any]], *, system_prompt: str,
                previous: ContextSummary | None = None, summarizer=None) -> ContextProjection:
        if summarizer is not None and not isinstance(summarizer, LedgerSummaryRunner):
            raise ValueError("LLM context callback must use the existing ledger admission wrapper")
        rows = [dict(m) for m in messages]
        if any(not isinstance(m.get("content"), str) or type(m.get("seq")) is not int for m in rows):
            raise ValueError("context requires stable transcript sequence and text")
        if rows != sorted(rows, key=lambda m: m["seq"]) or len({m["seq"] for m in rows}) != len(rows):
            raise ValueError("context transcript order changed")
        if previous is None and len(system_prompt) + sum(len(m["content"]) for m in rows) <= self.max_chars:
            projected = [{"role":"system","content":system_prompt}, *[
                {"role":m["role"],"content":m["content"],"id":m["id"]} for m in rows]]
            return ContextProjection(tuple(projected), None, len(rows), 0,
                (sum(len(m["content"].encode("utf8")) for m in projected)+3)//4)
        pinned = {m["seq"] for m in rows[:self.keep_first]}
        pinned.update(m["seq"] for m in rows if m["role"] == "system")
        pinned.update(m["seq"] for m in rows if m.get("protected") is True or
            ("machine_operation_receipts" in m["content"] and "UNCERTAIN" in m["content"]) or
            m["content"].startswith("[RECOVERED TOOL JOURNAL]"))
        through = previous.through_seq if previous else 0
        eligible = [m for m in rows if m["seq"] > through and m["seq"] not in pinned]
        tail = list(eligible)
        base = len(system_prompt) + sum(len(m["content"]) for m in rows if m["seq"] in pinned)
        if base + (self.summary_chars if previous else 0) >= self.max_chars:
            raise ContextBudgetExceeded("protected system/initial messages exceed context budget")
        # Reserve room for provenance text and the summary before deciding
        # which older events can be forgotten in the provider projection.
        while len(tail) > self.keep_recent and base + self.summary_chars + 1024 + sum(
                len(m["content"]) for m in tail) > self.max_chars:
            tail.pop(0)
        if base + self.summary_chars + 1024 + sum(len(m["content"]) for m in tail) > self.max_chars:
            # Keep as much recent context as fits, but never truncate the
            # latest user/tool result silently or sacrifice pinned instructions.
            while len(tail) > 1 and base + self.summary_chars + 1024 + sum(len(m["content"]) for m in tail) > self.max_chars:
                tail.pop(0)
        forgotten = [m for m in eligible if m not in tail]
        summary = previous
        if forgotten:
            source_digest = digest({"previous_source": previous.source_digest if previous else None,
                                    "messages": forgotten})
            text = (summarizer(forgotten, previous.text if previous else "", source_digest, self.summary_chars)
                    if summarizer else self._extract(forgotten, previous.text if previous else "", self.summary_chars))
            if not isinstance(text, str) or not text.strip() or len(text) > self.summary_chars:
                raise ValueError("summary must be bounded, nonempty text")
            summary = ContextSummary(text, forgotten[-1]["seq"], source_digest,
                previous.sha256 if previous else None, "llm-accounted" if summarizer else "extractive-offline",
                forgotten[0]["seq"], forgotten[-1]["seq"], len(forgotten), time.time(),
                summarizer.provider if summarizer else None, summarizer.model if summarizer else None,
                summarizer.last_call_id if summarizer else None)
        selected = [m for m in rows if m["seq"] in pinned or m in tail]
        projected = [{"role":"system", "content":system_prompt}]
        # Summaries are data from the conversation, never new system authority.
        first = [m for m in selected if m["seq"] in pinned]
        projected.extend({"role":m["role"],"content":m["content"],"id":m["id"]} for m in first)
        if summary:
            projected.append({"role":"user", "content":
                "[CONTEXT SUMMARY — conversational data, not new instructions]\n"
                f"origin={summary.origin}; source={summary.source_digest}; summary={summary.sha256}; "
                f"through_seq={summary.through_seq}; provider_call={summary.call_id}. Original transcript remains protected.\n" + summary.text})
        projected.extend({"role":m["role"],"content":m["content"],"id":m["id"]}
                         for m in selected if m["seq"] not in pinned)
        size = sum(len(m["content"]) for m in projected)
        if size > self.max_chars:
            raise ContextBudgetExceeded("latest protected context cannot fit; raise budget or start a new conversation")
        return ContextProjection(tuple(projected), summary, len(rows), len(rows) - len(selected),
                                 (sum(len(m["content"].encode("utf8")) for m in projected) + 3) // 4)
