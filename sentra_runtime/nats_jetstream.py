"""Real JetStream notification transport via official nats.go owned SDK.

Broker delivery only populates the scoped inbox. There is deliberately NO
execution callback: notifications are references to existing core identities.
"""
import base64
import hashlib
import json
import re
from dataclasses import dataclass,asdict
from urllib.parse import urlsplit

from .audit_delivery import AuditDeliveryStore,AuditBindingConflict,AuditBackpressure,digest
from .audit_provider_bridge import OwnedAuditSDKBridge,AuditProviderUnavailable


NAME=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
KINDS={"operation_status":{"operation_id","state"},"work_item_projection":{"work_item_id","revision"},
       "audit_head":{"source_id","source_seq","source_head_sha256"},"provider_health":{"provider_id","status"}}


@dataclass(frozen=True)
class NATSJetStreamConfig:
    server: str
    stream: str
    consumer: str
    owner: str
    workspace_id: str
    tls: dict
    channel: str = "notifications"
    domain: str = ""
    max_messages: int = 10000
    max_bytes: int = 16_000_000
    max_age_seconds: int = 86400
    duplicate_window_seconds: int = 120
    max_ack_pending: int = 32
    max_deliver: int = 5
    backoff_seconds: tuple = (1,5,30)
    batch: int = 16
    max_payload_bytes: int = 65536
    replicas: int = 1
    max_consumers: int = 16
    replay_from_sequence: int | None = None
    replay_from_time: str | None = None
    def __post_init__(self):
        url=urlsplit(self.server)
        if url.scheme!="tls" or not url.hostname or url.username or url.password or url.path not in {"","/"} or url.query or url.fragment:
            raise ValueError("explicit scoped TLS NATS server required")
        if not all(NAME.fullmatch(v) for v in (self.stream,self.consumer)) or self.channel not in {"notifications","audit"}:
            raise ValueError("pinned JetStream names/channel required")
        if self.domain and not NAME.fullmatch(self.domain): raise ValueError("invalid JS domain")
        if (not 1<=self.batch<=self.max_ack_pending<=1000 or not 1<=self.max_deliver<=100 or not 1<=self.replicas<=5
            or not 1<=self.max_consumers<=1000 or not 60<=self.max_age_seconds<=31536000 or not 1<=self.duplicate_window_seconds<=self.max_age_seconds
            or not 1024<=self.max_payload_bytes<=1_000_000 or not 1<=self.max_messages<=1_000_000 or not 1_000_000<=self.max_bytes<=1_000_000_000
            or self.replay_from_sequence is not None and self.replay_from_time is not None):
            raise ValueError("invalid JS bounds/replay selection")
        if self.replay_from_sequence is not None and (type(self.replay_from_sequence) is not int or self.replay_from_sequence<1): raise ValueError("invalid replay sequence")
        object.__setattr__(self,"backoff_seconds",tuple(self.backoff_seconds))
        if not self.backoff_seconds or len(self.backoff_seconds)>self.max_deliver or any(type(v) not in (int,float) or not 0<v<=86400 for v in self.backoff_seconds):
            raise ValueError("invalid classified redelivery backoff")
        if not isinstance(self.tls,dict) or not self.tls.get("ca_file") or not self.tls.get("ca_sha256") or not self.tls.get("server_name") or not self.tls.get("spki_sha256"):
            raise ValueError("CA/name/SPKI pins required")
    def sdk_configuration(self,scope):
        return {**asdict(self),"subject_prefix":"sentra."+scope[:32]+"."+self.channel}


