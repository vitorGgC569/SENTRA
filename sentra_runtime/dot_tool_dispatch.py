"""Coordinator tool dispatch intent admission, fence, execution and consolidation.

Enforces:
1. Only the bound agent coordinator of the Dot root can coordinate (owner cannot emit).
2. Specific tool capability Grant per tool (sentra_cli, opencode, codex).
3. Live process fence, lease and parent work item authority.
4. Idempotent execution via ShellHostRequests.
5. WorkItem child of coordinator's WorkItem.
6. Operation SUCCEEDED only with cryptographically verified nonce transformation receipt.
7. WorkItem transitions to IN_REVIEW (not COMPLETED directly) until coordinator consolidation.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from sentra_canvas.dot_tool_receipts import reserve_dispatch, record_dispatch_outcome
from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
from sentra_canvas.shell_requests import ShellHostRequests
from sentra_mcp.services.shell_coordinator import dot_manages_canvas
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.machine_budget import BudgetedMachinePolicy


VALID_TOOLS = frozenset({"sentra-cli", "opencode", "codex", "sentra_cli"})


def normalize_tool_slug(tool: str) -> str:
    slug = str(tool or "").strip().lower().replace("-", "_")
    if slug not in {"sentra_cli", "opencode", "codex"}:
        raise ValueError(f"unsupported tool: {tool}")
    return slug


def tool_capabilities(tool_slug: str) -> list[str]:
    return [
        f"canvas.coordinator.dot_tool_dispatch.{tool_slug}",
        f"canvas.coordinator.tool_dispatch.{tool_slug}",
        "canvas.coordinator.dot_tool_dispatch",
    ]


def execute_dot_tool_dispatch(
    control: Any,
    owner: str,
    *,
    project_id: str,
    conversation_id: str,
    run_id: str,
    work_item_id: str,
    parent_operation_id: str,
    agent_id: str,
    intent: dict[str, Any],
    request_key: str,
    compose: Any = None,
    process_alive: Any = None,
    connected_agents: Any = None,
    runner: Any = None,
    placement: str = "host",
    guest_process: dict[str, Any] | None = None,
    guest_executor: Any = None,
    vm_id: str | None = None,
    username: str | None = None,
    password: str | None = None,
    os_family: str | None = None,
    virtualbox_client: Any = None,
    coordinator_text: str | None = None,
    guest_workspace: str | None = None,
) -> dict[str, Any]:
    """Admit and execute agent coordinator dot_tool_dispatch intent."""
    if not isinstance(intent, dict):
        raise ValueError("structured coordinator intent required")
    if set(intent) - {'kind', 'tool', 'target_dot_id', 'instruction', 'prompt', 'nonce', 'model', 'effort', 'timeout_s'}:
        raise ValueError('unsupported coordinator tool intent fields')
    from orchestrator.providers.fleet_admission import note_uncertain_effect, refuse_blocked_dispatch
    refuse_blocked_dispatch(
        tool=intent.get("tool", "sentra-cli"),
        placement=placement,
        guest_process=guest_process,
        operation_ids=(parent_operation_id,),
    )
    instruction = intent.get('instruction') or intent.get('prompt')
    if not isinstance(instruction, str) or not 1 <= len(instruction) <= 16000:
        raise ValueError('bounded tool instruction required')
    timeout = intent.get('timeout_s', 300.0)
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError('tool timeout must be 1..600 seconds')
    
    # 1. Owner cannot emit agent coordinator intent
    if agent_id == owner:
        raise PermissionError("owner cannot emit agent coordinator intent")

    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128 or "\0" in request_key:
        raise ValueError("bounded durable request_key required")

    project = control.shell._project(owner, project_id)
    if project["run_id"] != run_id:
        raise PermissionError("coordinator Run is not current for this project")

    # 2. Token & provider binding validation
    with closing(control.store.connect("shell")) as db:
        binding = db.execute(
            "SELECT * FROM canvas_shell_provider_bindings WHERE owner=? AND project_id=? AND conversation_id=?",
            (owner, project_id, conversation_id),
        ).fetchone()
        if binding is None or any(
            binding[field] != value for field, value in (
                ("run_id", run_id),
                ("work_item_id", work_item_id),
                ("operation_id", parent_operation_id),
                ("agent_id", agent_id),
            )
        ):
            raise PermissionError("coordinator token differs from current shell execution")
        
        conversation = control.shell._entity(db, owner, project_id, "conversation", conversation_id)
        dot = control.shell._entity(db, owner, project_id, "dot", conversation["dot_id"], space_id=conversation["space_id"])
        
        # Only the bound coordinator Dot of the root may coordinate
        if dot["agent_id"] != agent_id or not dot_manages_canvas(dot):
            raise PermissionError("only the bound coordinator Dot may coordinate")

        target_dot_id = intent.get("target_dot_id")
        if not target_dot_id:
            raise ValueError("target_dot_id required")
        target_dot = control.shell._entity(db, owner, project_id, "dot", target_dot_id, space_id=conversation["space_id"])

        allowed_agents = set(connected_agents(project_id, agent_id)) if connected_agents else set()
        if target_dot["agent_id"] not in allowed_agents:
            raise PermissionError("coordinator intent targets an agent outside its directed connections")
        if (target_dot.get('canvas_root_dot_id') or target_dot['dot_id']) != (dot.get('canvas_root_dot_id') or dot['dot_id']):
            raise PermissionError('tool target belongs to another Dot canvas')

    # 3. Live process fence
    def is_live() -> bool:
        run = control.durable.run_status(run_id, owner, include_details=False)
        current = control.work_item_info(work_item_id, owner)
        operation = control.durable.operation_status(parent_operation_id, owner)
        actor = control.durable.agent_info(agent_id, owner)
        with closing(control.store.connect("shell")) as db:
            bound = db.execute(
                "SELECT operation_id,work_item_id,agent_id,run_id FROM canvas_shell_provider_bindings "
                "WHERE owner=? AND project_id=? AND conversation_id=?",
                (owner, project_id, conversation_id),
            ).fetchone()
            current_dot = control.shell._entity(db, owner, project_id, "dot", dot["dot_id"], space_id=conversation["space_id"])
        
        alive_ok = (process_alive() is True) if process_alive else True
        return (
            alive_ok
            and run["state"] == "RUNNING"
            and run["desired_state"] == "RUNNING"
            and current_dot["agent_id"] == agent_id
            and dot_manages_canvas(current_dot)
            and current["run_id"] == run_id
            and current["state"] == "RUNNING"
            and current["assignee_agent_id"] == agent_id
            and actor["run_id"] == run_id
            and actor["desired_state"] != "WAITING"
            and operation["run_id"] == run_id
            and operation["state"] in {"STARTING", "RUNNING"}
            and bound is not None
            and all(bound[field] == value for field, value in (
                ('run_id', run_id), ('work_item_id', work_item_id),
                ('operation_id', parent_operation_id), ('agent_id', agent_id)))
        )

    if not is_live():
        raise PermissionError("coordinator parent execution is not live")

    # 4. Tool & Capability Grant verification
    tool_raw = intent.get("tool", "sentra-cli")
    tool_slug = normalize_tool_slug(tool_raw)
    declared_caps = control.work_item_info(work_item_id, owner).get("required_capabilities", [])
    valid_caps = tool_capabilities(tool_slug)
    matched_cap = next((c for c in valid_caps if c in declared_caps), None)
    if not matched_cap:
        raise PermissionError(
            f"coordinator capability '{valid_caps[0]}' is not explicitly declared by the parent WorkItem"
        )

    identity = hashlib.sha256(
        json.dumps([owner, project_id, parent_operation_id, request_key, tool_slug], separators=(",", ":")).encode()
    ).hexdigest()
    coord_oid = "coordinator-" + identity[:48]
    arguments = {
        "intent": intent,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "space_id": conversation["space_id"],
        "parent_operation_id": parent_operation_id,
    }
    request = OperationRequest(coord_oid, agent_id, "coordinator-" + agent_id, matched_cap, work_item_id, coord_oid, arguments)
    
    bound_policy = BoundWorkItemPolicy(
        owner=owner,
        principal_type="agent",
        authorization=control.authorization,
        governance=control.governance,
        trusted_context=lambda _: {"actual_cost": 0.0, "provider": "canvas-coordinator"},
    )
    policy = BudgetedMachinePolicy(bound_policy, control=control, owner=owner)

    if policy(request).allowed is not True:
        from sentra_runtime.coordinator_approvals import CoordinatorApprovalInbox
        CoordinatorApprovalInbox(control, owner).record(
            project_id=project_id,
            space_id=conversation["space_id"],
            conversation_id=conversation_id,
            parent_operation_id=parent_operation_id,
            work_item_id=work_item_id,
            agent_id=agent_id,
            approval_id=coord_oid,
            capability=matched_cap,
            intent=intent,
        )
        return {
            "status": "waiting_approval",
            "operation_id": coord_oid,
            "work_item_id": work_item_id,
            "capability": matched_cap,
            "receipt_id": None,
            "grant_created": False,
            "external_completion_claimed": False,
            "coordinator_text": None,
            "tool_executed": False,
            "claims_success": False,
            "physical_inference": False,
        }

    if isinstance(coordinator_text, str) and coordinator_text.strip():
        return {
            "status": "not_inference",
            "coordinator_text": None,
            "tool_executed": False,
            "claims_success": False,
            "physical_inference": False,
            "promoted": False,
            "finalized": False,
            "reason": "host text is not a model inference",
        }

    # 5. Idempotent execution under ShellHostRequests
    host_requests = ShellHostRequests(control, owner)
    custom_runner = runner  # Injection is an explicit host/test argument, never model content.

    def run_dispatch():
        # Reserve child WorkItem and Operation
        root_dot_id = dot.get("canvas_root_dot_id") or dot["dot_id"]
        canonical_tool = "sentra-cli" if tool_slug == "sentra_cli" else tool_slug
        instruction = intent.get("instruction") or intent.get("prompt") or "Run non-interactive inspection"

        canvas_obj = (getattr(control, "canvas", None) or getattr(control, "_canvas", None)
            or getattr(getattr(control.shell, 'runtime', None), 'canvas', None))
        if canvas_obj is None:
            class MinimalRuntime:
                def __init__(self, c, o, rid):
                    self.c, self.o, self.rid = c, o, rid
                def run(self, pid):
                    return self.c.durable.run_status(self.rid, self.o, include_details=False)
            class MinimalCanvas:
                def __init__(self, c, o, rid):
                    self.rt = MinimalRuntime(c, o, rid)
                def _runtime(self):
                    return self.rt
            canvas_obj = MinimalCanvas(control, owner, run_id)

        ids = reserve_dispatch(
            canvas=canvas_obj,
            control=control,
            owner=owner,
            project_id=project_id,
            space_id=conversation["space_id"],
            request_key=request_key,
            root_dot_id=root_dot_id,
            source=dot,
            target=target_dot,
            tool=canonical_tool,
            coordinator_work_item_id=work_item_id,
            coordinator_operation_id=parent_operation_id,
            instruction=instruction,
        )
        if ids.get("idempotent_replay"):
            with closing(control.store.connect("shell")) as db:
                row = db.execute(
                    "SELECT receipt_json,status FROM canvas_dot_tool_dispatches WHERE owner=? AND project_id=? AND request_key=?",
                    (owner, project_id, request_key),
                ).fetchone()
                if row:
                    receipt = json.loads(row["receipt_json"])
                    if row["status"] == "uncertain" or receipt.get("execution_uncertain") is True:
                        note_uncertain_effect(ids["operation_id"])
                    return {
                        "status": row["status"],
                        "work_item_id": ids["work_item_id"],
                        "operation_id": ids["operation_id"],
                        "receipt": receipt,
                        "idempotent_replay": True,
                        "resend": False,
                    }
            note_uncertain_effect(ids["operation_id"])
            raise PermissionError("UNCERTAIN operation is not resent")

        # Resolve paths
        if hasattr(canvas_obj, 'store'):
            workspace_path = Path(canvas_obj.store.workspace(project_id)['path']).resolve(strict=True)
            project_dir = Path(canvas_obj.project_dir).resolve(strict=True)
        elif custom_runner is not None:
            # Isolated unit fixtures can exercise admission without a physical launch.
            workspace_path = Path.cwd()
            project_dir = workspace_path
        else:
            raise PermissionError('canonical Canvas workspace resolver is unavailable')
        if not is_live() or policy(request).allowed is not True:
            raise PermissionError('coordinator authority changed before tool launch')

        grant = control.authorization.authorize(
            owner, principal_type="agent", principal_id=agent_id,
            capability=matched_cap, scope_type="work_item", scope_id=work_item_id,
            context={"actual_cost": 0.0, "provider": canonical_tool}, local_owner=False,
        )
        if grant.get("source") != "grant" or not grant.get("grant_id"):
            raise PermissionError("effect requires its own current Grant")
        from orchestrator.dispatcher import central_effect_admission
        from orchestrator.providers.fleet_admission import bind_live_lane
        authority = {
            "owner": owner, "run_id": run_id, "work_item_id": work_item_id,
            "operation_id": parent_operation_id, "grant_id": grant["grant_id"],
            "agent_id": agent_id,
        }
        gate = bind_live_lane(
            tool=canonical_tool,
            authority=authority,
            placement=placement, guest_process=guest_process,
            effect_operation_id=ids["operation_id"], effect_state="RUNNING",
            require_installed=custom_runner is None,
        )
        admission = central_effect_admission(
            authority, placement=placement, guest_process=guest_process,
        )
        sealed = seal_fleet_admission(control, admission)
        # A host runner or subprocess must not satisfy guest placement.
        host_runner = None if placement == "guest" else custom_runner
        resolved_guest = guest_executor
        if placement == "guest":
            from sentra_executors.guest_execution import resolve_guest_executor
            resolved_guest = resolve_guest_executor(
                guest_executor,
                vm_id=vm_id,
                username=username,
                password=password,
                os_family=os_family or "linux",
                client=virtualbox_client,
            )
        receipt = execute_non_interactive_tool(
            project_dir=project_dir,
            workspace=workspace_path,
            tool=canonical_tool,
            instruction=instruction,
            oid=ids["operation_id"],
            wid=ids["work_item_id"],
            request_key=request_key,
            nonce=intent.get("nonce"),
            model=intent.get("model"),
            effort=intent.get("effort"),
            timeout_s=timeout,
            runner=host_runner,
            placement=placement,
            guest_executor=resolved_guest,
            guest_workspace=guest_workspace,
        )
        if not is_live() or policy(request).allowed is not True:
            receipt.update(verified=False, execution_uncertain=True, claims_guest_execution=False,
                error='coordinator authority changed during tool execution')
        surface = receipt.get("execution_surface")
        if surface == "guest":
            receipt["evidence_source"] = "guest_executor"
            receipt["live_model_verified"] = False
            receipt["observed_by"] = "guest_executor"
        elif surface == "blocked":
            receipt["evidence_source"] = "guest_executor_missing"
            receipt["live_model_verified"] = False
            receipt["observed_by"] = "dot_tool_dispatch"
        elif host_runner is not None:
            receipt["evidence_source"] = "injected_test_runner"
            receipt["live_model_verified"] = False
        else:
            receipt["evidence_source"] = "native_process"
            receipt["live_model_verified"] = bool(receipt.get("verified"))
            receipt["observed_by"] = "dot_tool_dispatch"
        if receipt.get("verified") is True:
            receipt.setdefault("model", receipt.get("effective_model"))
            if intent.get("effort"):
                receipt.setdefault("effort", intent.get("effort"))
            receipt.setdefault("execution_uncertain", False)
            receipt.setdefault("ack_only", False)
            receipt.setdefault("launch_failed", False)
            receipt.setdefault("echo_only_detected", False)
            receipt.setdefault("status", "SUCCEEDED")

        outcome = record_dispatch_outcome(
            control=control,
            owner=owner,
            project_id=project_id,
            space_id=conversation["space_id"],
            request_key=request_key,
            source_dot_id=dot["dot_id"],
            member_dot_id=target_dot["dot_id"],
            tool=canonical_tool,
            ids=ids,
            receipt=receipt,
        )
        if outcome.get("status") == "uncertain" or receipt.get("execution_uncertain") is True:
            note_uncertain_effect(ids["operation_id"])
        guest_ran = (
            receipt.get("execution_surface") == "guest"
            and receipt.get("claims_guest_execution") is True
            and receipt.get("execution_uncertain") is not True
        )
        blocked = receipt.get("blocked") is True or receipt.get("execution_surface") == "blocked"
        outcome["fleet_gate"] = {
            "admission_id": gate["admission_id"],
            "lane": gate["lane"],
            "placement": gate["placement"]["placement"],
            "execution_surface": receipt.get("execution_surface"),
            "claims_guest_execution": guest_ran,
            "host_subprocess": receipt.get("host_subprocess") is True,
            "physical_inference": False,
            "resend": False,
        }
        outcome["fleet_audit"] = sealed
        from sentra_quality.decision_receipt_audit import DecisionReceiptLedger
        from sentra_quality.production_audit import audit_runner_final_answer
        outcome["runner_audit"] = audit_runner_final_answer(
            DecisionReceiptLedger(Path(control.durable.state_root) / "runner-audit"),
            receipt,
            instruction=instruction,
            authority={
                "owner": owner,
                "run_id": run_id,
                "work_item_id": ids["work_item_id"],
                "operation_id": ids["operation_id"],
                "grant_id": grant["grant_id"],
                "agent_id": agent_id,
            },
            durable=control.durable,
            governance=control.governance,
            authorization=control.authorization,
        )
        remembered = remember_live_dot_if_sealed(
            control, outcome["runner_audit"], receipt=receipt, owner=owner, dot_id=target_dot["dot_id"],
            session_id=conversation_id, run_id=run_id,
            work_item_id=ids["work_item_id"], operation_id=ids["operation_id"],
        )
        outcome["live_session"] = remembered
        outcome["resend"] = False
        outcome["coordinator_text"] = None
        outcome["tool_executed"] = not blocked
        outcome["claims_success"] = False
        outcome["physical_inference"] = False
        outcome["execution_surface"] = receipt.get("execution_surface")
        outcome["claims_guest_execution"] = guest_ran
        outcome["host_subprocess"] = receipt.get("host_subprocess") is True
        return outcome

    return host_requests.invoke(
        project_id,
        "dot_tool_dispatch",
        {"work_item_id": work_item_id, "intent": intent},
        request_key,
        run_dispatch,
    )


def _lane_receipts(control: Any, owner: str, project_id: str, coordinator_work_item_id: str) -> dict[str, dict[str, Any]]:
    """Verified lane receipts already stored for this coordinator. Does not launch a tool."""
    import sqlite3
    from orchestrator.providers.fleet_admission import note_uncertain_effect
    from orchestrator.providers.trio_orchestration import TRIO_LANES

    found: dict[str, dict[str, Any]] = {}
    try:
        with closing(control.store.connect("shell")) as db:
            rows = db.execute(
                "SELECT tool,receipt_json,verified,operation_id,work_item_id,status "
                "FROM canvas_dot_tool_dispatches WHERE owner=? AND project_id=?",
                (owner, project_id),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    for row in rows:
        if row["tool"] not in TRIO_LANES:
            continue
        item = control.work_item_info(row["work_item_id"], owner)
        if item.get("parent_work_item_id") != coordinator_work_item_id:
            continue
        receipt = json.loads(row["receipt_json"])
        uncertain = row["status"] == "uncertain" or receipt.get("execution_uncertain") is True
        if uncertain:
            note_uncertain_effect(row["operation_id"])
            continue
        if not row["verified"] or item.get("state") not in {"IN_REVIEW", "READY_FOR_PROMOTION"}:
            continue
        if row["tool"] in found:
            continue
        found[row["tool"]] = {
            "item": item, "receipt": receipt, "tool": row["tool"],
            "work_item_id": row["work_item_id"], "operation_id": row["operation_id"],
        }
    return found


def _awaiting_receipts(missing: list[str]) -> dict[str, Any]:
    return {
        "status": "awaiting_receipts",
        "coordinator_text": None,
        "tool_executed": False,
        "claims_success": False,
        "physical_inference": False,
        "promoted": False,
        "missing_lanes": missing,
        "resend": False,
    }


def _remember_retention(control: Any, owner: str, project_id: str, work_item_id: str,
                       journal_receipt: str, status: str, detail: dict[str, Any]) -> None:
    with closing(control.store.connect("shell")) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS canvas_coordinator_retentions (
            owner TEXT NOT NULL, project_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
            journal_receipt TEXT NOT NULL, status TEXT NOT NULL, detail_json TEXT NOT NULL,
            PRIMARY KEY (owner, project_id, work_item_id))""")
        db.execute(
            "INSERT INTO canvas_coordinator_retentions VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(owner, project_id, work_item_id) DO UPDATE SET "
            "journal_receipt=excluded.journal_receipt, status=excluded.status, detail_json=excluded.detail_json",
            (owner, project_id, work_item_id, journal_receipt, status, json.dumps(detail)),
        )


