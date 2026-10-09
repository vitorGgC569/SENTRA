"""Prepared protocol acceptance; httpx fixtures are explicitly NOT AP servers.

The opt-in SDK test imports an actual installed piece/framework bundle selected
by the owner. Missing dependencies skip that test, never simulate its success.
"""
import asyncio
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from sentra_interop.activepieces import ActivepiecesCatalog, ActivepiecesPieceProvider, ActivepiecesProjectionStore, PieceDescriptor, HOOKS
from sentra_interop.activepieces_worker import InstalledPieceBundle, OwnedPieceSDKBackend
from sentra_interop.central import CentralInteropAdapter
from sentra_interop.workflow_http import ActivepiecesHTTPBackend, ActivepiecesHTTPBinding, WorkflowHTTPClient
from sentra_interop.workflow_contracts import digest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Capability, Machine, OperationRequest


CAPS=tuple(HOOKS.values())+("activepieces:observe","activepieces:cancel","activepieces:artifact","activepieces:catalog",
    "activepieces:trigger_ingest","activepieces:trigger_reconcile")


@pytest.fixture
def host(tmp_path):
    durable=DurableRunService(tmp_path/"central")
    control=ControlPlaneService(durable,ContextBusService(tmp_path/"central"))
    durable.create_run("owner",run_id="run",workspace=str(tmp_path))
    control.ensure_agent("run","owner",agent_id="agent",role="worker")
    control.create_work_item("run","owner",work_item_id="work",objective="Pieces acceptance",
        assignee_agent_id="agent",required_capabilities=list(CAPS))
    control.transition_work_item("work","owner","RUNNING")
    for cap in CAPS:
        control.authorization_grant("owner",principal_type="agent",principal_id="agent",capability=cap,scope_type="work_item",scope_id="work")
    center=CentralInteropAdapter(control=control,run_id="run",owner="owner",
        machine=Machine("machine","pieces","owner",tuple(Capability(c,c) for c in CAPS)))
    def request(cap,args,*,principal="agent"):
        key=uuid.uuid4().hex
        return OperationRequest("op-"+key,principal,"machine",cap,"work","idem-"+key,args)
    try: yield center,control,durable,request,tmp_path
    finally: durable.close()


def descriptor():
    # A static router/form fixture, never advertised as a real piece execution.
    return PieceDescriptor.from_metadata(name="@activepieces/piece-protocol-fixture",version="1.2.3",metadata={
        "contextInfo":{"version":"2"},"actions":{"echo":{"name":"echo","requireAuth":False,
            "props":{"text":{"type":"SHORT_TEXT","required":True}},"outputSchema":{"fields":[{"key":"answer","format":"string"}]}}},
        "triggers":{"changes":{"name":"changes","type":"WEBHOOK","requireAuth":False,"props":{}}}})


def native_provider(host,*,lost_response=False):
    httpx=pytest.importorskip("httpx",reason="native AP HTTP dependency not installed")
    center,_,_,request,root=host
    piece=descriptor(); props={"text":"hello"}
    step={"name":"echo-step","type":"PIECE","settings":{"pieceName":piece.name,"pieceVersion":piece.version,"actionName":"echo","input":props}}
    binding=ActivepiecesHTTPBinding(piece.name,piece.version,"echo","project","ap-flow","ap-version","echo-step",digest(step),digest(props))
    calls=[]; state={"complete":False,"cancelled":False,"drift":False}
    def router(req):
        calls.append((req.method,req.url.path,json.loads(req.content) if req.content else None))
        if req.method=="GET" and req.url.path.endswith("/flows/ap-flow"):
            return httpx.Response(200,json={"id":"ap-flow","projectId":"project","version":{"id":"ap-version","trigger":step if not state["drift"] else {**step,"description":"changed"}}})
        if req.method=="POST" and req.url.path.endswith("/sample-data/test-step"):
            assert json.loads(req.content)=={"projectId":"project","flowVersionId":"ap-version","stepName":"echo-step"}
            if lost_response: raise httpx.ReadError("fixture lost POST reply",request=req)
            return httpx.Response(200,json={"id":"ap-run","projectId":"project","flowId":"ap-flow","flowVersionId":"ap-version","status":"QUEUED","steps":None})
        if req.method=="POST" and req.url.path.endswith("/flow-runs/cancel"):
            assert json.loads(req.content)=={"projectId":"project","flowRunIds":["ap-run"]}
            state["cancelled"]=True
            return httpx.Response(204)
        if req.method=="GET" and req.url.path.endswith("/flow-runs/ap-run"):
            return httpx.Response(200,json={"id":"ap-run","projectId":"project","flowId":"ap-flow","flowVersionId":"ap-version",
                "status":"CANCELED" if state["cancelled"] else "SUCCEEDED" if state["complete"] else "RUNNING",
                "steps":{"echo-step":{"status":"SUCCEEDED","output":{"answer":"hello"}}} if state["complete"] else {}})
        if req.method=="GET" and "/pieces/" in req.url.path:
            return httpx.Response(200,json={**json.loads(piece.metadata_json),"name":piece.name,"version":piece.version})
        raise AssertionError("unexpected native AP router call "+str(req.url))
    client=httpx.AsyncClient(transport=httpx.MockTransport(router))
    backend=ActivepiecesHTTPBackend(WorkflowHTTPClient(base_url="http://127.0.0.1:9001/api",token="explicit-fixture",enabled=True,client=client),bindings=[binding])
    provider=ActivepiecesPieceProvider(center.protocol_gate(),catalog=ActivepiecesCatalog([piece]),
        store=ActivepiecesProjectionStore(root/"pieces.sqlite",workspace=root),backend=backend,input_resolver=lambda request:props)
    for cap in CAPS: center.bind_provider(cap,provider.host_handler)
    return provider,piece,props,calls,state,client


