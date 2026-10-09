"""Real piece descriptors, protected artifacts and host-bound Activepieces effects.

Descriptors cannot install/import packages. Actual execution is delegated to
an explicit owned SDK worker or pinned Activepieces HTTP configuration.
"""
from __future__ import annotations

import inspect
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sentra_core.conversations import _encode, _decode
from sentra_runtime.contracts import OperationResult
from .gate import DispatchOutcome, EffectRejected, _fingerprint
from .host_scope import HostScopedInteropGate
from .workflow_contracts import ActivityReceipt, canonical, digest, ident

PIECE_NAME=re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*$")
VERSION=re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HOOKS={"action":"activepieces:action","onEnable":"activepieces:trigger_enable","onDisable":"activepieces:trigger_disable",
       "onRenew":"activepieces:trigger_renew","trigger-run":"activepieces:trigger_run"}


@dataclass(frozen=True)
class PieceDescriptor:
    name: str
    version: str
    metadata_json: str

    @classmethod
    def from_metadata(cls,*,name,version,metadata):
        if not isinstance(name,str) or not PIECE_NAME.fullmatch(name) or not isinstance(version,str) or not VERSION.fullmatch(version):
            raise ValueError("piece package/version must be exact pins")
        if not isinstance(metadata,dict) or not isinstance(metadata.get("actions"),dict) or not isinstance(metadata.get("triggers"),dict):
            raise ValueError("actual piece SDK metadata required")
        return cls(name,version,canonical(metadata))

    @property
    def fingerprint(self): return digest({"name":self.name,"version":self.version,"metadata":json.loads(self.metadata_json)})

    def member(self,name,hook="action"):
        metadata=json.loads(self.metadata_json)
        if hook not in HOOKS: raise ValueError("unknown piece hook")
        member=metadata["actions" if hook=="action" else "triggers"].get(name)
        if not isinstance(member,dict) or member.get("name")!=name: raise ValueError("piece member not in pinned catalog")
        return member

    def forms(self,member_name,hook="action"):
        member=self.member(member_name,hook)
        props=member.get("props",{})
        if not isinstance(props,dict): raise ValueError("invalid piece properties")
        return {"props":props,"outputSchema":member.get("outputSchema"),"schema_sha256":digest(props),
                "output_schema_kind":"Activepieces field descriptors, not JSON Schema",
                "contextInfo":json.loads(self.metadata_json).get("contextInfo")}

    def validate_inputs(self,member_name,values,hook="action"):
        if not isinstance(values,dict): raise ValueError("piece properties must be JSON object")
        props=self.forms(member_name,hook)["props"]
        if set(values)-set(props): raise ValueError("unknown piece property")
        for key,prop in props.items():
            if not isinstance(prop,dict): raise ValueError("invalid property descriptor")
            if prop.get("required") is True and key not in values and "defaultValue" not in prop:
                raise ValueError("required piece property missing")
            if key not in values: continue
            kind,value=prop.get("type"),values[key]
            if kind in {"OAUTH2","OIDC","BASIC_AUTH","SECRET_TEXT","CUSTOM_AUTH"}:
                raise ValueError("credentials belong to an explicit host connection, never ordinary input props")
            if kind in {"SHORT_TEXT","LONG_TEXT","RICH_TEXT","COLOR","DATE_TIME"} and not isinstance(value,str): raise ValueError("piece text type mismatch")
            if kind=="NUMBER" and type(value) not in (int,float): raise ValueError("piece number type mismatch")
            if kind=="CHECKBOX" and type(value) is not bool: raise ValueError("piece checkbox type mismatch")
            if kind in {"OBJECT","DYNAMIC"} and not isinstance(value,dict): raise ValueError("piece object type mismatch")
            if kind in {"ARRAY","STATIC_MULTI_SELECT_DROPDOWN","MULTI_SELECT_DROPDOWN"} and not isinstance(value,list): raise ValueError("piece array type mismatch")
            if kind in {"STATIC_DROPDOWN","STATIC_MULTI_SELECT_DROPDOWN"}:
                options=prop.get("options",{}).get("options",[])
                choices=[o.get("value") for o in options if isinstance(o,dict)]
                if any(v not in choices for v in (value if isinstance(value,list) else [value])): raise ValueError("piece choice not advertised")
        canonical(values)


