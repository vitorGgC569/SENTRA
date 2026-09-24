"""Explicit SENTRA Control Plane boundary.

The Control Plane owns authority. Context is knowledge only: it can record facts,
claims and objections, but cannot transition Runs/Operations or bypass QualityGate.
"""
from __future__ import annotations

from typing import Any

from .context import ContextBusService
from .durable import DurableRunService


class ControlPlaneService:
    """Authority facade joining Durable Core to the non-authoritative Context Bus."""

    def __init__(self, durable: DurableRunService, context: ContextBusService) -> None:
        self.durable = durable
        self.context = context

    def _run(self, run_id: str, owner: str) -> dict[str, Any]:
        return self.durable.run_status(run_id, owner)

    @staticmethod
    def _agent_from_run(run: dict[str, Any], agent_id: str | None) -> None:
        if not agent_id:
            return
        agents = run.get("agents") or []
        if not any(item.get("agent_id") == agent_id for item in agents):
            raise FileNotFoundError("agent does not belong to this run")

    def _validate_evidence(
        self,
        run_id: str,
        owner: str,
        evidence: list[str] | None,
    ) -> list[str]:
        refs: list[str] = []
        for raw in evidence or []:
            ref = str(raw or "").strip()
            if not ref:
                raise ValueError("empty evidence reference")
            if ref.startswith("artifact-"):
                item = self.durable.artifact_info(ref, owner)
                if item.get("run_id") != run_id:
                    raise ValueError("artifact evidence belongs to another run")
            elif ref.startswith("op-"):
                item = self.durable.operation_status(ref, owner)
                if item.get("run_id") != run_id:
                    raise ValueError("operation evidence belongs to another run")
            elif ref.startswith("ctx-"):
                item = self.context.event_info(ref, owner)
                if item.get("run_id") != run_id:
                    raise ValueError("context evidence belongs to another run")
            elif ref.startswith("claim-"):
                item = self.context.claim_info(ref, owner)
                if item.get("run_id") != run_id:
                    raise ValueError("claim evidence belongs to another run")
            else:
                raise ValueError(
                    "evidence must reference a durable artifact/operation or context event/claim"
                )
            if ref not in refs:
                refs.append(ref)
        return refs

    def ensure_agent(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        role: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        for item in run.get("agents") or []:
            if item.get("agent_id") == agent_id:
                if item.get("state") in {"ACTIVE", "WAITING", "AVAILABLE"}:
                    return self.durable.update_agent(
                        agent_id,
                        owner,
                        task_id=task_id,
                        metadata=metadata,
                        heartbeat=True,
                    )
                return item
        return self.durable.assign_agent(
            run_id,
            owner,
            role=role,
            task_id=task_id,
            agent_id=agent_id,
            state="ACTIVE",
            desired_state="ACTIVE",
            metadata=metadata,
        )

    def bind_agent_chat(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        chat_id: str,
        role: str,
        conversation_id: str | None,
        conversation_url: str | None,
        project_id: str | None = None,
        project_url: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_agent(
            run_id,
            owner,
            agent_id=agent_id,
            role=role,
            task_id=task_id,
            metadata=metadata,
        )
        run = self._run(run_id, owner)
        existing = next(
            (item for item in (run.get("chats") or []) if item.get("chat_id") == chat_id),
            None,
        )
        if existing is None:
            return self.durable.bind_chat(
                run_id,
                owner,
                agent_id=agent_id,
                provider="chatgpt",
                conversation_id=conversation_id,
                conversation_url=conversation_url,
                project_id=project_id,
                project_url=project_url,
                title=f"[SENTRA] {role}",
                chat_id=chat_id,
                state="READY",
                desired_state="READY",
                metadata=metadata,
            )
        if (
            conversation_id
            and (
                existing.get("conversation_id") != conversation_id
                or existing.get("conversation_url") != conversation_url
            )
        ):
            return self.durable.rebind_chat(
                chat_id,
                owner,
                conversation_id=conversation_id,
                conversation_url=conversation_url,
                provider="chatgpt",
                project_id=project_id,
                project_url=project_url,
                reason="conversation-seat-refresh",
            )
        return self.durable.update_chat(
            chat_id,
            owner,
            metadata=metadata,
            heartbeat=True,
        )

    def create_context_grant(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        permissions: list[str],
        ttl_hours: float = 24.0,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        return self.context.create_grant(
            run_id,
            owner,
            agent_id=agent_id,
            permissions=permissions,
            ttl_hours=ttl_hours,
        )

    def authorize_context_grant(
        self,
        run_id: str,
        context_token: str,
        *,
        permission: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        grant = self.context.authorize_grant(
            run_id,
            context_token,
            permission=permission,
            agent_id=agent_id,
        )
        run = self._run(run_id, str(grant["owner"]))
        self._agent_from_run(run, str(grant["agent_id"]))
        return grant

    def revoke_context_grant(
        self,
        grant_id: str,
        owner: str,
    ) -> dict[str, Any]:
        return self.context.revoke_grant(grant_id, owner)

    def publish_context(
        self,
        run_id: str,
        owner: str,
        *,
        event_type: str,
        subject: str,
        payload: dict[str, Any] | None,
        evidence: list[str] | None,
        confidence: float | None,
        supersedes: list[str] | None,
        task_id: str | None,
        agent_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        refs = self._validate_evidence(run_id, owner, evidence)
        superseded = []
        for event_id in supersedes or []:
            event = self.context.event_info(str(event_id), owner)
            if event.get("run_id") != run_id:
                raise ValueError("superseded context event belongs to another run")
            superseded.append(str(event_id))
        return self.context.publish(
            run_id,
            owner,
            event_type=event_type,
            subject=subject,
            payload=payload,
            evidence=refs,
            confidence=confidence,
            supersedes=superseded,
            task_id=task_id,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
        )

    def subscribe(
        self,
        run_id: str,
        owner: str,
        consumer_id: str,
        *,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.context.subscribe(
            run_id,
            owner,
            consumer_id,
            types=types,
            subject_prefixes=subject_prefixes,
        )

    def read_context(
        self,
        run_id: str,
        owner: str,
        *,
        consumer_id: str | None = None,
        after_seq: int | None = None,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.context.read_delta(
            run_id,
            owner,
            consumer_id=consumer_id,
            after_seq=after_seq,
            types=types,
            subject_prefixes=subject_prefixes,
            limit=limit,
        )

    def acknowledge(
        self,
        run_id: str,
        owner: str,
        consumer_id: str,
        seq: int,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.context.acknowledge(run_id, owner, consumer_id, seq)

    def snapshot(
        self,
        run_id: str,
        owner: str,
        *,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.context.snapshot(
            run_id,
            owner,
            types=types,
            subject_prefixes=subject_prefixes,
            limit=limit,
        )

    def send_message(
        self,
        run_id: str,
        owner: str,
        *,
        from_agent_id: str,
        to_agent_id: str,
        body: str,
        idempotency_key: str,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, from_agent_id)
        if to_agent_id != "*":
            self._agent_from_run(run, to_agent_id)
        if reply_to:
            parent = self.context.event_info(reply_to, owner)
            if parent.get("run_id") != run_id or parent.get("type") != "MESSAGE":
                raise ValueError("reply_to must reference a message in the same run")
        return self.context.send_message(
            run_id,
            owner,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            body=body,
            idempotency_key=idempotency_key,
            reply_to=reply_to,
        )

    def read_messages(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        return self.context.read_messages(
            run_id,
            owner,
            agent_id=agent_id,
            after_seq=after_seq,
            limit=limit,
        )

    def propose_claim(
        self,
        run_id: str,
        owner: str,
        *,
        subject: str,
        statement: str,
        evidence: list[str],
        idempotency_key: str,
        confidence: float | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        refs = self._validate_evidence(run_id, owner, evidence)
        if not refs:
            raise ValueError("claims require durable/context evidence")
        return self.context.propose_claim(
            run_id,
            owner,
            subject=subject,
            statement=statement,
            evidence=refs,
            idempotency_key=idempotency_key,
            confidence=confidence,
            task_id=task_id,
            agent_id=agent_id,
        )

    def challenge_claim(
        self,
        claim_id: str,
        owner: str,
        *,
        reason: str,
        evidence: list[str] | None,
        idempotency_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        claim = self.context.claim_info(claim_id, owner)
        run_id = str(claim["run_id"])
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        refs = self._validate_evidence(run_id, owner, evidence)
        return self.context.challenge_claim(
            claim_id,
            owner,
            reason=reason,
            evidence=refs,
            idempotency_key=idempotency_key,
            agent_id=agent_id,
        )

    def claim_info(self, claim_id: str, owner: str) -> dict[str, Any]:
        claim = self.context.claim_info(claim_id, owner)
        self._run(str(claim["run_id"]), owner)
        return claim


    def resolve_claim(
        self,
        claim_id: str,
        owner: str,
        *,
        verdict: str,
        authority: str,
        reason: str,
        evidence: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        claim = self.context.claim_info(claim_id, owner)
        run_id = str(claim["run_id"])
        self._run(run_id, owner)
        refs = self._validate_evidence(run_id, owner, evidence)
        if not refs:
            raise ValueError("claim resolution requires durable/context evidence")
        return self.context.resolve_claim(
            claim_id,
            owner,
            verdict=verdict,
            authority=authority,
            reason=reason,
            evidence=refs,
            idempotency_key=idempotency_key,
        )