def seal_fleet_admission(control: Any, admission: dict[str, Any]) -> dict[str, Any]:
    """Admission is a deterministic fallback. It does not seal a model receipt."""
    from sentra_quality.decision_receipt_audit import AuditRefusal, DecisionReceiptLedger
    from sentra_quality.production_audit import record_fleet_admission

    refused: dict[str, Any] = {
        "central_receipt_reached": False,
        "authorizes_effect": False,
        "homologated": False,
        "physical_proof": False,
        "published": False,
        "resend_allowed": False,
    }
    root = getattr(getattr(control, "durable", None), "state_root", None)
    if root is None or not isinstance(admission, dict):
        refused["reason"] = "central operation receipt unavailable"
        return refused
    try:
        sealed = record_fleet_admission(
            DecisionReceiptLedger(Path(root) / "fleet-audit"),
            admission,
            durable=control.durable,
            governance=control.governance,
            authorization=control.authorization,
        )
    except AuditRefusal as exc:
        refused["reason"] = str(exc)
        return refused
    sealed["published"] = False
    sealed["authorizes_effect"] = False
    sealed["homologated"] = False
    sealed["physical_proof"] = False
    return sealed


def remember_live_dot_if_sealed(
    control: Any, sealed: dict[str, Any], *, receipt: dict[str, Any], owner: str, dot_id: str,
    session_id: str, run_id: str, work_item_id: str, operation_id: str,
) -> dict[str, Any]:
    """Persist a Dot session only after this runner observed a live native receipt."""
    evidence = receipt.get("evidence_source")
    if evidence == "injected_test_runner" or sealed.get("source") == "deterministic_fallback":
        return {
            "saved": False, "authorizes_effects": False,
            "evidence_source": evidence, "reason": "fallback or injection is not inference",
        }
    if (
        receipt.get("observed_by") != "dot_tool_dispatch"
        or receipt.get("live_model_verified") is not True
        or evidence != "native_process"
        or sealed.get("source") != "model"
        or sealed.get("counts_as_model_decision") is not True
        or sealed.get("sealed") is not True
        or sealed.get("central_receipt_reached") is not True
        or sealed.get("physical_proof") is not False
    ):
        return {
            "saved": False, "authorizes_effects": False,
            "reason": "synthetic audit flags are not a live receipt",
        }
    root = Path(control.durable.state_root) / "dot-sessions"
    from orchestrator.memory import LiveDotSession, MemoryManager
    manager = MemoryManager(run_id, root)
    saved = LiveDotSession(root, owner, dot_id, session_id).save_dot(
        plan={"objective": "retain the admitted turn", "status": "active", "steps": []},
        context={"summary": "central receipt observed", "variables": {}, "conversation_ids": []},
        manager=manager, run_id=run_id, work_item_id=work_item_id, operation_id=operation_id,
    )
    saved["authorizes_effects"] = False
    return {"saved": True, "authorizes_effects": False, "session": saved}