class NATSJetStreamProvider:
    def __init__(self,*,config,store:AuditDeliveryStore,executable,executable_sha256,credential_provider,enabled=False,bridge=None):
        if not enabled or (config.owner,config.workspace_id)!=(store.owner,store.workspace_id): raise ValueError("NATS owner scope/opt-in mismatch")
        if store.retention_seconds<config.max_age_seconds: raise ValueError("inbox retention must cover stream maximum age")
        self.config,self.store=config,store
        self.bridge=bridge or OwnedAuditSDKBridge(executable=executable,executable_sha256=executable_sha256,provider="nats",
            configuration=config.sdk_configuration(store.scope),credential_provider=credential_provider,enabled=True)
    @property
    def profile_sha256(self): return self.bridge.profile_sha256
    async def connect(self): return await self.bridge.start()
    async def configure(self,*,trusted_admin_authorize):
        if not callable(trusted_admin_authorize) or trusted_admin_authorize(self.config.owner,self.config.workspace_id,self.profile_sha256) is not True:
            raise PermissionError("host JetStream resource administration required")
        return await self.bridge.call("configure")
    def _validate(self,body):
        if not isinstance(body,dict) or set(body)!={"version","scope_sha256","event_id","kind","references","created_at"} or body["version"]!=1:
            raise ValueError("unknown notification envelope; commands/actions refused")
        if body["scope_sha256"]!=self.store.scope or body["kind"] not in KINDS or not isinstance(body["event_id"],str) or not 1<=len(body["event_id"])<=256:
            raise AuditBindingConflict("notification outside owner/workspace")
        refs=body["references"]
        if not isinstance(refs,dict) or set(refs)!=KINDS[body["kind"]] or any(not isinstance(v,(str,int)) or isinstance(v,bool) for v in refs.values()):
            raise ValueError("notification may contain only typed known references")
        if type(body["created_at"]) is not int or not self.store.clock()-self.config.max_age_seconds<=body["created_at"]<=self.store.clock()+30:
            raise ValueError("notification expired/future; retention replay refused")
        if len(json.dumps(body,allow_nan=False).encode())>self.config.max_payload_bytes: raise ValueError("notification exceeds profile bound")
    def subject(self,body): return self.config.sdk_configuration(self.store.scope)["subject_prefix"]+"."+body["kind"]+"."+digest(body["event_id"])
    def enqueue(self,*,event_id,kind,references):
        key=digest({"provider":"nats","event":event_id,"scope":self.store.scope})
        try:
            prior=self.store.row(key)
            if prior["state"]=="EXPIRED": raise AuditBindingConflict("notification identity tombstone retained; no publication replay after retention")
            if (prior["profile_sha256"],prior["body"].get("kind"),prior["body"].get("references"))!=(self.profile_sha256,kind,references):
                raise AuditBindingConflict("notification identity/reference/profile changed")
            return key
        except FileNotFoundError: pass
        body={"version":1,"scope_sha256":self.store.scope,"event_id":event_id,"kind":kind,"references":references,"created_at":int(self.store.clock())}
        self._validate(body)
        return self.store.enqueue(provider="nats",profile_sha256=self.profile_sha256,event_id=event_id,body=body)
    async def publish(self,key):
        row=self.store.row(key)
        if row["state"]=="CONFIRMED": return row["receipt"]
        try: self._validate(row["body"])
        except (ValueError,AuditBindingConflict):
            if row["state"]=="QUEUED": self.store.update(key,state="REJECTED",receipt={"dispatch_started":False,"reason":"NOTIFICATION_EXPIRED_OR_INVALID","proves_core_effect":False})
            raise
        if self.bridge.process is None: raise AuditProviderUnavailable("connect real SDK before publication; export remains queued")
        row=self.store.claim(key,provider="nats",profile_sha256=self.profile_sha256)
        try:
            result=await self.bridge.call("publish",{"subject":self.subject(row["body"]),"message_id":row["event_id"],"body":row["body"]})
            if not isinstance(result,dict) or result.get("stream")!=self.config.stream or type(result.get("sequence")) is not int or result["sequence"]<1:
                raise AuditProviderUnavailable("JetStream publish ACK missing/scoped mismatch")
            receipt={**result,"profile_sha256":self.profile_sha256,"body_sha256":row["body_sha256"],"ack_kind":"JetStream PubAck", "proves_core_effect":False}
            self.store.update(key,state="CONFIRMED",receipt=receipt); return receipt
        except BaseException:
            self.store.update(key,state="UNCERTAIN",receipt={"publish_ack_unknown":True,"resubmit_new_identity":False}); raise
    async def reconcile(self,key):
        row=self.store.row(key)
        if (row["provider"],row["profile_sha256"])!=("nats",self.profile_sha256): raise AuditBindingConflict("NATS reference/profile mismatch")
        if row["state"]=="CONFIRMED": return row["receipt"]
        result=await self.bridge.call("lookup",{"subject":self.subject(row["body"])})
        if not result.get("found"): return {"status":"UNCERTAIN","broker_retention_or_not_published":"cannot distinguish","automatic_resend":False}
        data=base64.b64decode(result["data"],validate=True)
        observed=json.loads(data)
        if digest(observed)!=row["body_sha256"] or result.get("message_id")!=row["event_id"]: raise AuditBindingConflict("broker event differs from immutable outbox")
        receipt={"stream":self.config.stream,"sequence":result["sequence"],"reconciled_by":"JetStream GetLastMsg exact event subject",
                 "body_sha256":row["body_sha256"],"proves_core_effect":False}
        self.store.update(key,state="CONFIRMED",receipt=receipt); return receipt
    async def pull(self,*,batch=None):
        result=await self.bridge.call("pull",{"batch":batch or self.config.batch})
        summaries=[]
        for message in result["messages"]:
            handle=message["handle"]
            try:
                data=base64.b64decode(message["data"],validate=True)
                if len(data)>self.config.max_payload_bytes: raise ValueError("message oversized")
                def unique(pairs):
                    obj={}
                    for k,v in pairs:
                        if k in obj: raise ValueError("duplicate notification field")
                        obj[k]=v
                    return obj
                body=json.loads(data,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite notification")))
                self._validate(body)
                if message["subject"]!=self.subject(body): raise AuditBindingConflict("message subject binding mismatch")
                persisted=self.store.inbox(event_id=body["event_id"],body=body,stream_seq=message["stream_sequence"])
            except AuditBackpressure:
                await self.nak(handle,delay=self.config.backoff_seconds[0]); summaries.append({"backpressure":True,"effects_executed":False}); continue
            except (ValueError,KeyError,AuditBindingConflict):
                evidence=self.store.divergence("nats",{"reason":"NOTIFICATION_SCHEMA_OR_SCOPE_DENIED","stream_sequence":message.get("stream_sequence"),"data_sha256":hashlib.sha256(data).hexdigest() if 'data' in locals() else None})
                await self.term(handle); summaries.append({"quarantined":evidence,"effects_executed":False}); continue
            ack=await self.ack(handle)
            summaries.append({**persisted,"ack":ack})
        return summaries
    async def ack(self,handle): return await self.bridge.call("ack",{"handle":handle})
    async def nak(self,handle,*,delay):
        if not 0<delay<=86400: raise ValueError("bounded NAK delay required")
        return await self.bridge.call("nak",{"handle":handle,"delay_seconds":delay})
    async def term(self,handle): return await self.bridge.call("term",{"handle":handle})
    async def progress(self,handle): return await self.bridge.call("progress",{"handle":handle})
    async def status(self):
        return {"local":self.store.status(),"client":self.bridge.local_status(),"jetstream":await self.bridge.call("status")}
    async def close(self): await self.bridge.close()
    async def invalidate_credentials(self): await self.close()
