"""Reviewed observation classifications; agent flags never qualify."""
def is_observation(request,kind):
    if kind=="openhands":
        return request.capability_id in {"openhands:read","openhands:events","openhands:evidence"}
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
    if kind=="daytona_session":return action in {"session.list","sandbox.read","sandbox.reconcile","pty.read","command.read"}
    if kind=="guacamole":return action in {"session.list","read","recording.read"}
    if kind=="rustdesk":return action=="session.list"
    return False
