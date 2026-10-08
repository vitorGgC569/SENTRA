"""Durable authority for tool-capable Web turns and their physical browser tabs."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import ctypes
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService, DurableStateConflict, StaleFenceError


@dataclass
class TurnCapability:
    token_hash: str
    run_id: str
    operation_id: str
    owner: str
    broker_registered: bool = False
    conversation_uri: str | None = None
    trace_id: str | None = None
    physical_key: str | None = None
    physical_fence: int | None = None
    logical_key: str | None = None
    logical_fence: int | None = None
    conversation_key: str | None = None
    conversation_fence: int | None = None
    completed_revision: int | None = None
    allowed_tools: frozenset[str] | None = None
    goal_run_id: str | None = None
    goal_id: str | None = None
    agent_id: str | None = None
    codex_thread_id: str | None = None
    native_turn_id: str | None = None


class TurnAuthority:
    def __init__(self, state_root: Path, descriptor: Path, *, clock=time.time) -> None:
        self.state_root = Path(state_root).resolve()
        self.durable = DurableRunService(self.state_root)
        self.descriptor = descriptor
        self.clock = clock
        self.lock = threading.RLock()
        self.capabilities: dict[str, TurnCapability] = {}

    @staticmethod
    def _goal_scope(
        conversation_uri: str | None,
        request_identity: str | None,
    ) -> str | None:
        if request_identity:
            try:
                metadata = json.loads(request_identity)
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = None
            thread_id = metadata.get("thread_id") if isinstance(metadata, dict) else None
            if isinstance(thread_id, str) and thread_id:
                # The Codex thread is the logical task identity. A physical
                # ChatGPT conversation may be rebound during recovery and must
                # not fork the durable Goal authority when that happens.
                return "codex-thread://" + thread_id
        if conversation_uri:
            return conversation_uri
        return None

    @staticmethod
    def _request_metadata(request_identity: str | None) -> dict[str, Any]:
        if not request_identity:
            return {}
        try:
            value = json.loads(request_identity)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _authority_run_for_scope(
        self,
        owner: str,
        scope: str,
        conversation_uri: str | None,
    ) -> tuple[dict[str, Any], str]:
        scope_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        authority_run = self.durable.create_run(
            owner,
            idempotency_key="codex-goal-authority:" + scope_hash,
            required_capabilities=[],
            capability_snapshot={
                "kind": "codex-goal-authority",
                "scope_hash": scope_hash,
                "conversation_uri": conversation_uri,
            },
        )
        return authority_run, scope_hash

    def _find_codex_agent_binding(
        self,
        owner: str,
        thread_id: str | None = None,
        *,
        agent_name: str | None = None,
    ) -> dict[str, Any] | None:
        if not thread_id and not agent_name:
            return None
        runs = self.durable.list_runs(owner, offset=0, limit=1000)
        for item in runs.get("items", []):
            snapshot = item.get("capability_snapshot") or {}
            if snapshot.get("kind") != "codex-goal-authority":
                continue
            detail = self.durable.run_status(str(item["run_id"]), owner)
            for agent in detail.get("agents", []):
                metadata = agent.get("metadata") or {}
                if metadata.get("source") != "codex-native-subagent":
                    continue
                matches_thread = bool(
                    thread_id and metadata.get("codex_thread_id") == thread_id
                )
                matches_name = bool(
                    agent_name and metadata.get("agent_name") == agent_name
                )
                if not (matches_thread or matches_name):
                    continue
                return {
                    "goal_run_id": str(item["run_id"]),
                    "goal_id": agent.get("goal_id"),
                    "agent_id": str(agent["agent_id"]),
                    "agent_state": agent.get("state"),
                    "parent_goal_id": metadata.get("parent_goal_id"),
                    "parent_thread_id": metadata.get("parent_thread_id"),
                    "agent_name": metadata.get("agent_name"),
                    "last_native_notification_key": metadata.get(
                        "last_native_notification_key"
                    ),
                    "scope_hash": snapshot.get("scope_hash"),
                }
        return None

    def _bind_codex_subagent(
        self,
        *,
        owner: str,
        request_identity: str | None,
        goal_text: str | None,
        task_text: str | None,
    ) -> dict[str, Any] | None:
        metadata = self._request_metadata(request_identity)
        thread_id = metadata.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None

        existing = self._find_codex_agent_binding(owner, thread_id)
        if existing is not None:
            updates: dict[str, Any] = {
                "heartbeat": True,
                "metadata": {"last_turn_at": self.clock()},
            }
            if existing.get("agent_state") == "AVAILABLE":
                updates["state"] = "ACTIVE"
                updates["desired_state"] = "ACTIVE"

            # A native child may have been observed before the parent acquired
            # a durable /goal. Attach the existing Agent to a subgoal later
            # instead of leaving it permanently unscoped.
            if existing.get("goal_id") is None:
                parent_thread = existing.get("parent_thread_id")
                stored_agent_name = existing.get("agent_name")
                if (
                    isinstance(parent_thread, str)
                    and parent_thread
                    and isinstance(stored_agent_name, str)
                    and stored_agent_name
                ):
                    parent_scope = "codex-thread://" + parent_thread
                    authority_run, scope_hash = self._authority_run_for_scope(
                        owner, parent_scope, None
                    )
                    authority_run_id = str(authority_run["run_id"])
                    goals = self.durable.list_goals(
                        authority_run_id, owner
                    ).get("items", [])
                    roots = [
                        item for item in goals
                        if (item.get("metadata") or {}).get("source")
                        == "codex-native-goal"
                        and not item.get("terminal")
                    ]
                    parent_goal = roots[-1] if roots else None
                    if parent_goal is None and str(goal_text or "").strip():
                        _, root_goal_id = self._sync_codex_goal(
                            owner=owner,
                            scope=parent_scope,
                            conversation_uri=None,
                            goal_present=True,
                            goal_text=goal_text,
                        )
                        parent_goal = (
                            self.durable.goal_info(root_goal_id, owner)
                            if root_goal_id
                            else None
                        )
                    if parent_goal is not None:
                        existing_parent_goal_id = str(parent_goal["goal_id"])
                        child_goal = self.durable.create_goal(
                            authority_run_id,
                            owner,
                            objective=(
                                str(task_text or "").strip()
                                or "Execute native Codex subagent task for "
                                + stored_agent_name
                            ),
                            acceptance_criteria=[
                                "Return a bounded result to the native Codex parent agent.",
                            ],
                            constraints=[
                                "Native Codex owns spawn, wait, follow-up, and terminal lifecycle.",
                                "SENTRA records authority and evidence without emulating collaboration tools.",
                            ],
                            priority="HIGH",
                            parent_goal_id=existing_parent_goal_id,
                            external_key=(
                                "codex-subagent:"
                                + hashlib.sha256(
                                    thread_id.encode("utf-8")
                                ).hexdigest()[:24]
                            ),
                            metadata={
                                "source": "codex-native-subgoal",
                                "harness_owned": True,
                                "codex_thread_id": thread_id,
                                "parent_thread_id": parent_thread,
                                "agent_name": stored_agent_name,
                                "scope_hash": scope_hash,
                            },
                        )
                        existing_child_goal_id = str(child_goal["goal_id"])
                        updates["goal_id"] = existing_child_goal_id
                        updates["metadata"] = {
                            "last_turn_at": self.clock(),
                            "parent_goal_id": existing_parent_goal_id,
                        }
                        existing["goal_run_id"] = authority_run_id
                        existing["goal_id"] = existing_child_goal_id
                        existing["parent_goal_id"] = existing_parent_goal_id

            current_goal_id = (
                str(updates.get("goal_id") or existing.get("goal_id"))
                if updates.get("goal_id") or existing.get("goal_id")
                else None
            )
            current_goal = (
                self.durable.goal_info(current_goal_id, owner)
                if current_goal_id is not None
                else None
            )
            if current_goal is not None and current_goal.get("terminal"):
                turn_id = metadata.get("turn_id")
                successor = self.durable.create_goal(
                    str(existing["goal_run_id"]),
                    owner,
                    objective=(
                        str(task_text or "").strip()
                        or "Continue native Codex subagent task"
                    ),
                    acceptance_criteria=[
                        "Return the requested native Codex follow-up result to the parent agent.",
                    ],
                    constraints=[
                        "Native Codex owns follow-up and terminal lifecycle.",
                        "SENTRA preserves Agent identity and versions the subgoal.",
                    ],
                    priority="HIGH",
                    parent_goal_id=(
                        str(existing["parent_goal_id"])
                        if isinstance(existing.get("parent_goal_id"), str)
                        else None
                    ),
                    external_key=(
                        "codex-subagent-followup:"
                        + hashlib.sha256(
                            (
                                thread_id
                                + ":"
                                + str(turn_id or "")
                                + ":"
                                + str(task_text or "")
                            ).encode("utf-8")
                        ).hexdigest()[:24]
                    ),
                    metadata={
                        "source": "codex-native-subgoal",
                        "harness_owned": True,
                        "codex_thread_id": thread_id,
                        "parent_thread_id": existing.get("parent_thread_id"),
                        "agent_name": existing.get("agent_name"),
                        "successor_of": current_goal_id,
                        "turn_id": turn_id,
                    },
                )
                successor_id = str(successor["goal_id"])
                updates["goal_id"] = successor_id
                updates["metadata"] = {
                    **dict(updates.get("metadata") or {}),
                    "previous_goal_id": current_goal_id,
                    "last_turn_at": self.clock(),
                }
                existing["goal_id"] = successor_id

            self.durable.update_agent(
                str(existing["agent_id"]),
                owner,
                **updates,
            )
            return existing

        parent_thread_id = metadata.get("parent_thread_id")
        agent_name = metadata.get("agent_name")
        subagent_kind = metadata.get("subagent_kind")
        if (
            subagent_kind != "thread_spawn"
            or not isinstance(parent_thread_id, str)
            or not parent_thread_id
            or not isinstance(agent_name, str)
            or not agent_name
        ):
            return None

        parent_binding = self._find_codex_agent_binding(owner, parent_thread_id)
        parent_goal = None
        if parent_binding is not None and isinstance(parent_binding.get("goal_id"), str):
            goal_run_id = str(parent_binding["goal_run_id"])
            parent_goal = self.durable.goal_info(
                str(parent_binding["goal_id"]),
                owner,
            )
            scope_hash = str(parent_binding.get("scope_hash") or "")
        else:
            parent_scope = "codex-thread://" + parent_thread_id
            authority_run, scope_hash = self._authority_run_for_scope(
                owner, parent_scope, None
            )
            goal_run_id = str(authority_run["run_id"])
            goals = self.durable.list_goals(goal_run_id, owner).get("items", [])
            root_goals = [
                item for item in goals
                if (item.get("metadata") or {}).get("source") == "codex-native-goal"
                and not item.get("terminal")
            ]
            parent_goal = root_goals[-1] if root_goals else None
            if parent_goal is None and str(goal_text or "").strip():
                _, synced_parent_goal_id = self._sync_codex_goal(
                    owner=owner,
                    scope=parent_scope,
                    conversation_uri=None,
                    goal_present=True,
                    goal_text=goal_text,
                )
                parent_goal = (
                    self.durable.goal_info(synced_parent_goal_id, owner)
                    if synced_parent_goal_id
                    else None
                )

        spawned_parent_goal_id = (
            str(parent_goal["goal_id"]) if parent_goal is not None else None
        )
        spawned_child_goal_id: str | None = None
        if spawned_parent_goal_id is not None:
            objective = str(task_text or "").strip() or (
                "Execute native Codex subagent task for " + agent_name
            )
            child_goal = self.durable.create_goal(
                goal_run_id,
                owner,
                objective=objective,
                acceptance_criteria=[
                    "Return a bounded result to the native Codex parent agent.",
                ],
                constraints=[
                    "Native Codex owns spawn, wait, follow-up, and terminal lifecycle.",
                    "SENTRA records authority and evidence without emulating collaboration tools.",
                ],
                priority="HIGH",
                parent_goal_id=spawned_parent_goal_id,
                external_key=(
                    "codex-subagent:"
                    + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:24]
                ),
                metadata={
                    "source": "codex-native-subgoal",
                    "harness_owned": True,
                    "codex_thread_id": thread_id,
                    "parent_thread_id": parent_thread_id,
                    "agent_name": agent_name,
                    "scope_hash": scope_hash,
                },
            )
            spawned_child_goal_id = str(child_goal["goal_id"])

        agent_id = (
            "agent-codex-"
            + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:24]
        )
        agent = self.durable.assign_agent(
            goal_run_id,
            owner,
            role=agent_name[:120],
            task_id=(
                "codex:"
                + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:24]
            ),
            goal_id=spawned_child_goal_id,
            agent_id=agent_id,
            state="ACTIVE",
            desired_state="ACTIVE",
            metadata={
                "source": "codex-native-subagent",
                "codex_thread_id": thread_id,
                "parent_thread_id": parent_thread_id,
                "parent_goal_id": spawned_parent_goal_id,
                "agent_name": agent_name,
                "subagent_kind": subagent_kind,
            },
        )
        self.durable.update_agent(
            agent_id,
            owner,
            goal_id=spawned_child_goal_id,
            heartbeat=True,
            metadata={"last_turn_at": self.clock()},
        )
        return {
            "goal_run_id": goal_run_id,
            "goal_id": spawned_child_goal_id,
            "agent_id": str(agent["agent_id"]),
            "parent_goal_id": spawned_parent_goal_id,
        }

    @staticmethod
    def _codex_notification_outcome(
        status: dict[str, Any],
    ) -> tuple[str, str, Any] | None:
        if "completed" in status:
            return "SUCCEEDED", "RESULT", status.get("completed")
        for key in ("failed", "errored", "error"):
            if key in status:
                return "FAILED", "FAILURE", status.get(key)
        for key in ("cancelled", "canceled"):
            if key in status:
                return "CANCELLED", "FAILURE", status.get(key)
        return None

    def apply_codex_subagent_notifications(
        self,
        notifications: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Project native Codex terminal notifications into Goal/Context state.

        The notification is authoritative only for native agent lifecycle. It
        cannot grant tools or filesystem authority.
        """
        owner = "sentra:web-model-gateway"
        applied: list[dict[str, Any]] = []
        for notification in notifications or []:
            if not isinstance(notification, dict):
                continue
            agent_path = notification.get("agent_path")
            status = notification.get("status")
            if not isinstance(agent_path, str) or not agent_path:
                continue
            if not isinstance(status, dict):
                continue
            outcome = self._codex_notification_outcome(status)
            if outcome is None:
                continue
            target_goal_state, event_type, result_value = outcome
            binding = self._find_codex_agent_binding(
                owner,
                agent_path,
                agent_name=agent_path,
            )
            if binding is None:
                continue

            notification_key = hashlib.sha256(
                json.dumps(
                    notification,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if binding.get("last_native_notification_key") == notification_key:
                continue

            goal_run_id = str(binding["goal_run_id"])
            goal_id = (
                str(binding["goal_id"])
                if isinstance(binding.get("goal_id"), str)
                else None
            )
            agent_id = str(binding["agent_id"])
            goal = (
                self.durable.goal_info(goal_id, owner)
                if goal_id is not None
                else None
            )

            agent = next(
                (
                    item
                    for item in self.durable.run_status(goal_run_id, owner).get("agents", [])
                    if item.get("agent_id") == agent_id
                ),
                None,
            )
            agent_changes: dict[str, Any] = {
                "heartbeat": True,
                "metadata": {
                    "native_terminal_status": status,
                    "native_terminal_at": self.clock(),
                    "last_native_notification_key": notification_key,
                },
                "event_type": "CODEX_SUBAGENT_TERMINAL",
            }
            if isinstance(agent, dict) and agent.get("state") in {"ACTIVE", "WAITING"}:
                agent_changes["state"] = "AVAILABLE"
                agent_changes["desired_state"] = "AVAILABLE"
            self.durable.update_agent(
                agent_id,
                owner,
                **agent_changes,
            )

            context = ContextBusService(self.state_root, clock=self.clock)
            try:
                control = ControlPlaneService(self.durable, context)
                if goal_id is not None and goal is not None and not goal.get("terminal"):
                    control.update_goal(
                        goal_id,
                        owner,
                        state=target_goal_state,
                        reason="native Codex subagent terminal notification",
                        metadata={
                            "native_terminal_status": status,
                            "native_terminal_at": self.clock(),
                        },
                    )
                event = control.publish_context(
                    goal_run_id,
                    owner,
                    event_type=event_type,
                    subject="codex.subagent." + hashlib.sha256(
                        agent_path.encode("utf-8")
                    ).hexdigest()[:24],
                    payload={
                        "agent_path": agent_path,
                        "goal_id": goal_id,
                        "agent_id": agent_id,
                        "status": status,
                        "result": result_value,
                    },
                    evidence=[],
                    confidence=None,
                    supersedes=[],
                    task_id="codex:" + hashlib.sha256(
                        agent_path.encode("utf-8")
                    ).hexdigest()[:24],
                    agent_id=agent_id,
                    idempotency_key=(
                        "codex-subagent-terminal:" + notification_key[:32]
                    ),
                )
            finally:
                context.close()

            self.durable.checkpoint(
                goal_run_id,
                owner,
                {
                    "goal_id": goal_id,
                    "agent_id": agent_id,
                    "agent_path": agent_path,
                    "status": status,
                    "context_event_id": event["event_id"],
                },
                label="codex-subagent-terminal",
            )
            applied.append({
                "goal_run_id": goal_run_id,
                "goal_id": goal_id,
                "agent_id": agent_id,
                "context_event_id": event["event_id"],
                "state": target_goal_state,
            })
        return applied

    def _sync_codex_goal(
        self,
        *,
        owner: str,
        scope: str,
        conversation_uri: str | None,
        goal_present: bool,
        goal_text: str | None,
    ) -> tuple[str, str | None]:
        scope_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        authority_run = self.durable.create_run(
            owner,
            idempotency_key="codex-goal-authority:" + scope_hash,
            required_capabilities=[],
            capability_snapshot={
                "kind": "codex-goal-authority",
                "scope_hash": scope_hash,
                "conversation_uri": conversation_uri,
            },
        )
        run_id = str(authority_run["run_id"])
        goals = self.durable.list_goals(run_id, owner).get("items", [])
        harness_goals = [
            item for item in goals
            if (item.get("metadata") or {}).get("source") == "codex-native-goal"
        ]
        current = harness_goals[-1] if harness_goals else None

        if goal_present:
            normalized = str(goal_text or "").strip()
            if normalized:
                if current is None or current.get("terminal"):
                    external_key = (
                        "codex-native-goal"
                        if current is None
                        else "codex-native-goal:" + hashlib.sha256(
                            (normalized + scope_hash).encode("utf-8")
                        ).hexdigest()[:16]
                    )
                    current = self.durable.create_goal(
                        run_id,
                        owner,
                        objective=normalized,
                        priority="HIGH",
                        external_key=external_key,
                        metadata={
                            "source": "codex-native-goal",
                            "harness_owned": True,
                            "conversation_uri": conversation_uri,
                            "scope_hash": scope_hash,
                        },
                    )
                else:
                    changes: dict[str, Any] = {
                        "objective": normalized,
                        "metadata": {
                            "source": "codex-native-goal",
                            "harness_owned": True,
                            "conversation_uri": conversation_uri,
                            "scope_hash": scope_hash,
                            "cleared": False,
                        },
                    }
                    if current.get("state") in {"PAUSED", "BLOCKED"}:
                        changes["state"] = "ACTIVE"
                        changes["reason"] = "Codex harness supplied active goal context"
                    current = self.durable.update_goal(
                        str(current["goal_id"]),
                        owner,
                        **changes,
                    )
            elif current is not None and not current.get("terminal"):
                if current.get("state") != "PAUSED":
                    current = self.durable.update_goal(
                        str(current["goal_id"]),
                        owner,
                        state="PAUSED",
                        reason="Codex harness cleared goal context",
                        metadata={
                            "source": "codex-native-goal",
                            "harness_owned": True,
                            "cleared": True,
                        },
                    )

        goal_id = str(current["goal_id"]) if current is not None else None
        return run_id, goal_id

    def issue(
        self,
        *,
        conversation_uri: str | None = None,
        request_identity: str | None = None,
        goal_text: str | None = None,
        goal_present: bool | None = None,
        task_text: str | None = None,
        subagent_notifications: list[dict[str, Any]] | None = None,
    ) -> str:
        token = "stc_" + secrets.token_urlsafe(36)
        key = hashlib.sha256(token.encode()).hexdigest()
        identity_hash = hashlib.sha256(request_identity.encode()).hexdigest() if request_identity else None
        identity_metadata = self._request_metadata(request_identity)
        native_turn_id = identity_metadata.get("turn_id")
        if not isinstance(native_turn_id, str) or len(native_turn_id) > 256:
            native_turn_id = None
        owner = "sentra:web-model-gateway"
        run = self.durable.create_run(
            owner,
            idempotency_key="web-turn:" + (identity_hash or key),
            required_capabilities=["model:chatgpt-web"],
            capability_snapshot={
                "kind": "chatgpt-web-turn",
                "token_hash": key,
                "conversation_uri": conversation_uri,
                "request_identity_hash": identity_hash,
                "native_turn_id": native_turn_id,
            },
        )
        if run.get("idempotent_replay"):
            raise DurableStateConflict("duplicate Web turn identity; automatic replay is disabled")

        effective_goal_present = (
            goal_text is not None if goal_present is None else bool(goal_present)
        )
        identity_metadata = self._request_metadata(request_identity)
        codex_thread_id = (
            str(identity_metadata.get("thread_id"))
            if isinstance(identity_metadata.get("thread_id"), str)
            else None
        )
        goal_run_id: str | None = None
        goal_id: str | None = None
        agent_id: str | None = None
        parent_goal_id: str | None = None

        subagent = self._bind_codex_subagent(
            owner=owner,
            request_identity=request_identity,
            goal_text=goal_text,
            task_text=task_text,
        )
        if subagent is not None:
            goal_run_id = str(subagent["goal_run_id"])
            goal_id = (
                str(subagent["goal_id"])
                if isinstance(subagent.get("goal_id"), str)
                else None
            )
            agent_id = str(subagent["agent_id"])
            parent_goal_id = (
                str(subagent["parent_goal_id"])
                if isinstance(subagent.get("parent_goal_id"), str)
                else None
            )
            self.durable.checkpoint(
                str(run["run_id"]),
                owner,
                {
                    "goal_run_id": goal_run_id,
                    "goal_id": goal_id,
                    "parent_goal_id": parent_goal_id,
                    "agent_id": agent_id,
                    "codex_thread_id": codex_thread_id,
                    "goal_context_present": effective_goal_present,
                    "native_subagent": True,
                },
                label="codex-goal-link",
            )
        else:
            goal_scope = self._goal_scope(conversation_uri, request_identity)
            if goal_scope is not None:
                goal_run_id, goal_id = self._sync_codex_goal(
                    owner=owner,
                    scope=goal_scope,
                    conversation_uri=conversation_uri,
                    goal_present=effective_goal_present,
                    goal_text=goal_text,
                )
                self.durable.checkpoint(
                    str(run["run_id"]),
                    owner,
                    {
                        "goal_run_id": goal_run_id,
                        "goal_id": goal_id,
                        "goal_scope_hash": hashlib.sha256(
                            goal_scope.encode("utf-8")
                        ).hexdigest(),
                        "goal_context_present": effective_goal_present,
                    },
                    label="codex-goal-link",
                )
            elif effective_goal_present and str(goal_text or "").strip():
                fallback = self.durable.create_goal(
                    str(run["run_id"]),
                    owner,
                    objective=str(goal_text).strip(),
                    priority="HIGH",
                    external_key="codex-native-goal",
                    metadata={
                        "source": "codex-native-goal",
                        "harness_owned": True,
                        "conversation_uri": conversation_uri,
                        "scope": "turn-local-fallback",
                    },
                )
                goal_run_id = str(run["run_id"])
                goal_id = str(fallback["goal_id"])

        applied_notifications = self.apply_codex_subagent_notifications(
            subagent_notifications
        )
        if applied_notifications:
            self.durable.checkpoint(
                str(run["run_id"]),
                owner,
                {"items": applied_notifications},
                label="codex-subagent-notifications",
            )

        operation = self.durable.create_operation(
            run["run_id"], owner, kind="chatgpt-web-turn",
            idempotency_key="turn:" + run["run_id"], initial_state="RUNNING",
        )
        self.durable.heartbeat(
            str(operation["operation_id"]),
            owner,
            progress={
                "goal_run_id": goal_run_id,
                "goal_id": goal_id,
                "agent_id": agent_id,
                "codex_thread_id": codex_thread_id,
            },
        )
        with self.lock:
            self.capabilities[key] = TurnCapability(
                key,
                run["run_id"],
                operation["operation_id"],
                owner,
                conversation_uri=conversation_uri,
                goal_run_id=goal_run_id,
                goal_id=goal_id,
                agent_id=agent_id,
                codex_thread_id=codex_thread_id,
                native_turn_id=native_turn_id,
            )
        return token

    def telemetry_metadata(self, token: str) -> dict[str, Any]:
        """Link browser phases to the originating turn without exporting grants."""
        with self.lock:
            cap = self._capability(token)
            state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            return {
                "correlation_id": cap.native_turn_id or cap.run_id,
                "thread_id": cap.codex_thread_id,
                "run_id": cap.run_id,
                "operation_id": cap.operation_id,
                "trace_id": cap.trace_id,
                "operation_state": state,
                "completion_verified": state == "SUCCEEDED",
            }

    def active_leases(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {"run_id": cap.run_id, "operation_id": cap.operation_id,
                 "trace_id": cap.trace_id, "conversation_uri": cap.conversation_uri,
                 "logical_resource": cap.logical_key, "logical_fencing_token": cap.logical_fence,
                 "physical_resource": cap.physical_key, "fencing_token": cap.physical_fence}
                for cap in self.capabilities.values() if cap.physical_key is not None
            ]

    def _rehydrate(self, key: str) -> TurnCapability | None:
        owner = "sentra:web-model-gateway"
        runs = self.durable.list_runs(owner, offset=0, limit=1000)
        for run in runs.get("items", []):
            snapshot = run.get("capability_snapshot") or {}
            stored = str(snapshot.get("token_hash") or "")
            if snapshot.get("kind") != "chatgpt-web-turn" or not stored or not hmac.compare_digest(stored, key):
                continue
            if run.get("terminal") or run.get("state") != "RUNNING":
                return None
            detail = self.durable.run_status(str(run["run_id"]), owner)
            operations = [
                item for item in detail.get("operations", [])
                if item.get("kind") in {"chatgpt-web-turn", "chatgpt-web-browser-phase"}
            ]
            if not operations:
                return None
            operation = operations[-1]
            progress = operation.get("progress") or {}
            trace_id = progress.get("trace_id")
            if not isinstance(trace_id, str):
                trace_id = None
            result = operation.get("result") or {}
            completed_revision = result.get("broker_revision")
            if not isinstance(completed_revision, int):
                completed_revision = None
            capability = TurnCapability(
                key,
                str(run["run_id"]),
                str(operation["operation_id"]),
                owner,
                broker_registered=bool(progress.get("broker_registered")),
                conversation_uri=(
                    snapshot.get("conversation_uri")
                    if isinstance(snapshot.get("conversation_uri"), str)
                    else None
                ),
                trace_id=trace_id,
                native_turn_id=(
                    snapshot.get("native_turn_id")
                    if isinstance(snapshot.get("native_turn_id"), str)
                    else None
                ),
                completed_revision=completed_revision,
                allowed_tools=(
                    frozenset(str(item) for item in progress.get("allowed_tools", []) if isinstance(item, str))
                    if isinstance(progress.get("allowed_tools"), list)
                    else None
                ),
                goal_run_id=(
                    str(progress["goal_run_id"])
                    if isinstance(progress.get("goal_run_id"), str)
                    else None
                ),
                goal_id=(
                    str(progress["goal_id"])
                    if isinstance(progress.get("goal_id"), str)
                    else None
                ),
                agent_id=(
                    str(progress["agent_id"])
                    if isinstance(progress.get("agent_id"), str)
                    else None
                ),
                codex_thread_id=(
                    str(progress["codex_thread_id"])
                    if isinstance(progress.get("codex_thread_id"), str)
                    else None
                ),
            )
            for lease in detail.get("leases", []):
                if lease.get("operation_id") != capability.operation_id:
                    continue
                resource_key = str(lease.get("resource_key") or "")
                fence = lease.get("fencing_token")
                if not isinstance(fence, int):
                    continue
                if resource_key.startswith("browser-tab:"):
                    capability.physical_key = resource_key
                    capability.physical_fence = fence
                elif resource_key.startswith("conversation-uri:"):
                    capability.logical_key = resource_key
                    capability.logical_fence = fence
                elif resource_key.startswith("conversation:"):
                    capability.conversation_key = resource_key
                    capability.conversation_fence = fence
            self.capabilities[key] = capability
            return capability
        return None

    def _capability(self, token: str) -> TurnCapability:
        if not isinstance(token, str) or not token.startswith("stc_"):
            raise PermissionError("invalid TurnCapability")
        key = hashlib.sha256(token.encode()).hexdigest()
        capability = self.capabilities.get(key)
        if capability is None:
            capability = self._rehydrate(key)
        if capability is None or not hmac.compare_digest(key, capability.token_hash):
            raise PermissionError("TurnCapability is unknown or retired")
        return capability

    def _physical_tab(self, trace_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            descriptor = json.loads(self.descriptor.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StaleFenceError("Browser Host descriptor is unavailable") from exc
        if descriptor.get("version") != 3 or descriptor.get("kind") != "codex-web-gpt-launcher":
            raise StaleFenceError("Browser Host descriptor is invalid")
        if descriptor.get("sentraManaged") is not True:
            raise StaleFenceError("Browser Host was not launched under SENTRA authority")
        pid = descriptor.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise StaleFenceError("Browser Host pid is invalid")
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                raise StaleFenceError("Browser Host process has exited")
            try:
                exit_code = ctypes.c_ulong()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
                    raise StaleFenceError("Browser Host process has exited")
            finally:
                kernel.CloseHandle(handle)
        else:
            try:
                os.kill(pid, 0)
            except OSError as exc:
                raise StaleFenceError("Browser Host process has exited") from exc
        matches = [tab for tab in descriptor.get("sentraTabs", [])
                   if isinstance(tab, dict) and tab.get("traceId") == trace_id
                   and tab.get("status") == "running"]
        if len(matches) != 1:
            raise StaleFenceError("no unique running physical tab owns this turn")
        tab = matches[0]
        surface = tab.get("surfaceId")
        if not isinstance(surface, str) or (tab.get("interactionMode") != "manual"
                                               and surface not in descriptor.get("surfaceTargets", {})):
            raise StaleFenceError("physical browser surface is unavailable")
        heartbeat = tab.get("lastHeartbeatAt")
        if not isinstance(heartbeat, (int, float)) or self.clock() * 1000 - heartbeat > 90_000:
            raise StaleFenceError("physical browser tab heartbeat expired")
        return descriptor, tab

    def _bind_physical(self, cap: TurnCapability, trace_id: str) -> None:
        descriptor, tab = self._physical_tab(trace_id)
        key = f"browser-tab:{descriptor['pid']}:{tab['tabId']}"
        if cap.physical_key is not None and cap.physical_key != key:
            raise StaleFenceError("physical browser tab changed during the turn")
        if cap.physical_key is None:
            lease = self.durable.acquire_lease(cap.run_id, cap.owner, key,
                                                operation_id=cap.operation_id, ttl_s=120)
            cap.physical_key = key
            cap.physical_fence = lease["fencing_token"]
        else:
            if cap.physical_fence is None:
                raise StaleFenceError("physical browser lease fence is missing")
            self.durable.renew_lease(key, cap.owner, cap.physical_fence, ttl_s=120)
        if cap.conversation_uri:
            logical_key = "conversation-uri:" + hashlib.sha256(cap.conversation_uri.encode()).hexdigest()
            if cap.logical_key is not None and cap.logical_key != logical_key:
                raise StaleFenceError("logical conversation identity changed during the turn")
            if cap.logical_key is None:
                lease = self.durable.acquire_lease(
                    cap.run_id, cap.owner, logical_key,
                    operation_id=cap.operation_id, ttl_s=120,
                )
                cap.logical_key = logical_key
                cap.logical_fence = lease["fencing_token"]
            else:
                if cap.logical_fence is None:
                    raise StaleFenceError("logical conversation lease fence is missing")
                self.durable.renew_lease(logical_key, cap.owner, cap.logical_fence, ttl_s=120)
        conversation = tab.get("conversationKey")
        if isinstance(conversation, str) and conversation:
            conversation_key = "conversation:" + hashlib.sha256(conversation.encode()).hexdigest()
            if cap.conversation_key is not None and cap.conversation_key != conversation_key:
                raise StaleFenceError("conversation changed during the turn")
            if cap.conversation_key is None:
                lease = self.durable.acquire_lease(cap.run_id, cap.owner, conversation_key,
                                                    operation_id=cap.operation_id, ttl_s=120)
                cap.conversation_key = conversation_key
                cap.conversation_fence = lease["fencing_token"]
            else:
                if cap.conversation_fence is None:
                    raise StaleFenceError("conversation lease fence is missing")
                self.durable.renew_lease(conversation_key, cap.owner, cap.conversation_fence, ttl_s=120)

    def _advance_phase(self, cap: TurnCapability, trace_id: str) -> None:
        if cap.trace_id is None or cap.trace_id == trace_id:
            cap.trace_id = trace_id
            return
        state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
        if state != "SUCCEEDED":
            raise StaleFenceError("previous browser phase has not completed")
        for key, fence in ((cap.logical_key, cap.logical_fence),
                           (cap.conversation_key, cap.conversation_fence),
                           (cap.physical_key, cap.physical_fence)):
            if key is not None and fence is not None:
                self.durable.release_lease(key, cap.owner, fence)
        operation = self.durable.create_operation(
            cap.run_id, cap.owner, kind="chatgpt-web-browser-phase",
            idempotency_key="browser-phase:" + trace_id, initial_state="RUNNING",
        )
        cap.operation_id = operation["operation_id"]
        cap.trace_id = trace_id
        cap.broker_registered = False
        cap.physical_key = None
        cap.physical_fence = None
        cap.logical_key = None
        cap.logical_fence = None
        cap.conversation_key = None
        cap.conversation_fence = None
        cap.completed_revision = None
        cap.allowed_tools = None

    def authorize(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = payload.get("capability")
        trace_id = payload.get("traceId")
        if not isinstance(token, str) or not token:
            raise ValueError("invalid turn capability")
        if not isinstance(trace_id, str) or not trace_id or len(trace_id) > 128:
            raise ValueError("invalid turn trace")
        with self.lock:
            cap = self._capability(token)
            state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            if cap.trace_id is not None and cap.trace_id != trace_id:
                if action not in {"register", "browser-start"}:
                    raise StaleFenceError("TurnCapability belongs to another browser phase")
                self._advance_phase(cap, trace_id)
                state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            if action == "register":
                if state != "RUNNING":
                    raise StaleFenceError("turn operation is no longer running")
                raw_tools = payload.get("allowedTools")
                if not isinstance(raw_tools, list) or len(raw_tools) > 512:
                    raise ValueError("allowedTools must be a list with at most 512 entries")
                allowed_tools: set[str] = set()
                for item in raw_tools:
                    if (not isinstance(item, str) or not item or len(item) > 256
                            or any(char in item for char in ("\n", "\r", "\x00"))):
                        raise ValueError("invalid allowed tool name")
                    allowed_tools.add(item)
                cap.trace_id = trace_id
                cap.broker_registered = True
                cap.allowed_tools = frozenset(allowed_tools)
                self.durable.heartbeat(
                    cap.operation_id,
                    cap.owner,
                    progress={
                        "trace_id": trace_id,
                        "broker_registered": True,
                        "conversation_uri": cap.conversation_uri,
                        "allowed_tools": sorted(cap.allowed_tools),
                    },
                )
                return {"authorized": True, "run_id": cap.run_id, "operation_id": cap.operation_id}
            if action == "browser-start":
                if state != "RUNNING":
                    raise StaleFenceError("turn operation is no longer running")
                cap.trace_id = trace_id
                self._bind_physical(cap, trace_id)
                self.durable.heartbeat(cap.operation_id, cap.owner,
                                       progress={"trace_id": trace_id,
                                                 "broker_registered": cap.broker_registered,
                                                 "physical_resource": cap.physical_key,
                                                 "conversation_uri": cap.conversation_uri},
                                       resource_key=cap.physical_key, fencing_token=cap.physical_fence)
                return {"authorized": True, "operation_id": cap.operation_id,
                        "physical_resource": cap.physical_key}
            if cap.trace_id is None:
                raise PermissionError("TurnCapability has not been registered by the broker")
            if action == "browser-heartbeat":
                if state != "RUNNING":
                    raise StaleFenceError("turn operation is no longer running")
                self._bind_physical(cap, trace_id)
                self.durable.heartbeat(
                    cap.operation_id, cap.owner,
                    progress={"trace_id": trace_id,
                              "broker_registered": cap.broker_registered,
                              "physical_resource": cap.physical_key,
                              "conversation_uri": cap.conversation_uri},
                    resource_key=cap.physical_key, fencing_token=cap.physical_fence,
                )
                return {"authorized": True, "operation_id": cap.operation_id,
                        "physical_resource": cap.physical_key}
            if action == "browser-complete":
                if cap.broker_registered or state != "RUNNING":
                    raise StaleFenceError("read-only browser completion is unavailable")
                self._bind_physical(cap, trace_id)
                self.durable.update_operation(
                    cap.operation_id, cap.owner, state="SUCCEEDED", event_type="WEB_BROWSER_FENCED",
                    result={"trace_id": trace_id, "physical_resource": cap.physical_key,
                            "conversation_uri": cap.conversation_uri},
                    resource_key=cap.physical_key, fencing_token=cap.physical_fence,
                )
                return {"authorized": True}
            if action in {"prepare", "complete"} and state == "SUCCEEDED" and cap.completed_revision == payload.get("revision"):
                return {"authorized": True, "idempotent_replay": True}
            if state != "RUNNING":
                raise StaleFenceError("turn operation is no longer running")
            if action not in {"tool", "prepare", "complete"}:
                raise ValueError("invalid turn authority action")
            self._bind_physical(cap, trace_id)
            if action == "tool":
                wire_name = payload.get("wireName")
                if not isinstance(wire_name, str) or not wire_name or len(wire_name) > 256:
                    raise ValueError("invalid tool name")
                if cap.allowed_tools is None:
                    raise PermissionError("turn tool contract was not registered")
                if wire_name not in cap.allowed_tools:
                    raise PermissionError("tool is outside the TurnCapability allowlist")
                self.durable.heartbeat(cap.operation_id, cap.owner,
                                       progress={"tool": wire_name, "physical_resource": cap.physical_key},
                                       resource_key=cap.physical_key, fencing_token=cap.physical_fence)
                self.durable.record_capabilities_used(cap.run_id, cap.owner, ["model:chatgpt-web", "browser:physical-tab", "tool:" + wire_name])
            else:
                revision = payload.get("revision")
                if not isinstance(revision, int) or revision < 0:
                    raise ValueError("invalid broker completion revision")
                if action == "prepare":
                    self.durable.heartbeat(cap.operation_id, cap.owner,
                                           progress={"completion_revision": revision,
                                                     "physical_resource": cap.physical_key},
                                           resource_key=cap.physical_key, fencing_token=cap.physical_fence)
                    return {"authorized": True, "prepared": True}
                self.durable.update_operation(
                    cap.operation_id, cap.owner, state="SUCCEEDED", event_type="WEB_TURN_FENCED",
                    result={"trace_id": trace_id, "broker_revision": revision,
                            "physical_resource": cap.physical_key,
                            "conversation_uri": cap.conversation_uri},
                    resource_key=cap.physical_key, fencing_token=cap.physical_fence,
                )
                cap.completed_revision = revision
            return {"authorized": True, "run_id": cap.run_id, "operation_id": cap.operation_id}

    def retire(self, token: str, *, failed: bool = False) -> None:
        with self.lock:
            cap = self._capability(token)
            state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            if os.getenv("SENTRA_GATEWAY_DEBUG_TURN", "").strip() == "1":
                print(
                    "SENTRA_TURN_RETIRE "
                    + json.dumps({
                        "trace_id": cap.trace_id,
                        "run_id": cap.run_id,
                        "operation_id": cap.operation_id,
                        "state_before": state,
                        "failed": failed,
                        "completed_revision": cap.completed_revision,
                    }, separators=(",", ":")),
                    flush=True,
                )
            if state == "RUNNING":
                self.durable.update_operation(cap.operation_id, cap.owner, state="UNCERTAIN",
                                              error={"reason": "broker completion fence was not committed"})
                state = "UNCERTAIN"
            for key, fence in ((cap.logical_key, cap.logical_fence),
                               (cap.conversation_key, cap.conversation_fence),
                               (cap.physical_key, cap.physical_fence)):
                if key is not None and fence is not None:
                    try:
                        self.durable.release_lease(key, cap.owner, fence)
                    except StaleFenceError:
                        pass
            self.capabilities.pop(cap.token_hash, None)
            delivered = state == "SUCCEEDED" and not failed
            if state == "SUCCEEDED" and failed:
                self.durable.checkpoint(cap.run_id, cap.owner, {"operation_id": cap.operation_id, "delivery_state": "UNCERTAIN"}, label="web-response-delivery")
            if cap.agent_id is not None and cap.goal_run_id is not None:
                self.durable.update_agent(
                    cap.agent_id,
                    cap.owner,
                    heartbeat=True,
                    metadata={
                        "last_turn_run_id": cap.run_id,
                        "last_turn_operation_id": cap.operation_id,
                        "last_turn_delivery": "DELIVERED" if delivered else "UNCERTAIN",
                        "last_turn_at": self.clock(),
                    },
                )
                self.durable.checkpoint(
                    cap.goal_run_id,
                    cap.owner,
                    {
                        "goal_id": cap.goal_id,
                        "agent_id": cap.agent_id,
                        "codex_thread_id": cap.codex_thread_id,
                        "turn_run_id": cap.run_id,
                        "turn_operation_id": cap.operation_id,
                        "delivery_state": "DELIVERED" if delivered else "UNCERTAIN",
                    },
                    label="codex-subagent-turn",
                )
            self.durable.transition_run(cap.run_id, cap.owner,
                                        "SUCCEEDED" if delivered else "BLOCKED",
                                        reason="Web turn completed and response delivery was confirmed" if delivered else "Web model execution or response delivery is uncertain")