def test_native_http_ack_is_waiting_observe_returns_real_router_output_and_artifact(host):
    center,_,durable,request,_=host
    provider,piece,props,calls,state,client=native_provider(host)
    async def case():
        args=provider.intent(piece_name=piece.name,piece_version=piece.version,member="echo",invocation_id="invoke1",props=props)
        operation=request("activepieces:action",args)
        result=await center.start(operation)
        assert result.state=="SUCCEEDED" and result.evidence["payload"]["status"]=="WAITING"
        assert result.evidence["payload"]["completion_confirmed"] is False
        assert (await center.start(operation)).state=="SUCCEEDED"
        assert len([c for c in calls if c[0]=="POST"])==1
        state["complete"]=True
        observed=await center.start(request("activepieces:observe",{"invocation_id":"invoke1","workflow":None}))
        assert observed.state=="SUCCEEDED" and observed.evidence["payload"]["piece_status"]=="SUCCEEDED"
        artifact=observed.evidence["payload"]["artifacts"][-1]
        output=await center.start(request("activepieces:artifact",{"invocation_id":"invoke1","artifact_id":artifact["artifact_id"]}))
        assert output.evidence["payload"]["artifact"]=={"answer":"hello"}
        assert durable.operation_status(operation.operation_id,"owner")["state"]=="SUCCEEDED"
        assert len([c for c in calls if c[0]=="POST"])==1
        await client.aclose()
    asyncio.run(case())


def test_lost_post_reply_never_resends_even_with_fresh_operation_id(host):
    center,_,_,request,_=host
    provider,piece,props,calls,state,client=native_provider(host,lost_response=True)
    async def case():
        args=provider.intent(piece_name=piece.name,piece_version=piece.version,member="echo",invocation_id="lost",props=props)
        operation=request("activepieces:action",args)
        assert (await center.start(operation)).state=="UNCERTAIN"
        await center.start(operation)
        assert (await center.start(request("activepieces:action",args))).state=="FAILED"
        observed=await center.start(request("activepieces:observe",{"invocation_id":"lost","workflow":None}))
        assert observed.evidence["payload"]["piece_status"]=="UNCERTAIN"
        assert len([c for c in calls if c[0]=="POST"])==1
        await client.aclose()
    asyncio.run(case())


def test_pinned_stored_step_drift_denial_catalog_and_cancel_diagnostics(host):
    center,_,_,request,_=host
    provider,piece,props,calls,state,client=native_provider(host)
    async def case():
        args=provider.intent(piece_name=piece.name,piece_version=piece.version,member="echo",invocation_id="drift",props=props)
        state["drift"]=True
        result=await center.start(request("activepieces:action",args))
        assert result.state=="FAILED" and result.evidence["effect_state"]=="NOT_STARTED"
        assert not any(c[0]=="POST" for c in calls)
        state["drift"]=False
        args=provider.intent(piece_name=piece.name,piece_version=piece.version,member="echo",invocation_id="valid",props=props)
        await center.start(request("activepieces:action",args))
        cancel=await center.start(request("activepieces:cancel",{"invocation_id":"valid","workflow":None}))
        assert cancel.evidence["payload"]["piece_status"]=="CANCELLED"
        assert cancel.evidence["payload"]["effects_rolled_back"] is False
        catalog=await center.start(request("activepieces:catalog",{"piece_name":piece.name,"piece_version":piece.version,"project_id":"project"}))
        assert catalog.evidence["payload"]["catalog_mutated"] is False
        assert provider.catalog.select(piece.name,piece.version).fingerprint==piece.fingerprint
        before=len(calls)
        assert (await center.start(request("activepieces:observe",{"invocation_id":"valid","workflow":None},principal="stranger"))).state=="FAILED"
        assert len(calls)==before
        await client.aclose()
    asyncio.run(case())


