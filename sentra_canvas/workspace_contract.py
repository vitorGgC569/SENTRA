"""Versioned presentation contract. Resource ownership remains in Canvas/control."""
from __future__ import annotations

import hashlib
import platform

PROTOCOL_VERSION = 1
PANE_KINDS = ("map", "terminals", "files", "review", "browser", "computer", "activity")


def inventory(canvas, project_id, params):
    if set(params) != {"space_id", "dot_id"}:
        raise ValueError("exact workspace scope required")
    from .shell_dot_canvas import dot_graph
    graph = dot_graph(canvas, project_id, params["dot_id"], params["space_id"])
    from sentra_runtime.orchestration_observation import convergence
    # Layout identity is opaque and owner scoped, never usable as authority.
    key = hashlib.sha256("\0".join((canvas.store.principal, project_id,
        params["space_id"], params["dot_id"])).encode()).hexdigest()
    host_id=hashlib.sha256((str(canvas.state_dir)+'\0'+platform.node()).encode()).hexdigest()[:24]
    terminal_owners={agent.get('terminal_id'):agent['id'] for agent in graph['agents'] if agent.get('terminal_id')}
    dots_by_agent={dot['agent_id']:dot for dot in graph['dots']}
    terminals={t['id']:{**t,'dot_id':dots_by_agent.get(terminal_owners.get(t['id']),{}).get('dot_id'),
        'host_id':host_id} for t in graph['terminals']}
    for session in graph['tool_sessions']:
        terminal=session['terminal']
        terminals[terminal['id']]={**terminal,'dot_id':session['member_dot_id'],'host_id':host_id,'tool':session['tool']}
    # Central terminal lifecycles may exist before a graph/tool view attaches.
    # Reuse the existing Dot inventory; observing it never starts a process.
    from .shell_dot_computer import DotComputerServices
    central=DotComputerServices(canvas).dispatch(project_id,'dot_computer_get',params)
    for terminal in central['terminals']:
        if terminal.get('dot_id') in {dot['dot_id'] for dot in graph['dots']}:
            terminals[terminal['id']]={**terminals.get(terminal['id'],{}),**terminal,'host_id':host_id}
    return {"protocol_version": PROTOCOL_VERSION, "layout_scope": key,
            "project_id": project_id, "space_id": params["space_id"],
            "dot_id": params["dot_id"], "graph": graph,
            "host": {"id":host_id,"label":platform.node(),"kind":"local"},
            "resources": {"terminals":list(terminals.values())},
            "receipts": [{"handoff_id": item.get("handoff_id"),
                          **delivery_projection(item)} for item in graph.get("deliveries", [])],
            "pane_kinds": list(PANE_KINDS), "repository_required": False,
            "convergence": convergence(graph.get("tasks", [])),
            "authority": "sentra-control-plane", "restoration_creates_resources": False}


def delivery_projection(receipt):
    """A presentation projection, not a receipt writer or a success heuristic."""
    state = str(receipt.get("operation_state", receipt.get("state", receipt.get("status", "unknown")))).upper()
    stage = {"QUEUED": "accepted", "ACCEPTED": "accepted", "SENT": "delivered",
             "RUNNING": "observing", "WAITING_EXTERNAL": "observing",
             "SUCCEEDED": "completed", "FAILED": "failed", "CANCELLED": "cancelled",
             "UNCERTAIN": "uncertain", "UNCONFIRMED": "uncertain"}.get(state, "unknown")
    from sentra_runtime.task_lifecycle import project_task
    return {"stage": stage, "source_state": state,
            "lifecycle":project_task(receipt),
            "completion_scope": "operation",
            "completed": state == "SUCCEEDED", "requires_reconciliation": stage == "uncertain",
            "automatic_retry": False, "operation_id": receipt.get("operation_id"),
            "receipt_id": receipt.get("receipt_id")}
