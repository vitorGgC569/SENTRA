"""Compact native Canvas control on the developer MCP surface."""
from typing import Any,Literal
from mcp.server.mcpserver.context import Context
from ..identity import resolve_owner,authorization_principal
from ..models import ResponseEnvelope
from .commander import _guard_tool_errors
from ..services.native_canvas import READ_ACTIONS
from sentra_core.conversations import UncertainCall


def register_native_canvas_tools(mcp,service):
    @mcp.tool()
    @_guard_tool_errors
    def sentra_canvas(
        action:Literal["status","start","workspaces","workspace","workspace_attach",
            "terminal_create","terminal_input","terminal_output","terminal_resize","terminal_close",
            "agent_create","agent_restart","team_create","task_delegate","task_status","task_cancel",
            "task_governance","task_block","task_unblock","task_verify","budget_list","budget_set",
            "note_create","note_update","note_delete","link","unlink","handoff","handoffs",
            "run_pause","run_resume","run_cancel","request_status","request_resolve"],
        ctx:Context,
        workspace:str|None=None,
        params:dict[str,Any]|None=None,
        request_key:str|None=None,
        confirm:bool=False,
        session_token:str|None=None,
    )->ResponseEnvelope:
        """Control SENTRA's native Canvas through existing Commander grants.

        start reuses/starts its persistent broker. workspace_attach takes name/path.
        Other actions require a Canvas workspace ID/name/path. Mutations require
        a stable request_key; reuse it only with identical arguments. task_delegate
        takes team/agent/prompt and runs the genuine CLI; agent_create takes
        name/model/role/start. terminal actions take id and their documented data,
        cols/rows or shell/name. Link/handoff take source/target and message.
        confirm=true is required for handoff/task_delegate/close/delete/run_cancel.
        request_status inspects uncertain delivery; request_resolve requires
        executed/evidence plus confirm=true, and never replays automatically.
        run_resume after cancellation opens a new run without replaying old tasks.
        task_governance reads the work item, quota ledger and admission decision;
        task_block/task_unblock take id and affect queued tasks only. budget_set
        takes scope (workspace/run/work_item), limits, optional task_id and mode;
        disable/enable an existing visible policy using policy_id and enabled.
        One quota_usage unit reserves one task admission; monetary pricing is unknown.
        task_delegate accepts optional checks [{path,sha256}] or [{path,text}]
        for at most 16 workspace-relative files. Successful CLI execution verifies
        those immutable criteria, registers artifacts and follows governance policy.
        task_verify takes id to recheck existing outputs without rerunning the task.
        Open a signed session with sentra_session_open when the transport requires it.
        """
        owner=resolve_owner(ctx,session_token=session_token,require_session=action not in READ_ACTIONS)
        principal,_,_=authorization_principal(ctx)
        try:
            result=service.execute(action,owner=owner,principal=principal,
                workspace=workspace,params=params,request_key=request_key,confirm=confirm)
            return ResponseEnvelope.success(result)
        except UncertainCall as exc:
            return ResponseEnvelope.failure("operation_uncertain",str(exc),category="state",retryable=False)
