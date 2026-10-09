"""Prepared acceptance using real central authority and real local file effects.

These tests do not certify Temporal/LangGraph services or an external connector.
No test substitutes an operations journal or fabricates provider completion.
"""
import asyncio
import json
import uuid
from dataclasses import replace

import pytest

from sentra_interop.central import CentralInteropAdapter
from sentra_interop.workflow_bridge import SubagentWorkflowBridge
from sentra_interop.workflow_checkpoint import WorkflowCheckpointStore, WorkflowCheckpointConflict
from sentra_interop.workflow_contracts import ActivityReceipt, ActivitySpec, RetryPolicy, WorkflowDefinition, digest
from sentra_interop.workflow_worker import CheckpointedWorkflowWorker, WorkflowActivityBinding
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Capability, Machine, OperationRequest
from sentra_runtime.effect_boundary import current_effect_context


CAPS=tuple("workflow:"+s for s in ("create","advance","resume","signal","cancel","observe","output","memory"))+("piece:file","piece:file_observe")


@pytest.fixture
def host(tmp_path):
    durable=DurableRunService(tmp_path/"central")
    control=ControlPlaneService(durable,ContextBusService(tmp_path/"central"))
    durable.create_run("owner",run_id="run",workspace=str(tmp_path))
    control.ensure_agent("run","owner",agent_id="agent",role="worker")
    control.create_work_item("run","owner",work_item_id="work",objective="Workflow acceptance",
        assignee_agent_id="agent",required_capabilities=list(CAPS))
    control.transition_work_item("work","owner","RUNNING")
    for cap in CAPS:
        control.authorization_grant("owner",principal_type="agent",principal_id="agent",capability=cap,
                                    scope_type="work_item",scope_id="work")
    center=CentralInteropAdapter(control=control,run_id="run",owner="owner",
        machine=Machine("machine","workflow","owner",tuple(Capability(c,c) for c in CAPS)))
    def request(cap,args,*,principal="agent"):
        key=uuid.uuid4().hex
        return OperationRequest("op-"+key,principal,"machine",cap,"work","idem-"+key,args)
    try: yield center,control,durable,request,tmp_path
    finally: durable.close()


def attach(host,definitions,bindings,*,payload_resolver=None):
    center,_,_,_,root=host
    bridge=SubagentWorkflowBridge(center.protocol_gate(),database=str(root/"workflow.sqlite"),workspace_root=str(root),
        workflow_id="flow",work_item_id="work",principal_id="agent")
    worker=bridge.bind_worker(definitions=definitions,bindings=bindings,worker_version="worker1",payload_resolver=payload_resolver)
    for cap in CAPS: center.bind_provider(cap,worker.host_handler)
    return worker,bridge


def receipt_payload(result):
    assert result.state=="SUCCEEDED", result
    return result.evidence["payload"]


def create_request(request,definition,inputs=None):
    inputs={} if inputs is None else inputs
    return request("workflow:create",{"workflow_id":"flow","definition_id":definition.definition_id,
        "definition_version":definition.version,"definition_sha256":definition.fingerprint,"input_sha256":digest(inputs)})


def file_binding(root,*,mode="complete"):
    calls=[]
    target=root/"actual-output.jsonl"
    def args(inputs,ref): return {"workflow":ref,"inputs_sha256":digest(inputs),"path":str(target)}
    async def invoke(request,inputs,ref,heartbeat):
        context=current_effect_context.get()
        assert context is not None and context.request.operation_id==request.operation_id
        context.checkpoint(); heartbeat()
        calls.append(request.operation_id)
        if mode=="transient" and len(calls)==1:
            assert not target.exists()
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="RESOURCE_BUSY_BEFORE_START",retryable=True)
        with target.open("a",encoding="utf8") as stream:
            stream.write(json.dumps({"step":ref["step_id"],"inputs":inputs})+"\n")
        if mode=="lost": raise ConnectionError("actual write happened; response unavailable")
        return ActivityReceipt("SUCCEEDED","COMPLETED",{"rows":len(target.read_text().splitlines())})
    async def observe(request,entry,ref,heartbeat):
        current_effect_context.get().checkpoint(); heartbeat()
        rows=[json.loads(line) for line in target.read_text().splitlines()] if target.exists() else []
        if any(row["step"]==ref["step_id"] for row in rows):
            return ActivityReceipt("SUCCEEDED","COMPLETED",{"rows":len(rows)})
        return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type="NO_EXTERNAL_COMPLETION_PROOF")
    binding=WorkflowActivityBinding("file","v1","piece:file",args,invoke,observe,"piece:file_observe",
        lambda entry,ref:{"workflow":ref,"path":str(target),"original_operation_id":entry["operation_id"]})
    return binding,calls,target


