"""Reviewed observation classifications; agent flags never qualify."""
def is_observation(request,kind):
    if kind=="openhands":
        return request.capability_id in {"openhands:read","openhands:events","openhands:evidence","openhands:health"}
    if kind == "acp":
        return request.capability_id in {"acp:events", "acp:state", "acp:list"}
    if kind == "a2a":
        return request.capability_id in {"a2a:discover", "a2a:get", "a2a:events", "a2a:artifact", "a2a:extended_card", "a2a:callback"}
    if kind == "mcp":
        return request.capability_id in {"mcp:list", "mcp:resources_list", "mcp:templates_list", "mcp:resource_read", "mcp:prompts_list", "mcp:prompt_read", "mcp:notifications"}
    if kind == "channels":
        return request.capability_id in {"channel:receipt", "channel:inbox"}
    if kind == "acp_registry":
        return request.capability_id in {"acp:catalog", "acp:plan", "acp:installed"}
    if kind in {"runtime", "runtime-temporal", "runtime-langgraph"}:
        return request.capability_id in {"runtime:temporal:observe", "runtime:temporal:reconcile",
                                         "runtime:langgraph:observe", "runtime:langgraph:reconcile"}
    if kind=="workflow":
        # advance/resume only reconcile durable checkpoints and PLAN future
        # operations; they must not block on an uncertain physical activity
        # lease. The activity itself still needs a separately fenced grant.
        return request.capability_id in {"workflow:observe","workflow:output",
                                         "workflow:advance","workflow:resume",
                                         "piece:file_observe"}
    if kind in {"pieces","activepieces"}:
        # Only pinned read-only queries bypass the physical effect lease.
        # Cancellation, trigger ingestion, and piece invocation still require
        # their own fenced physical admission, never an observation lease.
        return request.capability_id in {"activepieces:observe","activepieces:artifact",
                                         "activepieces:catalog","activepieces:trigger_reconcile"}
    action=request.arguments.get("action")
    if kind=="documents":
        return request.capability_id=="document:inspect" and action in {
            "excel.inspect","table.inspect","pdf.inspect","pdf.text","artifact.verify","acceptance.evaluate"}
    if kind=="playwright_browser":
        return request.capability_id=="browser:operate" and action in {"observe","read","evidence"}
    if kind=="daytona_session":return action in {"session.list","session.status","session.events","sandbox.read","sandbox.reconcile","sandbox.network.reconcile","pty.read","command.read","computer.observe","computer.status","computer.screenshot"}
    if kind=="guacamole":return action in {"session.list","status","read","recording.read","clipboard.read"}
    if kind=="rustdesk":return action in {"session.list","desktop.status","frame"}
    if kind=="virtualbox_vm":return request.capability_id == 'vm:observe' and action in {'status', 'frame'}
    if kind in {"windows_uia_semantic", "windows_guest_uia"}:return action in {"observe", "observe.hybrid", "read", "screenshot"}
    return False