def test_descriptor_schema_invalidation_and_protected_subscription_event_mapping(host):
    center,_,_,request,root=host
    piece=descriptor(); catalog=ActivepiecesCatalog([piece])
    catalog.select(piece.name,piece.version,fingerprint=piece.fingerprint)
    metadata=json.loads(piece.metadata_json); metadata["actions"]["echo"]["props"]["count"]={"type":"NUMBER","required":True}
    changed=PieceDescriptor.from_metadata(name=piece.name,version=piece.version,metadata=metadata)
    catalog.replace([changed])
    from sentra_interop.gate import EffectRejected
    with pytest.raises(EffectRejected): catalog.select(piece.name,piece.version,fingerprint=piece.fingerprint)
    assert piece.forms("echo")["output_schema_kind"]=="Activepieces field descriptors, not JSON Schema"
    with pytest.raises(ValueError): piece.validate_inputs("echo",{"text":False})
    store=ActivepiecesProjectionStore(root/"mapping.sqlite",workspace=root)
    enable=request("activepieces:trigger_enable",{})
    store.subscription(enable,"subscription",piece,"changes",None,hook="onEnable")
    with pytest.raises(EffectRejected): store.subscription(enable,"subscription",piece,"changes",None,hook="onEnable")
    event={"_dedupe_key":"vendor-event-1","body":{"secret":"protected"}}
    assert store.claim_trigger("subscription","vendor-event-1",event,"original-op") is None
    # A lost task callback cannot produce a second central WorkItem.
    with pytest.raises(EffectRejected): store.claim_trigger("subscription","vendor-event-1",event,"fresh-op")
    store.finish_trigger("subscription","vendor-event-1","fixture-work-reference")
    assert store.claim_trigger("subscription","vendor-event-1",event,"fresh-op")=="fixture-work-reference"
    with pytest.raises(EffectRejected): store.claim_trigger("subscription","vendor-event-1",{"other":True},"fresh-op")
    store.subscription(request("activepieces:trigger_disable",{}),"subscription",piece,"changes",None,hook="onDisable")
    with pytest.raises(EffectRejected): store.subscription(enable,"subscription",piece,"changes",None,hook="onRenew")
    with store.db() as db:
        assert db.execute("SELECT protected_event FROM ap_trigger_events").fetchone()[0].startswith(("dpapi:","keyring:"))


def test_real_installed_sdk_piece_opt_in(host):
    profile_path=os.environ.get("SENTRA_ACCEPTANCE_AP_SDK_PROFILE")
    if not profile_path: pytest.skip("requires owner-selected real built SDK/piece profile; no simulated fallback")
    profile=json.loads(Path(profile_path).read_text(encoding="utf8"))
    center,_,_,request,root=host
    piece=PieceDescriptor.from_metadata(name=profile["piece_name"],version=profile["piece_version"],metadata=profile["metadata"])
    bundle=InstalledPieceBundle(**profile["bundle"])
    backend=OwnedPieceSDKBackend(node_executable=profile["node_executable"],install_root=profile["install_root"],
        bundles=[bundle],artifact_root=profile["artifact_root"],project_id=profile["project_id"],flow_id=profile["flow_id"],flow_version=profile["flow_version"])
    props=profile["props"]
    provider=ActivepiecesPieceProvider(center.protocol_gate(),catalog=ActivepiecesCatalog([piece]),
        store=ActivepiecesProjectionStore(root/"sdk.sqlite",workspace=root),backend=backend,input_resolver=lambda request:props)
    for cap in CAPS: center.bind_provider(cap,provider.host_handler)
    async def case():
        args=provider.intent(piece_name=piece.name,piece_version=piece.version,member=profile["member"],invocation_id="real-sdk",props=props)
        result=await center.start(request("activepieces:action",args))
        assert result.state=="SUCCEEDED",result
        evidence=result.evidence["payload"]
        assert evidence["completion_confirmed"] is True and not backend.active
        artifact=evidence["artifacts"][-1]
        output=provider.store.read_artifact(request("activepieces:artifact",{}),"real-sdk",artifact["artifact_id"])
        assert digest(output)==profile["expected_output_sha256"]
    asyncio.run(case())