class ActivepiecesCatalog:
    def __init__(self,descriptors=()): self.replace(descriptors)
    def replace(self,descriptors):
        descriptors=tuple(descriptors)
        selected={(d.name,d.version):d for d in descriptors}
        if len(selected)!=len(descriptors): raise ValueError("duplicate piece version")
        self._pieces=selected
    def select(self,name,version,*,fingerprint=None):
        piece=self._pieces.get((name,version))
        if piece is None or (fingerprint is not None and piece.fingerprint!=fingerprint): raise EffectRejected("piece version/schema changed")
        return piece


class ActivepiecesProjectionStore:
    """Piece/run/connection mappings and protected outputs, not operations authority."""
    def __init__(self,database,*,workspace):
        root,self.path=Path(workspace).resolve(),Path(database).resolve()
        if self.path==root or not self.path.is_relative_to(root): raise ValueError("piece store outside workspace")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ap_invocations(
                invocation_id TEXT PRIMARY KEY,principal TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,
                operation_id TEXT NOT NULL,intent_digest TEXT NOT NULL,piece TEXT NOT NULL,version TEXT NOT NULL,
                member TEXT NOT NULL,hook TEXT NOT NULL,connection_id TEXT,provider_reference TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ap_artifacts(
                id TEXT PRIMARY KEY,invocation_id TEXT NOT NULL,sha256 TEXT NOT NULL,protected_content TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ap_storage(
                scope TEXT NOT NULL,key TEXT NOT NULL,protected_value TEXT NOT NULL,PRIMARY KEY(scope,key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS ap_trigger_events(
                subscription_id TEXT NOT NULL,event_key TEXT NOT NULL,sha256 TEXT NOT NULL,protected_event TEXT NOT NULL,
                operation_id TEXT NOT NULL,PRIMARY KEY(subscription_id,event_key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS ap_subscriptions(
                id TEXT PRIMARY KEY,principal TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,
                descriptor_digest TEXT NOT NULL,member TEXT NOT NULL,connection_id TEXT,enable_operation TEXT)""")
            if "work_item_reference" not in {r[1] for r in db.execute("PRAGMA table_info(ap_trigger_events)")}:
                db.execute("ALTER TABLE ap_trigger_events ADD COLUMN work_item_reference TEXT")
            if "disable_operation" not in {r[1] for r in db.execute("PRAGMA table_info(ap_subscriptions)")}:
                db.execute("ALTER TABLE ap_subscriptions ADD COLUMN disable_operation TEXT")
            if "subscription_id" not in {r[1] for r in db.execute("PRAGMA table_info(ap_invocations)")}:
                db.execute("ALTER TABLE ap_invocations ADD COLUMN subscription_id TEXT")

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def begin(self,request,invocation_id,descriptor,member,hook,connection_id):
        if not isinstance(invocation_id,str) or not 1<=len(invocation_id)<=512: raise ValueError("invalid piece invocation ID")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM ap_invocations WHERE invocation_id=?",(invocation_id,)).fetchone():
                raise EffectRejected("piece invocation already bound; observe original operation, never resend")
            db.execute("INSERT INTO ap_invocations(invocation_id,principal,machine,work_item,operation_id,intent_digest,piece,version,member,hook,connection_id,provider_reference,subscription_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(invocation_id,request.principal_id,
                request.machine_id,request.work_item_id,request.operation_id,_fingerprint(request),descriptor.name,
                descriptor.version,member,hook,connection_id,None,request.arguments.get("subscription_id")))

    def binding(self,request,invocation_id):
        with self.db() as db: row=db.execute("SELECT * FROM ap_invocations WHERE invocation_id=?",(invocation_id,)).fetchone()
        if row is None: raise EffectRejected("piece invocation mapping missing")
        if (row["principal"],row["machine"],row["work_item"])!=(request.principal_id,request.machine_id,request.work_item_id):
            raise EffectRejected("piece invocation scope mismatch")
        return dict(row)

    def reference(self,invocation_id,value):
        with self.db() as db: db.execute("UPDATE ap_invocations SET provider_reference=? WHERE invocation_id=?",(value,invocation_id))

    def artifact(self,invocation_id,value,*,kind="json-output"):
        encrypted,hash_value=_encode(value),digest(value)
        key="ap-artifact-"+digest({"invocation":invocation_id,"value":hash_value,"kind":kind})
        with self.db() as db: db.execute("INSERT OR IGNORE INTO ap_artifacts VALUES(?,?,?,?)",(key,invocation_id,hash_value,encrypted))
        return {"artifact_id":key,"sha256":hash_value,"kind":kind,"protected":True}

    def read_artifact(self,request,invocation_id,artifact_id):
        self.binding(request,invocation_id)
        with self.db() as db: row=db.execute("SELECT * FROM ap_artifacts WHERE id=? AND invocation_id=?",(artifact_id,invocation_id)).fetchone()
        if row is None: raise FileNotFoundError("piece artifact not found")
        value=_decode(row["protected_content"])
        if digest(value)!=row["sha256"]: raise ValueError("piece artifact digest mismatch")
        return value

    def storage(self,scope,method,key,value=None):
        if not isinstance(key,str) or not 1<=len(key)<=256: raise ValueError("invalid piece store key")
        with self.db() as db:
            if method=="put":
                db.execute("INSERT INTO ap_storage VALUES(?,?,?) ON CONFLICT(scope,key) DO UPDATE SET protected_value=excluded.protected_value",
                           (scope,key,_encode(value))); return value
            if method=="delete": db.execute("DELETE FROM ap_storage WHERE scope=? AND key=?",(scope,key)); return None
            row=db.execute("SELECT protected_value FROM ap_storage WHERE scope=? AND key=?",(scope,key)).fetchone()
            return _decode(row[0]) if row else None

    def subscription(self,request,subscription_id,descriptor,member,connection_id,*,hook):
        ident(subscription_id)
        values=(request.principal_id,request.machine_id,request.work_item_id,descriptor.fingerprint,member,connection_id)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM ap_subscriptions WHERE id=?",(subscription_id,)).fetchone()
            if row:
                if tuple(row[k] for k in ("principal","machine","work_item","descriptor_digest","member","connection_id"))!=values:
                    raise EffectRejected("trigger subscription scope/version/connection changed")
                if hook=="onEnable": raise EffectRejected("subscription enable already attempted; reconcile/disable, never duplicate")
                if hook=="onDisable":
                    if row["disable_operation"]: raise EffectRejected("subscription disable already attempted; observe original operation")
                    db.execute("UPDATE ap_subscriptions SET disable_operation=? WHERE id=?",(request.operation_id,subscription_id))
                elif row["disable_operation"]: raise EffectRejected("subscription disable requested; renewal/polling stopped")
                return dict(row)
            if hook!="onEnable": raise EffectRejected("trigger subscription missing")
            db.execute("INSERT INTO ap_subscriptions(id,principal,machine,work_item,descriptor_digest,member,connection_id,enable_operation) VALUES(?,?,?,?,?,?,?,?)",
                       (subscription_id,*values,request.operation_id))
        return {"id":subscription_id,"enable_operation":request.operation_id}

    def claim_trigger(self,subscription_id,event_key,event,operation_id):
        protected,hash_value=_encode(event),digest(event)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT sha256,work_item_reference FROM ap_trigger_events WHERE subscription_id=? AND event_key=?",
                           (subscription_id,event_key)).fetchone()
            if row:
                if row["sha256"]!=hash_value: raise EffectRejected("trigger dedupe key has conflicting event content")
                if row["work_item_reference"] is None:
                    raise EffectRejected("trigger admission outcome uncertain; reconcile central WorkItem, never emit again")
                return row["work_item_reference"]
            db.execute("INSERT INTO ap_trigger_events VALUES(?,?,?,?,?,NULL)",(subscription_id,event_key,hash_value,protected,operation_id))
        return None

    def finish_trigger(self,subscription_id,event_key,work_item_reference):
        with self.db() as db: db.execute("UPDATE ap_trigger_events SET work_item_reference=? WHERE subscription_id=? AND event_key=?",
                                       (work_item_reference,subscription_id,event_key))


class ActivepiecesPieceProvider:
    def __init__(self,gate,*,catalog,store,backend,connection_resolver=None,input_resolver=None,trigger_admitter=None,trigger_lookup=None):
        if not callable(getattr(gate,"physical_context",None)): raise ValueError("pieces need host durable physical admission")
        self.gate=gate if isinstance(gate,HostScopedInteropGate) else HostScopedInteropGate(gate)
        self.catalog,self.store,self.backend=catalog,store,backend
        self.connection_resolver,self.input_resolver=connection_resolver,input_resolver
        self.trigger_admitter,self.trigger_lookup=trigger_admitter,trigger_lookup

    def intent(self,*,piece_name,piece_version,member,invocation_id,props,connection_id=None,hook="action",workflow=None,
               subscription_id=None,trigger_payload=None):
        descriptor=self.catalog.select(piece_name,piece_version)
        descriptor.member(member,hook)
        if hook!="action": ident(subscription_id)
        elif subscription_id is not None or trigger_payload is not None: raise ValueError("action has no trigger subscription/payload")
        return {"piece_name":piece_name,"piece_version":piece_version,"member":member,"hook":hook,
                "invocation_id":invocation_id,"props_sha256":digest(props),"connection_id":connection_id,
                "descriptor_sha256":descriptor.fingerprint,"backend_sha256":self.backend.configuration_sha256,"workflow":workflow,
                "subscription_id":subscription_id,"trigger_payload_sha256":digest(trigger_payload) if hook=="trigger-run" else None}

    async def _admit(self,request,effect):
        return await self.gate.execute(request,effect)

    async def invoke_receipt(self,request,*,props,heartbeat=lambda:None,trigger_payload=None):
        args=request.arguments
        intent_fingerprint=_fingerprint(request)
        props=json.loads(canonical(props))
        descriptor=self.catalog.select(args.get("piece_name"),args.get("piece_version"),fingerprint=args.get("descriptor_sha256"))
        hook=args.get("hook")
        if request.capability_id!=HOOKS.get(hook) or args!=self.intent(piece_name=descriptor.name,piece_version=descriptor.version,
            member=args.get("member"),invocation_id=args.get("invocation_id"),props=props,connection_id=args.get("connection_id"),
            hook=hook,workflow=args.get("workflow"),subscription_id=args.get("subscription_id"),trigger_payload=trigger_payload):
            raise EffectRejected("piece operation intent mismatch")
        try: descriptor.validate_inputs(args["member"],props,hook)
        except ValueError: return ActivityReceipt("FAILED","NOT_STARTED",failure_type="INVALID_INPUT")
        preflight=self.backend.preflight(descriptor,args["member"],hook)
        if inspect.isawaitable(preflight): preflight=await preflight
        if preflight is not None: return preflight
        auth=None
        if args["connection_id"] is not None:
            if not callable(self.connection_resolver): return ActivityReceipt("FAILED","NOT_STARTED",failure_type="CONNECTION_UNAVAILABLE")
            auth=self.connection_resolver(args["connection_id"],request,descriptor)
            if inspect.isawaitable(auth): auth=await auth
        metadata=json.loads(descriptor.metadata_json)
        if metadata.get("auth") is not None and descriptor.member(args["member"],hook).get("requireAuth",True) and auth is None:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="AUTH_DENIED")
        if _fingerprint(request)!=intent_fingerprint: raise EffectRejected("piece request changed during credential resolution")
        if hook!="action":
            subscription=self.store.subscription(request,args.get("subscription_id"),descriptor,args["member"],args["connection_id"],hook=hook)
            if hook in {"onRenew","trigger-run"}:
                enabled=await self.gate.journal.get(subscription["enable_operation"])
                if enabled is None or enabled.state!="SUCCEEDED": raise EffectRejected("trigger enable is not centrally confirmed")
        self.store.begin(request,args["invocation_id"],descriptor,args["member"],hook,args["connection_id"])
        receipt=await self.backend.execute(request,descriptor,props,auth,self.store,heartbeat,trigger_payload=trigger_payload)
        if not isinstance(receipt,ActivityReceipt): raise ValueError("piece backend must report a typed real receipt")
        if receipt.provider_reference: self.store.reference(args["invocation_id"],receipt.provider_reference)
        if receipt.status=="SUCCEEDED":
            artifact=self.store.artifact(args["invocation_id"],receipt.output)
            receipt=ActivityReceipt(receipt.status,receipt.effect_state,receipt.output,provider_reference=receipt.provider_reference,
                                    artifacts=(*receipt.artifacts,artifact))
        return receipt

    async def execute(self,request,*,props,trigger_payload=None):
        async def effect():
            receipt=await self.invoke_receipt(request,props=props,trigger_payload=trigger_payload)
            meta={"invocation_id":request.arguments["invocation_id"],"receipt_sha256":digest(receipt.__dict__),
                  "status":receipt.status,"effect_state":receipt.effect_state,"provider_reference":receipt.provider_reference,
                  "artifacts":list(receipt.artifacts),"completion_confirmed":receipt.status=="SUCCEEDED"}
            if receipt.status in {"FAILED","UNCERTAIN","CANCELLED"}: return OperationResult(request.operation_id,receipt.status,meta,receipt.failure_type)
            return meta
        return await self._admit(request,effect)

    async def host_handler(self,request):
        if request.capability_id=="activepieces:catalog":
            outcome=await self.catalog_read(request,piece_name=request.arguments.get("piece_name"),
                piece_version=request.arguments.get("piece_version"),project_id=request.arguments.get("project_id"))
            return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation
        if request.capability_id=="activepieces:trigger_reconcile":
            outcome=await self.reconcile_trigger(request,subscription_id=request.arguments.get("subscription_id"),event_key=request.arguments.get("event_key"))
            return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation
        if request.capability_id in {"activepieces:observe","activepieces:cancel"}:
            outcome=await self.observe(request,invocation_id=request.arguments.get("invocation_id"),
                                       cancel=request.capability_id=="activepieces:cancel",workflow=request.arguments.get("workflow"))
            return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation
        if request.capability_id=="activepieces:artifact":
            outcome=await self.artifact(request,invocation_id=request.arguments.get("invocation_id"),artifact_id=request.arguments.get("artifact_id"))
            return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation
        if not callable(self.input_resolver): raise EffectRejected("host protected piece input resolver unavailable")
        props=self.input_resolver(request)
        if inspect.isawaitable(props): props=await props
        if request.capability_id=="activepieces:trigger_ingest":
            outcome=await self.ingest_trigger(request,subscription_id=request.arguments.get("subscription_id"),
                                             invocation_id=request.arguments.get("invocation_id"),events=props)
            return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation
        trigger_payload=None
        if request.arguments.get("hook")=="trigger-run":
            if not isinstance(props,dict) or set(props)!={"props","trigger_payload"}: raise EffectRejected("trigger inputs need host-resolved props and payload")
            props,trigger_payload=props["props"],props["trigger_payload"]
        outcome=await self.execute(request,props=props,trigger_payload=trigger_payload)
        return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation

    async def catalog_read(self,request,*,piece_name,piece_version,project_id):
        async def effect():
            if request.capability_id!="activepieces:catalog" or request.arguments!={"piece_name":piece_name,"piece_version":piece_version,"project_id":project_id}:
                raise EffectRejected("piece catalog intent mismatch")
            callback=getattr(self.backend,"metadata",None)
            if not callable(callback): raise EffectRejected("live metadata discovery unavailable in configured backend")
            descriptor=await callback(request,piece_name=piece_name,piece_version=piece_version,project_id=project_id)
            # Discovery provides evidence for owner review; it cannot install,
            # authorize or silently replace a descriptor used by a live flow.
            return {"name":descriptor.name,"version":descriptor.version,"descriptor_sha256":descriptor.fingerprint,
                    "metadata":json.loads(descriptor.metadata_json),"catalog_mutated":False}
        return await self._admit(request,effect)

    def workflow_binding(self,*,handler_id,piece_name,piece_version,member,connection_id=None,hook="action",subscription_id=None):
        from .workflow_worker import WorkflowActivityBinding
        descriptor=self.catalog.select(piece_name,piece_version)
        descriptor.member(member,hook)
        if hook!="action": ident(subscription_id)
        def unpack(inputs):
            if hook!="trigger-run": return inputs,None
            if set(inputs)!={"props","trigger_payload"}: raise EffectRejected("trigger activity inputs must separate props and payload")
            return inputs["props"],inputs["trigger_payload"]
        def arguments(inputs,ref):
            invocation=digest(ref)
            props,payload=unpack(inputs)
            return self.intent(piece_name=piece_name,piece_version=piece_version,member=member,invocation_id=invocation,
                               props=props,connection_id=connection_id,hook=hook,workflow=ref,subscription_id=subscription_id,trigger_payload=payload)
        async def invoke(request,inputs,ref,heartbeat):
            props,payload=unpack(inputs)
            return await self.invoke_receipt(request,props=props,heartbeat=heartbeat,trigger_payload=payload)
        def observe_arguments(entry,ref): return {"invocation_id":digest(ref),"workflow":ref}
        async def observe(request,entry,ref,heartbeat): return await self.observe_receipt(request,heartbeat=heartbeat)
        binding_version=digest({"descriptor":descriptor.fingerprint,"backend":self.backend.configuration_sha256,
                                "member":member,"hook":hook,"connection":connection_id,"subscription":subscription_id})
        return WorkflowActivityBinding(handler_id,binding_version,HOOKS[hook],arguments,invoke,
                                       observe,"activepieces:observe",observe_arguments)

    async def observe_receipt(self,request,*,cancel=False,heartbeat=lambda:None):
        args=request.arguments
        cap="activepieces:cancel" if cancel else "activepieces:observe"
        if request.capability_id!=cap or set(args)!={"invocation_id","workflow"}:
            raise EffectRejected("piece observe/cancel intent mismatch")
        binding=self.store.binding(request,args["invocation_id"])
        callback=getattr(self.backend,"cancel" if cancel else "observe",None)
        if not callable(callback):
            # A terminated process is not evidence of an external rollback.
            # Only a stored central completion/artifact can reconcile it.
            return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type="PROVIDER_RECONCILIATION_UNAVAILABLE")
        receipt=await callback(request,binding,heartbeat)
        if receipt.status=="SUCCEEDED":
            artifact=self.store.artifact(args["invocation_id"],receipt.output)
            return ActivityReceipt("SUCCEEDED","COMPLETED",receipt.output,provider_reference=receipt.provider_reference,
                                   artifacts=(*receipt.artifacts,artifact))
        return receipt

    async def observe(self,request,*,invocation_id,cancel=False,workflow=None):
        async def effect():
            if request.arguments!={"invocation_id":invocation_id,"workflow":workflow}: raise EffectRejected("piece reference mismatch")
            receipt=await self.observe_receipt(request,cancel=cancel)
            # This operation observes a prior effect; its own success is a read
            # confirmation, with the reported piece status kept separately.
            return {"invocation_id":invocation_id,"piece_status":receipt.status,"effect_state":receipt.effect_state,
                    "provider_reference":receipt.provider_reference,"artifacts":list(receipt.artifacts),
                    "effects_rolled_back":False,"receipt_sha256":digest(receipt.__dict__)}
        return await self._admit(request,effect)

    async def artifact(self,request,*,invocation_id,artifact_id):
        async def effect():
            if request.capability_id!="activepieces:artifact" or request.arguments!={"invocation_id":invocation_id,"artifact_id":artifact_id}:
                raise EffectRejected("piece artifact intent mismatch")
            return {"artifact":self.store.read_artifact(request,invocation_id,artifact_id)}
        return await self._admit(request,effect)

    async def ingest_trigger(self,request,*,subscription_id,invocation_id,events):
        async def effect():
            if request.capability_id!="activepieces:trigger_ingest" or request.arguments!={"subscription_id":subscription_id,
                "invocation_id":invocation_id,"events_sha256":digest(events)}:
                raise EffectRejected("trigger ingestion intent mismatch")
            if not isinstance(events,list) or len(events)>100 or not callable(self.trigger_admitter):
                raise EffectRejected("real central trigger task admission callback required")
            with self.store.db() as db: row=db.execute("SELECT * FROM ap_subscriptions WHERE id=?",(subscription_id,)).fetchone()
            if row is None or tuple(row[k] for k in ("principal","machine","work_item"))!=(request.principal_id,request.machine_id,request.work_item_id):
                raise EffectRejected("trigger subscription not accessible")
            if row["disable_operation"]: raise EffectRejected("trigger subscription disable requested; event ingress stopped")
            enabled=await self.gate.journal.get(row["enable_operation"])
            if enabled is None or enabled.state!="SUCCEEDED": raise EffectRejected("trigger enable is not centrally confirmed")
            source=self.store.binding(request,invocation_id)
            if source["hook"]!="trigger-run" or source["subscription_id"]!=subscription_id:
                raise EffectRejected("event source is not this subscription's actual trigger run")
            completed=await self.gate.journal.get(source["operation_id"])
            meta=completed.evidence.get("payload",completed.evidence) if completed else None
            if completed is None or completed.state!="SUCCEEDED" or not isinstance(meta,dict):
                raise EffectRejected("trigger run has no central completion receipt")
            if not any(a.get("kind")=="json-output" and a.get("sha256")==digest(events) for a in meta.get("artifacts",[]) if isinstance(a,dict)):
                raise EffectRejected("events differ from the actual protected trigger output")
            outputs=[]
            for event in events:
                if not isinstance(event,dict): raise ValueError("SDK trigger events must be JSON objects")
                event_key=event.get("_dedupe_key")
                if event_key is None: event_key=digest(event)
                if not isinstance(event_key,str) or not 1<=len(event_key)<=512: raise ValueError("invalid trigger dedupe key")
                prior=self.store.claim_trigger(subscription_id,event_key,event,request.operation_id)
                if prior is not None:
                    outputs.append({"event_key":event_key,"work_item_id":prior,"duplicate":True}); continue
                task_key="piece-event-"+digest({"subscription":subscription_id,"key":event_key})
                result=self.trigger_admitter(request,task_key,event)
                if inspect.isawaitable(result): result=await result
                if not isinstance(result,dict) or not isinstance(result.get("work_item_id"),str) or not result["work_item_id"]:
                    raise ValueError("central trigger callback omitted real WorkItem identity")
                self.store.finish_trigger(subscription_id,event_key,result["work_item_id"])
                outputs.append({"event_key":event_key,"work_item_id":result["work_item_id"],"duplicate":False})
            return {"events":outputs,"created_by":"existing central task admission","replayed_effect":False}
        return await self._admit(request,effect)

    async def reconcile_trigger(self,request,*,subscription_id,event_key):
        """Recover ONLY an existing central task identity; never create one here."""
        async def effect():
            if request.capability_id!="activepieces:trigger_reconcile" or request.arguments!={"subscription_id":subscription_id,"event_key":event_key}:
                raise EffectRejected("trigger reconciliation intent mismatch")
            with self.store.db() as db:
                subscription=db.execute("SELECT * FROM ap_subscriptions WHERE id=?",(subscription_id,)).fetchone()
                event=db.execute("SELECT * FROM ap_trigger_events WHERE subscription_id=? AND event_key=?",(subscription_id,event_key)).fetchone()
            if subscription is None or event is None or tuple(subscription[k] for k in ("principal","machine","work_item"))!=(request.principal_id,request.machine_id,request.work_item_id):
                raise EffectRejected("trigger event not accessible")
            reference=event["work_item_reference"]
            if reference is None:
                if not callable(self.trigger_lookup): raise EffectRejected("central task lookup unavailable; admission remains uncertain")
                task_key="piece-event-"+digest({"subscription":subscription_id,"key":event_key})
                result=self.trigger_lookup(request,task_key)
                if inspect.isawaitable(result): result=await result
                reference=result.get("work_item_id") if isinstance(result,dict) else None
                if reference is not None:
                    if not isinstance(reference,str) or not reference: raise ValueError("invalid central task reference")
                    self.store.finish_trigger(subscription_id,event_key,reference)
            return {"work_item_id":reference,"admission_status":"CONFIRMED" if reference else "UNCERTAIN",
                    "original_operation_id":event["operation_id"],"replayed_effect":False}
        return await self._admit(request,effect)
