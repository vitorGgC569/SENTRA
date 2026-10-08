"""Explicit SENTRA Control Plane boundary.

The Control Plane owns authority. Context is knowledge only: it can record facts,
claims and objections, but cannot transition Runs/Operations or bypass QualityGate.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
import uuid

from sentra_core.conversation import ConversationIdentity

from .authorization import AuthorizationService
from .budget_policy import BudgetPolicyService
from .context import ContextBusService
from .control_store import SQLiteControlPlaneStore
from .durable import DurableRunService
from .event_ingress import EventIngressService
from .execution_workspace import ExecutionWorkspaceService
from .governance import GovernanceService
from .plugin_host import PluginWorkerHost
from .session_checkpoint import SessionCheckpointService
from .task_ledger import DurableTaskLedger


class ControlPlaneService:
    """Authority facade joining Durable Core to the non-authoritative Context Bus."""

    def __init__(self, durable: DurableRunService, context: ContextBusService) -> None:
        self.durable = durable
        self.context = context
        self.store = SQLiteControlPlaneStore(durable.state_root)
        self.task_ledger = DurableTaskLedger(durable.state_root, store=self.store)
        self.authorization = AuthorizationService(durable.state_root, store=self.store)
        self.governance = GovernanceService(
            durable.state_root, durable=durable, store=self.store
        )
        self.budgets = BudgetPolicyService(
            durable.state_root, governance=self.governance, store=self.store
        )
        self.ingress = EventIngressService(durable.state_root, store=self.store)
        self.session_checkpoints = SessionCheckpointService(durable.state_root, store=self.store)
        self.execution_workspaces = ExecutionWorkspaceService(
            durable.state_root, durable=durable, store=self.store
        )
        self.plugin_host: PluginWorkerHost | None = None

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


    def create_goal(
        self,
        run_id: str,
        owner: str,
        *,
        objective: str,
        acceptance_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        priority: str = "MEDIUM",
        budget: dict[str, Any] | None = None,
        deadline: float | None = None,
        parent_goal_id: str | None = None,
        goal_id: str | None = None,
        external_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.durable.create_goal(
            run_id, owner,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            constraints=constraints,
            priority=priority,
            budget=budget,
            deadline=deadline,
            parent_goal_id=parent_goal_id,
            goal_id=goal_id,
            external_key=external_key,
            metadata=metadata,
        )

    def update_goal(self, goal_id: str, owner: str, **changes: Any) -> dict[str, Any]:
        item = self.durable.goal_info(goal_id, owner)
        self._run(str(item["run_id"]), owner)
        return self.durable.update_goal(goal_id, owner, **changes)

    def goal_info(self, goal_id: str, owner: str) -> dict[str, Any]:
        item = self.durable.goal_info(goal_id, owner)
        self._run(str(item["run_id"]), owner)
        return item

    def list_goals(
        self, run_id: str, owner: str, *, states: list[str] | None = None
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.durable.list_goals(run_id, owner, states=states)

    def ensure_agent(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        role: str,
        task_id: str | None = None,
        goal_id: str | None = None,
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
                        goal_id=goal_id,
                        metadata=metadata,
                        heartbeat=True,
                    )
                return item
        return self.durable.assign_agent(
            run_id,
            owner,
            role=role,
            task_id=task_id,
            goal_id=goal_id,
            agent_id=agent_id,
            state="ACTIVE",
            desired_state="ACTIVE",
            metadata=metadata,
        )

    @staticmethod
    def _chat_provider(provider: str | None, conversation_url: str | None) -> str:
        requested = str(provider or "").strip().lower()
        if requested and requested not in {"chatgpt", "gemini"}:
            raise ValueError("unsupported chat provider")
        identity = (
            ConversationIdentity.parse(str(conversation_url))
            if conversation_url else None
        )
        inferred = identity.provider if identity is not None else ""
        if requested and inferred and requested != inferred:
            raise ValueError("chat provider does not match conversation URL")
        return requested or inferred or "chatgpt"

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
        provider: str | None = None,
        project_id: str | None = None,
        project_url: str | None = None,
        task_id: str | None = None,
        goal_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_provider = self._chat_provider(provider, conversation_url)
        if conversation_url:
            identity = ConversationIdentity.parse(str(conversation_url))
            if conversation_id and str(conversation_id) != identity.conversation_id:
                raise ValueError("conversation_id does not match conversation URL")
            conversation_id = identity.conversation_id
            conversation_url = identity.canonical_url
        self.ensure_agent(
            run_id,
            owner,
            agent_id=agent_id,
            role=role,
            task_id=task_id,
            goal_id=goal_id,
            metadata=metadata,
        )
        run = self._run(run_id, owner)
        existing = next(
            (item for item in (run.get("chats") or []) if item.get("chat_id") == chat_id),
            None,
        )
        if existing is not None and existing.get("agent_id") != agent_id:
            raise FileExistsError(
                f"chat_id {chat_id!r} is already bound to another agent"
            )
        if existing is None:
            return self.durable.bind_chat(
                run_id,
                owner,
                agent_id=agent_id,
                provider=effective_provider,
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
        identity_changed = bool(
            conversation_id
            and (
                existing.get("conversation_id") != conversation_id
                or existing.get("conversation_url") != conversation_url
            )
        )
        provider_changed = existing.get("provider") != effective_provider
        if identity_changed or provider_changed:
            self.durable.rebind_chat(
                chat_id,
                owner,
                conversation_id=conversation_id,
                conversation_url=conversation_url,
                provider=effective_provider,
                project_id=project_id,
                project_url=project_url,
                reason=(
                    "conversation-seat-refresh"
                    if identity_changed
                    else "conversation-provider-refresh"
                ),
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


    # -- Governance / Paperclip-derived control primitives -----------------
    def create_work_item(self, run_id: str, owner: str, **kwargs: Any) -> dict[str, Any]:
        run = self._run(run_id, owner)
        goal_id = kwargs.get("goal_id")
        if goal_id:
            goal = self.goal_info(str(goal_id), owner)
            if goal.get("run_id") != run_id:
                raise ValueError("work item goal belongs to another run")
        assignee = kwargs.get("assignee_agent_id")
        self._agent_from_run(run, assignee)
        item = self.governance.create_work_item(run_id, owner, **kwargs)
        budget = kwargs.get("budget") or {}
        limits = budget.get("limits") if isinstance(budget, dict) else None
        if isinstance(limits, dict) and limits:
            existing = [
                policy for policy in self.budgets.list_policies(owner)["items"]
                if policy["scope_type"] == "work_item"
                and policy.get("scope_id") == item["work_item_id"]
                and (policy.get("metadata") or {}).get("source") == "work_item_budget"
            ]
            if not existing:
                self.budgets.set_policy(
                    owner,
                    scope_type="work_item",
                    scope_id=item["work_item_id"],
                    limits=limits,
                    mode=str(budget.get("mode") or "hard_stop"),
                    window_seconds=budget.get("window_seconds"),
                    metadata={"source": "work_item_budget"},
                )
        return item

    def work_item_info(self, work_item_id: str, owner: str) -> dict[str, Any]:
        item = self.governance.work_item_info(work_item_id, owner)
        self._run(str(item["run_id"]), owner)
        return item

    def list_work_items(
        self, owner: str, *, run_id: str | None = None,
        states: list[str] | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        if run_id:
            self._run(run_id, owner)
        return self.governance.list_work_items(
            owner, run_id=run_id, states=states, limit=limit, offset=offset
        )

    def transition_work_item(
        self, work_item_id: str, owner: str, state: str, *,
        reason: str = "", metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.work_item_info(work_item_id, owner)
        return self.governance.transition_work_item(
            work_item_id, owner, state, reason=reason, metadata=metadata
        )

    def checkout_work_item(
        self, work_item_id: str, owner: str, *, run_id: str, agent_id: str | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        self.work_item_info(work_item_id, owner)
        return self.governance.checkout(work_item_id, owner, run_id=run_id, agent_id=agent_id)

    def start_work_item_execution(
        self, work_item_id: str, owner: str, *, run_id: str, agent_id: str | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        item = self.work_item_info(work_item_id, owner)
        authority_run = self._run(str(item["run_id"]), owner)
        self.budgets.require(
            owner,
            workspace=authority_run.get("workspace"),
            goal_id=item.get("goal_id"),
            work_item_id=work_item_id,
            agent_id=agent_id or item.get("assignee_agent_id"),
        )
        return self.governance.start_execution(
            work_item_id, owner, run_id=run_id, agent_id=agent_id
        )

    def release_work_item_locks(
        self, work_item_id: str, owner: str, *, run_id: str,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        return self.governance.release_run_locks(work_item_id, owner, run_id=run_id)

    def record_work_item_failure(self, work_item_id: str, owner: str, **kwargs: Any) -> dict[str, Any]:
        self.work_item_info(work_item_id, owner)
        return self.governance.record_failure(work_item_id, owner, **kwargs)

    def begin_work_item_recovery(self, work_item_id: str, owner: str, **kwargs: Any) -> dict[str, Any]:
        item = self.work_item_info(work_item_id, owner)
        run_id = kwargs.get("run_id")
        agent_id = kwargs.get("agent_id")
        if run_id:
            run = self._run(str(run_id), owner)
            self._agent_from_run(run, agent_id)
        elif agent_id:
            self._agent_from_run(self._run(str(item["run_id"]), owner), agent_id)
        return self.governance.begin_recovery(work_item_id, owner, **kwargs)

    def complete_work_item_recovery(
        self,
        work_item_id: str,
        owner: str,
        *,
        outcome: str = "resume",
        reason: str = "",
    ) -> dict[str, Any]:
        self.work_item_info(work_item_id, owner)
        return self.governance.complete_recovery(
            work_item_id, owner, outcome=outcome, reason=reason
        )

    def record_work_item_quality_gate(
        self,
        work_item_id: str,
        owner: str,
        *,
        passed: bool,
        reason: str = "",
        evidence: list[str] | None = None,
        candidate_revision: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = self.work_item_info(work_item_id, owner)
        refs = self._validate_evidence(str(item["run_id"]), owner, evidence)
        return self.governance.record_quality_gate(
            work_item_id,
            owner,
            passed=passed,
            reason=reason,
            evidence=refs,
            candidate_revision=candidate_revision,
            metadata=metadata,
        )

    def submit_work_item_policy(
        self, work_item_id: str, owner: str, *, evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        item = self.work_item_info(work_item_id, owner)
        refs = self._validate_evidence(str(item["run_id"]), owner, evidence)
        return self.governance.submit_for_policy(work_item_id, owner, evidence=refs)

    def decide_work_item_policy(self, work_item_id: str, owner: str, **kwargs: Any) -> dict[str, Any]:
        item = self.work_item_info(work_item_id, owner)
        refs = self._validate_evidence(str(item["run_id"]), owner, kwargs.pop("evidence", None))
        return self.governance.decide_policy_stage(
            work_item_id, owner, evidence=refs, **kwargs
        )

    def record_cost(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        run_id = kwargs.get("run_id")
        if run_id:
            self._run(str(run_id), owner)
        work_item_id = kwargs.get("work_item_id")
        item = None
        if work_item_id:
            item = self.work_item_info(str(work_item_id), owner)
        recorded = self.governance.record_cost(owner, **kwargs)
        workspace = kwargs.get("workspace")
        if item is not None and not workspace:
            workspace = self._run(str(item["run_id"]), owner).get("workspace")
        budget = self.budgets.check(
            owner,
            workspace=workspace,
            goal_id=kwargs.get("goal_id") or (item or {}).get("goal_id"),
            work_item_id=str(work_item_id) if work_item_id else None,
            agent_id=kwargs.get("agent_id") or (item or {}).get("assignee_agent_id"),
            provider=kwargs.get("provider"),
        )
        if item is not None and not budget["allowed"] and not item.get("terminal"):
            try:
                item = self.governance.transition_work_item(
                    str(work_item_id), owner, "BLOCKED",
                    reason="budget hard-stop exceeded",
                    metadata={"budget_blocked": True},
                )
            except Exception:
                # Cost evidence must never be dropped merely because the current
                # task state has no direct BLOCKED transition.
                pass
        return {**recorded, "budget": budget}

    def cost_summary(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.governance.cost_summary(owner, **kwargs)

    def list_activity(self, owner: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self.governance.list_activity(owner, limit=limit, offset=offset)

    def create_routine(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        authority_run_id = kwargs.pop("authority_run_id", None)
        goal_id = kwargs.pop("goal_id", None)
        metadata = dict(kwargs.pop("metadata", None) or {})
        if authority_run_id:
            self._run(str(authority_run_id), owner)
            metadata["_runtime_authority_run_id"] = str(authority_run_id)
            if goal_id:
                goal = self.goal_info(str(goal_id), owner)
                if goal.get("run_id") != authority_run_id:
                    raise ValueError("routine goal belongs to another authority run")
                metadata["_runtime_goal_id"] = str(goal_id)
        result = self.governance.create_routine(owner, metadata=metadata, **kwargs)
        return result

    def routine_info(self, routine_id: str, owner: str) -> dict[str, Any]:
        return self.governance.routine_info(routine_id, owner)

    def fire_routine(
        self, routine_id: str, owner: str, *, run_id: str, goal_id: str | None = None,
        source: str = "manual", occurrence_key: str | None = None,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        if goal_id:
            goal = self.goal_info(goal_id, owner)
            if goal.get("run_id") != run_id:
                raise ValueError("routine goal belongs to another run")
        return self.governance.fire_routine(
            routine_id, owner, run_id=run_id, goal_id=goal_id, source=source,
            occurrence_key=occurrence_key,
        )

    def create_secret(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.governance.create_secret(owner, **kwargs)

    def secret_info(self, secret_id: str, owner: str) -> dict[str, Any]:
        return self.governance.secret_info(secret_id, owner)

    def rotate_secret(self, secret_id: str, owner: str, *, value: str) -> dict[str, Any]:
        return self.governance.rotate_secret(secret_id, owner, value=value)

    def bind_secret(self, secret_id: str, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.governance.bind_secret(secret_id, owner, **kwargs)

    def register_work_product(
        self, work_item_id: str, owner: str, *, artifact_id: str,
        kind: str = "artifact", title: str = "", metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = self.work_item_info(work_item_id, owner)
        artifact = self.durable.artifact_info(artifact_id, owner)
        if artifact.get("run_id") != item.get("run_id"):
            raise ValueError("work product artifact belongs to another run")
        return self.governance.register_work_product(
            work_item_id, owner, artifact_id=artifact_id, kind=kind, title=title, metadata=metadata
        )

    def install_skill(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.governance.install_skill(owner, **kwargs)

    def register_plugin(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.governance.register_plugin(owner, **kwargs)

    def export_blueprint(self, run_id: str, owner: str) -> dict[str, Any]:
        run = self._run(run_id, owner)
        snapshot = self.governance.portable_snapshot(owner, run_id=run_id)
        snapshot["goals"] = self.list_goals(run_id, owner).get("items", [])
        snapshot["agents"] = [
            {
                "agent_id": item.get("agent_id"), "role": item.get("role"),
                "goal_id": item.get("goal_id"), "metadata": item.get("metadata") or {},
            }
            for item in (run.get("agents") or [])
        ]
        # Conversation, device, absolute path and secret identities are intentionally absent.
        for goal in snapshot["goals"]:
            for key in ("created_at", "updated_at", "owner", "run_id"):
                goal.pop(key, None)
        snapshot["run"] = {
            "required_capabilities": run.get("required_capabilities") or [],
            "workspace_required": bool(run.get("workspace")),
        }
        return snapshot


    def ingest_source_event(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        run_id = kwargs.get("run_id")
        operation_id = kwargs.get("operation_id")
        if run_id:
            self._run(str(run_id), owner)
        if operation_id:
            operation = self.durable.operation_status(str(operation_id), owner)
            if run_id and operation.get("run_id") != run_id:
                raise ValueError("source event operation belongs to another run")
        result = self.ingress.ingest(owner, **kwargs)
        self.governance.activity(
            owner, "source_event.ingest", "replay" if result["idempotent_replay"] else "ok",
            run_id=run_id, operation_id=operation_id,
            payload={
                "source_instance_id": kwargs.get("source_instance_id"),
                "source_epoch": kwargs.get("source_epoch"),
                "source_seq": kwargs.get("source_seq"),
                "highest_contiguous_source_seq": result["highest_contiguous_source_seq"],
            },
        )
        return result

    def source_stream_status(
        self, owner: str, *, source_instance_id: str, source_epoch: str,
    ) -> dict[str, Any]:
        return self.ingress.status(
            owner, source_instance_id=source_instance_id, source_epoch=source_epoch
        )

    def write_session_checkpoint(
        self,
        owner: str,
        *,
        run_id: str,
        chat_id: str,
        source_instance_id: str,
        source_epoch: str,
        source_seq: int,
        checkpoint: dict[str, Any],
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        chat = next(
            (item for item in (run.get("chats") or []) if item.get("chat_id") == chat_id),
            None,
        )
        if chat is None:
            raise FileNotFoundError("chat does not belong to this run")
        result = self.session_checkpoints.write(
            owner,
            run_id=run_id,
            chat_id=chat_id,
            agent_id=chat.get("agent_id"),
            provider=chat.get("provider"),
            conversation_id=chat.get("conversation_id"),
            source_instance_id=source_instance_id,
            source_epoch=source_epoch,
            source_seq=source_seq,
            checkpoint=checkpoint,
            cursor=cursor,
        )
        self.governance.activity(
            owner,
            "session_checkpoint.write",
            "ok",
            run_id=run_id,
            agent_id=chat.get("agent_id"),
            chat_id=chat_id,
            payload={
                "checkpoint_id": result["checkpoint_id"],
                "source_instance_id": source_instance_id,
                "source_epoch": source_epoch,
                "source_seq": source_seq,
            },
        )
        return result

    def latest_session_checkpoint(
        self,
        owner: str,
        *,
        run_id: str,
        chat_id: str,
        source_instance_id: str | None = None,
        source_epoch: str | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        if not any(
            item.get("chat_id") == chat_id for item in (run.get("chats") or [])
        ):
            raise FileNotFoundError("chat does not belong to this run")
        result = self.session_checkpoints.latest(
            owner,
            chat_id=chat_id,
            source_instance_id=source_instance_id,
            source_epoch=source_epoch,
        )
        if result.get("run_id") != run_id:
            raise ValueError("session checkpoint belongs to another run")
        return result

    def create_execution_workspace(
        self, owner: str, *, authority_run_id: str, work_item_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._run(authority_run_id, owner)
        if work_item_id:
            item = self.work_item_info(work_item_id, owner)
            if item.get("run_id") != authority_run_id:
                raise ValueError("execution workspace work item belongs to another authority run")
        result = self.execution_workspaces.create(
            owner, authority_run_id=authority_run_id, work_item_id=work_item_id, **kwargs
        )
        self.governance.activity(
            owner, "execution_workspace.create", "ok", run_id=authority_run_id,
            work_item_id=work_item_id,
            payload={"execution_workspace_id": result["execution_workspace_id"], "backend": result["backend"]},
        )
        return result

    def execution_workspace_info(
        self, execution_workspace_id: str, owner: str,
    ) -> dict[str, Any]:
        return self.execution_workspaces.info(execution_workspace_id, owner)

    def transition_execution_workspace(
        self, execution_workspace_id: str, owner: str, state: str, **kwargs: Any,
    ) -> dict[str, Any]:
        result = self.execution_workspaces.transition(
            execution_workspace_id, owner, state, **kwargs
        )
        self.governance.activity(
            owner, "execution_workspace.transition", "ok",
            run_id=result.get("authority_run_id"), work_item_id=result.get("work_item_id"),
            payload={"execution_workspace_id": execution_workspace_id, "state": result["state"]},
        )
        return result

    def acquire_execution_workspace(
        self, execution_workspace_id: str, owner: str, *, execution_run_id: str,
        operation_id: str | None = None, ttl_s: float = 300.0,
    ) -> dict[str, Any]:
        self._run(execution_run_id, owner)
        if operation_id:
            operation = self.durable.operation_status(operation_id, owner)
            if operation.get("run_id") != execution_run_id:
                raise ValueError("execution workspace operation belongs to another run")
        result = self.execution_workspaces.acquire(
            execution_workspace_id, owner, execution_run_id=execution_run_id,
            operation_id=operation_id, ttl_s=ttl_s,
        )
        item = result["workspace"]
        self.governance.activity(
            owner, "execution_workspace.acquire", "ok", run_id=execution_run_id,
            operation_id=operation_id, work_item_id=item.get("work_item_id"),
            payload={"execution_workspace_id": execution_workspace_id,
                     "fencing_token": item.get("fencing_token")},
        )
        return result

    def renew_execution_workspace(
        self, execution_workspace_id: str, owner: str, *, fencing_token: int,
        ttl_s: float = 300.0,
    ) -> dict[str, Any]:
        return self.execution_workspaces.renew(
            execution_workspace_id, owner, fencing_token=fencing_token, ttl_s=ttl_s
        )

    def release_execution_workspace(
        self, execution_workspace_id: str, owner: str, *, fencing_token: int,
        dirty: bool = False,
    ) -> dict[str, Any]:
        result = self.execution_workspaces.release(
            execution_workspace_id, owner, fencing_token=fencing_token, dirty=dirty
        )
        self.governance.activity(
            owner, "execution_workspace.release", "ok",
            run_id=result.get("authority_run_id"), work_item_id=result.get("work_item_id"),
            payload={"execution_workspace_id": execution_workspace_id,
                     "state": result["state"], "dirty": dirty},
        )
        return result


    @staticmethod
    def _validate_blueprint_payload(blueprint: dict[str, Any]) -> dict[str, int]:
        if not isinstance(blueprint, dict):
            raise ValueError("blueprint must be an object")
        if blueprint.get("kind") != "sentra-governance-blueprint":
            raise ValueError("unsupported blueprint kind")
        if blueprint.get("schema_version") != 1:
            raise ValueError("unsupported blueprint schema_version")
        if blueprint.get("contains_secret_values") is not False:
            raise ValueError("blueprint must explicitly declare contains_secret_values=false")
        forbidden_keys = {
            "protected_value", "secret_value", "session_token", "conversation_id",
            "conversation_url", "device_id", "checkout_run_id", "execution_run_id",
            "fencing_token",
        }

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                hit = forbidden_keys & set(value)
                if hit:
                    raise ValueError(
                        "blueprint contains non-portable/sensitive fields: " + ", ".join(sorted(hit))
                    )
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(blueprint)
        sections = ("goals", "agents", "work_items", "routines", "skills", "plugins", "secret_requirements")
        counts: dict[str, int] = {}
        for section in sections:
            value = blueprint.get(section) or []
            if not isinstance(value, list):
                raise ValueError(f"blueprint {section} must be a list")
            counts[section] = len(value)
        return counts

    def import_blueprint(
        self,
        run_id: str,
        owner: str,
        *,
        blueprint: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        self._run(run_id, owner)
        counts = self._validate_blueprint_payload(blueprint)
        plan = {
            "dry_run": bool(dry_run),
            "target_run_id": run_id,
            "counts": counts,
            "required_secrets": [
                {
                    "name": item.get("name"),
                    "scope_type": item.get("scope_type"),
                    "scope_id": item.get("scope_id"),
                    "metadata": item.get("metadata") or {},
                }
                for item in (blueprint.get("secret_requirements") or [])
            ],
            "trust_policy": {
                "secret_values_imported": False,
                "plugin_ui_trust_imported": False,
                "plugin_capability_verification_imported": False,
                "chat_bindings_imported": False,
                "device_bindings_imported": False,
            },
        }
        if dry_run:
            return plan

        source_goals = list(blueprint.get("goals") or [])
        goal_map = {
            str(item.get("goal_id")): "goal-" + uuid.uuid4().hex
            for item in source_goals if item.get("goal_id")
        }
        pending = list(source_goals)
        created_goals: list[dict[str, Any]] = []
        while pending:
            progressed = False
            for item in list(pending):
                old_id = str(item.get("goal_id") or "")
                old_parent = item.get("parent_goal_id")
                if old_parent and str(old_parent) not in goal_map:
                    raise ValueError("blueprint goal references a missing parent")
                mapped_parent = goal_map.get(str(old_parent)) if old_parent else None
                if mapped_parent and not any(g.get("goal_id") == mapped_parent for g in created_goals):
                    continue
                metadata = dict(item.get("metadata") or {})
                metadata["imported_from_goal_id"] = old_id or None
                created = self.create_goal(
                    run_id,
                    owner,
                    objective=str(item.get("objective") or "").strip(),
                    acceptance_criteria=item.get("acceptance_criteria") or [],
                    constraints=item.get("constraints") or [],
                    priority=str(item.get("priority") or "MEDIUM"),
                    budget=item.get("budget") or {},
                    deadline=item.get("deadline"),
                    parent_goal_id=mapped_parent,
                    goal_id=goal_map.get(old_id) or ("goal-" + uuid.uuid4().hex),
                    external_key=None,
                    metadata=metadata,
                )
                created_goals.append(created)
                pending.remove(item)
                progressed = True
            if not progressed:
                raise ValueError("blueprint goal hierarchy could not be resolved")

        agent_map: dict[str, str] = {}
        created_agents: list[dict[str, Any]] = []
        for item in blueprint.get("agents") or []:
            old_id = str(item.get("agent_id") or "")
            new_id = "agent-" + uuid.uuid4().hex
            agent_map[old_id] = new_id
            old_goal = item.get("goal_id")
            metadata = dict(item.get("metadata") or {})
            metadata["imported_from_agent_id"] = old_id or None
            created_agents.append(self.durable.assign_agent(
                run_id,
                owner,
                role=str(item.get("role") or "worker"),
                goal_id=goal_map.get(str(old_goal)) if old_goal else None,
                agent_id=new_id,
                state="AVAILABLE",
                desired_state="AVAILABLE",
                metadata=metadata,
            ))

        source_work = list(blueprint.get("work_items") or [])
        work_map = {
            str(item.get("work_item_id")): "work-" + uuid.uuid4().hex
            for item in source_work if item.get("work_item_id")
        }
        created_work: list[dict[str, Any]] = []
        for item in source_work:
            old_id = str(item.get("work_item_id") or "")
            old_goal = item.get("goal_id")
            old_parent = item.get("parent_work_item_id")
            metadata = dict(item.get("metadata") or {})
            metadata["imported_from_work_item_id"] = old_id or None
            if item.get("external_key"):
                metadata["imported_external_key"] = item.get("external_key")
            created_work.append(self.governance.create_work_item(
                run_id,
                owner,
                work_item_id=work_map.get(old_id) or ("work-" + uuid.uuid4().hex),
                objective=str(item.get("objective") or "").strip(),
                goal_id=goal_map.get(str(old_goal)) if old_goal else None,
                external_key=None,
                parent_work_item_id=work_map.get(str(old_parent)) if old_parent else None,
                acceptance_criteria=item.get("acceptance_criteria") or [],
                blockers=[work_map.get(str(x), str(x)) for x in (item.get("blockers") or [])],
                dependencies=[work_map.get(str(x), str(x)) for x in (item.get("dependencies") or [])],
                assignee_agent_id=agent_map.get(str(item.get("assignee_agent_id"))) if item.get("assignee_agent_id") else None,
                assignee_user_id=None,
                required_capabilities=item.get("required_capabilities") or [],
                target_files=item.get("target_files") or [],
                resource_locks=item.get("resource_locks") or [],
                side_effect_scope=str(item.get("side_effect_scope") or "workspace"),
                execution_policy=item.get("execution_policy") or {},
                retry_policy=item.get("retry_policy") or {},
                budget=item.get("budget") or {},
                metadata=metadata,
            ))

        created_routines: list[dict[str, Any]] = []
        for item in blueprint.get("routines") or []:
            work_template = dict(item.get("work_template") or {})
            old_goal = work_template.get("goal_id")
            if old_goal:
                work_template["goal_id"] = goal_map.get(str(old_goal))
            created_routines.append(self.create_routine(
                owner,
                name=str(item.get("name") or "").strip(),
                trigger_kind=str(item.get("trigger_kind") or "").strip(),
                trigger_spec=item.get("trigger_spec") or {},
                work_template=work_template,
                active_policy=str(item.get("active_policy") or "coalesce_if_active"),
                missed_policy=str(item.get("missed_policy") or "skip_missed"),
                missed_cap=int(item.get("missed_cap") or 1),
                enabled=False,
                next_due_at=None,
                metadata={
                    **dict(item.get("metadata") or {}),
                    "imported_enabled": bool(item.get("enabled", True)),
                    "requires_runtime_bind": True,
                },
            ))

        created_skills = [
            self.install_skill(
                owner,
                name=str(item.get("name") or "").strip(),
                version=str(item.get("version") or "").strip(),
                content=str(item.get("content") or ""),
                source=str(item.get("source") or "blueprint"),
                metadata=item.get("metadata") or {},
            )
            for item in (blueprint.get("skills") or [])
        ]
        created_plugins = [
            self.register_plugin(
                owner,
                manifest=item.get("manifest") or {
                    "name": item.get("name"), "version": item.get("version"),
                    "capabilities": item.get("declared_capabilities") or [],
                },
                verified_methods=[],
                narrowed_capabilities=item.get("narrowed_capabilities") or item.get("declared_capabilities") or [],
                trusted_ui=False,
                metadata={**dict(item.get("metadata") or {}), "requires_reverification": True},
            )
            for item in (blueprint.get("plugins") or [])
        ]

        self.governance.activity(
            owner,
            "blueprint.import",
            "ok",
            run_id=run_id,
            payload={
                "counts": counts,
                "goal_mapping": goal_map,
                "agent_mapping": agent_map,
                "work_mapping": work_map,
            },
        )
        return {
            **plan,
            "dry_run": False,
            "goal_mapping": goal_map,
            "agent_mapping": agent_map,
            "work_mapping": work_map,
            "created": {
                "goals": len(created_goals),
                "agents": len(created_agents),
                "work_items": len(created_work),
                "routines": len(created_routines),
                "skills": len(created_skills),
                "plugins": len(created_plugins),
            },
        }


    # -- Capability/scope authorization ------------------------------------
    def authorization_grant(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        result = self.authorization.grant(owner, **kwargs)
        self.governance.activity(
            owner, "authorization.grant", "ok", actor_type="system",
            payload={
                "grant_id": result["grant_id"],
                "principal_type": result["principal_type"],
                "principal_id": result["principal_id"],
                "capability": result["capability"],
                "scope_type": result["scope_type"],
                "scope_id": result.get("scope_id"),
            },
        )
        return result

    def authorization_revoke(self, grant_id: str, owner: str) -> dict[str, Any]:
        result = self.authorization.revoke(grant_id, owner)
        self.governance.activity(
            owner, "authorization.revoke", "ok",
            payload={"grant_id": grant_id},
        )
        return result

    def authorization_check(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        decision = self.authorization.authorize(owner, **kwargs)
        self.governance.activity(
            owner, "authorization.check", "allowed" if decision["allowed"] else "denied",
            actor_type=str(kwargs.get("principal_type") or "system"),
            actor_id=str(kwargs.get("principal_id") or "") or None,
            payload={
                "capability": kwargs.get("capability"),
                "scope_type": kwargs.get("scope_type"),
                "scope_id": kwargs.get("scope_id"),
                "source": decision.get("source"),
                "grant_id": decision.get("grant_id"),
                "reason": decision.get("reason"),
            },
        )
        return decision

    def authorization_list(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.authorization.list_grants(owner, **kwargs)


    def budget_set(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        result = self.budgets.set_policy(owner, **kwargs)
        self.governance.activity(
            owner, "budget.set", "ok",
            payload={
                "budget_policy_id": result["budget_policy_id"],
                "scope_type": result["scope_type"],
                "scope_id": result.get("scope_id"),
                "mode": result["mode"],
                "limits": result["limits"],
            },
        )
        return result

    def budget_check(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.budgets.check(owner, **kwargs)

    def budget_list(self, owner: str, *, enabled_only: bool = False) -> dict[str, Any]:
        return self.budgets.list_policies(owner, enabled_only=enabled_only)


    def attach_process_service(self, processes: Any) -> None:
        self.plugin_host = PluginWorkerHost(
            self.durable.state_root,
            processes=processes,
            governance=self.governance,
            authorization=self.authorization,
            store=self.store,
        )

    def _plugin_host(self) -> PluginWorkerHost:
        if self.plugin_host is None:
            raise RuntimeError("plugin worker host is not attached to ProcessService")
        return self.plugin_host

    def plugin_worker_start(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        run_id = kwargs.get("run_id")
        if run_id:
            self._run(str(run_id), owner)
        return self._plugin_host().start(owner, **kwargs)

    def plugin_worker_call(
        self, plugin_worker_id: str, owner: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._plugin_host().call(plugin_worker_id, owner, **kwargs)

    def plugin_worker_stop(
        self, plugin_worker_id: str, owner: str
    ) -> dict[str, Any]:
        return self._plugin_host().stop(plugin_worker_id, owner)

    def plugin_info(self, plugin_id: str, owner: str) -> dict[str, Any]:
        return self.governance.plugin_info(plugin_id, owner)

    def plugin_list(self, owner: str) -> dict[str, Any]:
        return self.governance.list_plugins(owner)


    def skill_list(self, owner: str) -> dict[str, Any]:
        return self.governance.list_skills(owner)

    def skill_bind(
        self,
        skill_id: str,
        owner: str,
        *,
        run_id: str,
        agent_id: str,
        priority: int = 100,
        enabled: bool = True,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        return self.governance.bind_skill(
            skill_id,
            owner,
            run_id=run_id,
            agent_id=agent_id,
            priority=priority,
            enabled=enabled,
        )

    def agent_skills(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        max_chars: int = 6000,
    ) -> dict[str, Any]:
        run = self._run(run_id, owner)
        self._agent_from_run(run, agent_id)
        return self.governance.agent_skills(
            owner, run_id=run_id, agent_id=agent_id, max_chars=max_chars
        )


    def bind_routine(
        self,
        routine_id: str,
        owner: str,
        *,
        authority_run_id: str,
        goal_id: str | None = None,
        enable: bool | None = None,
    ) -> dict[str, Any]:
        self._run(authority_run_id, owner)
        if goal_id:
            goal = self.goal_info(goal_id, owner)
            if goal.get("run_id") != authority_run_id:
                raise ValueError("routine goal belongs to another authority run")
        result = self.governance.bind_routine_runtime(
            routine_id,
            owner,
            authority_run_id=authority_run_id,
            goal_id=goal_id,
        )
        if enable is not None:
            result = self.governance.set_routine_enabled(
                routine_id, owner, enabled=enable
            )
        return result

    def set_routine_enabled(
        self, routine_id: str, owner: str, *, enabled: bool
    ) -> dict[str, Any]:
        return self.governance.set_routine_enabled(
            routine_id, owner, enabled=enabled
        )

    def routine_list(self, owner: str, *, enabled_only: bool = False) -> dict[str, Any]:
        return self.governance.list_routines(owner, enabled_only=enabled_only)

    def tick_routines(self, *, now: float | None = None) -> dict[str, Any]:
        from .routine_scheduler import RoutineSchedulerService
        return RoutineSchedulerService(self).tick(now=now)
