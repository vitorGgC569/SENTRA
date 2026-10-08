"""Persistent multi-provider swarm coordinated by SENTRA Control Plane.

The swarm is intentionally not an all-to-all chat room. Logical Agents keep stable
identity while provider conversations are replaceable. Knowledge flows through the
Context Bus; implementation authority remains with OMA + deterministic Quality Gate.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.rate_governor import ProviderRateGovernor
from orchestrator.turn_scheduler import ConversationTurnScheduler
from orchestrator.providers.extension_provider import BrowserExtensionProvider
from browser.extension_transport import ExtensionDeliveryError, ExtensionTransport
from browser.outcomes import classify_failure
from sentra_core.conversation import ConversationIdentity
from orchestrator.providers.gemini_web_provider import GeminiWebProvider
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.context_projection import ControlPlaneContextBridge
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService, DurableStateConflict


PHASES = (
    "discover",
    "peer_questions",
    "cross_review",
    "implement",
    "test",
    "challenge",
    "synthesize",
)

_RECOVERABLE_CONVERSATION_ERRORS = (
    "DEPENDENCY_ERROR: composer ausente",
    "CONVERSATION_HYDRATION_TIMEOUT",
    "CONVERSATION_MISMATCH",
    "STALE_CONVERSATION",
)

_Q_RE = re.compile(r"^\s*Q->([A-Za-z0-9_.-]{1,128})\s*:\s*(.+?)\s*$", re.MULTILINE)


class SwarmCollectionPending(RuntimeError):
    """A prompt is already sent; only read-only collection may resume."""


class SwarmDeliveryError(RuntimeError):
    """Provider failure carrying replay-safety evidence from the browser layer."""

    def __init__(
        self,
        message: str,
        *,
        delivery_state: str = "UNCERTAIN",
        retry_safe: bool = False,
    ) -> None:
        super().__init__(message)
        self.delivery_state = str(delivery_state or "UNCERTAIN")
        self.retry_safe = bool(retry_safe)


@dataclass(frozen=True)
class SwarmAgentSpec:
    role: str
    provider: str
    focus: str
    model: str | None = None
    capabilities: tuple[str, ...] = ("discover", "review")

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.role):
            raise ValueError(f"invalid swarm role: {self.role!r}")
        if self.provider not in {"chatgpt", "gemini"}:
            raise ValueError("swarm provider must be chatgpt or gemini")
        if self.provider == "gemini" and (self.model or "flash") not in {
            "flash-lite", "flash", "pro"
        }:
            raise ValueError("Gemini swarm model must be flash-lite, flash or pro")
        if not str(self.focus or "").strip():
            raise ValueError("swarm agent focus is required")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SwarmAgentSpec":
        item = cls(
            role=str(value["role"]),
            provider=str(value["provider"]),
            focus=str(value.get("focus") or value["role"]),
            model=value.get("model"),
            capabilities=tuple(value.get("capabilities") or ("discover", "review")),
        )
        item.validate()
        return item


LEAN_SWARM_AGENTS: tuple[SwarmAgentSpec, ...] = (
    SwarmAgentSpec(
        "gpt.implementation", "chatgpt",
        "implementation design, code changes and integration boundaries",
        capabilities=("discover", "review", "implement", "synthesize"),
    ),
    SwarmAgentSpec(
        "gemini.adversarial", "gemini",
        "falsification, browser risks, tests and release evidence",
        model="flash",
        capabilities=("discover", "review", "test"),
    ),
)


DEFAULT_SWARM_AGENTS: tuple[SwarmAgentSpec, ...] = (
    SwarmAgentSpec(
        "gpt.arch", "chatgpt",
        "architecture, Control Plane, Durable Core and invariants",
        capabilities=("discover", "review", "synthesize"),
    ),
    SwarmAgentSpec(
        "gpt.implementation", "chatgpt",
        "implementation design, code changes and integration boundaries",
        capabilities=("discover", "review", "implement"),
    ),
    SwarmAgentSpec(
        "gpt.security", "chatgpt",
        "security, leases, fencing, idempotency, recovery and tunnel boundaries",
        capabilities=("discover", "review"),
    ),
    SwarmAgentSpec(
        "gemini.browser", "gemini",
        "Edge relay, web-model DOM protocol and browser failure modes",
        model="flash", capabilities=("discover", "review"),
    ),
    SwarmAgentSpec(
        "gemini.adversarial", "gemini",
        "races, false-success, hidden coupling and falsification",
        model="flash", capabilities=("discover", "review"),
    ),
    SwarmAgentSpec(
        "gemini.tests", "gemini",
        "tests, reproducibility, E2E evidence and release gates",
        model="flash", capabilities=("discover", "review", "test"),
    ),
    SwarmAgentSpec(
        "gemini.product", "gemini",
        "product UX, diagnostics, installer, update and rollback",
        model="flash", capabilities=("discover", "review"),
    ),
)


class _PinnedRunBridge:
    """Present one durable swarm Run to an OMA run with a different local id."""

    def __init__(self, inner: ControlPlaneContextBridge, run_id: str) -> None:
        self.inner = inner
        self.run_id = run_id

    def prepare(self, **kwargs):
        kwargs["run_id"] = self.run_id
        return self.inner.prepare(**kwargs)

    def acknowledge(self, **kwargs):
        kwargs["run_id"] = self.run_id
        return self.inner.acknowledge(**kwargs)

    def publish_response(self, **kwargs):
        kwargs["run_id"] = self.run_id
        return self.inner.publish_response(**kwargs)


class PersistentSwarm:
    """Durable ChatGPT+Gemini swarm with bounded targeted collaboration."""

    def __init__(
        self,
        state_root: Path,
        *,
        relay_base: str = "http://127.0.0.1:8765",
        relay_token: str | None = None,
        provider_intervals: dict[str, float] | None = None,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.swarm_root = self.state_root / "swarms"
        self.swarm_root.mkdir(parents=True, exist_ok=True)
        self.durable = DurableRunService(self.state_root)
        self.context = ContextBusService(self.state_root)
        self.control = ControlPlaneService(self.durable, self.context)
        self.relay_base = relay_base
        self._relay_token = relay_token
        self.provider_intervals = {
            "chatgpt": 30.0,
            "gemini": 15.0,
            **{str(k): float(v) for k, v in (provider_intervals or {}).items()},
        }

    def close(self) -> None:
        self.context.close()
        self.durable.close()

    def _manifest_path(self, run_id: str) -> Path:
        return self.swarm_root / run_id / "manifest.json"

    def _round_dir(self, run_id: str, round_no: int) -> Path:
        return self.swarm_root / run_id / "rounds" / str(round_no)

    def _output_path(self, run_id: str, round_no: int, phase: str, role: str) -> Path:
        return self._round_dir(run_id, round_no) / phase / f"{role}.txt"

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        manifest["updated_at"] = time.time()
        self._atomic_json(self._manifest_path(str(manifest["run_id"])), manifest)

    @staticmethod
    def _reconcile_legacy_pre_send_delivery(manifest: dict[str, Any]) -> bool:
        """Upgrade old manifests only when source ordering proves NOT_SENT."""
        changed = False
        for round_state in (manifest.get("rounds") or {}).values():
            if not isinstance(round_state, dict):
                continue
            for phase_state in (round_state.get("phases") or {}).values():
                if not isinstance(phase_state, dict):
                    continue
                deliveries = phase_state.get("deliveries") or {}
                if not isinstance(deliveries, dict):
                    continue
                for delivery in deliveries.values():
                    if not isinstance(delivery, dict):
                        continue
                    if str(delivery.get("state") or "") != "UNCERTAIN":
                        continue
                    error = str(delivery.get("error") or "")
                    if "MODEL_SELECTION_FAILED" not in error:
                        continue
                    delivery.update({
                        "state": "NOT_SENT",
                        "retry_safe": True,
                        "reconciled_from": "UNCERTAIN",
                        "reconcile_reason": "MODEL_SELECTION_FAILED is pre-SEND_MESSAGE",
                    })
                    changed = True
        return changed

    def load_manifest(self, run_id: str) -> dict[str, Any]:
        path = self._manifest_path(run_id)
        if not path.is_file():
            raise FileNotFoundError("swarm run not found")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            raise ValueError("invalid swarm manifest")
        if self._reconcile_legacy_pre_send_delivery(value):
            self._save_manifest(value)
        return value

    def _token(self) -> str:
        if self._relay_token:
            return self._relay_token
        token_path = self.state_root / "browser" / "relay-token"
        if not token_path.is_file():
            # Development checkout compatibility.
            token_path = self.state_root / "relay-token"
        if not token_path.is_file():
            raise RuntimeError(
                "SENTRA Edge relay token not found; pair the principal Edge extension first"
            )
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 16:
            raise RuntimeError("invalid SENTRA Edge relay token")
        return token

    @staticmethod
    def _owner(run_id: str) -> str:
        return f"swarm:{run_id}"

    @staticmethod
    def _seat(run_id: str, role: str) -> str:
        return f"{run_id}:{role}"

    def _bridge(self, manifest: dict[str, Any]) -> ControlPlaneContextBridge:
        return ControlPlaneContextBridge(
            self.control,
            str(manifest["owner"]),
            max_chars=int(manifest.get("max_context_chars", 10000)),
            max_items=int(manifest.get("max_context_items", 100)),
        )

    def create(
        self,
        goal: str,
        *,
        workspace: str | None = None,
        run_id: str | None = None,
        agents: Iterable[SwarmAgentSpec] = DEFAULT_SWARM_AGENTS,
        acceptance_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        objective = str(goal or "").strip()
        if not objective:
            raise ValueError("swarm goal is required")
        specs = tuple(agents)
        if not 2 <= len(specs) <= 16:
            raise ValueError("swarm requires 2..16 logical agents")
        roles: set[str] = set()
        for spec in specs:
            spec.validate()
            if spec.role in roles:
                raise ValueError(f"duplicate swarm role: {spec.role}")
            roles.add(spec.role)

        rid = run_id or ("swarm-" + uuid.uuid4().hex[:16])
        owner = self._owner(rid)
        run = self.durable.create_run(
            owner,
            workspace=workspace,
            run_id=rid,
            idempotency_key="swarm:create",
            required_capabilities=[
                "control_plane", "shared_context", "browser_control",
            ],
        )
        root_goal = self.control.create_goal(
            rid,
            owner,
            objective=objective,
            acceptance_criteria=acceptance_criteria or [],
            constraints=constraints or [],
            priority="HIGH",
            external_key="swarm-root",
            metadata={"kind": "persistent-multi-provider-swarm"},
        )
        bridge = ControlPlaneContextBridge(self.control, owner)
        for spec in specs:
            seat = self._seat(rid, spec.role)
            self.control.ensure_agent(
                rid,
                owner,
                agent_id=bridge._agent_id(seat),
                role=spec.role,
                goal_id=root_goal["goal_id"],
                metadata={
                    "seat": seat,
                    "provider": spec.provider,
                    "model": spec.model,
                    "focus": spec.focus,
                    "capabilities": list(spec.capabilities),
                    "source": "persistent-swarm",
                },
            )

        now = time.time()
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "authority": "durable-core",
            "run_id": rid,
            "owner": owner,
            "goal_id": root_goal["goal_id"],
            "goal": objective,
            "workspace": workspace,
            "agents": [asdict(spec) for spec in specs],
            "rounds_completed": 0,
            "active_round": 0,
            "rounds": {},
            "quality_gate": {"green": False, "status": "NOT_RUN"},
            "max_context_chars": 10000,
            "max_context_items": 100,
            "created_at": now,
            "updated_at": now,
        }
        self._save_manifest(manifest)
        return self.status(rid)

    def status(self, run_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        run = self.durable.run_status(run_id, str(manifest["owner"]))
        chats = {
            str(item.get("agent_id")): {
                "chat_id": item.get("chat_id"),
                "provider": item.get("provider"),
                "conversation_id": item.get("conversation_id"),
                "conversation_url": item.get("conversation_url"),
                "state": item.get("state"),
            }
            for item in run.get("chats", [])
        }
        logical_agents = []
        for spec_dict in manifest["agents"]:
            spec = SwarmAgentSpec.from_dict(spec_dict)
            seat = self._seat(run_id, spec.role)
            aid = ControlPlaneContextBridge._agent_id(seat)
            logical_agents.append({
                **spec_dict,
                "agent_id": aid,
                "chat": chats.get(aid),
            })
        return {
            "run_id": run_id,
            "state": run["state"],
            "goal_id": manifest["goal_id"],
            "goal": manifest["goal"],
            "workspace": manifest.get("workspace"),
            "rounds_completed": manifest.get("rounds_completed", 0),
            "active_round": manifest.get("active_round", 0),
            "quality_gate": manifest.get("quality_gate"),
            "agents": logical_agents,
        }

    def list_runs(self, limit: int = 100) -> dict[str, Any]:
        if not 1 <= int(limit) <= 1000:
            raise ValueError("limit must be 1..1000")
        items: list[dict[str, Any]] = []
        candidates = sorted(
            (path for path in self.swarm_root.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates[: int(limit)]:
            try:
                items.append(self.status(path.name))
            except Exception as exc:
                items.append({
                    "run_id": path.name,
                    "state": "INVALID",
                    "error": str(exc)[:500],
                })
        return {"items": items, "count": len(items)}

    def chats(self, run_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        run = self.durable.run_status(run_id, str(manifest["owner"]))
        return {
            "run_id": run_id,
            "state": run["state"],
            "items": list(run.get("chats", [])),
        }

    def pause(self, run_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        owner = str(manifest["owner"])
        run = self.durable.run_status(run_id, owner)
        state = str(run["state"])
        if state == "PAUSED":
            return self.status(run_id)
        if state not in {"CREATED", "RUNNING"}:
            raise RuntimeError(
                f"SWARM_PAUSE_UNAVAILABLE: run state {state} cannot transition to PAUSED"
            )
        self.durable.transition_run(
            run_id, owner, "PAUSED", reason="operator paused persistent swarm"
        )
        goal = self.control.goal_info(str(manifest["goal_id"]), owner)
        if goal.get("state") == "ACTIVE":
            self.control.update_goal(
                str(manifest["goal_id"]),
                owner,
                state="PAUSED",
                reason="operator paused persistent swarm",
            )
        return self.status(run_id)

    def resume(self, run_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        owner = str(manifest["owner"])
        run = self.durable.run_status(run_id, owner)
        state = str(run["state"])
        if state == "RUNNING":
            return self.status(run_id)
        if state not in {"PAUSED", "RECOVERING", "BLOCKED"}:
            raise RuntimeError(
                f"SWARM_RESUME_UNAVAILABLE: run state {state} cannot transition to RUNNING"
            )
        self.durable.transition_run(
            run_id, owner, "RUNNING", reason="operator resumed persistent swarm"
        )
        goal = self.control.goal_info(str(manifest["goal_id"]), owner)
        if goal.get("state") in {"PAUSED", "BLOCKED"}:
            self.control.update_goal(
                str(manifest["goal_id"]),
                owner,
                state="ACTIVE",
                reason="operator resumed persistent swarm",
            )
        return self.status(run_id)

    def cancel(self, run_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        owner = str(manifest["owner"])
        run = self.durable.run_status(run_id, owner)
        cancelled_ops: list[dict[str, Any]] = []
        for op in run.get("operations", []):
            state = str(op.get("state") or "")
            if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                continue
            progress = dict(op.get("progress") or {})
            delivery_state = str(progress.get("delivery_state") or "")
            try:
                if state == "UNCERTAIN":
                    updated = self.durable.update_operation(
                        op["operation_id"],
                        owner,
                        state="CANCELLED",
                        event_type="SWARM_TURN_CANCELLED_BY_OPERATOR",
                        progress={"operator_cancelled": True},
                    )
                else:
                    side_effect = delivery_state not in {"", "NOT_SENT"}
                    updated = self.durable.request_cancel(
                        op["operation_id"],
                        owner,
                        side_effect_may_have_started=side_effect,
                    )
                cancelled_ops.append({
                    "operation_id": updated["operation_id"],
                    "state": updated["state"],
                })
            except DurableStateConflict:
                continue

        run = self.durable.run_status(run_id, owner)
        if run["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            self.durable.transition_run(
                run_id,
                owner,
                "CANCELLED",
                reason="operator cancelled persistent swarm; in-flight provider effects are not replayed",
            )
        goal = self.control.goal_info(str(manifest["goal_id"]), owner)
        if goal.get("state") not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            self.control.update_goal(
                str(manifest["goal_id"]),
                owner,
                state="CANCELLED",
                reason="operator cancelled persistent swarm",
            )
        result = self.status(run_id)
        result["cancelled_operations"] = cancelled_ops
        return result

    def reconcile(self, run_id: str, *, stale_after_s: float = 120.0) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        owner = str(manifest["owner"])
        durable_report = self.durable.reconcile(
            run_id, owner, stale_after_s=stale_after_s
        )
        run = self.durable.run_status(run_id, owner)
        actions: list[dict[str, Any]] = []
        for op in run.get("operations", []):
            if op.get("kind") != "swarm.agent_turn":
                continue
            progress = dict(op.get("progress") or {})
            error = dict(op.get("error") or {})
            state = str(op.get("state") or "")
            delivery_state = str(
                progress.get("delivery_state")
                or error.get("delivery_state")
                or ""
            )
            item = {
                "operation_id": op.get("operation_id"),
                "state": state,
                "delivery_state": delivery_state or None,
                "round": progress.get("round"),
                "phase": progress.get("phase"),
                "role": progress.get("role"),
                "provider": progress.get("provider"),
            }
            if state == "SUCCEEDED":
                item["action"] = "NO_ACTION"
            elif state == "FAILED" and delivery_state == "NOT_SENT":
                item["action"] = "SAFE_NEW_ATTEMPT"
                item["automatic_replay"] = False
            elif state == "WAITING_EXTERNAL" and progress.get("conversation_url"):
                item["action"] = "COLLECT_ONLY"
                item["automatic_replay"] = False
            elif state == "UNCERTAIN":
                item["action"] = "MANUAL_EVIDENCE_REQUIRED"
                item["automatic_replay"] = False
            elif state == "CANCEL_REQUESTED":
                item["action"] = "AWAIT_PROVIDER_SETTLEMENT"
                item["automatic_replay"] = False
            else:
                item["action"] = "OBSERVE"
            actions.append(item)
        return {
            "run_id": run_id,
            "status": self.status(run_id),
            "durable": durable_report,
            "swarm_actions": actions,
            "auto_replay": False,
        }

    async def cleanup(self, run_id: str, *, timeout_s: int = 30) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        owner = str(manifest["owner"])
        run = self.durable.run_status(run_id, owner)
        transport = ExtensionTransport(self.relay_base, token=self._token())
        result: dict[str, Any] = {
            "run_id": run_id,
            "cleared": [],
            "retained": [],
            "failed": [],
        }
        for chat in run.get("chats", []):
            url = str(chat.get("conversation_url") or "").strip()
            if not url:
                continue
            try:
                identity = ConversationIdentity.parse(url)
                response = await transport.delete_chat(
                    identity.canonical_url,
                    timeout_s=timeout_s,
                    provider=identity.provider,
                )
                if response.get("status") == "COMPLETED":
                    try:
                        self.durable.update_chat(
                            chat["chat_id"],
                            owner,
                            state="DISCONNECTED",
                            desired_state="IDLE",
                            metadata={
                                "cleanup_status": "deleted",
                                "cleanup_at": time.time(),
                            },
                            event_type="SWARM_CHAT_CLEANED",
                        )
                    except DurableStateConflict:
                        pass
                    result["cleared"].append({
                        "chat_id": chat["chat_id"],
                        "provider": identity.provider,
                        "conversation_url": identity.canonical_url,
                    })
                elif response.get("retained"):
                    try:
                        self.durable.update_chat(
                            chat["chat_id"],
                            owner,
                            desired_state="IDLE",
                            metadata={
                                "cleanup_status": "retained",
                                "cleanup_reason": response.get("reason"),
                                "cleanup_at": time.time(),
                            },
                            event_type="SWARM_CHAT_RETAINED",
                        )
                    except DurableStateConflict:
                        pass
                    result["retained"].append({
                        "chat_id": chat["chat_id"],
                        "provider": identity.provider,
                        "conversation_url": identity.canonical_url,
                        "reason": response.get("reason"),
                    })
                else:
                    result["failed"].append({
                        "chat_id": chat["chat_id"],
                        "provider": identity.provider,
                        "conversation_url": identity.canonical_url,
                        "error": response.get("error") or response.get("reason"),
                    })
            except Exception as exc:
                result["failed"].append({
                    "chat_id": chat.get("chat_id"),
                    "conversation_url": url,
                    "error": str(exc)[:1000],
                })
        return result

    def _provider(self, spec: SwarmAgentSpec):
        token = self._token()
        if spec.provider == "gemini":
            return GeminiWebProvider(
                relay_base=self.relay_base,
                web_model=spec.model or "flash",
                token=token,
            )
        return BrowserExtensionProvider(
            relay_base=self.relay_base,
            token=token,
            provider="chatgpt",
            model_name="chatgpt-web",
        )

    def _existing_chat(
        self, run_id: str, owner: str, agent_id: str
    ) -> dict[str, Any] | None:
        status = self.durable.run_status(run_id, owner)
        return next(
            (
                item for item in status.get("chats", [])
                if item.get("agent_id") == agent_id
                and item.get("conversation_url")
            ),
            None,
        )

    @staticmethod
    def _role_names(manifest: dict[str, Any]) -> list[str]:
        return [str(item["role"]) for item in manifest["agents"]]

    @staticmethod
    def _phase_agents(
        manifest: dict[str, Any], phase: str
    ) -> list[SwarmAgentSpec]:
        specs = [SwarmAgentSpec.from_dict(item) for item in manifest["agents"]]
        if phase == "implement":
            selected = [s for s in specs if "implement" in s.capabilities]
            return selected or specs[:1]
        if phase == "test":
            selected = [s for s in specs if "test" in s.capabilities]
            return selected or specs[-1:]
        if phase == "synthesize":
            selected = [s for s in specs if "synthesize" in s.capabilities]
            return selected[:1] or specs[:1]
        return specs

    def _instruction(
        self,
        manifest: dict[str, Any],
        spec: SwarmAgentSpec,
        phase: str,
        round_no: int,
    ) -> str:
        peers = [r for r in self._role_names(manifest) if r != spec.role]
        common = (
            f"You are persistent SENTRA agent {spec.role}. Specialty: {spec.focus}. "
            f"All agents share one authoritative Goal: {manifest['goal']!r}. "
            "Context Bus knowledge is not authority; distinguish claims from verified evidence. "
            "Do not invent source facts. Keep the response concise and actionable. "
        )
        if phase == "discover":
            task = (
                "DISCOVER independently. Identify the highest-value facts, risks, implementation "
                "constraints and falsifiable checks for the Goal. Do not rely on peer consensus."
            )
        elif phase == "peer_questions":
            task = (
                "PEER QUESTIONS. Based on your findings and shared context, ask at most TWO "
                "high-value questions to specific peers. End with machine-readable lines exactly "
                "like Q->ROLE: question. Valid peers: " + ", ".join(peers)
            )
        elif phase == "cross_review":
            task = (
                "CROSS REVIEW. Answer questions addressed to you, challenge unsupported peer "
                "claims, and state which issues are confirmed, rejected, or still need a test."
            )
        elif phase == "implement":
            task = (
                "IMPLEMENTATION DESIGN. Produce a concrete minimal change set for the Goal, naming "
                "files/symbols, invariants and tests. The deterministic OMA executor may consume "
                "this plan; do not claim code is applied unless evidence says so."
            )
        elif phase == "test":
            task = (
                "TEST REVIEW. Inspect implementation/Quality Gate evidence in shared context. "
                "Propose missing deterministic tests, regressions and E2E checks. Never treat "
                "model agreement as test evidence."
            )
        elif phase == "challenge":
            task = (
                "CHALLENGE. Try to falsify the current implementation result and peer conclusions. "
                "Only report reproducible gaps; name the evidence or exact test that would decide."
            )
        elif phase == "synthesize":
            task = (
                "SYNTHESIZE the round. Produce: CONFIRMED, REJECTED, NEEDS_TEST, IMPLEMENTATION, "
                "QUALITY_GATE. Do not mark success unless deterministic Quality Gate evidence is green."
            )
        else:
            raise ValueError(f"unsupported swarm phase: {phase}")
        return common + f" Round {round_no}. " + task

    def _save_output(
        self, run_id: str, round_no: int, phase: str, role: str, text: str
    ) -> Path:
        """Write projection output atomically; Durable artifact is authority."""
        path = self._output_path(run_id, round_no, phase, role)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{role}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(str(text))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path

    @staticmethod
    def turn_idempotency_key(
        round_no: int,
        phase: str,
        role: str,
        prompt_hash: str,
        attempt: int = 0,
    ) -> str:
        raw = f"{round_no}|{phase}|{role}|{prompt_hash}|{attempt}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]
        safe_role = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(role))[:48]
        safe_phase = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(phase))[:32]
        return f"swarm-turn:r{int(round_no)}:{safe_phase}:{safe_role}:a{int(attempt)}:{digest}"

    @staticmethod
    def _turn_resource_key(run_id: str, round_no: int, phase: str, role: str) -> str:
        raw = f"{run_id}|{round_no}|{phase}|{role}"
        return "swarm-turn:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]

    @staticmethod
    def _controller_resource_key(run_id: str) -> str:
        return "swarm-controller:" + hashlib.sha256(
            str(run_id).encode("utf-8")
        ).hexdigest()[:48]

    def _governor(self, run_id: str) -> ProviderRateGovernor:
        del run_id
        return ProviderRateGovernor(
            self.provider_intervals,
            state_path=self.state_root / "provider-rate.json",
        )

    async def _controller_lease_heartbeat(
        self,
        resource_key: str,
        owner: str,
        fencing_token: int,
        stop: asyncio.Event,
        failure: list[BaseException],
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=30.0)
                break
            except asyncio.TimeoutError:
                pass
            try:
                self.durable.renew_lease(
                    resource_key, owner, fencing_token, ttl_s=90.0
                )
            except BaseException as exc:
                failure.append(exc)
                stop.set()
                break

    def _turn_operation(
        self,
        manifest: dict[str, Any],
        spec: SwarmAgentSpec,
        phase: str,
        round_no: int,
        delivery: dict[str, Any],
    ) -> tuple[dict[str, Any], int, str]:
        rid = str(manifest["run_id"])
        owner = str(manifest["owner"])
        logical_prompt = self._instruction(manifest, spec, phase, round_no)
        logical_hash = hashlib.sha256(logical_prompt.encode("utf-8")).hexdigest()
        attempt = max(0, int(delivery.get("attempt", 0) or 0))
        if str(delivery.get("state") or "") == "NOT_SENT":
            attempt += 1
        for _ in range(32):
            key = self.turn_idempotency_key(
                round_no, phase, spec.role, logical_hash, attempt
            )
            op = self.durable.create_operation(
                rid,
                owner,
                kind="swarm.agent_turn",
                idempotency_key=key,
                cleanup_policy="preserve",
                initial_state="QUEUED",
            )
            if (
                op.get("idempotent_replay")
                and op.get("state") == "FAILED"
                and (op.get("error") or {}).get("delivery_state") == "NOT_SENT"
                and bool((op.get("error") or {}).get("retry_safe"))
            ):
                attempt += 1
                continue
            delivery.update(
                attempt=attempt,
                operation_id=op["operation_id"],
                idempotency_key=key,
                new_operation=not bool(op.get("idempotent_replay", False)),
            )
            return op, attempt, logical_hash
        raise RuntimeError("swarm turn retry-attempt bound exceeded")

    def _restore_succeeded_turn(
        self, op: dict[str, Any], owner: str
    ) -> AgentResponse:
        result = dict(op.get("result") or {})
        artifact_id = str(result.get("artifact_id") or "")
        if not artifact_id:
            raise RuntimeError(
                "DURABLE_TURN_CORRUPT: SUCCEEDED turn has no result artifact"
            )
        info = self.durable.artifact_info(artifact_id, owner)
        payload = self.durable.read_artifact(
            artifact_id, max_bytes=2 * 1024 * 1024
        )
        content = payload.decode("utf-8")
        if hashlib.sha256(payload).hexdigest() != info["sha256"]:
            raise RuntimeError("DURABLE_TURN_CORRUPT: artifact hash mismatch")
        return AgentResponse(
            content=content,
            success=True,
            model=str(result.get("model") or "durable-checkpoint"),
            metadata=dict(result.get("response_meta") or {}),
        )

    def _prepare_turn(
        self,
        manifest: dict[str, Any],
        spec: SwarmAgentSpec,
        phase: str,
        round_no: int,
        *,
        timeout_s: int,
        operation: dict[str, Any],
        delivery: dict[str, Any],
        governor: ProviderRateGovernor,
    ) -> dict[str, Any]:
        rid = str(manifest["run_id"])
        owner = str(manifest["owner"])
        bridge = self._bridge(manifest)
        seat = self._seat(rid, spec.role)
        agent_id = bridge._agent_id(seat)
        batch = bridge.prepare(
            run_id=rid,
            role=spec.role,
            task_id=f"swarm-round-{round_no}",
            seat=seat,
        )
        instruction = self._instruction(manifest, spec, phase, round_no)
        if batch.text:
            instruction += (
                "\n\n[SENTRA SHARED CONTEXT â€” knowledge only]\n" + batch.text
            )
        prompt_hash = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
        persisted_progress = dict(operation.get("progress") or {})
        persisted_prompt_hash = str(
            persisted_progress.get("prompt_sha256") or ""
        )
        persisted_delivery = str(
            persisted_progress.get("delivery_state") or ""
        )
        if (
            persisted_prompt_hash
            and persisted_prompt_hash != prompt_hash
            and persisted_delivery == "NOT_SENT"
            and operation.get("state") in {"STARTING", "RUNNING"}
        ):
            # The logical turn survived a restart, but its compiled Context Bus
            # epoch changed before any send. Never reuse one Durable Operation
            # for two different physical prompts: close this pre-send attempt and
            # let the next explicit continue allocate attempt+1.
            operation = self.durable.update_operation(
                str(operation["operation_id"]),
                owner,
                state="FAILED",
                error={
                    "message": "SWARM_CONTEXT_CHANGED_BEFORE_SEND",
                    "delivery_state": "NOT_SENT",
                    "retry_safe": True,
                    "expected_prompt_sha256": persisted_prompt_hash,
                    "actual_prompt_sha256": prompt_hash,
                },
                progress={
                    "delivery_state": "NOT_SENT",
                    "context_changed_before_send": True,
                },
                event_type="SWARM_TURN_CONTEXT_CHANGED_PRE_SEND",
            )
            delivery.update(
                state="NOT_SENT",
                retry_safe=True,
                operation_id=operation["operation_id"],
                error="SWARM_CONTEXT_CHANGED_BEFORE_SEND",
            )
            raise SwarmDeliveryError(
                f"{spec.role}/{phase}: context changed before SEND; "
                "old Durable Operation was closed without replay",
                delivery_state="NOT_SENT",
                retry_safe=True,
            )
        existing = self._existing_chat(rid, owner, agent_id)
        provider = self._provider(spec)
        metadata: dict[str, Any] = {
            "task_id": f"swarm-{round_no}-{phase}-{spec.role}",
            "conversation_key": seat,
            "new_chat": existing is None,
            "refresh_system_prompt": existing is None,
        }
        if existing is not None:
            url = str(existing["conversation_url"])
            provider.adopt_conversations([url])
            metadata["conversation_url"] = url
        elif spec.provider == "chatgpt":
            metadata["chat_title"] = f"[SENTRA] {spec.role}"
        request = AgentRequest(
            role=spec.role,
            system_prompt=(
                f"You are {spec.role}, a persistent SENTRA swarm specialist. "
                f"Specialty: {spec.focus}."
            ),
            user_prompt=instruction,
            timeout=max(30, min(int(timeout_s), 900)),
            max_output_tokens=1400,
            metadata=metadata,
        )
        renderer = getattr(provider, "render_prompt", None)
        prompt = renderer(request) if callable(renderer) else (
            request.user_prompt
            if existing is not None
            else f"{request.system_prompt}\n\n{request.user_prompt}"
        )
        if len(prompt) > 20000:
            raise SwarmDeliveryError(
                f"{spec.role}/{phase}: [CONTEXT_BUDGET] prompt exceeds 20000 characters",
                delivery_state="NOT_SENT",
                retry_safe=True,
            )
        resource_key = self._turn_resource_key(
            rid, round_no, phase, spec.role
        )
        lease = self.durable.acquire_lease(
            rid,
            owner,
            resource_key,
            operation_id=str(operation["operation_id"]),
            ttl_s=900.0,
        )
        if operation["state"] == "QUEUED":
            operation = self.durable.update_operation(
                str(operation["operation_id"]),
                owner,
                state="STARTING",
                progress={
                    "round": round_no,
                    "phase": phase,
                    "role": spec.role,
                    "provider": spec.provider,
                    "agent_id": agent_id,
                    "delivery_state": "NOT_SENT",
                    "prompt_sha256": prompt_hash,
                },
                resource_key=resource_key,
                fencing_token=int(lease["fencing_token"]),
            )
        return {
            "manifest": manifest,
            "spec": spec,
            "phase": phase,
            "round_no": round_no,
            "owner": owner,
            "run_id": rid,
            "bridge": bridge,
            "seat": seat,
            "agent_id": agent_id,
            "batch": batch,
            "prompt_hash": prompt_hash,
            "existing": existing,
            "provider": provider,
            "request": request,
            "prompt": prompt,
            "operation": operation,
            "delivery": delivery,
            "resource_key": resource_key,
            "fencing_token": int(lease["fencing_token"]),
            "governor": governor,
        }

    def _release_turn_lease(self, prepared: dict[str, Any]) -> None:
        try:
            self.durable.release_lease(
                prepared["resource_key"],
                prepared["owner"],
                int(prepared["fencing_token"]),
            )
        except Exception:
            pass

    @staticmethod
    def _split_capable(prepared: dict[str, Any]) -> bool:
        transport = getattr(prepared["provider"], "transport", None)
        return bool(
            transport
            and callable(getattr(transport, "send_chat", None))
            and callable(getattr(transport, "collect_chat", None))
        )

    @staticmethod
    def _decode_send_terminal(
        result: dict[str, Any], provider: str, model: str | None
    ) -> dict[str, Any]:
        raw = result.get("result")
        decoded: dict[str, Any] = {}
        if isinstance(raw, str) and raw:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {}
            if isinstance(value, dict):
                decoded = value
        return {
            **decoded,
            "job_id": result.get("job_id"),
            "worker": result.get("worker"),
            "conversation_url": (
                result.get("conversation_url")
                or decoded.get("conversation_url")
            ),
            "conversation_id": (
                result.get("conversation_id")
                or decoded.get("conversation_id")
            ),
            "provider": provider,
            "model": model,
            "_needs_ack": True,
        }

    async def _record_split_sent(
        self,
        prepared: dict[str, Any],
        sent: dict[str, Any],
    ) -> dict[str, Any]:
        spec: SwarmAgentSpec = prepared["spec"]
        identity = ConversationIdentity.from_parts(
            spec.provider,
            str(sent.get("conversation_id") or ""),
            str(sent.get("conversation_url") or ""),
        )
        chat = self.control.bind_agent_chat(
            prepared["run_id"],
            prepared["owner"],
            agent_id=prepared["agent_id"],
            chat_id=prepared["bridge"]._chat_id(prepared["seat"]),
            role=spec.role,
            conversation_id=identity.conversation_id,
            conversation_url=identity.canonical_url,
            provider=identity.provider,
            task_id=f"swarm-round-{prepared['round_no']}",
            goal_id=str(prepared["manifest"]["goal_id"]),
            metadata={
                "seat": prepared["seat"],
                "source": "persistent-swarm",
                "operation_id": prepared["operation"]["operation_id"],
            },
        )
        self.durable.update_chat(
            chat["chat_id"],
            prepared["owner"],
            state="GENERATING",
            desired_state="READY",
            metadata={"operation_id": prepared["operation"]["operation_id"]},
            event_type="SWARM_CHAT_GENERATING",
        )
        try:
            self.durable.update_agent(
                prepared["agent_id"],
                prepared["owner"],
                state="WAITING",
                task_id=f"swarm-round-{prepared['round_no']}",
                chat_id=chat["chat_id"],
                metadata={
                    "active_operation_id": prepared["operation"]["operation_id"]
                },
                event_type="SWARM_AGENT_WAITING",
            )
        except DurableStateConflict:
            pass
        progress = {
            "round": prepared["round_no"],
            "phase": prepared["phase"],
            "role": spec.role,
            "provider": spec.provider,
            "agent_id": prepared["agent_id"],
            "chat_id": chat["chat_id"],
            "relay_job_id": sent.get("job_id"),
            "delivery_state": "SENT",
            "conversation_id": identity.conversation_id,
            "conversation_url": identity.canonical_url,
            "worker": sent.get("worker"),
            "prompt_sha256": prepared["prompt_hash"],
        }
        prepared["operation"] = self.durable.update_operation(
            prepared["operation"]["operation_id"],
            prepared["owner"],
            state="WAITING_EXTERNAL",
            progress=progress,
            resource_key=prepared["resource_key"],
            fencing_token=prepared["fencing_token"],
            event_type="SWARM_TURN_SENT",
        )
        prepared["delivery"].update(
            state="SENT",
            operation_id=prepared["operation"]["operation_id"],
            conversation_url=identity.canonical_url,
            conversation_id=identity.conversation_id,
            updated_at=time.time(),
        )
        job_id = str(sent.get("job_id") or "")
        if job_id:
            try:
                await prepared["provider"].transport.ack_job(job_id)
            except Exception:
                prepared["delivery"]["relay_ack_pending"] = True
        return {
            **sent,
            "conversation_url": identity.canonical_url,
            "conversation_id": identity.conversation_id,
            "prepared": prepared,
        }

    def _record_turn_failure(
        self,
        prepared: dict[str, Any],
        exc: BaseException,
        *,
        delivery_state: str,
        retry_safe: bool,
        phase: str = "",
        job_id: str | None = None,
    ) -> None:
        state = (
            "FAILED"
            if delivery_state == "NOT_SENT" and retry_safe
            else "UNCERTAIN"
        )
        error = {
            "message": str(exc)[:2000],
            "delivery_state": delivery_state,
            "retry_safe": bool(retry_safe),
            "phase": phase,
            "relay_job_id": job_id,
        }
        try:
            prepared["operation"] = self.durable.update_operation(
                prepared["operation"]["operation_id"],
                prepared["owner"],
                state=state,
                progress={
                    "delivery_state": delivery_state,
                    "relay_job_id": job_id,
                    "failure_phase": phase,
                },
                error=error,
                resource_key=prepared["resource_key"],
                fencing_token=prepared["fencing_token"],
                event_type="SWARM_TURN_FAILED",
            )
        finally:
            prepared["delivery"].update(
                state="NOT_SENT" if state == "FAILED" else "UNCERTAIN",
                retry_safe=bool(retry_safe and state == "FAILED"),
                error=str(exc)[:1000],
                operation_id=prepared["operation"]["operation_id"],
                updated_at=time.time(),
            )
            self._release_turn_lease(prepared)

    async def _resume_relay_send(
        self, prepared: dict[str, Any], job_id: str
    ) -> dict[str, Any]:
        transport = prepared["provider"].transport
        deadline = time.monotonic() + min(
            60.0, float(prepared["request"].timeout)
        )
        while time.monotonic() < deadline:
            result = await transport.inspect_job(job_id, timeout_s=5.0)
            if not result.get("pending"):
                if result.get("status") != "COMPLETED":
                    may_have_sent = bool(result.get("_may_have_sent"))
                    err = ExtensionDeliveryError(
                        str(result.get("error") or "resumed CHAT_SEND failed"),
                        delivery_state=(
                            "UNCERTAIN" if may_have_sent else "NOT_SENT"
                        ),
                        retry_safe=not may_have_sent,
                        phase=str(result.get("_delivery_phase") or ""),
                        job_id=job_id,
                    )
                    self._record_turn_failure(
                        prepared,
                        err,
                        delivery_state=err.delivery_state,
                        retry_safe=err.retry_safe,
                        phase=err.phase,
                        job_id=job_id,
                    )
                    try:
                        await transport.ack_job(job_id)
                    except Exception:
                        pass
                    raise SwarmDeliveryError(
                        str(err),
                        delivery_state=err.delivery_state,
                        retry_safe=err.retry_safe,
                    )
                sent = self._decode_send_terminal(
                    result,
                    prepared["spec"].provider,
                    prepared["spec"].model,
                )
                return await self._record_split_sent(prepared, sent)
            prepared["operation"] = self.durable.update_operation(
                prepared["operation"]["operation_id"],
                prepared["owner"],
                progress={
                    "relay_job_id": job_id,
                    "relay_phase": result.get("phase"),
                    "relay_may_have_sent": bool(
                        result.get("may_have_sent")
                    ),
                },
                resource_key=prepared["resource_key"],
                fencing_token=prepared["fencing_token"],
                event_type="SWARM_TURN_RELAY_OBSERVED",
            )
        self._release_turn_lease(prepared)
        raise RuntimeError(
            "SWARM_DISPATCH_STILL_RUNNING: existing relay job remains active; "
            "continue later without resending"
        )

    async def _start_split_turn(
        self, prepared: dict[str, Any]
    ) -> dict[str, Any]:
        op = self.durable.operation_status(
            prepared["operation"]["operation_id"],
            prepared["owner"],
        )
        prepared["operation"] = op
        progress = dict(op.get("progress") or {})
        if (
            op["state"] == "WAITING_EXTERNAL"
            and progress.get("conversation_url")
        ):
            return {
                "conversation_url": progress["conversation_url"],
                "conversation_id": progress.get("conversation_id"),
                "worker": progress.get("worker"),
                "provider": prepared["spec"].provider,
                "model": prepared["spec"].model,
                "job_id": progress.get("relay_job_id"),
                "prepared": prepared,
                "resumed_collect_only": True,
            }
        if (
            op["state"] in {"STARTING", "RUNNING"}
            and progress.get("relay_job_id")
        ):
            return await self._resume_relay_send(
                prepared, str(progress["relay_job_id"])
            )
        if (
            op["state"] in {"STARTING", "RUNNING"}
            and not bool(prepared["delivery"].get("new_operation", False))
        ):
            self._record_turn_failure(
                prepared,
                RuntimeError(
                    "dispatch intent exists without observable relay job"
                ),
                delivery_state="UNCERTAIN",
                retry_safe=False,
                phase="dispatch_recovery",
            )
            raise SwarmDeliveryError(
                "dispatch intent exists without observable relay job",
                delivery_state="UNCERTAIN",
                retry_safe=False,
            )

        prepared["operation"] = self.durable.update_operation(
            op["operation_id"],
            prepared["owner"],
            state="RUNNING",
            progress={
                "delivery_state": "NOT_SENT",
                "dispatch_started_at": time.time(),
            },
            resource_key=prepared["resource_key"],
            fencing_token=prepared["fencing_token"],
            event_type="SWARM_TURN_DISPATCHING",
        )
        governor: ProviderRateGovernor = prepared["governor"]
        await governor.wait(prepared["spec"].provider)
        governor.record_dispatch(prepared["spec"].provider)

        async def submitted(job_id: str) -> None:
            prepared["operation"] = self.durable.update_operation(
                prepared["operation"]["operation_id"],
                prepared["owner"],
                progress={
                    "relay_job_id": job_id,
                    "relay_task_id": prepared["request"].metadata["task_id"],
                    "delivery_state": "NOT_SENT",
                },
                resource_key=prepared["resource_key"],
                fencing_token=prepared["fencing_token"],
                event_type="SWARM_TURN_RELAY_SUBMITTED",
            )

        transport = prepared["provider"].transport
        try:
            sent = await transport.send_chat(
                task_id=prepared["request"].metadata["task_id"],
                prompt=prepared["prompt"],
                timeout_s=min(
                    90, int(prepared["request"].timeout)
                ),
                conversation_url=prepared["request"].metadata.get(
                    "conversation_url"
                ),
                provider=prepared["spec"].provider,
                model=prepared["spec"].model,
                chat_title=prepared["request"].metadata.get(
                    "chat_title"
                ),
                on_submitted=submitted,
            )
        except ExtensionDeliveryError as exc:
            if (
                any(
                    marker in str(exc)
                    for marker in _RECOVERABLE_CONVERSATION_ERRORS
                )
                and exc.delivery_state == "NOT_SENT"
                and prepared["existing"] is not None
            ):
                try:
                    if exc.job_id:
                        await transport.ack_job(exc.job_id)
                except Exception:
                    pass
                prepared["delivery"]["rebind_reason"] = str(exc)[:500]
                rebind_request = AgentRequest(
                    role=prepared["request"].role,
                    system_prompt=prepared["request"].system_prompt,
                    user_prompt=prepared["request"].user_prompt,
                    timeout=prepared["request"].timeout,
                    max_output_tokens=prepared["request"].max_output_tokens,
                    metadata={
                        **prepared["request"].metadata,
                        "new_chat": True,
                        "refresh_system_prompt": True,
                        "conversation_url": None,
                        "task_id": (
                            prepared["request"].metadata["task_id"]
                            + "-rebind"
                        ),
                    },
                )
                prepared["request"] = rebind_request
                prepared["prompt"] = prepared[
                    "provider"
                ].render_prompt(rebind_request)
                await governor.wait(prepared["spec"].provider)
                governor.record_dispatch(prepared["spec"].provider)
                try:
                    sent = await transport.send_chat(
                        task_id=rebind_request.metadata["task_id"],
                        prompt=prepared["prompt"],
                        timeout_s=min(
                            90, int(rebind_request.timeout)
                        ),
                        conversation_url=None,
                        provider=prepared["spec"].provider,
                        model=prepared["spec"].model,
                        chat_title=rebind_request.metadata.get(
                            "chat_title"
                        ),
                        on_submitted=submitted,
                    )
                except ExtensionDeliveryError as retry_exc:
                    self._record_turn_failure(
                        prepared,
                        retry_exc,
                        delivery_state=retry_exc.delivery_state,
                        retry_safe=retry_exc.retry_safe,
                        phase=retry_exc.phase,
                        job_id=retry_exc.job_id,
                    )
                    raise SwarmDeliveryError(
                        str(retry_exc),
                        delivery_state=retry_exc.delivery_state,
                        retry_safe=retry_exc.retry_safe,
                    ) from retry_exc
            else:
                self._record_turn_failure(
                    prepared,
                    exc,
                    delivery_state=exc.delivery_state,
                    retry_safe=exc.retry_safe,
                    phase=exc.phase,
                    job_id=exc.job_id,
                )
                if "additional" in str(exc).lower():
                    governor.hold(
                        prepared["spec"].provider,
                        60.0,
                        reason="PLATFORM_HOLD",
                    )
                raise SwarmDeliveryError(
                    str(exc),
                    delivery_state=exc.delivery_state,
                    retry_safe=exc.retry_safe,
                ) from exc
        except Exception as exc:
            meta = classify_failure(exc)
            self._record_turn_failure(
                prepared,
                exc,
                delivery_state=str(
                    meta.get("delivery_state") or "UNCERTAIN"
                ),
                retry_safe=bool(meta.get("retry_safe", False)),
                phase=str(meta.get("error_kind") or "dispatch"),
            )
            raise SwarmDeliveryError(
                str(exc),
                delivery_state=str(
                    meta.get("delivery_state") or "UNCERTAIN"
                ),
                retry_safe=bool(meta.get("retry_safe", False)),
            ) from exc
        return await self._record_split_sent(prepared, sent)

    async def _finalize_turn(
        self, prepared: dict[str, Any], response: AgentResponse
    ) -> AgentResponse:
        batch = prepared["batch"]
        bridge = prepared["bridge"]
        if batch.last_seq > 0 and batch.consumer_id:
            bridge.acknowledge(
                run_id=prepared["run_id"],
                role=prepared["spec"].role,
                task_id=f"swarm-round-{prepared['round_no']}",
                seat=prepared["seat"],
                consumer_id=batch.consumer_id,
                last_seq=batch.last_seq,
            )
        bridge.publish_response(
            run_id=prepared["run_id"],
            role=prepared["spec"].role,
            task_id=f"swarm-round-{prepared['round_no']}",
            seat=prepared["seat"],
            content=response.content,
            metadata=response.metadata,
            request_sha256=prepared["prompt_hash"],
        )
        path = self._save_output(
            prepared["run_id"],
            prepared["round_no"],
            prepared["phase"],
            prepared["spec"].role,
            response.content,
        )
        artifact = self.durable.register_artifact(
            prepared["run_id"],
            prepared["owner"],
            path,
            operation_id=prepared["operation"]["operation_id"],
            mime_type="text/plain",
            metadata={
                "kind": "swarm-agent-turn",
                "round": prepared["round_no"],
                "phase": prepared["phase"],
                "role": prepared["spec"].role,
            },
        )
        try:
            chat_id = prepared["bridge"]._chat_id(prepared["seat"])
            self.durable.update_chat(
                chat_id,
                prepared["owner"],
                state="READY",
                desired_state="READY",
                metadata={
                    "last_operation_id": prepared["operation"]["operation_id"]
                },
                event_type="SWARM_CHAT_READY",
            )
        except Exception:
            pass
        try:
            self.durable.update_agent(
                prepared["agent_id"],
                prepared["owner"],
                state="ACTIVE",
                metadata={"active_operation_id": None},
                event_type="SWARM_AGENT_ACTIVE",
            )
        except DurableStateConflict:
            pass
        prepared["operation"] = self.durable.update_operation(
            prepared["operation"]["operation_id"],
            prepared["owner"],
            state="SUCCEEDED",
            progress={
                "delivery_state": "COMPLETED",
                "artifact_id": artifact["artifact_id"],
            },
            result={
                "artifact_id": artifact["artifact_id"],
                "sha256": artifact["sha256"],
                "model": response.model,
                "response_meta": dict(response.metadata or {}),
            },
            resource_key=prepared["resource_key"],
            fencing_token=prepared["fencing_token"],
            event_type="SWARM_TURN_SUCCEEDED",
        )
        prepared["delivery"].update(
            state="COMPLETED",
            retry_safe=False,
            operation_id=prepared["operation"]["operation_id"],
            artifact_id=artifact["artifact_id"],
            completed_at=time.time(),
        )
        self._release_turn_lease(prepared)
        return response

    async def _collect_split_turn(
        self, started: dict[str, Any]
    ) -> dict[str, Any]:
        prepared = started["prepared"]
        transport = prepared["provider"].transport
        try:
            collected = await transport.collect_chat(
                task_id=prepared["request"].metadata["task_id"],
                conversation_url=str(started["conversation_url"]),
                timeout_s=int(prepared["request"].timeout),
                provider=prepared["spec"].provider,
            )
        except Exception as exc:
            text = str(exc)
            if (
                "additional_checks" in text.lower()
                or "rate" in text.lower()
            ):
                prepared["governor"].hold(
                    prepared["spec"].provider,
                    60.0,
                    reason="PLATFORM_HOLD",
                )
                try:
                    self.durable.update_chat(
                        prepared["bridge"]._chat_id(
                            prepared["seat"]
                        ),
                        prepared["owner"],
                        state="PLATFORM_HOLD",
                        desired_state="READY",
                        metadata={"collect_error": text[:500]},
                        event_type="SWARM_PROVIDER_HOLD",
                    )
                except Exception:
                    pass
            prepared["operation"] = self.durable.update_operation(
                prepared["operation"]["operation_id"],
                prepared["owner"],
                progress={
                    "delivery_state": "SENT",
                    "collect_error": text[:1000],
                    "collect_retry_safe": True,
                },
                resource_key=prepared["resource_key"],
                fencing_token=prepared["fencing_token"],
                event_type="SWARM_COLLECTION_PENDING",
            )
            prepared["delivery"].update(
                state="WAITING_EXTERNAL",
                retry_safe=True,
                collect_only=True,
                error=text[:1000],
                operation_id=prepared["operation"]["operation_id"],
                updated_at=time.time(),
            )
            self._release_turn_lease(prepared)
            raise SwarmCollectionPending(
                f"{prepared['spec'].role}/{prepared['phase']}: {text}"
            ) from exc

        identity = ConversationIdentity.from_parts(
            prepared["spec"].provider,
            str(
                collected.get("conversation_id")
                or started.get("conversation_id")
                or ""
            ),
            str(
                collected.get("conversation_url")
                or started["conversation_url"]
            ),
        )
        response = AgentResponse(
            content=str(collected.get("text") or ""),
            success=True,
            model=getattr(
                prepared["provider"],
                "model_name",
                prepared["spec"].provider,
            ),
            metadata={
                "conversation_id": identity.conversation_id,
                "conversation_url": identity.canonical_url,
                "provider": identity.provider,
                "web_model": prepared["spec"].model,
                "worker": (
                    collected.get("worker")
                    or started.get("worker")
                ),
                "delivery_state": "CONFIRMED",
            },
        )
        response = await self._finalize_turn(prepared, response)
        prepared["governor"].record_outcome(
            prepared["spec"].provider, "COMPLETED"
        )
        return {"response": response, "prepared": prepared}

    async def _execute_legacy_prepared(
        self, prepared: dict[str, Any]
    ) -> AgentResponse:
        if (
            prepared["operation"]["state"] in {"STARTING", "RUNNING", "WAITING_EXTERNAL"}
            and not bool(prepared["delivery"].get("new_operation", False))
        ):
            self._record_turn_failure(
                prepared,
                RuntimeError("legacy provider turn cannot be safely resumed after dispatch intent"),
                delivery_state="UNCERTAIN",
                retry_safe=False,
                phase="legacy_recovery",
            )
            raise SwarmDeliveryError(
                "legacy provider turn cannot be safely resumed after dispatch intent",
                delivery_state="UNCERTAIN",
                retry_safe=False,
            )
        prepared["operation"] = self.durable.update_operation(
            prepared["operation"]["operation_id"],
            prepared["owner"],
            state="RUNNING",
            progress={"delivery_state": "NOT_SENT"},
            resource_key=prepared["resource_key"],
            fencing_token=prepared["fencing_token"],
            event_type="SWARM_TURN_DISPATCHING",
        )
        try:
            response = await prepared["provider"].execute(
                prepared["request"]
            )
        except Exception as exc:
            self._record_turn_failure(
                prepared,
                exc,
                delivery_state="UNCERTAIN",
                retry_safe=False,
            )
            raise
        if not response.success:
            meta = dict(response.metadata or {})
            self._record_turn_failure(
                prepared,
                RuntimeError(
                    str(response.error or "provider failed")
                ),
                delivery_state=str(
                    meta.get("delivery_state") or "UNCERTAIN"
                ),
                retry_safe=bool(
                    meta.get("retry_safe", False)
                ),
            )
            raise SwarmDeliveryError(
                f"{prepared['spec'].role}/{prepared['phase']}: "
                f"{response.error}",
                delivery_state=str(
                    meta.get("delivery_state") or "UNCERTAIN"
                ),
                retry_safe=bool(
                    meta.get("retry_safe", False)
                ),
            )
        return await self._finalize_turn(prepared, response)

    @staticmethod
    def _legacy_pre_send_not_ready(delivery: dict[str, Any]) -> bool:
        """Recognize the pre-1.6.44 wait-settled error proven to occur before SEND_MESSAGE."""
        error = str((delivery or {}).get("error") or "")
        return "TAB_ERROR" in error and "estabilizou (gera" in error

    def _dispatch_questions(
        self,
        manifest: dict[str, Any],
        round_no: int,
        outputs: dict[str, AgentResponse],
    ) -> int:
        rid = str(manifest["run_id"])
        owner = str(manifest["owner"])
        bridge = self._bridge(manifest)
        roles = set(self._role_names(manifest))
        sent = 0
        for source_role, response in outputs.items():
            seat = self._seat(rid, source_role)
            sender = bridge._agent_id(seat)
            per_source = 0
            for match in _Q_RE.finditer(str(response.content or "")):
                target_role = match.group(1)
                question = match.group(2).strip()
                if target_role not in roles or target_role == source_role or not question:
                    continue
                target = bridge._agent_id(self._seat(rid, target_role))
                self.control.send_message(
                    rid,
                    owner,
                    from_agent_id=sender,
                    to_agent_id=target,
                    body=question[:4000],
                    idempotency_key=(
                        f"swarm:q:r{round_no}:{source_role}:{target_role}:{per_source}"
                    ),
                )
                sent += 1
                per_source += 1
                if per_source >= 2:
                    break
        return sent

    async def _run_oma(
        self,
        manifest: dict[str, Any],
        round_no: int,
        *,
        config_path: Path,
        worker: str | None,
        reviewer: str | None,
        sandbox: str,
        trust_workspace: bool,
    ) -> dict[str, Any]:
        workspace_text = str(manifest.get("workspace") or "").strip()
        if not workspace_text:
            raise ValueError("swarm --execute requires a workspace")
        workspace = Path(workspace_text).expanduser().resolve(strict=True)
        import yaml
        from orchestrator.configuration import build_router, close_router, engine_options
        from orchestrator.runtime import IntegratedRun

        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise ValueError("SENTRA config must be a mapping")
        config = copy.deepcopy(config)
        validation = config.setdefault("validation", {})
        execution = validation.setdefault("execution", {})
        if sandbox == "docker":
            execution["backend"] = "docker"
        elif not trust_workspace:
            raise ValueError("host implementation requires explicit --trust-workspace")

        router = build_router(config, worker=worker, reviewer=reviewer, root=config_path.parent)
        options = engine_options(config)
        options["fixed_conversations"] = True
        options["shared_context_bridge"] = _PinnedRunBridge(
            self._bridge(manifest), str(manifest["run_id"])
        )
        implementation_run_id = (
            f"{manifest['run_id'][:70]}-impl-r{round_no}"
        )
        resume = (
            workspace / "runs" / implementation_run_id / "snapshot.json"
        ).is_file()
        try:
            result = await IntegratedRun(
                workspace,
                implementation_run_id,
                str(manifest["goal"]),
                router,
                resume=resume,
                **options,
            ).run()
        finally:
            await close_router(router)

        gate_green = result.get("status") in {"CANDIDATE_READY", "APPLIED"}
        manifest["quality_gate"] = {
            "green": gate_green,
            "status": result.get("status"),
            "implementation_run_id": implementation_run_id,
            "handoff_path": result.get("handoff_path"),
            "patch_path": result.get("patch_path"),
            "completed_tasks": result.get("completed_tasks"),
            "total_tasks": result.get("total_tasks"),
        }
        self.control.publish_context(
            str(manifest["run_id"]),
            str(manifest["owner"]),
            event_type="RESULT" if gate_green else "FAILURE",
            subject=f"swarm.implementation.round.{round_no}",
            payload=dict(manifest["quality_gate"]),
            evidence=[],
            confidence=1.0,
            supersedes=[],
            task_id=f"swarm-round-{round_no}",
            agent_id=None,
            idempotency_key=f"swarm-oma-result-r{round_no}",
        )
        self._save_manifest(manifest)
        return result

    async def run_round(
        self,
        run_id: str,
        *,
        timeout_s: int = 180,
        execute: bool = False,
        config_path: Path | None = None,
        worker: str | None = None,
        reviewer: str | None = None,
        sandbox: str = "docker",
        trust_workspace: bool = False,
    ) -> dict[str, Any]:
        manifest = self.load_manifest(run_id)
        owner = str(manifest["owner"])
        current_run = self.durable.run_status(run_id, owner)
        if current_run["state"] != "RUNNING":
            raise RuntimeError(
                "SWARM_NOT_RUNNABLE: run state "
                f"{current_run['state']} requires resume/reconcile before new sends"
            )
        controller_key = self._controller_resource_key(run_id)
        controller_id = "swarm-controller-" + uuid.uuid4().hex[:24]
        try:
            controller = self.durable.acquire_lease(
                run_id,
                owner,
                controller_key,
                operation_id=controller_id,
                ttl_s=90.0,
            )
        except DurableStateConflict as exc:
            raise RuntimeError(
                "SWARM_ALREADY_RUNNING: another swarm continue/run owns "
                "the controller lease"
            ) from exc

        stop_heartbeat = asyncio.Event()
        heartbeat_failures: list[BaseException] = []
        heartbeat = asyncio.create_task(
            self._controller_lease_heartbeat(
                controller_key,
                owner,
                int(controller["fencing_token"]),
                stop_heartbeat,
                heartbeat_failures,
            )
        )
        governor = self._governor(run_id)
        try:
            round_no = int(manifest.get("rounds_completed", 0)) + 1
            manifest["active_round"] = round_no
            round_state = manifest.setdefault("rounds", {}).setdefault(
                str(round_no), {"phases": {}, "questions_sent": 0}
            )
            self._save_manifest(manifest)

            for phase in PHASES:
                observed = self.durable.run_status(run_id, owner)
                if observed["state"] != "RUNNING":
                    raise RuntimeError(
                        "SWARM_STOPPED: run state changed to "
                        f"{observed['state']}; no new turn was dispatched"
                    )
                if heartbeat_failures:
                    raise RuntimeError(
                        "SWARM_CONTROLLER_LEASE_LOST: "
                        f"{heartbeat_failures[0]}"
                    )
                phase_state = round_state["phases"].setdefault(
                    phase,
                    {
                        "completed": False,
                        "roles": [],
                        "deliveries": {},
                    },
                )
                phase_state.setdefault("roles", [])
                deliveries = phase_state.setdefault("deliveries", {})
                if phase_state.get("completed"):
                    continue

                outputs: dict[str, AgentResponse] = {}
                split_pending: list[dict[str, Any]] = []
                phase_errors: list[BaseException] = []

                for spec in self._phase_agents(manifest, phase):
                    delivery = deliveries.setdefault(spec.role, {})
                    if (
                        str(delivery.get("state") or "")
                        == "UNCERTAIN"
                        and self._legacy_pre_send_not_ready(delivery)
                    ):
                        delivery.update(
                            state="NOT_SENT",
                            retry_safe=True,
                            reconciled=(
                                "legacy wait-settled error is "
                                "source-proven pre-SEND_MESSAGE"
                            ),
                            reconciled_at=time.time(),
                        )
                    elif str(delivery.get("state") or "") == "UNCERTAIN":
                        raise RuntimeError(
                            "SWARM_DELIVERY_UNCERTAIN: "
                            f"{spec.role}/{phase} has ambiguous legacy delivery; "
                            "reconcile before any resend"
                        )

                    op, attempt, _logical_hash = self._turn_operation(
                        manifest,
                        spec,
                        phase,
                        round_no,
                        delivery,
                    )
                    delivery["attempt"] = attempt

                    if op["state"] == "SUCCEEDED":
                        response = self._restore_succeeded_turn(
                            op, owner
                        )
                        outputs[spec.role] = response
                        if spec.role not in phase_state["roles"]:
                            phase_state["roles"].append(spec.role)
                        delivery.update(
                            state="COMPLETED",
                            operation_id=op["operation_id"],
                            artifact_id=(
                                op.get("result") or {}
                            ).get("artifact_id"),
                            recovered_from_durable=True,
                        )
                        self._save_manifest(manifest)
                        continue

                    if op["state"] == "UNCERTAIN":
                        delivery.update(
                            state="UNCERTAIN",
                            retry_safe=False,
                            operation_id=op["operation_id"],
                            error=str(
                                (op.get("error") or {}).get(
                                    "message"
                                )
                                or ""
                            )[:1000],
                        )
                        self._save_manifest(manifest)
                        raise RuntimeError(
                            "SWARM_DELIVERY_UNCERTAIN: "
                            f"{spec.role}/{phase} is UNCERTAIN in "
                            "Durable Core; reconcile before any resend"
                        )
                    if op["state"] == "CANCELLED":
                        raise RuntimeError(
                            f"SWARM_TURN_CANCELLED: "
                            f"{spec.role}/{phase}"
                        )

                    path = self._output_path(
                        run_id, round_no, phase, spec.role
                    )
                    if (
                        path.is_file()
                        and op["state"] != "SUCCEEDED"
                    ):
                        delivery["orphan_projection"] = str(path)

                    try:
                        prepared = self._prepare_turn(
                            manifest,
                            spec,
                            phase,
                            round_no,
                            timeout_s=timeout_s,
                            operation=op,
                            delivery=delivery,
                            governor=governor,
                        )
                    except SwarmDeliveryError as exc:
                        delivery.update(
                            state="NOT_SENT",
                            retry_safe=exc.retry_safe,
                            error=str(exc)[:1000],
                            operation_id=op["operation_id"],
                        )
                        try:
                            self.durable.update_operation(
                                op["operation_id"],
                                owner,
                                state="FAILED",
                                error={
                                    "message": str(exc),
                                    "delivery_state": "NOT_SENT",
                                    "retry_safe": bool(
                                        exc.retry_safe
                                    ),
                                },
                                progress={
                                    "delivery_state": "NOT_SENT"
                                },
                                event_type=(
                                    "SWARM_TURN_PREPARE_FAILED"
                                ),
                            )
                        except Exception:
                            pass
                        self._save_manifest(manifest)
                        raise

                    delivery.update(
                        state=(
                            "WAITING_EXTERNAL"
                            if prepared["operation"]["state"]
                            == "WAITING_EXTERNAL"
                            else "IN_FLIGHT"
                        ),
                        operation_id=prepared["operation"][
                            "operation_id"
                        ],
                        started_at=(
                            delivery.get("started_at")
                            or time.time()
                        ),
                    )
                    self._save_manifest(manifest)
                    if self._split_capable(prepared):
                        split_pending.append(prepared)
                    else:
                        try:
                            response = (
                                await self._execute_legacy_prepared(
                                    prepared
                                )
                            )
                        except BaseException as exc:
                            phase_errors.append(exc)
                        else:
                            outputs[spec.role] = response
                            if (
                                spec.role
                                not in phase_state["roles"]
                            ):
                                phase_state["roles"].append(
                                    spec.role
                                )
                            self._save_manifest(manifest)

                if split_pending:
                    scheduler = ConversationTurnScheduler(
                        start=self._start_split_turn,
                        collect=self._collect_split_turn,
                        collect_concurrency=min(
                            8, max(1, len(split_pending))
                        ),
                    )
                    scheduled = await scheduler.run_batch(
                        split_pending
                    )
                    for item in scheduled:
                        prepared_raw = item.get("_scheduler_item")
                        if not isinstance(prepared_raw, dict):
                            prepared_raw = item.get("prepared")
                        scheduled_prepared: dict[str, Any] | None = (
                            prepared_raw
                            if isinstance(prepared_raw, dict)
                            else None
                        )
                        role = (
                            scheduled_prepared["spec"].role
                            if isinstance(scheduled_prepared, dict)
                            else "unknown"
                        )
                        if item.get("_scheduler_error"):
                            if isinstance(scheduled_prepared, dict):
                                op_now = (
                                    self.durable.operation_status(
                                        scheduled_prepared["operation"][
                                            "operation_id"
                                        ],
                                        owner,
                                    )
                                )
                                if (
                                    op_now["state"]
                                    == "WAITING_EXTERNAL"
                                ):
                                    scheduled_prepared["delivery"].update(
                                        state="WAITING_EXTERNAL",
                                        collect_only=True,
                                        retry_safe=True,
                                        operation_id=op_now[
                                            "operation_id"
                                        ],
                                        error=str(
                                            item[
                                                "_scheduler_error"
                                            ]
                                        )[:1000],
                                    )
                                elif (
                                    op_now["state"]
                                    == "FAILED"
                                ):
                                    err = (
                                        op_now.get("error")
                                        or {}
                                    )
                                    scheduled_prepared["delivery"].update(
                                        state=(
                                            "NOT_SENT"
                                            if err.get(
                                                "delivery_state"
                                            )
                                            == "NOT_SENT"
                                            else "UNCERTAIN"
                                        ),
                                        retry_safe=bool(
                                            err.get(
                                                "retry_safe",
                                                False,
                                            )
                                        ),
                                        operation_id=op_now[
                                            "operation_id"
                                        ],
                                        error=str(
                                            err.get("message")
                                            or item[
                                                "_scheduler_error"
                                            ]
                                        )[:1000],
                                    )
                                else:
                                    scheduled_prepared["delivery"].update(
                                        state="UNCERTAIN",
                                        retry_safe=False,
                                        operation_id=op_now[
                                            "operation_id"
                                        ],
                                        error=str(
                                            item[
                                                "_scheduler_error"
                                            ]
                                        )[:1000],
                                    )
                            phase_errors.append(
                                RuntimeError(
                                    str(
                                        item[
                                            "_scheduler_error"
                                        ]
                                    )
                                )
                            )
                            continue
                        response_raw = item.get("response")
                        if isinstance(
                            response_raw, AgentResponse
                        ):
                            outputs[role] = response_raw
                            if (
                                role
                                not in phase_state["roles"]
                            ):
                                phase_state["roles"].append(
                                    role
                                )
                    self._save_manifest(manifest)

                if phase_errors:
                    raise phase_errors[0]

                expected_roles = {
                    item.role
                    for item in self._phase_agents(
                        manifest, phase
                    )
                }
                if set(outputs) != expected_roles:
                    missing = sorted(
                        expected_roles - set(outputs)
                    )
                    raise RuntimeError(
                        "SWARM_PHASE_INCOMPLETE: "
                        + ", ".join(missing)
                    )

                if phase == "peer_questions":
                    round_state["questions_sent"] = (
                        self._dispatch_questions(
                            manifest,
                            round_no,
                            outputs,
                        )
                    )
                if phase == "implement" and execute:
                    if config_path is None:
                        raise ValueError(
                            "--execute requires --config"
                        )
                    await self._run_oma(
                        manifest,
                        round_no,
                        config_path=Path(
                            config_path
                        ).resolve(),
                        worker=worker,
                        reviewer=reviewer,
                        sandbox=sandbox,
                        trust_workspace=trust_workspace,
                    )

                phase_state["completed"] = True
                self._save_manifest(manifest)

            manifest["rounds_completed"] = round_no
            manifest["active_round"] = 0
            if bool(
                (
                    manifest.get("quality_gate") or {}
                ).get("green")
            ):
                goal = self.control.goal_info(
                    str(manifest["goal_id"]), owner
                )
                if goal.get("state") == "ACTIVE":
                    self.control.update_goal(
                        str(manifest["goal_id"]),
                        owner,
                        state="SUCCEEDED",
                        reason=(
                            "deterministic OMA "
                            "Quality Gate green"
                        ),
                    )
                run = self.durable.run_status(
                    run_id, owner
                )
                if run.get("state") == "RUNNING":
                    self.durable.transition_run(
                        run_id,
                        owner,
                        "SUCCEEDED",
                        reason=(
                            "swarm completed with "
                            "deterministic Quality Gate green"
                        ),
                        result={
                            "quality_gate": manifest[
                                "quality_gate"
                            ]
                        },
                    )
            self._save_manifest(manifest)
            return self.status(run_id)
        finally:
            stop_heartbeat.set()
            try:
                await heartbeat
            except BaseException:
                pass
            try:
                self.durable.release_lease(
                    controller_key,
                    owner,
                    int(controller["fencing_token"]),
                )
            except Exception:
                pass

    async def run_until_gate(
        self,
        run_id: str,
        *,
        max_rounds: int = 3,
        **kwargs,
    ) -> dict[str, Any]:
        if not 1 <= int(max_rounds) <= 20:
            raise ValueError("max_rounds must be 1..20")
        result = self.status(run_id)
        for _ in range(int(max_rounds)):
            if bool((result.get("quality_gate") or {}).get("green")):
                break
            result = await self.run_round(run_id, **kwargs)
        return result
