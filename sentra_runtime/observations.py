"""Reviewed observation classifications; agent flags never qualify."""
def is_observation(request,kind):
    if kind=="openhands":
        return request.capability_id in {"openhands:read","openhands:events","openhands:evidence"}
    if kind=="workflow":
        return request.capability_id in {"workflow:observe","workflow:output"}
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
