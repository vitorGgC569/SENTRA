"""Prepared acceptance: real central SQLite, explicit httpx protocol fixture.

MockTransport below proves router payloads/admission/recovery, never an external
OpenHands Agent Server or an actual agent tool execution.
"""
import asyncio
import json
import uuid

import pytest

from sentra_interop.openhands_provider import (OpenHandsAgentServerProvider,OpenHandsHTTPTransport,
                                              OpenHandsIdentityStore,OpenHandsServerConfig)
from sentra_interop.openhands import OpenHandsSDKEvent
from sentra_interop.central import CentralInteropAdapter
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Capability,Machine,OperationRequest


@pytest.fixture
def harness(tmp_path):
    httpx=pytest.importorskip("httpx",reason="OpenHands opt-in HTTP dependency not installed")
    durable=DurableRunService(tmp_path/"central")
    cp=ControlPlaneService(durable,ContextBusService(tmp_path/"central"))
    caps=tuple("openhands:"+c for c in ("create","read","events","evidence","message","run","cancel"))
    durable.create_run("owner",run_id="run",workspace=str(tmp_path))
    cp.ensure_agent("run","owner",agent_id="agent",role="worker")
    cp.create_work_item("run","owner",work_item_id="work",objective="OpenHands acceptance",
                        assignee_agent_id="agent",required_capabilities=list(caps))
    cp.transition_work_item("work","owner","RUNNING")
    for cap in caps:
        cp.authorization_grant("owner",principal_type="agent",principal_id="agent",capability=cap,
                               scope_type="work_item",scope_id="work")
    center=CentralInteropAdapter(control=cp,run_id="run",owner="owner",
        machine=Machine("machine","agent-server","owner",tuple(Capability(c,c) for c in caps)))
    config=OpenHandsServerConfig("http://127.0.0.1:9000","fixture","/workspace",str(uuid.uuid4()),enabled=True)
    records={}
    calls=[]
    source=[{"id":"event-1","kind":"ActionEvent","source":"agent","timestamp":"2026-10-09T10:00:00",
        "parent_id":"__root__","tool_name":"read_file","tool_call_id":"call-1","thought":[],"action":{"path":"a"}},
        {"id":"event-2","kind":"ObservationEvent","source":"environment","timestamp":"2026-10-09T10:00:01",
        "tool_name":"read_file","tool_call_id":"call-1","action_id":"event-1","observation":{"text":"actual fixture evidence"}}]
    state={"message_429":False,"status_unavailable":False}
    def route(req):
        calls.append((req.method,req.url.path,dict(req.url.params)))
        assert req.headers["X-Session-API-Key"]=="unit-credential"
        path=req.url.path
        if req.method=="POST" and path=="/api/conversations":
            body=json.loads(req.content)
            records[body["conversation_id"]]={"id":body["conversation_id"],"workspace":body["workspace"],
                "execution_status":"idle","parent_conversation_id":body.get("parent_conversation_id"),"sub_conversation_ids":[]}
            return httpx.Response(201,json=records[body["conversation_id"]])
        remote=path.split("/")[3]
        if req.method=="GET" and path.endswith("/events/search"):
            return httpx.Response(200,json={"items":sorted(source,key=lambda e:e["timestamp"]),"next_page_id":None})
        if req.method=="POST" and path.endswith("/events"):
            if state["message_429"]: return httpx.Response(429,json={"detail":"message saved"})
            return httpx.Response(200,json={"success":True})
        if req.method=="POST" and path.endswith(("/pause","/interrupt")):
            records[remote]["execution_status"]="paused"
            return httpx.Response(200,json={"success":True})
        if req.method=="GET":
            if state["status_unavailable"]: return httpx.Response(503,json={"detail":"temporary"})
            return httpx.Response(200,json=records[remote])
        return httpx.Response(200,json={"success":True})
    client=httpx.AsyncClient(transport=httpx.MockTransport(route))
    transport=OpenHandsHTTPTransport(config,api_key="unit-credential",client=client)
    store=OpenHandsIdentityStore(str(tmp_path/"identities.sqlite"),workspace=str(tmp_path))
    provider=OpenHandsAgentServerProvider(center.protocol_gate(),config=config,identity_store=store,transport=transport)
    provider._test_center=center
    n=[0]
    def request(cap,args,principal="agent"):
        n[0]+=1
        return OperationRequest("oh-operation-"+str(n[0]),principal,"machine",cap,"work","oh-key-"+str(n[0]),args)
    try: yield provider,request,records,calls,state,source,durable,client
    finally:
        asyncio.run(client.aclose())
        durable.close()


