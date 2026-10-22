"""ConPTY input through actual central durable SQLite/grants/physical fence.

Fake transport deliberately isolated: this proves the SENTRA physical admission
and no double delivery, not OS ConPTY availability.
"""
import asyncio
import pytest
from sentra_executors.conpty_sessions import ExistingConPTYSession
from sentra_mcp.services.action_consent_gate import ActionConsentService,_digest
from test_sentra_cos_chat2_action_and_message import _central, OWNER


class _Store:
    principal=OWNER
    def __init__(self,path): self.path=str(path)
    def workspace(self,id):
        assert id=="ws-stdin-tested"
        return dict(owner=OWNER,run_id="run-api",path=self.path)
    def resource(self,kind,id,ws):
        assert (kind,id,ws)==("terminals","terminal-tested","ws-stdin-tested")
        return {"id":id,"status":"running"}


class _Canvas:
    def __init__(self,path):
        self.store=_Store(path)
        self.sent=[]
    def terminal_input(self,workspace,terminal,data):
        self.sent.append((workspace,terminal,data))


def test_consented_stdin_durable_operation_single_delivery(tmp_path):
    cp,_,args=_central(tmp_path)
    cp.create_work_item("run-api",OWNER,work_item_id="WI-stdin-consent",
        objective="Physical ConPTY test",assignee_agent_id="agent-001",
        required_capabilities=["api:action:terminal.write_stdin","terminal:write"],
        metadata={'workspace_id':'ws-stdin-tested'})
    cp.transition_work_item("WI-stdin-consent",OWNER,"RUNNING")
    auth=lambda owner,purpose,proof: OWNER if owner==OWNER and proof.startswith("approved-click-") else None
    consent=ActionConsentService(tmp_path/"state",owner_authenticator=auth)
    terminal=_Canvas(tmp_path)
    binding=ExistingConPTYSession(control=cp,canvas=terminal)
    owner=OWNER
    try:
        consent.allow_api(owner=owner,agent_id="agent-001",work_item_id="WI-stdin-consent",
            enabled=True,expected_revision=0,human_confirmed=True,
            owner_proof="approved-click-1-superlong-unique")
        data="status\r"
        body={"action":"write_stdin","workspace_id":"ws-stdin-tested",
              "terminal_id":"terminal-tested",
              "payload_sha256":__import__("hashlib").sha256(data.encode()).hexdigest()}
        proposal=consent.propose_action(owner=owner,agent_id="agent-001",
                work_item_id="WI-stdin-consent",request_id=args["request_id"],
                message_id=args["message_id"],action="terminal.write_stdin",body=body)
        assert proposal["body_sha256"]==_digest(body)
        consent.approve_action(action_id=proposal["action_id"],
                body_sha256=proposal["body_sha256"],human_confirmed=True,
                owner_proof="approved-click-2-superlong-unique")
        params=dict(consent=consent,owner=owner,run_id="run-api",
                work_item_id="WI-stdin-consent",principal_id="agent-001",
                workspace_id="ws-stdin-tested",terminal_id="terminal-tested",
                data=data,request_id=args["request_id"],message_id=args["message_id"],
                action_id=proposal["action_id"],operation_id="op-stdin-confirmed",
                idempotency_key="idem-stdin-confirmed")
        with pytest.raises(PermissionError):
            binding.write_stdin(owner,run_id="run-api",work_item_id="WI-stdin-consent",
                principal_id="agent-001",workspace_id="ws-stdin-tested",
                terminal_id="terminal-tested",data=data,operator_approved=True)
        with pytest.raises(PermissionError,match="grant"):
            asyncio.run(binding.execute_consented_stdin(**params))
        assert terminal.sent==[]
        cp.authorization_grant(owner,principal_type="agent",
            principal_id="agent-001",capability="api:action:terminal.write_stdin",
            scope_type="work_item",scope_id="WI-stdin-consent")
        cp.authorization_grant(owner,principal_type="agent",
            principal_id="agent-001",capability="terminal:write",
            scope_type="work_item",scope_id="WI-stdin-consent")
        first=asyncio.run(binding.execute_consented_stdin(**params))
        assert first.operation.state=="SUCCEEDED", first.operation
        assert len(terminal.sent)==1 and terminal.sent[0][-1]==data
        replay=asyncio.run(binding.execute_consented_stdin(**params))
        assert replay.duplicate and len(terminal.sent)==1
        assert cp.durable.operation_status("op-stdin-confirmed",owner)["state"]=="SUCCEEDED"
        with pytest.raises(PermissionError,match="used"):
            asyncio.run(binding.execute_consented_stdin(
                **{**params,"operation_id":"op-stdin-another",
                    "idempotency_key":"idem-stdin-another"}))
        assert len(terminal.sent)==1
    finally:
        cp.durable.close()