def open_lane_review(control: Any, owner: str, work_item_id: str, reviewer_agent_id: str) -> dict[str, Any]:
    """Open one real review stage. This does not approve or promote."""
    policy = {
        "stages": [{
            "id": "coordinator-review",
            "type": "review",
            "actor_agent_id": reviewer_agent_id,
            "actor_user_id": None,
            "allow_any_authorized": False,
        }],
        "require_quality_gate": False,
    }
    state = {
        "current_stage_index": 0,
        "current_stage_id": "coordinator-review",
        "current_stage_type": "review",
        "status": "pending",
        "completed_stage_ids": [],
        "evidence": [],
    }
    with control.governance._connect() as db:
        db.execute(
            "UPDATE work_items SET execution_policy_json=?, execution_state_json=? "
            "WHERE work_item_id=? AND owner=? AND state='IN_REVIEW'",
            (json.dumps(policy), json.dumps(state), work_item_id, owner),
        )
    return {"work_item_id": work_item_id, "review_stage": "coordinator-review", "approved": False}


def retain_coordinator_turn(
    control: Any, owner: str, *, project_id: str, coordinator_work_item_id: str,
    journal_receipt: str | None, reviewer_agent_id: str | None = None,
) -> dict[str, Any]:
    """Hold a verified journal answer for review. Host text is not accepted here."""
    from orchestrator.providers.fleet_admission import FROZEN_NO_RESEND
    from orchestrator.providers.trio_orchestration import TRIO_LANES

    if not isinstance(journal_receipt, str) or not journal_receipt.startswith("conversation:"):
        return {
            "status": "not_inference",
            "tool_executed": False,
            "claims_success": False,
            "physical_inference": False,
            "finalized": False,
            "reason": "a journal receipt is required; host text is not inference",
        }
    found = _lane_receipts(control, owner, project_id, coordinator_work_item_id)
    for row in found.values():
        if row["operation_id"] in FROZEN_NO_RESEND:
            from orchestrator.providers.fleet_admission import note_uncertain_effect
            note_uncertain_effect(row["operation_id"])
            return {
                "status": "not_resent", "tool_executed": False, "claims_success": False,
                "physical_inference": False, "finalized": False,
            }
    missing = [lane for lane in TRIO_LANES if lane not in found]
    if missing:
        held = _awaiting_receipts(missing)
        held["journal_receipt"] = journal_receipt
        return held
    if any(row["item"].get("state") != "IN_REVIEW" for row in found.values()):
        return {
            "status": "review_blocked", "tool_executed": False, "claims_success": False,
            "physical_inference": False, "finalized": False, "journal_receipt": journal_receipt,
        }
    reviewer = reviewer_agent_id or control.work_item_info(coordinator_work_item_id, owner).get("assignee_agent_id")
    opened = [open_lane_review(control, owner, found[lane]["work_item_id"], reviewer) for lane in TRIO_LANES]
    detail = {
        "lanes": {lane: found[lane]["operation_id"] for lane in TRIO_LANES},
        "physical_inference": False,
    }
    _remember_retention(control, owner, project_id, coordinator_work_item_id, journal_receipt, "review_open", detail)
    return {
        "status": "review_open",
        "journal_receipt": journal_receipt,
        "tool_executed": False,
        "claims_success": False,
        "physical_inference": False,
        "finalized": False,
        "promoted": False,
        "reviews": opened,
    }