def test_create_parent_child_read_reattach_and_event_dedupe(harness):
    provider,req,records,calls,state,source,durable,client=harness
    async def case():
        root,child=str(uuid.uuid4()),str(uuid.uuid4())
        parent_args=provider.create_arguments(local_id="parent",conversation_id=root)
        opened=await provider.create(req("openhands:create",parent_args),local_id="parent",conversation_id=root)
        assert opened.operation.state=="SUCCEEDED" and not opened.payload["completion_confirmed"]
        child_args=provider.create_arguments(local_id="child",conversation_id=child,parent_local_id="parent")
        result=await provider.create(req("openhands:create",child_args),local_id="child",conversation_id=child,parent_local_id="parent")
        assert result.operation.state=="SUCCEEDED" and records[child]["parent_conversation_id"]==root
        before=len(calls)
        again=await provider.reattach(req("openhands:read",{"local_id":"child"}),local_id="child")
        assert again.operation.state=="SUCCEEDED" and calls[before][0]=="GET"
        args={"local_id":"parent","page_id":None,"limit":100}
        first=await provider.events(req("openhands:events",args),local_id="parent")
        second=await provider.events(req("openhands:events",args),local_id="parent")
        assert len(first.payload["events"])==2 and second.payload["events"]==[]
        assert second.payload["duplicates"]==2 and first.payload["server_sequence_available"] is False
        assert first.payload["tool_projection"][0]["event_id"]=="event-2"
        evidence=await provider.evidence(req("openhands:evidence",{"local_id":"parent","event_id":"event-2"}),local_id="parent",event_id="event-2")
        assert evidence.payload["event"]["observation"]["text"]=="actual fixture evidence"
        assert evidence.payload["verified_sentra_effect"] is False
        rebound=OpenHandsAgentServerProvider(provider.gate,config=provider.config,
            identity_store=OpenHandsIdentityStore(str(provider.store.path),workspace=str(provider.store.path.parent)),transport=provider.transport)
        assert (await rebound.reattach(req("openhands:read",{"local_id":"parent"}),local_id="parent")).operation.state=="SUCCEEDED"
        assert len([c for c in calls if c[0]=="POST" and c[1]=="/api/conversations"])==2
        assert durable.operation_status(opened.operation.operation_id,"owner")["state"]=="SUCCEEDED"
    asyncio.run(case())


def test_scope_denial_and_429_saved_message_never_resubmit(harness):
    provider,req,records,calls,state,source,durable,client=harness
    async def case():
        remote=str(uuid.uuid4())
        args=provider.create_arguments(local_id="local",conversation_id=remote)
        assert (await provider.create(req("openhands:create",args),local_id="local",conversation_id=remote)).operation.state=="SUCCEEDED"
        count=len(calls)
        denied=await provider.read(req("openhands:read",{"local_id":"local"},principal="stranger"),local_id="local")
        assert denied.operation.state=="FAILED" and len(calls)==count
        state["message_429"]=True
        from sentra_interop.openhands_provider import _digest
        intent=req("openhands:message",{"local_id":"local","text_sha256":_digest("hello"),"run":True})
        result=await provider.send_message(intent,local_id="local",text="hello",run=True)
        assert result.operation.state=="UNCERTAIN" and result.operation.evidence["message_saved"] is True
        assert result.operation.evidence["resend_message"] is False
        await provider.send_message(intent,local_id="local",text="hello",run=True)
        assert len([c for c in calls if c[0]=="POST" and c[1].endswith("/events")])==1
    asyncio.run(case())