def test_bind_provider_borrows_exact_outer_intent_and_restart_never_replays(host):
    center,_,durable,request,root=host
    binding,calls,target=file_binding(root)
    definition=WorkflowDefinition("example","v1","worker1",(ActivitySpec("write",handler_id="file",handler_version="v1"),))
    worker,bridge=attach(host,[definition],[binding])
    async def case():
        receipt_payload(await center.start(create_request(request,definition)))
        plan=receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        item=plan["ready"][0]; operation=request(item["capability_id"],item["arguments"])
        assert (await center.start(operation)).state=="SUCCEEDED"
        assert worker.store.load("flow","",operation)["state"]["steps"]["write"]["state"]=="PENDING_ACK"
        assert durable.operation_status(operation.operation_id,"owner")["state"]=="SUCCEEDED"
        assert (await center.start(operation)).state=="SUCCEEDED"
        assert calls==[operation.operation_id] and len(target.read_text().splitlines())==1
        restarted=CheckpointedWorkflowWorker(center.protocol_gate(),store=WorkflowCheckpointStore(root/"workflow.sqlite",workspace=root),
            definitions=[definition],bindings=[binding],worker_version="worker1")
        outcome=await restarted.advance(request("workflow:resume",{"workflow_id":"flow","namespace":""}),workflow_id="flow",resume=True)
        assert outcome.payload["status"]=="SUCCEEDED" and outcome.payload["ready"]==[]
        assert len(calls)==1
        with worker.store.db() as db:
            assert db.execute("SELECT protected_write FROM wf_pending_writes").fetchone()[0].startswith(("dpapi:","keyring:"))
        from sentra_interop.workflow_bridge import WorkflowReplayDenied
        with pytest.raises(WorkflowReplayDenied): await bridge.run_step(operation,step_id="unsafe",effect=lambda:None)
    asyncio.run(case())


def test_lost_reply_requires_observation_and_can_resume_independent_step(host):
    center,_,_,request,root=host
    binding,calls,target=file_binding(root,mode="lost")
    definition=WorkflowDefinition("example","v1","worker1",(
        ActivitySpec("write",handler_id="file",handler_version="v1"),
        ActivitySpec("independent",kind="wait",wait_seconds=0),
        ActivitySpec("after",kind="wait",dependencies=("write",),wait_seconds=0)))
    worker,_=attach(host,[definition],[binding])
    async def case():
        receipt_payload(await center.start(create_request(request,definition)))
        plan=receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        operation=request("piece:file",plan["ready"][0]["arguments"])
        assert (await center.start(operation)).state=="UNCERTAIN"
        resumed=receipt_payload(await center.start(request("workflow:resume",{"workflow_id":"flow","namespace":""})))
        assert resumed["status"]=="UNCERTAIN" and resumed["ready"]==[]
        assert worker.store.load("flow","",operation)["state"]["steps"]["independent"]["state"]=="SUCCEEDED"
        # A fresh effect ID cannot sidestep the persisted claim.
        assert (await center.start(request("piece:file",operation.arguments))).state=="FAILED"
        observer=resumed["reconciliation"][0]
        receipt_payload(await center.start(request(observer["capability_id"],observer["arguments"])))
        final=receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        assert final["status"]=="SUCCEEDED" and len(calls)==1 and target.exists()
    asyncio.run(case())


def test_signal_admitted_completed_subflow_and_ancestor_cancel(host):
    center,_,_,request,root=host
    child=WorkflowDefinition("child","v1","worker1",(ActivitySpec("approval",kind="wait",signal_name="approve"),))
    parent=WorkflowDefinition("parent","v1","worker1",(ActivitySpec("childstep",kind="subflow",subflow_id="child",subflow_version="v1"),))
    worker,_=attach(host,[parent,child],[])
    async def case():
        receipt_payload(await center.start(create_request(request,parent)))
        receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":"childstep"})))
        args={"workflow_id":"flow","namespace":"childstep","name":"approve","signal_id":"signal1","payload_sha256":digest({"approved":True})}
        admitted=await worker.signal(request("workflow:signal",args),workflow_id="flow",ns="childstep",name="approve",signal_id="signal1",payload={"approved":True})
        assert admitted.payload["phase"]=="ADMITTED" and not admitted.payload["activity_completed"]
        assert receipt_payload(await center.start(request("workflow:resume",{"workflow_id":"flow","namespace":"childstep"})))["status"]=="SUCCEEDED"
        assert receipt_payload(await center.start(request("workflow:resume",{"workflow_id":"flow","namespace":""})))["status"]=="SUCCEEDED"
        observed=receipt_payload(await center.start(request("workflow:observe",{"workflow_id":"flow","namespace":"childstep","checkpoint_id":None})))
        assert observed["signals"][0]["state"]=="COMPLETED"
        receipt_payload(await center.start(request("workflow:cancel",{"workflow_id":"flow","namespace":""})))
        assert receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":"childstep"})))["status"]=="CANCEL_REQUESTED"
    asyncio.run(case())