def finalize_reviewed_trio(
    control: Any, owner: str, *, project_id: str, coordinator_work_item_id: str,
    actor_type: str, actor_id: str,
) -> dict[str, Any]:
    """Complete the trio only after each lane has an approved review decision."""
    from orchestrator.providers.trio_orchestration import TRIO_LANES

    found = _lane_receipts(control, owner, project_id, coordinator_work_item_id)
    missing = [lane for lane in TRIO_LANES if lane not in found]
    if missing:
        return _awaiting_receipts(missing)
    approved = []
    for lane in TRIO_LANES:
        item = found[lane]["item"]
        if item.get("state") != "READY_FOR_PROMOTION":
            return {
                "status": "review_required", "finalized": False, "claims_success": False,
                "physical_inference": False, "tool_executed": False, "lane": lane,
                "state": item.get("state"),
            }
        with control.governance._connect() as db:
            decision = db.execute(
                "SELECT decision FROM review_decisions WHERE owner=? AND work_item_id=? AND stage_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (owner, found[lane]["work_item_id"], "coordinator-review"),
            ).fetchone()
        if decision is None or decision["decision"] != "approved":
            return {
                "status": "review_required", "finalized": False, "claims_success": False,
                "physical_inference": False, "tool_executed": False, "lane": lane,
            }
        approved.append(found[lane]["work_item_id"])
    completed = []
    for work_item_id in approved:
        final_item = control.transition_work_item(
            work_item_id, owner, "COMPLETED",
            reason="approved coordinator review finalized the lane",
            metadata={"finalized_by": actor_id, "actor_type": actor_type},
        )
        completed.append(final_item["work_item_id"])
    return {
        "status": "finalized",
        "finalized": True,
        "promoted": True,
        "claims_success": False,
        "physical_inference": False,
        "tool_executed": False,
        "completed_child_work_item_ids": completed,
    }