def test_cancel_requires_status_confirmation_and_reports_no_rollback(harness):
    provider,req,records,calls,state,source,durable,client=harness
    async def case():
        remote=str(uuid.uuid4())
        await provider.create(req("openhands:create",provider.create_arguments(local_id="local",conversation_id=remote)),local_id="local",conversation_id=remote)
        result=await provider.cancel(req("openhands:cancel",{"local_id":"local","immediate":True}),local_id="local")
        assert result.operation.state=="CANCELLED"
        assert result.operation.evidence["effects_rolled_back"] is False
        state["status_unavailable"]=True
        uncertain=await provider.cancel(req("openhands:cancel",{"local_id":"local","immediate":True}),local_id="local")
        assert uncertain.operation.state=="UNCERTAIN"
        assert uncertain.operation.evidence["diagnostic"]=="STATUS_UNAVAILABLE_AFTER_ACK"
    asyncio.run(case())


def test_sdk_tool_call_started_terminal_are_distinct_events_not_mutated_identity(harness):
    provider,req,records,calls,state,source,durable,client=harness
    from sentra_core.conversations import _encode
    source[:]=[{"id":"start","kind":"ACPToolCallEvent","source":"agent","timestamp":"2026-10-09T10:00:00",
                "tool_call_id":"same-call","title":"Read","status":"started"},
               {"id":"end","kind":"ACPToolCallEvent","source":"agent","timestamp":"2026-10-09T10:00:01",
                "tool_call_id":"same-call","title":"Read","status":"completed","raw_output":{"text":"done"}}]
    async def case():
        remote=str(uuid.uuid4())
        await provider.create(req("openhands:create",provider.create_arguments(local_id="local",conversation_id=remote)),local_id="local",conversation_id=remote)
        result=await provider.events(req("openhands:events",{"local_id":"local","page_id":None,"limit":100}),local_id="local")
        assert len(result.payload["events"])==2
        assert result.payload["tool_projection"][0]["status"]=="completed"
        with provider.store._db() as db:
            assert db.execute("SELECT COUNT(*) FROM oh_events").fetchone()[0]==2
            assert db.execute("SELECT protected_event FROM oh_events LIMIT 1").fetchone()[0].startswith(("dpapi:","keyring:"))
    asyncio.run(case())


def test_recovery_from_head_fills_earlier_timestamp_gap_without_replaying_messages(harness):
    provider,req,records,calls,state,source,durable,client=harness
    async def case():
        remote=str(uuid.uuid4())
        await provider.create(req("openhands:create",provider.create_arguments(local_id="local",conversation_id=remote)),local_id="local",conversation_id=remote)
        await provider.events(req("openhands:events",{"local_id":"local","page_id":None,"limit":100}),local_id="local")
        source.append({"id":"gap-event","kind":"MessageEvent","source":"user","timestamp":"2026-10-09T09:59:00",
                       "llm_message":{"role":"user","content":[{"type":"text","text":"gap"}]}})
        recovered=[page async for page in provider.recover_events(local_id="local",request_factory=req)]
        assert [e["event_id"] for e in recovered[0].payload["events"]]==["gap-event"]
        assert recovered[0].payload["duplicates"]==2
        assert not any(method=="POST" and path.endswith("/events") for method,path,params in calls)
    asyncio.run(case())


def test_host_already_fenced_provider_callback_does_not_reserve_twice(harness):
    provider,req,records,calls,state,source,durable,client=harness
    async def case():
        center=provider._test_center
        remote=str(uuid.uuid4())
        args=provider.create_arguments(local_id="host-bound",conversation_id=remote)
        center.bind_provider("openhands:create",provider.host_handler)
        operation=req("openhands:create",args)
        result=await center.start(operation)
        assert result.state=="SUCCEEDED"
        assert len([c for c in calls if c[0]=="POST" and c[1]=="/api/conversations"])==1
        assert provider.store.lookup("host-bound")["remote_id"]==remote
    asyncio.run(case())