def test_retry_classification_bounds_and_frozen_checkpoint_identity(host):
    policy=RetryPolicy(max_attempts=3,initial_seconds=1,maximum_seconds=3,expiration_seconds=6)
    transient=ActivityReceipt("FAILED","NOT_STARTED",failure_type="DEPENDENCY_UNAVAILABLE",retryable=True)
    assert policy.next_at(transient,attempt=1,started=0,now=0)==1
    assert policy.next_at(transient,attempt=3,started=0,now=0) is None
    assert policy.next_at(transient,attempt=2,started=0,now=5) is None
    assert policy.next_at(ActivityReceipt("FAILED","UNKNOWN"),attempt=1,started=0,now=0) is None
    with pytest.raises(ValueError): ActivityReceipt("UNCERTAIN","UNKNOWN",retryable=True)
    center,_,_,request,root=host
    binding,_,_=file_binding(root)
    definition=WorkflowDefinition("example","v1","worker1",(ActivitySpec("write",handler_id="file",handler_version="v1"),))
    store=WorkflowCheckpointStore(root/"projection.sqlite",workspace=root)
    req=create_request(request,definition)
    store.open(workflow_id="flow",ns="",definition=definition,request=req,inputs={"secret":"original"})
    first=store.load("flow","",req)
    with pytest.raises(WorkflowCheckpointConflict):
        store.open(workflow_id="flow",ns="",definition=definition,request=req,inputs={"secret":"changed"})
    with pytest.raises(PermissionError): store.load("flow","",replace(req,principal_id="other"))
    state=dict(first["state"]); state["status"]="WAITING"
    store.save(first,state)
    with pytest.raises(WorkflowCheckpointConflict): store.save(first,state)
    assert store.load("flow","",req,checkpoint_id=first["id"])["revision"]==0
    incompatible=CheckpointedWorkflowWorker(center.protocol_gate(),store=store,definitions=[definition],bindings=[binding],worker_version="worker2")
    from sentra_interop.gate import EffectRejected
    with pytest.raises(EffectRejected): incompatible._load("flow","",req)
    store.memory_put("flow","child","memo",{"origin":"step","value":"remember"},ttl_seconds=60)
    assert store.memory_search("flow","child",query="remember")
    assert not store.memory_search("flow","sibling",query="remember")
    with store.db() as db: db.execute("UPDATE wf_memory SET expires=0")
    assert not store.memory_search("flow","child")


def test_idle_timeout_keeps_original_effect_identity(host):
    center,_,_,request,root=host
    calls=[]
    async def blocked(req,inputs,ref,heartbeat):
        calls.append(req.operation_id)
        await asyncio.Event().wait()
    binding=WorkflowActivityBinding("stalled","v1","piece:file",lambda inputs,ref:{"workflow":ref},blocked)
    definition=WorkflowDefinition("stall","v1","worker1",(ActivitySpec("stall",handler_id="stalled",handler_version="v1",idle_timeout=.03,total_timeout=1),))
    worker,_=attach(host,[definition],[binding])
    async def case():
        receipt_payload(await center.start(create_request(request,definition)))
        plan=receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        args=plan["ready"][0]["arguments"]
        assert (await center.start(request("piece:file",args))).state=="UNCERTAIN"
        assert receipt_payload(await center.start(request("workflow:resume",{"workflow_id":"flow","namespace":""})))["ready"]==[]
        assert (await center.start(request("piece:file",args))).state=="FAILED"
        assert len(calls)==1
    asyncio.run(case())


def test_only_confirmed_never_started_failure_gets_new_attempt(host):
    center,_,_,request,root=host
    binding,calls,target=file_binding(root,mode="transient")
    definition=WorkflowDefinition("retry","v1","worker1",(ActivitySpec("write",handler_id="file",handler_version="v1",
        retry=RetryPolicy(max_attempts=2,initial_seconds=1,maximum_seconds=1,expiration_seconds=60)),))
    worker,_=attach(host,[definition],[binding])
    clock=[10.0]; worker.clock=lambda:clock[0]
    async def case():
        receipt_payload(await center.start(create_request(request,definition)))
        plan=receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        first=request("piece:file",plan["ready"][0]["arguments"])
        assert (await center.start(first)).state=="FAILED" and not target.exists()
        waiting=receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))
        assert waiting["ready"]==[] and waiting["waits"][0]["retry_at"]==11
        clock[0]=11
        retry=receipt_payload(await center.start(request("workflow:resume",{"workflow_id":"flow","namespace":""})))["ready"][0]
        assert retry["attempt"]==2
        second=request(retry["capability_id"],retry["arguments"])
        assert second.operation_id!=first.operation_id
        assert (await center.start(second)).state=="SUCCEEDED"
        assert receipt_payload(await center.start(request("workflow:advance",{"workflow_id":"flow","namespace":""})))["status"]=="SUCCEEDED"
        assert calls==[first.operation_id,second.operation_id] and len(target.read_text().splitlines())==1
    asyncio.run(case())
