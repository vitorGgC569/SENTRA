"""Host-driven, checkpointed subordinate workflows; no global scheduler.

Each effect is a distinct admitted central operation. advance/resume only plan
work; they never hold a control-operation physical lock while submitting a
different activity. Pending writes become usable after central acknowledgement.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from sentra_core.conversations import _decode
from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import DispatchOutcome, EffectRejected, _fingerprint
from .host_scope import HostScopedInteropGate
from .workflow_checkpoint import WorkflowCheckpointStore, namespace, WorkflowCheckpointConflict
from .workflow_contracts import ActivityReceipt, WorkflowDefinition, ident, digest


@dataclass(frozen=True)
class WorkflowActivityBinding:
    handler_id: str
    version: str
    capability_id: str
    arguments: Callable  # (resolved_inputs, workflow_reference) -> exact OperationRequest arguments
    invoke: Callable     # async (request, inputs, reference, heartbeat) -> ActivityReceipt
    observe: Callable | None = None
    observe_capability: str | None = None
    observe_arguments: Callable | None = None


class CheckpointedWorkflowWorker:
    def __init__(self,gate,*,store:WorkflowCheckpointStore,definitions,bindings,worker_version,
                 compatible_worker_versions=frozenset(),clock=time.time,scope=None,payload_resolver=None):
        if not callable(getattr(gate,"physical_context",None)):
            raise ValueError("workflow effects require the existing durable physical gate")
        self.gate=gate if isinstance(gate,HostScopedInteropGate) else HostScopedInteropGate(gate)
        self.store,self.clock=store,clock
        self.scope,self.payload_resolver=scope,payload_resolver
        self.worker_version=ident(worker_version)
        self.compatible=set(compatible_worker_versions)|{worker_version}
        definitions,bindings=tuple(definitions),tuple(bindings)
        self.definitions={(d.definition_id,d.version):d for d in definitions}
        self.bindings={(b.handler_id,b.version):b for b in bindings}
        if len(self.definitions)!=len(definitions) or len(self.bindings)!=len(bindings):
            raise ValueError("duplicate workflow definition/worker version")
        active=set()
        def check(key):
            if key in active: raise ValueError("recursive workflow subflow")
            if key not in self.definitions: raise ValueError("missing pinned subflow definition")
            active.add(key)
            for step in self.definitions[key].steps:
                if step.kind=="subflow": check((step.subflow_id,step.subflow_version))
                elif step.kind=="activity" and (step.handler_id,step.handler_version) not in self.bindings:
                    raise ValueError("missing version-pinned activity binding")
            active.remove(key)
        for key in self.definitions: check(key)

    async def _admit(self,request,effect,timeout=None):
        if self.scope is not None:
            workflow_id,principal,machine,work_item=self.scope
            args=request.arguments
            request_workflow=args.get("workflow_id") or (args.get("workflow") or {}).get("workflow_id")
            if (request_workflow,request.principal_id,request.machine_id,request.work_item_id)!=(workflow_id,principal,machine,work_item):
                raise EffectRejected("bridge workflow scope mismatch")
        return await self.gate.execute(request,effect,timeout=timeout)

    @staticmethod
    def host_result(outcome): return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation

    def _check(self,request,cap,args):
        if request.capability_id!=cap or request.arguments!=args: raise EffectRejected("workflow intent mismatch")

    def _load(self,workflow_id,ns,request):
        loaded=self.store.load(workflow_id,ns,request)
        state=loaded["state"]
        definition=self.definitions.get((state["definition_id"],state["definition_version"]))
        if definition is None or definition.fingerprint!=loaded["instance"]["definition_digest"]:
            raise EffectRejected("checkpoint definition/schema changed")
        if loaded["instance"]["worker_version"] not in self.compatible:
            raise EffectRejected("workflow worker version needs explicit compatible binding")
        parent=loaded["instance"]["parent_namespace"]
        while parent is not None:
            ancestor=self.store.load(workflow_id,parent,request)
            if ancestor["state"]["cancel_requested"]: loaded["ancestor_cancelled"]=True
            parent=ancestor["instance"]["parent_namespace"]
        return loaded,definition

    async def create(self,request,*,workflow_id,definition_id,definition_version,inputs):
        async def effect():
            definition=self.definitions[(definition_id,definition_version)]
            if definition.worker_version not in self.compatible: raise EffectRejected("definition worker version is not compatible")
            self._check(request,"workflow:create",{"workflow_id":workflow_id,"definition_id":definition_id,
                "definition_version":definition_version,"definition_sha256":definition.fingerprint,"input_sha256":digest(inputs)})
            checkpoint=self.store.open(workflow_id=workflow_id,ns="",definition=definition,request=request,inputs=inputs)
            saved=self.store.load(workflow_id,"",request)
            return {"workflow_id":workflow_id,"checkpoint_id":checkpoint,"status":saved["state"]["status"],
                    "effects_started":False,"reattach_replays_effects":False}
        return await self._admit(request,effect)

    def _resolve(self,step,state):
        mapping=json.loads(step.inputs_json)
        result={}
        for name,spec in mapping.items():
            if not isinstance(spec,dict) or "source" not in spec:
                result[name]=spec; continue
            source=spec["source"]
            if source=="input": value=state["input"]
            elif source in {"activity","signal"}:
                parent=state["steps"].get(spec.get("step_id"))
                if parent is None or parent["state"]!="SUCCEEDED": raise EffectRejected("workflow input dependency incomplete")
                value=parent.get("output")
            elif source=="literal": value=spec.get("value")
            else: raise EffectRejected("unknown workflow input binding")
            for key in spec.get("path",[]):
                if isinstance(value,list) and type(key) is int: value=value[key]
                elif isinstance(value,dict) and isinstance(key,str): value=value[key]
                else: raise EffectRejected("workflow input mapping path unavailable")
            result[name]=value
        return result

    async def _refresh(self,loaded,definition,request):
        state=loaded["state"]
        changed=False
        for spec in definition.steps:
            entry=state["steps"].get(spec.step_id)
            if entry is None or spec.kind!="activity" or entry["state"] not in {"IN_FLIGHT","PENDING_ACK","PENDING_OBSERVATION_ACK","UNCERTAIN"}: continue
            observation=entry.get("confirmation_operation_id")
            operation=await self.gate.journal.get(observation or entry["operation_id"])
            write=self.store.get_write(loaded["instance"]["workflow_id"],loaded["instance"]["namespace"],entry.get("write_key",spec.step_id),entry["attempt"],
                                       operation_id=observation or entry["operation_id"])
            if operation is None or operation.state not in {"SUCCEEDED","FAILED","CANCELLED"} or write is None:
                if entry["state"]!="UNCERTAIN": entry["state"]="UNCERTAIN"; changed=True
                continue
            meta=operation.evidence.get("payload",operation.evidence)
            if not isinstance(meta,dict) or meta.get("receipt_sha256")!=digest(write):
                entry["state"]="UNCERTAIN"; changed=True; continue
            receipt=ActivityReceipt(**{**write,"artifacts":tuple(write.get("artifacts",()))})
            if receipt.status=="SUCCEEDED" and operation.state=="SUCCEEDED":
                entry.update(state="SUCCEEDED",output=receipt.output,artifacts=list(receipt.artifacts))
            elif receipt.status=="FAILED" and operation.state in ({"SUCCEEDED","FAILED"} if observation else {"FAILED"}):
                due=spec.retry.next_at(receipt,attempt=entry["attempt"],started=entry["started"],now=self.clock())
                entry.update(state="RETRY_WAIT" if due is not None else "FAILED",retry_at=due,
                             failure_type=receipt.failure_type,effect_state=receipt.effect_state)
            elif receipt.status=="CANCELLED" and operation.state in ({"SUCCEEDED","CANCELLED"} if observation else {"CANCELLED"}): entry["state"]="CANCELLED"
            elif receipt.status=="WAITING" and operation.state=="SUCCEEDED":
                entry.update(state="WAITING_PROVIDER",provider_reference=receipt.provider_reference)
            else: entry["state"]="UNCERTAIN"
            changed=True
        if changed:
            self.store.save(loaded,state)
            return self._load(loaded["instance"]["workflow_id"],loaded["instance"]["namespace"],request)[0]
        return loaded

    async def advance(self,request,*,workflow_id,ns="",resume=False):
        async def effect():
            self._check(request,"workflow:resume" if resume else "workflow:advance",{"workflow_id":workflow_id,"namespace":ns})
            loaded,definition=self._load(workflow_id,ns,request)
            loaded=await self._refresh(loaded,definition,request)
            state=loaded["state"]
            ready=[]
            waits=[]
            changed=False
            if state["cancel_requested"] or loaded.get("ancestor_cancelled"):
                return {"workflow_id":workflow_id,"namespace":ns,"status":"CANCEL_REQUESTED","ready":[],"checkpoint_id":loaded["id"]}
            for spec in definition.steps:
                entry=state["steps"].get(spec.step_id)
                if entry and entry["state"] in {"SUCCEEDED","IN_FLIGHT","PENDING_ACK","PENDING_OBSERVATION_ACK","CANCELLED","WAITING_PROVIDER"}: continue
                if entry and spec.kind!="subflow" and entry["state"] in {"UNCERTAIN","FAILED"}: continue
                if any(state["steps"].get(key,{}).get("state")!="SUCCEEDED" for key in spec.dependencies): continue
                if spec.kind=="activity":
                    if entry and entry["state"]=="RETRY_WAIT" and self.clock()<entry["retry_at"]:
                        waits.append({"step_id":spec.step_id,"retry_at":entry["retry_at"]}); continue
                    binding=self.bindings[(spec.handler_id,spec.handler_version)]
                    attempt=entry["attempt"]+1 if entry else 1
                    reference={"workflow_id":workflow_id,"namespace":ns,"step_id":spec.step_id,"attempt":attempt,
                               "definition_sha256":definition.fingerprint}
                    inputs=self._resolve(spec,state)
                    ready.append({"step_id":spec.step_id,"attempt":attempt,"capability_id":binding.capability_id,
                                  "arguments":binding.arguments(inputs,reference),"input_sha256":digest(inputs)})
                elif spec.kind=="wait":
                    if entry is None:
                        entry={"state":"WAITING","since":self.clock(),"signal_name":spec.signal_name,
                               "deadline":self.clock()+spec.wait_seconds if spec.wait_seconds is not None else None}
                        state["steps"][spec.step_id]=entry; changed=True
                    signals=self.store.pending_signals(workflow_id,ns,spec.signal_name) if spec.signal_name else []
                    confirmed=[]
                    for signal in signals:
                        source=await self.gate.journal.get(signal["operation_id"])
                        if source and source.state=="SUCCEEDED": confirmed.append(signal)
                    if confirmed:
                        signal=confirmed[0]
                        payload=_decode(signal["protected_payload"])
                        if digest(payload)!=signal["sha256"]: raise ValueError("workflow signal payload changed")
                        entry.update(state="SUCCEEDED",output=payload,signal_id=signal["signal_id"])
                        self.store.complete_signal(loaded,state,signal["signal_id"])
                        loaded=self._load(workflow_id,ns,request)[0]; state=loaded["state"]; changed=False
                    elif entry["deadline"] is not None and self.clock()>=entry["deadline"]:
                        entry.update(state="FAILED" if spec.signal_name else "SUCCEEDED",output=None,
                                     failure_type="SIGNAL_EXPIRED" if spec.signal_name else None); changed=True
                    else: waits.append({"step_id":spec.step_id,"signal_name":spec.signal_name,"deadline":entry["deadline"]})
                else:
                    child_ns=namespace(ns+"/"+spec.step_id if ns else spec.step_id)
                    child=self.definitions[(spec.subflow_id,spec.subflow_version)]
                    self.store.open(workflow_id=workflow_id,ns=child_ns,definition=child,request=request,
                                    inputs=self._resolve(spec,state),parent_namespace=ns)
                    child_loaded,child_definition=self._load(workflow_id,child_ns,request)
                    if child_loaded["state"]["status"]=="SUCCEEDED":
                        state["steps"][spec.step_id]={"state":"SUCCEEDED","output":{
                            key:value.get("output") for key,value in child_loaded["state"]["steps"].items()},
                            "subflow_namespace":child_ns,"checkpoint_id":child_loaded["id"]}; changed=True
                    elif child_loaded["state"]["status"] in {"FAILED","UNCERTAIN","CANCELLED","CANCEL_REQUESTED"}:
                        state["steps"][spec.step_id]={"state":"UNCERTAIN" if child_loaded["state"]["status"]=="UNCERTAIN" else "FAILED",
                            "failure_type":"SUBFLOW_STOPPED","subflow_namespace":child_ns}; changed=True
                    else:
                        state["steps"][spec.step_id]={"state":"WAITING_SUBFLOW","subflow_namespace":child_ns}; changed=True
                        waits.append({"step_id":spec.step_id,"subflow_namespace":child_ns})
            phases={entry["state"] for entry in state["steps"].values()}
            status=("SUCCEEDED" if len(state["steps"])==len(definition.steps) and phases=={"SUCCEEDED"} else
                    "UNCERTAIN" if "UNCERTAIN" in phases else "FAILED" if "FAILED" in phases else "CANCELLED" if "CANCELLED" in phases else "READY" if ready else "WAITING")
            if state["status"]!=status: state["status"]=status; changed=True
            if changed: self.store.save(loaded,state); loaded=self._load(workflow_id,ns,request)[0]
            if status in {"FAILED","CANCELLED"}: ready=[]
            reconciliation=[]
            for spec in definition.steps:
                entry=state["steps"].get(spec.step_id)
                if spec.kind!="activity" or not entry or entry["state"] not in {"UNCERTAIN","WAITING_PROVIDER"}: continue
                binding=self.bindings[(spec.handler_id,spec.handler_version)]
                if binding.observe and binding.observe_arguments:
                    ref={"workflow_id":workflow_id,"namespace":ns,"step_id":spec.step_id,"attempt":entry["attempt"],"definition_sha256":definition.fingerprint}
                    reconciliation.append({"step_id":spec.step_id,"original_operation_id":entry["operation_id"],
                        "capability_id":binding.observe_capability,"arguments":binding.observe_arguments(entry,ref)})
            return {"workflow_id":workflow_id,"namespace":ns,"status":status,"checkpoint_id":loaded["id"],
                    "ready":ready,"waits":waits,"reconciliation":reconciliation,"automatic_effect_replay":False,
                    "requires_reconciliation":[key for key,value in state["steps"].items() if value["state"]=="UNCERTAIN"]}
        return await self._admit(request,effect)

    async def run_activity(self,request,*,workflow_id,ns,step_id):
        async def effect():
            loaded,definition=self._load(workflow_id,ns,request)
            state=loaded["state"]
            if state["cancel_requested"] or loaded.get("ancestor_cancelled") or state["status"] in {"FAILED","CANCELLED"}: raise EffectRejected("workflow is stopped")
            spec=next((s for s in definition.steps if s.step_id==step_id),None)
            if spec is None or spec.kind!="activity": raise EffectRejected("unknown workflow activity")
            if any(state["steps"].get(key,{}).get("state")!="SUCCEEDED" for key in spec.dependencies): raise EffectRejected("activity dependencies incomplete")
            entry=state["steps"].get(step_id)
            if entry and (entry["state"]!="RETRY_WAIT" or self.clock()<entry["retry_at"]):
                raise EffectRejected("activity already dispatched; reconcile original operation")
            binding=self.bindings[(spec.handler_id,spec.handler_version)]
            attempt=entry["attempt"]+1 if entry else 1
            reference={"workflow_id":workflow_id,"namespace":ns,"step_id":step_id,"attempt":attempt,"definition_sha256":definition.fingerprint}
            inputs=self._resolve(spec,state)
            self._check(request,binding.capability_id,binding.arguments(inputs,reference))
            started=entry["started"] if entry else self.clock()
            if self.clock()>started+spec.retry.expiration_seconds: raise EffectRejected("activity expired before dispatch")
            state["steps"][step_id]={"state":"IN_FLIGHT","operation_id":request.operation_id,"attempt":attempt,
                                     "started":started,"input_sha256":digest(inputs)}
            self.store.save(loaded,state)
            last_progress=[asyncio.get_running_loop().time()]
            def heartbeat():
                from sentra_runtime.effect_boundary import current_effect_context
                context=current_effect_context.get()
                if context: context.checkpoint()
                last_progress[0]=asyncio.get_running_loop().time()
            async def invoke():
                value=binding.invoke(request,inputs,reference,heartbeat)
                return await value if inspect.isawaitable(value) else value
            task=asyncio.create_task(invoke())
            try:
                deadline=asyncio.get_running_loop().time()+spec.total_timeout
                while not task.done():
                    remaining=min(deadline-asyncio.get_running_loop().time(),
                                  spec.idle_timeout-(asyncio.get_running_loop().time()-last_progress[0]))
                    if remaining<=0: raise TimeoutError("activity no-progress/total timeout; never replay")
                    await asyncio.wait({task},timeout=min(remaining,.25))
                receipt=await task
                if not isinstance(receipt,ActivityReceipt): raise ValueError("worker omitted typed activity receipt")
                write=asdict(receipt)
                self.store.put_write(workflow_id,ns,step_id,attempt,request.operation_id,write)
                latest=self._load(workflow_id,ns,request)[0]
                latest["state"]["steps"][step_id]["state"]="PENDING_ACK"
                self.store.save(latest,latest["state"])
                meta={"workflow_id":workflow_id,"namespace":ns,"step_id":step_id,"attempt":attempt,
                    "receipt_sha256":digest(write),"status":receipt.status,"effect_state":receipt.effect_state,
                    "provider_reference":receipt.provider_reference,"artifacts":list(receipt.artifacts)}
                if receipt.status in {"FAILED","UNCERTAIN","CANCELLED"}:
                    return OperationResult(request.operation_id,receipt.status,meta,error=receipt.failure_type)
                return meta
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
        return await self._admit(request,effect)

    async def signal(self,request,*,workflow_id,ns,name,signal_id,payload):
        async def effect():
            self._check(request,"workflow:signal",{"workflow_id":workflow_id,"namespace":ns,"name":name,
                        "signal_id":signal_id,"payload_sha256":digest(payload)})
            loaded,definition=self._load(workflow_id,ns,request)
            if loaded["state"]["cancel_requested"] or loaded.get("ancestor_cancelled") or name not in {s.signal_name for s in definition.steps if s.kind=="wait"}:
                raise EffectRejected("signal is not declared or workflow cancelled")
            phase,duplicate=self.store.admit_signal(workflow_id,ns,signal_id,name,payload,request.operation_id)
            return {"signal_id":signal_id,"phase":phase,"duplicate":duplicate,"activity_completed":False}
        return await self._admit(request,effect)

    async def cancel(self,request,*,workflow_id,ns=""):
        async def effect():
            self._check(request,"workflow:cancel",{"workflow_id":workflow_id,"namespace":ns})
            loaded,definition=self._load(workflow_id,ns,request)
            state=loaded["state"]
            state["cancel_requested"]=True; state["status"]="CANCEL_REQUESTED"
            active=[v["operation_id"] for v in state["steps"].values() if v.get("operation_id") and
                    v["state"] in {"IN_FLIGHT","PENDING_ACK","PENDING_OBSERVATION_ACK","UNCERTAIN","WAITING_PROVIDER"}]
            self.store.save(loaded,state)
            with self.store.db() as db:
                descendants=[r[0] for r in db.execute("SELECT namespace FROM wf_instances WHERE workflow_id=?",(workflow_id,))
                    if r[0]!=ns and (not ns or r[0].startswith(ns+"/"))]
            for descendant in descendants:
                child=self.store.load(workflow_id,descendant,request)
                active.extend(v["operation_id"] for v in child["state"]["steps"].values() if v.get("operation_id") and
                    v["state"] in {"IN_FLIGHT","PENDING_ACK","PENDING_OBSERVATION_ACK","UNCERTAIN","WAITING_PROVIDER"})
            return {"workflow_id":workflow_id,"namespace":ns,"cancel_requested":True,
                    "active_operations":sorted(set(active)),"effects_rolled_back":False,"provider_cancel_required":bool(active)}
        return await self._admit(request,effect)

    async def observe(self,request,*,workflow_id,ns="",checkpoint_id=None):
        async def effect():
            self._check(request,"workflow:observe",{"workflow_id":workflow_id,"namespace":ns,"checkpoint_id":checkpoint_id})
            loaded=self.store.load(workflow_id,ns,request,checkpoint_id=checkpoint_id)
            with self.store.db() as db:
                signals=[dict(r) for r in db.execute("SELECT signal_id,name,state,operation_id FROM wf_signals WHERE workflow_id=? AND namespace=?",
                                                   (workflow_id,ns))]
            return {k:loaded[k] for k in ("id","parent_id","revision","sha256")}|{
                "status":loaded["state"]["status"],"steps":{key:{k:v for k,v in row.items() if k!="output"}
                    for key,row in loaded["state"]["steps"].items()},"signals":signals,"state_replay_executes_effects":False}
        return await self._admit(request,effect)

    async def output(self,request,*,workflow_id,ns,step_id):
        async def effect():
            self._check(request,"workflow:output",{"workflow_id":workflow_id,"namespace":ns,"step_id":step_id})
            loaded,definition=self._load(workflow_id,ns,request)
            entry=loaded["state"]["steps"].get(step_id)
            if not entry or entry["state"]!="SUCCEEDED": raise EffectRejected("workflow output not centrally confirmed")
            return {"output":entry.get("output"),"artifacts":entry.get("artifacts",[])}
        return await self._admit(request,effect)

    async def memory(self,request,*,workflow_id,ns,action,key=None,value=None,query="",limit=20,ttl_seconds=None):
        async def effect():
            self._check(request,"workflow:memory",{"workflow_id":workflow_id,"namespace":ns,"action":action,"key":key,
                "value_sha256":digest(value) if action=="put" else None,"query":query,"limit":limit,"ttl_seconds":ttl_seconds})
            self._load(workflow_id,ns,request)
            if action=="put":
                self.store.memory_put(workflow_id,ns,key,value,ttl_seconds=ttl_seconds); return {"stored":True,"sha256":digest(value)}
            if action not in {"get","search"}: raise EffectRejected("unknown workflow memory operation")
            return {"items":self.store.memory_search(workflow_id,ns,query=query,limit=limit,key=key if action=="get" else None)}
        return await self._admit(request,effect)

    async def host_activity_handler(self,request):
        ref=request.arguments.get("workflow")
        if not isinstance(ref,dict): raise EffectRejected("activity must carry exact workflow reference")
        loaded,definition=self._load(ref.get("workflow_id"),ref.get("namespace"),request)
        spec=next((s for s in definition.steps if s.step_id==ref.get("step_id")),None)
        if spec is None or spec.kind!="activity": raise EffectRejected("activity reference not declared")
        binding=self.bindings[(spec.handler_id,spec.handler_version)]
        outcome=(await self.observe_activity(request,workflow_id=ref["workflow_id"],ns=ref["namespace"],step_id=ref["step_id"])
            if request.capability_id==binding.observe_capability else await self.run_activity(request,
                workflow_id=ref["workflow_id"],ns=ref["namespace"],step_id=ref["step_id"]))
        return self.host_result(outcome)

    async def _payload(self,request,key,default):
        expected=request.arguments.get(key)
        if expected==digest(default): return default
        if not callable(self.payload_resolver): raise EffectRejected("host protected workflow payload resolver unavailable")
        value=self.payload_resolver(request,key)
        if inspect.isawaitable(value): value=await value
        if digest(value)!=expected: raise EffectRejected("workflow payload resolver digest mismatch")
        return value

    async def host_handler(self,request):
        args=request.arguments; cap=request.capability_id
        workflow_id,ns=args.get("workflow_id"),args.get("namespace","")
        if cap=="workflow:create":
            outcome=await self.create(request,workflow_id=workflow_id,definition_id=args.get("definition_id"),
                definition_version=args.get("definition_version"),inputs=await self._payload(request,"input_sha256",{}))
        elif cap in {"workflow:advance","workflow:resume"}:
            outcome=await self.advance(request,workflow_id=workflow_id,ns=ns,resume=cap=="workflow:resume")
        elif cap=="workflow:signal":
            outcome=await self.signal(request,workflow_id=workflow_id,ns=ns,name=args.get("name"),signal_id=args.get("signal_id"),
                                      payload=await self._payload(request,"payload_sha256",None))
        elif cap=="workflow:cancel": outcome=await self.cancel(request,workflow_id=workflow_id,ns=ns)
        elif cap=="workflow:observe": outcome=await self.observe(request,workflow_id=workflow_id,ns=ns,checkpoint_id=args.get("checkpoint_id"))
        elif cap=="workflow:output": outcome=await self.output(request,workflow_id=workflow_id,ns=ns,step_id=args.get("step_id"))
        elif cap=="workflow:memory":
            value=await self._payload(request,"value_sha256",None) if args.get("action")=="put" else None
            outcome=await self.memory(request,workflow_id=workflow_id,ns=ns,action=args.get("action"),key=args.get("key"),
                value=value,query=args.get("query",""),limit=args.get("limit",20),ttl_seconds=args.get("ttl_seconds"))
        else: return await self.host_activity_handler(request)
        return self.host_result(outcome)

    async def observe_activity(self,request,*,workflow_id,ns,step_id):
        async def effect():
            loaded,definition=self._load(workflow_id,ns,request)
            spec=next((s for s in definition.steps if s.step_id==step_id),None)
            entry=loaded["state"]["steps"].get(step_id)
            if spec is None or entry is None or entry["state"] not in {"WAITING_PROVIDER","UNCERTAIN"}:
                raise EffectRejected("activity needs a prior provider reference to reconcile")
            binding=self.bindings[(spec.handler_id,spec.handler_version)]
            if not binding.observe or not binding.observe_arguments: raise EffectRejected("worker has no real provider observer")
            ref={"workflow_id":workflow_id,"namespace":ns,"step_id":step_id,"attempt":entry["attempt"],"definition_sha256":definition.fingerprint}
            self._check(request,binding.observe_capability,binding.observe_arguments(entry,ref))
            def checkpoint():
                from sentra_runtime.effect_boundary import current_effect_context
                context=current_effect_context.get()
                if context: context.checkpoint()
            receipt=await binding.observe(request,entry,ref,checkpoint)
            if not isinstance(receipt,ActivityReceipt): raise ValueError("provider observer omitted typed receipt")
            write=asdict(receipt)
            write_key="observe:"+step_id+":"+request.operation_id
            self.store.put_write(workflow_id,ns,write_key,entry["attempt"],request.operation_id,write)
            entry.update(state="PENDING_OBSERVATION_ACK",confirmation_operation_id=request.operation_id,write_key=write_key)
            self.store.save(loaded,loaded["state"])
            return {"workflow_id":workflow_id,"namespace":ns,"step_id":step_id,"receipt_sha256":digest(write),
                "reported_status":receipt.status,"original_operation_id":entry["operation_id"],"replayed_effect":False,
                "artifacts":list(receipt.artifacts)}
        return await self._admit(request,effect)
