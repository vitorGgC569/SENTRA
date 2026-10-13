"""Conversation goals for the signed-in shell, using existing central authority."""
from contextlib import closing
from sentra_executors.goal_loop import ConversationGoalLoop
from .shell_requests import ShellHostRequests
from .store import Denied

GOAL_ACTIONS = frozenset({"goal_status", "goal_set", "goal_stop", "goal_complete", "goal_loop_start", "goal_loop_stop", "goal_loop_step"})


def dispatch_goal(canvas, project_id, action, params, request_key):
    fields = {"space_id", "conversation_id", "goal_id"}
    fields |= {"goal_set": {"objective"}, "goal_loop_start": {"max_steps", "max_cost_usd", "deadline_seconds"},
        "goal_loop_step": {"objective"}}.get(action, set())
    if set(params) - fields or not {"space_id", "conversation_id"} <= params.keys():
        raise ValueError("canonical Space/conversation goal required")
    control, runtime = canvas._shell_service(), canvas._runtime()
    owner, cid = runtime.owner, params["conversation_id"]
    control.shell.get_space(params["space_id"], owner, project_id=project_id)
    with closing(control.store.connect("shell")) as db:
        conversation = control.shell._entity(db, owner, project_id, "conversation", cid, space_id=params["space_id"])
        dot = control.shell._entity(db, owner, project_id, "dot", conversation["dot_id"], space_id=params["space_id"])
    service = ConversationGoalLoop(control)
    current = service.status(owner, cid)
    if params.get("goal_id") and params["goal_id"] != current.get("goal_id"):
        raise Denied("goal changed or belongs to another conversation")
    if action == "goal_status":
        return {**current, "dot_id": dot["dot_id"]}
    def apply():
        if action == "goal_set":
            current = service.set(owner, cid, run_id=runtime.run(project_id)["run_id"],
                objective=params.get("objective"), operator_approved=True)
        elif action == "goal_stop":
            current = service.stop(owner, cid, operator_approved=True)
        elif action == "goal_complete":
            current = service.status(owner, cid)
            if current.get("goal") and not current["goal"].get("terminal"):
                service.loop_stop(owner, cid, operator_approved=True)
                control.update_goal(current["goal_id"], owner, state="SUCCEEDED", reason="conversation owner confirmed completion")
            current = service.status(owner, cid)
        elif action == "goal_loop_start":
            current = service.open(owner, cid, principal_id=dot["agent_id"],
                max_steps=params.get("max_steps", 2), max_cost_usd=params.get("max_cost_usd", 0),
                deadline_seconds=params.get("deadline_seconds", 120), operator_approved=True)
        elif action == "goal_loop_stop":
            current = service.loop_stop(owner, cid, operator_approved=True)
        else:
            current = service.advance(owner, cid, objective=params.get("objective"), operator_approved=True)
        return {**current, "dot_id": dot["dot_id"], "status": "committed"}
    return ShellHostRequests(control, owner).invoke(project_id, action, params, request_key, apply)


def goal_context(control, owner, conversation_id):
    current = ConversationGoalLoop(control).status(owner, conversation_id)
    if current["state"] != "ACTIVE":
        return None
    return {"goal_id": current["goal_id"], "objective": current["goal"]["objective"]}
