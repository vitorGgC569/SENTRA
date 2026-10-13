"""Transactional Compact & Resume orchestrator (Rastro).

Ports the phase protocol (not the 1.807-line module) from
`third_party/chat-on-steroids/src/main/session/continuation.ts`,
`handoff.ts` and `resume-gate.ts`:

  open -> summary -> exclusive claim -> preflight -> durable commit
  -> publish/abort

Exactly one unresolved handoff per logical chat (central UNIQUE index).
A successor rebinds the SAME Run/Chat/WorkItem/agent binding; leases,
grants and provenance are preserved, uncertain effects are never
replayed, and abort keeps the origin binding untouched. The Control
Plane stays authoritative; this service only sequences its checkpoints,
continuations and the relay's durable outbox via ConversationWebContinuation.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from sentra_core.conversation import ConversationIdentity
from sentra_mcp.services.session_checkpoint import SessionCheckpointConflict
from .continuation_web import WebContinuationConflict
from .conversation_continuation import ConversationWebContinuation


class CompactResumeConflict(SessionCheckpointConflict):
    pass


class CompactResumeService:
    def __init__(self, control, jobs=None, conversations=None, *, clock=time.time,
                 account_attestor=None) -> None:
        self.control = control
        self.conversations = conversations
        self.clock = clock
        resolved = jobs if jobs is not None else getattr(control, "relay_jobs", None)
        if resolved is None:
            raise ValueError("Compact&Resume requires the host relay JobStore (jobs)")
        self.jobs = resolved
        self.inner = ConversationWebContinuation(
            control, resolved, conversations=conversations,
            account_attestor=account_attestor)

    @staticmethod
    def _epoch(owner: str, run_id: str, chat_id: str, request_key: str) -> str:
        return hashlib.sha256(json.dumps(
            [owner, run_id, chat_id, request_key],
            separators=(",", ":")).encode("utf-8")).hexdigest()

    def begin(self, owner: str, conversation_id: str, *, run_id: str, chat_id: str,
              work_item_id: str, principal_id: str, request_key: str,
              summary: str, cursor: dict | None = None, target_url: str | None = None,
              operator_approved: bool = False, transcript_sha256: str | None = None,
              transcript_message_ids: list | None = None,
              children_snapshot: dict | None = None) -> dict[str, Any]:
        """Phase open->summary->claim. Returns a phase-labelled status dict."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required for Compact&Resume")
        if target_url is not None:
            identity = ConversationIdentity.parse(target_url)
            if identity.provider != "chatgpt":
                raise ValueError("ChatGPT destination required")
        try:
            prepared = self.inner.prepare(
                owner, conversation_id, run_id=run_id, chat_id=chat_id,
                work_item_id=work_item_id, principal_id=principal_id,
                request_key=request_key, summary=summary,
                cursor=cursor or {}, target_url=target_url, operator_approved=True,
                transcript_sha256=transcript_sha256,
                transcript_message_ids=transcript_message_ids,
                children_snapshot=children_snapshot)
        except (WebContinuationConflict, SessionCheckpointConflict) as exc:
            raise CompactResumeConflict(str(exc)) from exc
        phase = "claimed" if not prepared.get("blocked") else "blocked"
        return {"phase": phase, "epoch": self._epoch(owner, run_id, chat_id, request_key),
                "request_key": request_key, "automatic_retry": False, **prepared}

    def preflight(self, owner: str, conversation_id: str, *,
                  allocation_id: str | None = None,
                  continuation_id: str | None = None) -> dict[str, Any]:
        """Phase claim->preflight: grant, account, single-handoff and delivery checks."""
        status = self.inner.status(owner, conversation_id, allocation_id=allocation_id,
                                   continuation_id=continuation_id)
        if status.get("delivery_state") == "unconfirmed" or status.get(
                "requires_operator_reconciliation"):
            return {**status, "phase": "preflight_blocked",
                    "reason": "uncertain delivery requires reconciliation",
                    "automatic_retry": False}
        if status.get("blocked"):
            return {**status, "phase": "preflight_blocked", "automatic_retry": False}
        return {**status, "phase": "preflight_ok", "automatic_retry": False}

    def commit(self, owner: str, conversation_id: str, *,
               allocation_id: str | None = None,
               continuation_id: str | None = None,
               operator_approved: bool = False,
               transcript_sha256: str | None = None) -> dict[str, Any]:
        """Phase preflight->commit->publish. Requires exact authenticated receipt."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required to publish successor")
        checked = self.preflight(owner, conversation_id, allocation_id=allocation_id,
                                 continuation_id=continuation_id)
        if checked.get("phase") != "preflight_ok":
            raise CompactResumeConflict(checked.get("reason") or "successor is not ready")
        try:
            done = self.inner.resume(owner, conversation_id, allocation_id=allocation_id,
                                     continuation_id=continuation_id, operator_approved=True,
                                     transcript_sha256=transcript_sha256)
        except (WebContinuationConflict, SessionCheckpointConflict) as exc:
            raise CompactResumeConflict(str(exc)) from exc
        if done.get("blocked") or not done.get("successor_ready"):
            raise CompactResumeConflict("successor requires exact authenticated Web receipt")
        return {**done, "phase": "published", "automatic_retry": False}

    def abort(self, owner: str, continuation_id: str, *,
              operator_approved: bool = False) -> dict[str, Any]:
        """Abort a staged handoff; the origin binding is preserved verbatim."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required to abort continuation")
        try:
            result = self.control.cancel_chat_continuation(
                owner, continuation_id, operator_approved=True)
        except AttributeError as exc:
            raise CompactResumeConflict("central continuation authority unavailable") from exc
        return {"phase": "aborted", "continuation_id": continuation_id,
                "state": result.get("state"), "automatic_retry": False}

    def status(self, owner: str, conversation_id: str, *,
               allocation_id: str | None = None,
               continuation_id: str | None = None) -> dict[str, Any]:
        state = self.inner.status(owner, conversation_id, allocation_id=allocation_id,
                                  continuation_id=continuation_id)
        return {**state, "phase": "published" if state.get("state") == "PUBLISHED"
                else "unconfirmed" if state.get("state") == "UNCONFIRMED"
                else "waiting_receipt", "automatic_retry": False}