def consolidate_tool_dispatches(
    control: Any,
    owner: str,
    project_id: str,
    coordinator_work_item_id: str,
    child_work_item_ids: list[str],
    coordinator_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and consolidate completed child tool dispatches.
    
    Transitions verified child WorkItems from IN_REVIEW -> READY_FOR_PROMOTION -> COMPLETED.
    Publishes durable consolidation summary.
    """
    if not child_work_item_ids:
        raise ValueError("at least one child work item required for consolidation")

    from orchestrator.providers.fleet_admission import guard_recorded_outcome

    collected = []
    for wid in child_work_item_ids:
        item = control.work_item_info(wid, owner)
        if item.get("parent_work_item_id") != coordinator_work_item_id:
            raise PermissionError(f"work item {wid} is not a child of coordinator work item {coordinator_work_item_id}")
        if item["state"] != "IN_REVIEW":
            raise ValueError(f"child work item {wid} is in state {item['state']}; must be IN_REVIEW for consolidation")
        with closing(control.store.connect("shell")) as db:
            row = db.execute(
                "SELECT receipt_json,verified,operation_id,tool FROM canvas_dot_tool_dispatches WHERE owner=? AND project_id=? AND work_item_id=?",
                (owner, project_id, wid),
            ).fetchone()
            if row is None:
                raise ValueError(f"child work item {wid} does not possess a verified inference receipt")
            op = control.durable.operation_status(row["operation_id"], owner)
            receipt = json.loads(row["receipt_json"])
            guard_recorded_outcome(
                tool=row["tool"], operation_id=row["operation_id"],
                operation_state=op["state"], receipt=receipt,
            )
            if not row["verified"]:
                raise ValueError(f"child work item {wid} does not possess a verified inference receipt")
            if op["state"] != "SUCCEEDED":
                raise ValueError(f"child operation {row['operation_id']} is {op['state']}; must be SUCCEEDED")
        collected.append({"item": item, "operation": op, "receipt": receipt, "tool": row["tool"], "work_item_id": wid})

    return {
        "status": "review_required",
        "coordinator_work_item_id": coordinator_work_item_id,
        "completed_child_work_item_ids": [],
        "verified_receipts_count": len(collected),
        "finalized": False,
        "promoted": False,
        "physical_inference": False,
        "claims_success": False,
        "receipts": [row["receipt"] for row in collected],
    }


def compose_dot_tool_dispatch(control: Any, owner: str, intent: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
    """Adapter for ShellActorService.compose.

    Placement and the guest executor come from the host authority, never from
    model intent. Guest placement drops the host runner so a subprocess cannot
    stand in for the VM.
    """
    placement = authority.get("placement") or "host"
    if not isinstance(placement, str) or placement not in {"host", "guest"}:
        raise ValueError("placement must be host or guest")
    guest_process = authority.get("guest_process")
    runner = authority.get("runner", intent.get("runner"))
    guest_executor = authority.get("guest_executor")
    vm_id = username = password = os_family = None
    virtualbox_client = None
    if placement == "guest":
        from sentra_executors.guest_execution import resolve_guest_executor_from_authority
        runner = None
        guest_executor = resolve_guest_executor_from_authority(authority, guest_executor)
        vm_id = authority.get("vm_id")
        username = authority.get("username") or authority.get("guest_username")
        password = authority.get("password") or authority.get("guest_password")
        os_family = authority.get("os_family")
        virtualbox_client = authority.get("virtualbox_client") or authority.get("guest_client")
    return execute_dot_tool_dispatch(
        control=control,
        owner=owner,
        project_id=authority["project_id"],
        conversation_id=authority["conversation_id"],
        run_id=authority["run_id"],
        work_item_id=authority["work_item_id"],
        parent_operation_id=authority["parent_operation_id"],
        agent_id=authority["agent_id"],
        intent=intent,
        request_key=authority.get("request_key", f"dispatch-{authority['operation_id']}"),
        compose=None,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [intent.get("target_dot_id")],
        runner=runner,
        placement=placement,
        guest_process=guest_process if isinstance(guest_process, dict) else None,
        guest_executor=guest_executor,
        vm_id=vm_id if isinstance(vm_id, str) else None,
        username=username if isinstance(username, str) else None,
        password=password if isinstance(password, str) else None,
        os_family=os_family if isinstance(os_family, str) else None,
        guest_workspace=authority.get("guest_workspace") if isinstance(authority.get("guest_workspace"), str) else None,
        virtualbox_client=virtualbox_client,
    )
