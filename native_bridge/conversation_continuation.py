"""Host Compact&Resume command over existing protected checkpoint/outbox APIs."""
from __future__ import annotations

import hashlib
import json

from .continuation_web import WebContinuation, WebContinuationConflict


class ConversationWebContinuation:
    def __init__(self, control, jobs, conversations=None, *, account_attestor=None):
        self.control, self.conversations = control, conversations
        self.account_attestor = account_attestor
        self.web = WebContinuation(control, jobs)

    def _conversation(self, owner, conversation_id, run_id=None):
        if not isinstance(conversation_id, str) or not 1 <= len(conversation_id) <= 512:
            raise ValueError("bounded logical conversation required")
        if self.conversations is not None:
            principal = self.conversations.principal
            if owner not in {principal, "cli:" + principal, "canvas:" + principal}:
                raise PermissionError("ConversationStore owner differs from caller")
            conversation = self.conversations.status(conversation_id)
            if run_id and self.control._run(run_id, owner).get("workspace") != conversation["workspace"]:
                raise PermissionError("conversation and Run workspaces differ")

    @staticmethod
    def _blocked(reason, **values):
        return {**values, "state": "BLOCKED", "blocked": True, "reason": reason,
                "successor_ready": False, "automatic_retry": False}

    def _account_proven(self, owner, row):
        if not callable(self.account_attestor):
            return False
        run = self.control._run(row["run_id"], owner)
        source = self.control._continuation_chat(owner, {"run_id": row["run_id"], "chat_id": row["chat_id"]})
        expected = dict(owner=owner, run_id=row["run_id"], chat_id=row["chat_id"],
                        work_item_id=row["work_item_id"], principal_id=row["principal_id"],
                        workspace=run.get("workspace"), source_conversation_id=source.get("conversation_id"))
        observed = self.account_attestor(**expected)
        return isinstance(observed, dict) and observed.get("authenticated") is True and all(
            observed.get(k) == v for k, v in expected.items())

    def prepare(self, owner, conversation_id, *, run_id, chat_id, work_item_id,
                principal_id, request_key, summary, cursor=None, target_url=None,
                operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("host owner approval required for Compact&Resume")
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
            raise ValueError("bounded stable request_key required")
        if not isinstance(summary, str) or not 1 <= len(summary) <= 16000:
            raise ValueError("bounded reviewed summary required")
        self._conversation(owner, conversation_id, run_id)
        run = self.control._run(run_id, owner)
        self.control._agent_from_run(run, principal_id)
        item = self.control.work_item_info(work_item_id, owner)
        if item["run_id"] != run_id or (item.get("assignee_agent_id") and
                                          item["assignee_agent_id"] != principal_id):
            raise PermissionError("Compact&Resume WorkItem authority differs")
        source = self.control._continuation_chat(owner, {"run_id": run_id, "chat_id": chat_id})
        if source.get("agent_id") != principal_id or source.get("provider") != "chatgpt":
            raise PermissionError("Compact&Resume requires the real agent ChatGPT binding")
        epoch = hashlib.sha256(json.dumps([owner, run_id, chat_id, request_key],
                                         separators=(",", ":")).encode()).hexdigest()
        preferences = self.conversations.model_preferences(conversation_id) if self.conversations else None
        payload = {"summary": summary, "logical_conversation_id": conversation_id,
                   "work_item_id": work_item_id, "principal_id": principal_id,
                   "target_url": target_url, "requested_preferences": preferences}
        checkpoint = self.control.write_session_checkpoint(
            owner, run_id=run_id, chat_id=chat_id, source_instance_id="conversation-compact-resume",
            source_epoch=epoch, source_seq=0, checkpoint=payload, cursor=cursor or {})
        values = {"conversation_id": conversation_id, "run_id": run_id,
                  "chat_id": chat_id, "checkpoint_id": checkpoint["checkpoint_id"]}
        try:
            self.web._authority(owner, run_id, work_item_id, principal_id)
        except PermissionError as exc:
            return self._blocked(str(exc), required_capability="web:send", **values)
        if not self._account_proven(owner, dict(run_id=run_id, chat_id=chat_id,
                                              work_item_id=work_item_id, principal_id=principal_id)):
            return self._blocked("authenticated Web account proof unavailable or mismatched", **values)
        args = dict(owner=owner, run_id=run_id, chat_id=chat_id, work_item_id=work_item_id,
                    principal_id=principal_id, request_key=request_key, summary=summary, operator_approved=True)
        if target_url:
            staged = self.web.stage(target_url=target_url, **args)
            return self.status(owner, conversation_id, continuation_id=staged["continuation_id"])
        allocated = self.web.allocate_new_target(**args)
        return self.status(owner, conversation_id, allocation_id=allocated["allocation_id"])

    def _binding(self, owner, conversation_id, allocation_id, continuation_id):
        self._conversation(owner, conversation_id)
        if bool(allocation_id) == bool(continuation_id):
            raise ValueError("provide exactly one allocation_id or continuation_id")
        table, key, ident = ("web_target_allocations", "allocation_id", allocation_id) if allocation_id else (
            "web_continuation_transfers", "continuation_id", continuation_id)
        with self.web.store.connect("session_checkpoint") as db:
            row = db.execute(f"SELECT * FROM {table} WHERE owner=? AND {key}=?", (owner, ident)).fetchone()
        if row is None:
            raise FileNotFoundError("Compact&Resume binding not found for owner")
        row = dict(row)
        self._conversation(owner, conversation_id, row["run_id"])
        if allocation_id:
            checkpoint_id = row["checkpoint_id"]
        else:
            checkpoint_id = self.control.session_checkpoints.continuation(owner, continuation_id)["checkpoint_id"]
        with self.web.store.connect("session_checkpoint") as db:
            checkpoint = db.execute("SELECT * FROM session_checkpoints WHERE owner=? AND checkpoint_id=?",
                                    (owner, checkpoint_id)).fetchone()
        if checkpoint is None or self.control.session_checkpoints._row(checkpoint)["checkpoint"].get(
                "logical_conversation_id") != conversation_id:
            raise PermissionError("Compact&Resume checkpoint belongs to another logical conversation")
        return row

    def status(self, owner, conversation_id, *, allocation_id=None, continuation_id=None):
        row = self._binding(owner, conversation_id, allocation_id, continuation_id)
        state = self.web.target_status(owner, allocation_id) if allocation_id else self.web.status(owner, continuation_id)
        published = state.get("state", state.get("stage")) == "PUBLISHED"
        account = self._account_proven(owner, row) if published else False
        ready = published and state["collector_message_attested"] and account
        uncertain = state.get("delivery_state") == "unconfirmed" or state.get("requires_operator_reconciliation", False)
        return {**state, "conversation_id": conversation_id, "run_id": row["run_id"],
                "state": "PUBLISHED" if published else "UNCONFIRMED" if uncertain else "WAITING_RECEIPT",
                "account_identity_attested": account,
                "successor_ready": ready, "blocked": not ready, "automatic_retry": False}

    def resume(self, owner, conversation_id, *, allocation_id=None, continuation_id=None, operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("host owner approval required to resume successor")
        row = self._binding(owner, conversation_id, allocation_id, continuation_id)
        if not self._account_proven(owner, row):
            return self._blocked("authenticated Web account proof unavailable or mismatched",
                                 conversation_id=conversation_id, allocation_id=allocation_id,
                                 continuation_id=continuation_id, run_id=row["run_id"])
        if allocation_id:
            status = self.web.target_status(owner, allocation_id)
            if status["state"] == "PUBLISHED":
                return self.status(owner, conversation_id, allocation_id=allocation_id)
            if not status["receipt_exact"] or not status["collector_message_attested"]:
                return self._blocked("new chat requires exact authenticated Web receipt", **status)
            prepared = self.web.claim_new_target(owner, allocation_id)
            continuation_id = prepared["continuation_id"]
        status = self.web.status(owner, continuation_id)
        if not status["target_receipt_exact"] or not status["collector_message_attested"]:
            return self._blocked("successor requires exact authenticated Web receipt", **status)
        self.web.commit(owner, continuation_id, operator_approved=True)
        return self.status(owner, conversation_id, continuation_id=continuation_id)
