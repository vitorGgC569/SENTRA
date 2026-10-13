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
) -> dict[str, Any]:
    """Admit and execute agent coordinator dot_tool_dispatch intent."""
    if not isinstance(intent, dict):
        raise ValueError("structured coordinator intent required")
    if set(intent) - {'kind', 'tool', 'target_dot_id', 'instruction', 'prompt', 'nonce', 'model', 'effort', 'timeout_s'}:
        raise ValueError('unsupported coordinator tool intent fields')
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
                    return {
                        "status": row["status"],
                        "work_item_id": ids["work_item_id"],
                        "operation_id": ids["operation_id"],
                        "receipt": receipt,
                        "idempotent_replay": True,
                    }

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
            runner=custom_runner,
        )
        if not is_live() or policy(request).allowed is not True:
            receipt.update(verified=False, execution_uncertain=True,
                error='coordinator authority changed during tool execution')
        receipt['evidence_source'] = 'injected_test_runner' if custom_runner is not None else 'native_process'
        receipt['live_model_verified'] = bool(receipt.get('verified') and custom_runner is None)

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
        return outcome

    return host_requests.invoke(
        project_id,
        "dot_tool_dispatch",
        {"work_item_id": work_item_id, "intent": intent},
        request_key,
        run_dispatch,
    )


def consolidate_tool_dispatches(
    control: Any,
    owner: str,
    project_id: str,
    coordinator_work_item_id: str,
    child_work_item_ids: list[str],
) -> dict[str, Any]:
    """Validate and consolidate completed child tool dispatches.
    
    Transitions verified child WorkItems from IN_REVIEW -> READY_FOR_PROMOTION -> COMPLETED.
    Publishes durable consolidation summary.
    """
    if not child_work_item_ids:
        raise ValueError("at least one child work item required for consolidation")

    consolidated = []
    receipts = []
    
    for wid in child_work_item_ids:
        item = control.work_item_info(wid, owner)
        if item.get("parent_work_item_id") != coordinator_work_item_id:
            raise PermissionError(f"work item {wid} is not a child of coordinator work item {coordinator_work_item_id}")
        
        # State must be IN_REVIEW
        if item["state"] != "IN_REVIEW":
            raise ValueError(f"child work item {wid} is in state {item['state']}; must be IN_REVIEW for consolidation")
        
        with closing(control.store.connect("shell")) as db:
            row = db.execute(
                "SELECT receipt_json,verified,operation_id FROM canvas_dot_tool_dispatches WHERE owner=? AND project_id=? AND work_item_id=?",
                (owner, project_id, wid),
            ).fetchone()
            if not row or not row["verified"]:
                raise ValueError(f"child work item {wid} does not possess a verified inference receipt")
            
            op = control.durable.operation_status(row["operation_id"], owner)
            if op["state"] != "SUCCEEDED":
                raise ValueError(f"child operation {row['operation_id']} is {op['state']}; must be SUCCEEDED")
            
            receipt = json.loads(row["receipt_json"])
            receipts.append(receipt)

        # Transition: IN_REVIEW -> READY_FOR_PROMOTION -> COMPLETED
        control.transition_work_item(
            wid, owner, "READY_FOR_PROMOTION",
            reason="coordinator validated non-interactive receipt",
            metadata={"consolidated_by": coordinator_work_item_id},
        )
        final_item = control.transition_work_item(
            wid, owner, "COMPLETED",
            reason="coordinator published final consolidation",
            metadata={"consolidated_by": coordinator_work_item_id},
        )
        consolidated.append(final_item["work_item_id"])

    summary = {
        "status": "consolidated",
        "coordinator_work_item_id": coordinator_work_item_id,
        "completed_child_work_item_ids": consolidated,
        "verified_receipts_count": len(receipts),
        "receipts": receipts,
    }
    return summary


def compose_dot_tool_dispatch(control: Any, owner: str, intent: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
    """Adapter for ShellActorService.compose."""
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
        runner=intent.get("runner"),
    )
