"""Windows-only owned real PTY proof through host-auth, SQLite and central gate."""
import asyncio
import hashlib
import os
import time
import pytest
from sentra_canvas.service import Canvas
from sentra_executors.conpty_sessions import ExistingConPTYSession
from sentra_mcp.services.action_consent_gate import ActionConsentService, HostOwnerClickAuthenticator, HostOwnerSession
from sentra_mcp.services.browser_evidence import BrowserEvidenceService
from test_governance_coordination import _services
from test_sentra_cos_chat2_action_and_message import _observe,EXT,SHA,REQ,MSG


@pytest.mark.skipif(os.name!="nt", reason="Windows ConPTY only")
def test_owned_windows_pty_start_write_read_physical_fences(tmp_path):
    canvas=Canvas(tmp_path/"canvas",max_terminals=1)
    durable,context,cp=_services(tmp_path/"core")
    try:
        ws=canvas.create_workspace("IsolatedConPTYLab")
        owner=canvas.store.principal
        run=durable.create_run(owner,workspace=ws["path"],run_id=ws["run_id"])["run_id"]
        cp.ensure_agent(run,owner,agent_id="pty-agent",role="builder")
        wi="WI-physical-pty-2026"
        cp.create_work_item(run,owner,work_item_id=wi,objective="Review and run local PTY",
            assignee_agent_id="pty-agent",required_capabilities=[
                "api:action:terminal.start","api:action:terminal.write_stdin",
                "terminal:start","terminal:write","terminal:read",
                "api:action:terminal.close","terminal:close"])
        cp.transition_work_item(wi,owner,"RUNNING")
        be=BrowserEvidenceService(tmp_path/"core")
        be.configure(extension_id=EXT,source_sha256=SHA,principal=owner,
            workspace=str(tmp_path/"core"),enabled=True,expected_revision=0)
        _observe(be)
        host_session=HostOwnerSession(owner,"lab-session-"+("s"*48),
                                      "http://127.0.0.1:8765",True)
        issuer=HostOwnerClickAuthenticator(tmp_path/"core",session_lookup=lambda:host_session)
        consent=ActionConsentService(tmp_path/"core",owner_authenticator=issuer)
        consent.allow_api(owner=owner,agent_id="pty-agent",work_item_id=wi,
            enabled=True,expected_revision=0,human_confirmed=True,
            owner_proof=issuer.issue_click(owner=owner,purpose="api-consent"))
        for capability in ("api:action:terminal.start","api:action:terminal.write_stdin",
                           "terminal:start","terminal:write","terminal:read",
                           "api:action:terminal.close","terminal:close"):
            cp.authorization_grant(owner,principal_type="agent",principal_id="pty-agent",
                    capability=capability,scope_type="work_item",scope_id=wi)
        start_errors=[]
        native_start=canvas.create_terminal
        def inspect_start(*a,**kw):
            try:
                return native_start(*a,**kw)
            except Exception as exc:
                start_errors.append(type(exc).__name__+": "+str(exc))
                raise
        canvas.create_terminal=inspect_start
        adapter=ExistingConPTYSession(control=cp,canvas=canvas)
        def propose(action,body,proof):
            proposal=consent.propose_action(owner=owner,agent_id="pty-agent",work_item_id=wi,
                request_id=REQ,message_id=MSG,action=action,body=body)
            consent.approve_action(action_id=proposal["action_id"],
                body_sha256=proposal["body_sha256"],human_confirmed=True,
                owner_proof=issuer.issue_click(owner=owner,purpose="action:"+proposal["action_id"]))
            return proposal["action_id"]
        action=propose("terminal.start",{"workspace_id":ws["id"],
                "name":"PTY_Isolated", "shell":"powershell"},"lab-click-02-start-receipt")
        try:
            start=asyncio.run(adapter.execute_consented_start(
                consent=consent,owner=owner,run_id=run,work_item_id=wi,
                principal_id="pty-agent",workspace_id=ws["id"],name="PTY_Isolated",
                shell="powershell",request_id=REQ,message_id=MSG,action_id=action,
                operation_id="op-physical-start2026",idempotency_key="idem-physical-start2026"))
        except (OSError,ImportError,FileNotFoundError) as exc:
            pytest.skip("ConPTY host unavailable: "+type(exc).__name__)
        assert start.operation.state=="SUCCEEDED", (start.operation,start_errors)
        terminal_id=start.payload["id"]
        assert cp.durable.operation_status("op-physical-start2026",owner)["state"]=="SUCCEEDED"
        again=asyncio.run(adapter.execute_consented_start(
                consent=consent,owner=owner,run_id=run,work_item_id=wi,
                principal_id="pty-agent",workspace_id=ws["id"],name="PTY_Isolated",
                shell="powershell",request_id=REQ,message_id=MSG,action_id=action,
                operation_id="op-physical-start2026",idempotency_key="idem-physical-start2026"))
        assert again.duplicate and len(canvas.store.list_resources("terminals",ws["id"]))==1
        command="Write-Output SENTRA_OWNED_PTY_OK\r"
        body={"action":"write_stdin","workspace_id":ws["id"],
              "terminal_id":terminal_id,
              "payload_sha256":hashlib.sha256(command.encode()).hexdigest()}
        action2=propose("terminal.write_stdin",body,"lab-click-03-write-unique")
        write=dict(consent=consent,owner=owner,run_id=run,work_item_id=wi,
                   principal_id="pty-agent",workspace_id=ws["id"],
                   terminal_id=terminal_id,data=command,request_id=REQ,message_id=MSG,
                   action_id=action2,operation_id="op-physical-write2026",
                   idempotency_key="idem-physical-write2026")
        done=asyncio.run(adapter.execute_consented_stdin(**write))
        assert done.operation.state=="SUCCEEDED",done.operation
        # Re-create host objects after simulated ACK loss; same durable Operation
        # returns a duplicate and cannot write the PTY for a second time.
        restarted_consent=ActionConsentService(tmp_path/"core",
            owner_authenticator=HostOwnerClickAuthenticator(
                tmp_path/"core",session_lookup=lambda:host_session))
        restarted_adapter=ExistingConPTYSession(control=cp,canvas=canvas)
        assert asyncio.run(restarted_adapter.execute_consented_stdin(
            **{**write,"consent":restarted_consent})).duplicate
        observed=""
        for _ in range(24):
            observed=adapter.read(owner,run_id=run,work_item_id=wi,
                principal_id="pty-agent",workspace_id=ws["id"],
                terminal_id=terminal_id,head_chars=8192,tail_chars=8192)["tail"]
            if "SENTRA_OWNED_PTY_OK" in observed:
                break
            time.sleep(0.15)
        assert "SENTRA_OWNED_PTY_OK" in observed
        assert adapter.read(owner,run_id=run,work_item_id=wi,
            principal_id="pty-agent",workspace_id=ws["id"],
            terminal_id=terminal_id)["live"] is True
        gc_action=propose("terminal.close",
            {"workspace_id":ws["id"],"terminal_id":terminal_id},
            "lab-click-04-owned-handle-gc")
        gc=dict(consent=consent,owner=owner,run_id=run,work_item_id=wi,
            principal_id="pty-agent",workspace_id=ws["id"],terminal_id=terminal_id,
            request_id=REQ,message_id=MSG,action_id=gc_action,
            operation_id="op-physical-close2026",
            idempotency_key="idem-physical-close2026")
        closed=asyncio.run(adapter.execute_consented_close(**gc))
        assert closed.operation.state=="SUCCEEDED",closed.operation
        assert closed.payload["closed_owned_handle"] is True
        assert asyncio.run(adapter.execute_consented_close(**gc)).duplicate
        assert canvas.store.resource("terminals",terminal_id,ws["id"])["status"]=="closed"
        # Persisted PID alone is never GC ownership; the live handle is closed.
        gc_again=propose("terminal.close",
            {"workspace_id":ws["id"],"terminal_id":terminal_id},
            "lab-click-05-stale-pid-no-handle")
        denied=asyncio.run(adapter.execute_consented_close(
            **{**gc,"action_id":gc_again,"operation_id":"op-pid-only-rejected",
               "idempotency_key":"idem-pid-only-rejected"}))
        assert denied.operation.state=="UNCERTAIN"
        assert canvas.store.resource("terminals",terminal_id,ws["id"])["status"]=="closed"
        assert len(canvas.store.list_resources("terminals",ws["id"]))==1
    finally:
        # Canvas holds its own live PTY handle; no global PID enumeration/kills.
        canvas.shutdown()
        context.close()
        durable.close()
