"""G06 native Canvas protected transcript; no subprocess or parallel PTY spawned."""
import pytest

from sentra_canvas.service import Canvas
from sentra_executors.conpty_sessions import ExistingConPTYSession
from test_governance_coordination import _services


def test_existing_canvas_transcript_cursor_head_tail_with_central_workitem(tmp_path):
    canvas=Canvas(tmp_path/"canvas",max_terminals=2)
    durable,context,control=_services(tmp_path/"core")
    try:
        ws=canvas.create_workspace("ConPTYLab")
        owner=canvas.store.principal
        run=durable.create_run(owner,workspace=ws["path"],run_id=ws["run_id"])["run_id"]
        control.ensure_agent(run,owner,agent_id="conpty-agent",role="builder")
        work=control.create_work_item(run,owner,objective="Inspect existing terminal",assignee_agent_id="conpty-agent",metadata={"workspace_id":ws["id"]})
        terminal=canvas.store.create_terminal(ws["id"],"PreviouslyStarted","sentra-cli")
        canvas.store.append_terminal_output(ws["id"],terminal["id"],"line-one\nline-two\n")
        canvas.store.terminal_state(ws["id"],terminal["id"],"exited")
        from sentra_executors.conpty_sessions import PersistentConPTYLedger
        PersistentConPTYLedger(control).register(owner,workspace_id=ws["id"],terminal_id=terminal["id"],run_id=run,work_item_id=work["work_item_id"],principal_id="conpty-agent",name="PreviouslyStarted",shell="sentra-cli")
        adapter=ExistingConPTYSession(control=control,canvas=canvas)
        params=dict(owner=owner,run_id=run,work_item_id=work["work_item_id"],
                    principal_id="conpty-agent",workspace_id=ws["id"],
                    terminal_id=terminal["id"])
        with pytest.raises(PermissionError):
            adapter.read(**params)
        control.authorization.grant(owner,principal_type="agent",
            principal_id="conpty-agent",capability="terminal:read",
            scope_type="work_item",scope_id=work["work_item_id"])
        output=adapter.read(**params,head_chars=5,tail_chars=5)
        assert output["head"]=="line-" and output["tail"]=="-two\n"
        assert output["cursor"]==len("line-one\nline-two\n")
        assert output["status"]=="exited"
        assert output["live"] is False and output["persisted"] is True
        assert output["owned_process_terminated"] is False
        assert adapter.read(**{**params,"cursor":output["cursor"]})["tail"]==""
        with pytest.raises(PermissionError):
            adapter.read(**{**params,"owner":"wrong-owner"})
        with pytest.raises(PermissionError):
            adapter.read(**{**params,"run_id":"wrong-run"})
        with pytest.raises(PermissionError):
            adapter.write_stdin(**params,data="unsafe\r",operator_approved=True)
        with pytest.raises(ValueError):
            adapter.read(**params,tail_chars=9000)
        assert canvas.store.resource("terminals",terminal["id"],ws["id"])["status"]=="exited"
    finally:
        canvas.shutdown();context.close();durable.close()


def test_conpty_requires_durable_effect_for_write_even_with_grant(tmp_path):
    canvas=Canvas(tmp_path/"canvas",max_terminals=1)
    durable,context,control=_services(tmp_path/"core")
    try:
        ws=canvas.create_workspace("ConPTYGate")
        owner=canvas.store.principal
        run=durable.create_run(owner,workspace=ws["path"],run_id=ws["run_id"])["run_id"]
        control.ensure_agent(run,owner,agent_id="conpty-agent",role="builder")
        work=control.create_work_item(run,owner,objective="Write via central gate only",assignee_agent_id="conpty-agent",metadata={"workspace_id":ws["id"]})
        terminal=canvas.store.create_terminal(ws["id"],"NotRunning","sentra-cli")
        control.authorization.grant(owner,principal_type="agent",
            principal_id="conpty-agent",capability="terminal:write",
            scope_type="work_item",scope_id=work["work_item_id"])
        gate=ExistingConPTYSession(control=control,canvas=canvas)
        p=dict(owner=owner,run_id=run,work_item_id=work["work_item_id"],
               principal_id="conpty-agent",workspace_id=ws["id"],
               terminal_id=terminal["id"],data="status\r")
        with pytest.raises(PermissionError,match="approval"):
            gate.write_stdin(**p)
        with pytest.raises(PermissionError,match="central durable"):
            gate.write_stdin(**p,operator_approved=True)
        assert canvas.store.resource("terminals",terminal["id"],ws["id"])["status"]=="starting"
    finally:
        canvas.shutdown();context.close();durable.close()
