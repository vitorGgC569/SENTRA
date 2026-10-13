"""Optional Slack, Telegram and WhatsApp Cloud channels on the ControlStore.

Ingress authenticates raw webhooks and only records an allowlisted inbox.
Workflows explicitly claim and acknowledge it. Outbound effects require an
existing central Operation; provider ACK and recipient receipt are distinct.
No channel creates ChatTrust, Grants, agents, tasks or a second scheduler.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from contextlib import contextmanager

from sentra_core.conversations import _encode,_decode
from sentra_runtime.contracts import OperationResult
from sentra_runtime.effect_boundary import current_effect_context
from .a2a_provider import decode,approved_url
from .gate import EffectRejected
from .provider_store import identifier,canonical,digest

MAX_WEBHOOK=1024*1024
CHANNEL_CAPABILITIES=("channel:send","channel:receipt","channel:inbox","channel:renew",
                      "channel:revoke","channel:delete","channel:webhook_set","channel:webhook_delete")


class ChannelService:
    def __init__(self,control,*,owner):
        self.control,self.owner=control,owner
        self.http=None
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS channel_connectors(
                owner TEXT NOT NULL,id TEXT PRIMARY KEY,project TEXT NOT NULL,kind TEXT NOT NULL,
                revision INTEGER NOT NULL,enabled INTEGER NOT NULL,configuration TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_inbox(
                owner TEXT NOT NULL,connector TEXT NOT NULL,event_id TEXT NOT NULL,sha256 TEXT NOT NULL,
                project TEXT NOT NULL,conversation TEXT NOT NULL,space TEXT,agent TEXT NOT NULL,
                payload TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,claim_id TEXT,
                consumer TEXT,lease_until REAL,operation TEXT,work_item TEXT,receipt TEXT,
                PRIMARY KEY(owner,connector,event_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_outbox(
                owner TEXT NOT NULL,connector TEXT NOT NULL,operation TEXT NOT NULL PRIMARY KEY,
                work_item TEXT NOT NULL,intent TEXT NOT NULL,recipient TEXT NOT NULL,content TEXT NOT NULL,
                state TEXT NOT NULL,external_id TEXT,provider_receipt TEXT,recipient_receipt TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_recipient_events(
                owner TEXT NOT NULL,connector TEXT NOT NULL,external_id TEXT NOT NULL,recipient TEXT NOT NULL,
                receipt TEXT NOT NULL,PRIMARY KEY(owner,connector,external_id,recipient))""")

    @contextmanager
    def db(self):
        db=self.control.store.connect("channels")
        try:
            with db:yield db
        finally:db.close()

    def configure(self,*,connector_id,configuration,expected_revision=0):
        identifier(connector_id)
        if not isinstance(configuration,dict) or type(expected_revision) is not int or expected_revision<0:
            raise ValueError("channel configuration and expected revision required")
        config=json.loads(canonical(configuration));kind=config.get("kind")
        if kind not in {"slack","telegram","whatsapp_cloud"}:
            raise ValueError("unsupported channel; WhatsApp QR/libsignal transport is unavailable")
        project=identifier(config.get("project_id"));agent=identifier(config.get("agent_id"))
        if config.get("enabled") is not True:raise ValueError("channel must be explicitly enabled")
        if any(k in config for k in {"token","app_secret","signing_secret","password","owner","chat_trust"}):
            raise ValueError("channel configuration only accepts vault secret references")
        routes=config.get("routes")
        if not isinstance(routes,list) or not routes or len(routes)>100:raise ValueError("channel routes require explicit sender allowlists")
        seen=set()
        for route in routes:
            if not isinstance(route,dict) or set(route)-{"external_workspace","external_conversation","sender_ids",
                "conversation_id","space_id"} or not {"external_workspace","external_conversation","sender_ids","conversation_id"}<=set(route):
                raise ValueError("invalid channel route")
            key=(identifier(route["external_workspace"]),identifier(route["external_conversation"]))
            if key in seen:raise ValueError("ambiguous channel route")
            seen.add(key);identifier(route["conversation_id"])
            if route.get("space_id") is not None:identifier(route["space_id"])
            if not isinstance(route["sender_ids"],list) or not route["sender_ids"]:raise ValueError("empty channel sender allowlist")
            for value in route["sender_ids"]:identifier(value)
        scopes=config.get("scopes",[])
        if not isinstance(scopes,list) or any(not isinstance(s,str) for s in scopes):raise ValueError("invalid channel scopes")
        required={"slack":{"chat:write"},"telegram":{"bot.send"},"whatsapp_cloud":{"whatsapp_business_messaging"}}[kind]
        if not required<=set(scopes):raise ValueError("channel send scope has not been explicitly configured")
        refs=["token_ref","signing_secret_ref"] if kind=="slack" else ["token_ref","webhook_secret_ref"] if kind=="telegram" else ["token_ref","app_secret_ref","verify_token_ref"]
        for key in refs:
            if not config.get(key):raise ValueError("channel missing required secret reference")
        if kind=="slack":identifier(config.get("team_id"))
        elif kind=="telegram":identifier(config.get("bot_id"))
        else:
            identifier(config.get("business_id"));identifier(config.get("phone_number_id"))
            if not re.fullmatch(r"v[0-9]+\.[0-9]+",config.get("api_version","")):
                raise ValueError("WhatsApp Cloud requires explicit Graph API version pin")
        if config.get("webhook_url"):approved_url(config["webhook_url"])
        for key,value in config.items():
            if key.endswith("_ref") and value:
                self.control.secret_info(value,self.owner)
                self.control.bind_secret(value,self.owner,target_type="agent",target_id=agent,
                                         purpose="channel:"+connector_id+":"+key)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT * FROM channel_connectors WHERE id=?",(connector_id,)).fetchone()
            if old and old["owner"]!=self.owner:raise EffectRejected("channel belongs to another owner")
            if (old["revision"] if old else 0)!=expected_revision:raise EffectRejected("channel configuration revision conflict")
            if old and (old["project"]!=project or old["kind"]!=kind):raise EffectRejected("channel identity cannot change projects/providers")
            revision=expected_revision+1
            db.execute("INSERT INTO channel_connectors VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "revision=excluded.revision,enabled=excluded.enabled,configuration=excluded.configuration",
                (self.owner,connector_id,project,kind,revision,1,_encode(config)))
        return {"connector_id":connector_id,"project_id":project,"workspace_id":project,"kind":kind,
                "revision":revision,"enabled":True,"grant_created":False,"chat_trust_inherited":False}

    def configuration(self,connector_id,*,active=True):
        with self.db() as db:row=db.execute("SELECT * FROM channel_connectors WHERE id=? AND owner=?",
                                         (connector_id,self.owner)).fetchone()
        if row is None:raise FileNotFoundError("channel not configured")
        if active and row["enabled"]!=1:raise EffectRejected("channel revoked/deleted")
        return _decode(row["configuration"])

    def list_connectors(self,*,project_id,limit=100):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError("invalid connector page")
        with self.db() as db:rows=db.execute("SELECT id,project,kind,revision,enabled FROM channel_connectors WHERE "
            "owner=? AND project=? ORDER BY id LIMIT ?",(self.owner,project_id,limit)).fetchall()
        return [{"connector_id":r["id"],"project_id":r["project"],"workspace_id":r["project"],
                 "kind":r["kind"],"revision":r["revision"],"enabled":bool(r["enabled"]),
                 "chat_trust_inherited":False} for r in rows]

    def owner_receipt(self,*,connector_id,project_id,operation_id):
        config=self.configuration(connector_id,active=False)
        if config["project_id"]!=project_id:raise EffectRejected("channel receipt project mismatch")
        with self.db() as db:row=db.execute("SELECT * FROM channel_outbox WHERE owner=? AND connector=? AND operation=?",
                                           (self.owner,connector_id,operation_id)).fetchone()
        if row is None:raise FileNotFoundError("channel receipt not found")
        return {"connector_id":connector_id,"project_id":project_id,"operation_id":operation_id,
            "work_item_id":row["work_item"],"state":"uncertain" if row["state"]=="IN_FLIGHT" else row["state"].lower(),
            "provider_receipt":_decode(row["provider_receipt"]) if row["provider_receipt"] else None,
            "recipient_receipt":_decode(row["recipient_receipt"]) if row["recipient_receipt"] else None,"retry_permitted":False}

    def secret(self,connector,key,config=None):
        config=config or self.configuration(connector)
        ref=config.get(key)
        if not ref:raise EffectRejected("channel secret is not configured")
        value=self.control.governance.resolve_secret_for_runtime(ref,self.owner,actor_type="agent",
            actor_id=config["agent_id"],purpose="channel:"+connector+":"+key)
        if not isinstance(value,str) or not value or any(c in value for c in "\0\r\n"):
            raise EffectRejected("channel credential unavailable")
        return value

    def challenge(self,connector_id,query):
        config=self.configuration(connector_id)
        if config["kind"]!="whatsapp_cloud" or query.get("hub.mode")!="subscribe" or not hmac.compare_digest(
                str(query.get("hub.verify_token","")),self.secret(connector_id,"verify_token_ref",config)):
            raise EffectRejected("channel verification rejected")
        value=query.get("hub.challenge")
        if not isinstance(value,str) or not re.fullmatch(r"[0-9]{1,128}",value):raise ValueError("invalid channel challenge")
        return value

    def authenticate(self,connector,raw,headers,config):
        values={str(k).lower():str(v) for k,v in headers.items()}
        kind=config["kind"]
        if kind=="slack":
            stamp=values.get("x-slack-request-timestamp","")
            if not stamp.isdigit() or abs(time.time()-int(stamp))>300:raise EffectRejected("Slack webhook timestamp invalid")
            signature="v0="+hmac.new(self.secret(connector,"signing_secret_ref",config).encode(),
                b"v0:"+stamp.encode()+b":"+raw,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature,values.get("x-slack-signature","")):raise EffectRejected("Slack webhook signature invalid")
        elif kind=="telegram":
            if not hmac.compare_digest(self.secret(connector,"webhook_secret_ref",config),
                    values.get("x-telegram-bot-api-secret-token","")):raise EffectRejected("Telegram webhook secret invalid")
        else:
            signature="sha256="+hmac.new(self.secret(connector,"app_secret_ref",config).encode(),raw,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature,values.get("x-hub-signature-256","")):raise EffectRejected("WhatsApp webhook signature invalid")

    def route(self,config,workspace,conversation,sender):
        for route in config["routes"]:
            if (route["external_workspace"],route["external_conversation"])==(str(workspace),str(conversation)):
                if str(sender) not in route["sender_ids"]:raise EffectRejected("channel sender not allowlisted")
                return route
        raise EffectRejected("channel workspace/conversation not allowlisted")

    def receive(self,*,connector_id,raw_body,headers):
        if not isinstance(raw_body,bytes) or not 0<len(raw_body)<=MAX_WEBHOOK:raise ValueError("invalid channel webhook body")
        config=self.configuration(connector_id)
        self.authenticate(connector_id,raw_body,headers,config)
        payload=decode(raw_body)
        if not isinstance(payload,dict):raise ValueError("invalid channel webhook object")
        kind=config["kind"];events=[];receipts=[]
        if kind=="slack":
            if payload.get("type")=="url_verification":
                challenge=payload.get("challenge")
                if not isinstance(challenge,str) or len(challenge)>512:raise ValueError("invalid Slack challenge")
                return {"challenge":challenge}
            if payload.get("team_id")!=config["team_id"]:raise EffectRejected("Slack team mismatch")
            event=payload.get("event",{})
            if event.get("type") not in {"message","app_mention"} or event.get("bot_id") or event.get("subtype"):
                return {"ok":True,"ignored":True,"effect_dispatched":False}
            route=self.route(config,payload["team_id"],event.get("channel"),event.get("user"))
            eid=identifier(payload.get("event_id"))
            events.append((eid,route,{"text":event.get("text",""),"sender":event["user"],
                "external_conversation":event["channel"],"external_workspace":payload["team_id"],
                "external_message_id":event.get("ts"),"reply_to":event.get("thread_ts")}))
        elif kind=="telegram":
            update=payload.get("update_id")
            if type(update) is not int or update<0:raise ValueError("invalid Telegram update id")
            message=payload.get("message")
            if not isinstance(message,dict):return {"ok":True,"ignored":True,"effect_dispatched":False}
            if message.get("from",{}).get("is_bot"):return {"ok":True,"ignored":True,"effect_dispatched":False}
            stamp=message.get("date")
            if type(stamp) is not int or not 0<=time.time()-stamp<=86400:raise EffectRejected("Telegram webhook message age invalid")
            chat=str(message.get("chat",{}).get("id"));sender=str(message.get("from",{}).get("id"))
            route=self.route(config,config["bot_id"],chat,sender)
            events.append((str(update),route,{"text":message.get("text",""),"sender":sender,
                "external_conversation":chat,"external_workspace":config["bot_id"],
                "external_message_id":str(message.get("message_id")),
                "reply_to":str(message["reply_to_message"]["message_id"]) if message.get("reply_to_message") else None}))
        else:
            if payload.get("object")!="whatsapp_business_account":raise ValueError("invalid WhatsApp webhook object")
            for entry in payload.get("entry",[]):
                if str(entry.get("id"))!=config["business_id"]:raise EffectRejected("WhatsApp business mismatch")
                for change in entry.get("changes",[]):
                    value=change.get("value",{})
                    if value.get("metadata",{}).get("phone_number_id")!=config["phone_number_id"]:
                        raise EffectRejected("WhatsApp phone identity mismatch")
                    for message in value.get("messages",[]):
                        if message.get("type")!="text":continue
                        sender=identifier(message.get("from"))
                        route=self.route(config,config["business_id"],sender,sender)
                        stamp=int(message.get("timestamp","0"))
                        if not 0<=time.time()-stamp<=86400:raise EffectRejected("WhatsApp message age invalid")
                        events.append((identifier(message.get("id")),route,{"text":message.get("text",{}).get("body",""),
                            "sender":sender,"external_conversation":sender,"external_workspace":config["business_id"],
                            "external_message_id":message["id"],"reply_to":message.get("context",{}).get("id")}))
                    receipts.extend(value.get("statuses",[]))
        accepted=[]
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for eid,route,event in events:
                if not isinstance(event["text"],str) or len(event["text"].encode())>32768:raise ValueError("channel message exceeds bound")
                sha=digest(event)
                old=db.execute("SELECT sha256 FROM channel_inbox WHERE owner=? AND connector=? AND event_id=?",
                    (self.owner,connector_id,eid)).fetchone()
                if old and old["sha256"]!=sha:raise EffectRejected("channel event replay changed content")
                if not old:
                    db.execute("INSERT INTO channel_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (self.owner,connector_id,eid,sha,config["project_id"],route["conversation_id"],route.get("space_id"),
                         config["agent_id"],_encode(event),"PENDING",1,None,None,None,None,None,None))
                accepted.append({"event_id":eid,"project_id":config["project_id"],"workspace_id":config["project_id"],
                    "conversation_id":route["conversation_id"],"space_id":route.get("space_id"),"duplicate":bool(old)})
                if event.get("reply_to"):
                    db.execute("UPDATE channel_outbox SET recipient_receipt=? WHERE owner=? AND connector=? AND external_id=? AND recipient=?",
                        (_encode({"status":"recipient_replied","event_id":eid,"sender":event["sender"]}),self.owner,
                         connector_id,event["reply_to"],event["external_conversation"]))
            for receipt in receipts:
                if not isinstance(receipt,dict) or receipt.get("status") not in {"sent","delivered","read","failed"}:
                    raise ValueError("invalid WhatsApp recipient receipt")
                external=identifier(receipt.get("id"));recipient=identifier(receipt.get("recipient_id"))
                if not any(r["external_conversation"]==recipient for r in config["routes"]):
                    raise EffectRejected("WhatsApp status recipient not allowlisted")
                previous=db.execute("SELECT receipt FROM channel_recipient_events WHERE owner=? AND connector=? AND external_id=? AND recipient=?",
                                    (self.owner,connector_id,external,recipient)).fetchone()
                if previous:
                    old=_decode(previous["receipt"])
                    rank={"sent":0,"failed":0,"delivered":1,"read":2}
                    if rank[old["status"]]>=rank[receipt["status"]]:continue
                protected=_encode({"status":receipt["status"],"external_message_id":external,"timestamp":receipt.get("timestamp")})
                db.execute("INSERT INTO channel_recipient_events VALUES(?,?,?,?,?) ON CONFLICT(owner,connector,external_id,recipient) "
                    "DO UPDATE SET receipt=excluded.receipt",(self.owner,connector_id,external,recipient,protected))
                if isinstance(receipt.get("biz_opaque_callback_data"),str):
                    db.execute("UPDATE channel_outbox SET external_id=?,provider_receipt=?,state='PROVIDER_ACCEPTED' "
                        "WHERE owner=? AND connector=? AND operation=? AND recipient=? AND (external_id IS NULL OR external_id=?)",
                        (external,_encode({"external_message_id":external,"status":"provider_accepted_by_callback"}),
                         self.owner,connector_id,receipt["biz_opaque_callback_data"],recipient,external))
                rows=db.execute("SELECT * FROM channel_outbox WHERE owner=? AND connector=? AND external_id=? AND recipient=?",
                    (self.owner,connector_id,receipt.get("id"),receipt.get("recipient_id"))).fetchall()
                for row in rows:
                    old=_decode(row["recipient_receipt"]) if row["recipient_receipt"] else None
                    rank={"sent":0,"failed":0,"delivered":1,"read":2}
                    if old and rank.get(old.get("status"),-1)>=rank[receipt["status"]]:continue
                    db.execute("UPDATE channel_outbox SET recipient_receipt=? WHERE operation=?",
                        (protected,row["operation"]))
        return {"ok":True,"connector_id":connector_id,"project_id":config["project_id"],"workspace_id":config["project_id"],
                "accepted":accepted,"receipts_recorded":len(receipts),"effect_dispatched":False,"chat_trust_inherited":False}

    def pending_inbound(self,*,connector_id,project_id,limit=100):
        config=self.configuration(connector_id)
        if config["project_id"]!=project_id:raise EffectRejected("channel project mismatch")
        if type(limit) is not int or not 1<=limit<=100:raise ValueError("invalid channel page")
        with self.db() as db:rows=db.execute("SELECT * FROM channel_inbox WHERE owner=? AND connector=? AND project=? "
            "AND state='PENDING' ORDER BY event_id LIMIT ?",(self.owner,connector_id,project_id,limit)).fetchall()
        return [{"connector_id":connector_id,"event_id":r["event_id"],"project_id":r["project"],"workspace_id":r["project"],
                 "conversation_id":r["conversation"],"space_id":r["space"],"agent_id":r["agent"],
                 "revision":r["revision"],"payload":_decode(r["payload"]),"chat_trust_inherited":False} for r in rows]

    def claim(self,*,connector_id,event_id,consumer_id,expected_revision,lease_seconds=60):
        config=self.configuration(connector_id)
        if type(lease_seconds) is not int or not 1<=lease_seconds<=300:raise ValueError("invalid channel claim lease")
        claim_id=str(uuid.uuid4())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM channel_inbox WHERE owner=? AND connector=? AND event_id=?",
                           (self.owner,connector_id,event_id)).fetchone()
            if row is None:raise FileNotFoundError("channel event not found")
            if row["state"]!="PENDING" or row["revision"]!=expected_revision:
                raise EffectRejected("channel event already claimed; reconcile before dispatch")
            db.execute("UPDATE channel_inbox SET state='CLAIMED',claim_id=?,consumer=?,lease_until=?,revision=revision+1 "
                       "WHERE owner=? AND connector=? AND event_id=?",
                       (claim_id,identifier(consumer_id),time.time()+lease_seconds,self.owner,connector_id,event_id))
        return {"claim_id":claim_id,"event_id":event_id,"connector_id":connector_id,"project_id":config["project_id"],
                "workspace_id":config["project_id"],"revision":expected_revision+1,"dispatch_idempotency_key":"channel:"+connector_id+":"+event_id}

    def inbound_claim(self, *, connector_id, event_id, consumer_id=None):
        config = self.configuration(connector_id)
        with self.db() as db:
            row = db.execute("SELECT * FROM channel_inbox WHERE owner=? AND connector=? AND event_id=?",
                (self.owner, connector_id, event_id)).fetchone()
        if row is None:
            raise FileNotFoundError("channel event not found")
        if row["project"] != config["project_id"] or row["agent"] != config["agent_id"]:
            raise EffectRejected("inbox configuration scope changed")
        if row["state"] == "PENDING":
            return None
        if row["state"] not in {"CLAIMED", "ACKNOWLEDGED"} or consumer_id is not None and row["consumer"] != consumer_id:
            raise EffectRejected("channel claim unavailable or held by another consumer")
        return {"claim_id": row["claim_id"], "event_id": event_id, "connector_id": connector_id,
            "project_id": row["project"], "workspace_id": row["project"], "revision": row["revision"],
            "dispatch_idempotency_key": "channel:" + connector_id + ":" + event_id}

    def claimed_payload(self, *, connector_id, event_id, claim_id):
        self.inbound_claim(connector_id=connector_id, event_id=event_id)
        with self.db() as db:
            row = db.execute("SELECT payload,claim_id FROM channel_inbox WHERE owner=? AND connector=? AND event_id=?",
                (self.owner, connector_id, event_id)).fetchone()
        if row is None or row["claim_id"] != claim_id:
            raise EffectRejected("channel payload claim mismatch")
        return _decode(row["payload"])

    def ack(self,*,claim_id,work_item_id,operation_id,receipt_id=None):
        item=self.control.work_item_info(work_item_id,self.owner)
        operation=self.control.durable.operation_status(operation_id,self.owner)
        progress=operation.get("progress",{})
        if operation["run_id"]!=item["run_id"] or progress.get("work_item_id")!=work_item_id:
            raise EffectRejected("channel acknowledgement has another central WorkItem")
        state="ACKNOWLEDGED" if operation["state"]=="SUCCEEDED" else "UNCERTAIN"
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM channel_inbox WHERE owner=? AND claim_id=?",(self.owner,claim_id)).fetchone()
            if row is None:raise FileNotFoundError("channel claim not found")
            if item.get("metadata",{}).get("workspace_id")!=row["project"]:
                raise EffectRejected("channel acknowledgement project mismatch")
            if row["state"]=="ACKNOWLEDGED":
                if row["operation"]!=operation_id:raise EffectRejected("channel event acknowledgement conflict")
            elif row["state"]!="CLAIMED":raise EffectRejected("channel claim is unavailable")
            db.execute("UPDATE channel_inbox SET state=?,operation=?,work_item=?,receipt=?,revision=revision+1 WHERE claim_id=?",
                       (state,operation_id,work_item_id,receipt_id or operation_id,claim_id))
        return {"claim_id":claim_id,"status":state.lower(),"operation_id":operation_id,"receipt_id":receipt_id or operation_id}

    def checkpoint(self,request=None):
        context=current_effect_context.get()
        if context is None or request and context.request!=request:raise EffectRejected("channel effect outside central admission")
        context.checkpoint()

    async def api(self,connector,method,body,*,form=False):
        config=self.configuration(connector);self.checkpoint()
        if self.http is None:
            import httpx
            self.http=httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30)
        kind=config["kind"];headers={"Accept":"application/json"}
        if kind=="slack":
            if method not in {"chat.postMessage","oauth.v2.access","auth.revoke"}:raise ValueError("invalid Slack method")
            url="https://slack.com/api/"+method
            headers["Authorization"]="Bearer "+self.secret(connector,"token_ref",config)
        elif kind=="telegram":
            if method not in {"sendMessage","setWebhook","deleteWebhook","logOut"}:raise ValueError("invalid Telegram method")
            url="https://api.telegram.org/bot"+self.secret(connector,"token_ref",config)+"/"+method
        else:
            if method!="messages":raise ValueError("invalid WhatsApp API method")
            url="https://graph.facebook.com/"+config["api_version"]+"/"+config["phone_number_id"]+"/messages"
            headers["Authorization"]="Bearer "+self.secret(connector,"token_ref",config)
        async with self.http.stream("POST",url,headers=headers,**({"data":body} if form else {"json":body})) as response:
            raw=bytearray()
            async for chunk in response.aiter_bytes():
                self.checkpoint();raw.extend(chunk)
                if len(raw)>MAX_WEBHOOK:raise ValueError("channel API response exceeds bound")
            if not 200<=response.status_code<300:raise RuntimeError("channel API rejected request")
        value=decode(raw)
        if not isinstance(value,dict) or kind in {"slack","telegram"} and value.get("ok") is not True:
            raise RuntimeError("channel API did not acknowledge request")
        return value

    async def send(self,request,*,connector_id,recipient,text):
        self.checkpoint(request);config=self.configuration(connector_id)
        if request.capability_id!="channel:send" or request.arguments!={"connector_id":connector_id,"recipient":recipient,"text_sha256":digest(text)}:
            raise EffectRejected("channel send immutable intent mismatch")
        if not isinstance(text,str) or not text or len(text.encode())>16000:raise ValueError("channel message invalid")
        if not any(r["external_conversation"]==recipient for r in config["routes"]):raise EffectRejected("channel recipient not allowlisted")
        item=self.control.work_item_info(request.work_item_id,self.owner)
        if item.get("metadata",{}).get("workspace_id")!=config["project_id"] or request.principal_id!=config["agent_id"]:
            raise EffectRejected("channel send project/agent mismatch")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT * FROM channel_outbox WHERE operation=?",(request.operation_id,)).fetchone()
            if old:raise EffectRejected("channel outbox already sent or uncertain; inspect receipt")
            db.execute("INSERT INTO channel_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (self.owner,connector_id,request.operation_id,request.work_item_id,digest(request.arguments),recipient,_encode(text),
                 "IN_FLIGHT",None,None,None))
        try:
            kind=config["kind"]
            if kind=="slack":
                result=await self.api(connector_id,"chat.postMessage",{"channel":recipient,"text":text,
                    "client_msg_id":str(uuid.uuid5(uuid.NAMESPACE_URL,request.operation_id)),"unfurl_links":False,"unfurl_media":False})
                if result.get("channel")!=recipient:raise ValueError("Slack message recipient changed")
                external=identifier(result.get("ts"))
            elif kind=="telegram":
                result=await self.api(connector_id,"sendMessage",{"chat_id":recipient,"text":text,"link_preview_options":{"is_disabled":True}})
                message=result.get("result",{})
                if str(message.get("chat",{}).get("id"))!=recipient:raise ValueError("Telegram message recipient changed")
                external=identifier(str(message.get("message_id")))
            else:
                result=await self.api(connector_id,"messages",{"messaging_product":"whatsapp","recipient_type":"individual",
                    "to":recipient,"type":"text","text":{"preview_url":False,"body":text},
                    "biz_opaque_callback_data":request.operation_id})
                if not isinstance(result.get("messages"),list) or len(result["messages"])!=1:raise ValueError("WhatsApp send acknowledgement missing")
                external=identifier(result["messages"][0].get("id"))
            self.checkpoint(request)
            receipt={"external_message_id":external,"status":"provider_accepted","recipient_receipt":None}
            with self.db() as db:
                early=db.execute("SELECT receipt FROM channel_recipient_events WHERE owner=? AND connector=? AND external_id=? AND recipient=?",
                                 (self.owner,connector_id,external,recipient)).fetchone()
                db.execute("UPDATE channel_outbox SET state='PROVIDER_ACCEPTED',external_id=?,provider_receipt=?,recipient_receipt=? WHERE operation=?",
                           (external,_encode(receipt),early["receipt"] if early else None,request.operation_id))
            return {"connector_id":connector_id,"project_id":config["project_id"],**receipt,
                    "recipient_delivery_supported":kind=="whatsapp_cloud","recipient_reply_supported":True}
        except BaseException:
            with self.db() as db:db.execute("UPDATE channel_outbox SET state='UNCERTAIN' WHERE operation=?",(request.operation_id,))
            raise

    def receipt(self,request,*,connector_id,operation_id):
        self.checkpoint(request)
        with self.db() as db:row=db.execute("SELECT * FROM channel_outbox WHERE owner=? AND connector=? AND operation=? AND work_item=?",
            (self.owner,connector_id,operation_id,request.work_item_id)).fetchone()
        if row is None:raise FileNotFoundError("channel delivery receipt not found")
        config=self.configuration(connector_id,active=False)
        return {"operation_id":operation_id,"state":"uncertain" if row["state"]=="IN_FLIGHT" else row["state"].lower(),
                "provider_receipt":_decode(row["provider_receipt"]) if row["provider_receipt"] else None,
                "recipient_receipt":_decode(row["recipient_receipt"]) if row["recipient_receipt"] else None,
                "recipient_delivery_supported":config["kind"]=="whatsapp_cloud","retry_permitted":False}

    async def lifecycle(self,request,*,connector_id,action):
        self.checkpoint(request);config=self.configuration(connector_id)
        if request.capability_id!="channel:"+action or request.arguments!={"connector_id":connector_id}:
            raise EffectRejected("channel lifecycle intent mismatch")
        kind=config["kind"]
        if action=="renew":
            if kind!="slack":raise EffectRejected("this provider requires explicit token replacement through owner vault rotation")
            body={"grant_type":"refresh_token","refresh_token":self.secret(connector_id,"refresh_token_ref",config),
                  "client_id":config.get("client_id"),"client_secret":self.secret(connector_id,"client_secret_ref",config)}
            result=await self.api(connector_id,"oauth.v2.access",body,form=True)
            if result.get("team",{}).get("id")!=config["team_id"] or not isinstance(result.get("access_token"),str):
                raise ValueError("Slack refreshed token identity mismatch")
            if not set(config["scopes"])<=set(result.get("scope","").split(",")):
                raise EffectRejected("Slack refreshed token lost configured scopes")
            self.control.rotate_secret(config["token_ref"],self.owner,value=result["access_token"])
            if result.get("refresh_token"):self.control.rotate_secret(config["refresh_token_ref"],self.owner,value=result["refresh_token"])
            return {"renewed":True,"scope_checked":True,"connector_id":connector_id}
        if action=="webhook_set":
            if kind!="telegram":raise EffectRejected("Slack/WhatsApp webhook setup requires owner app-console registration")
            url=config.get("webhook_url")
            if not url or not url.startswith("https://"):raise EffectRejected("public HTTPS Telegram webhook is not configured")
            await self.api(connector_id,"setWebhook",{"url":url,"secret_token":self.secret(connector_id,"webhook_secret_ref",config),
                "allowed_updates":["message"],"drop_pending_updates":False})
            return {"webhook_registered":True}
        if action=="webhook_delete":
            if kind!="telegram":raise EffectRejected("provider webhook removal requires owner app-console action")
            await self.api(connector_id,"deleteWebhook",{"drop_pending_updates":False})
            return {"webhook_deleted":True}
        if action not in {"revoke","delete"}:raise EffectRejected("unknown channel lifecycle action")
        remote_revoked=False
        if action=="revoke" and kind=="slack":
            try:
                result=await self.api(connector_id,"auth.revoke",{})
                remote_revoked=result.get("revoked") is True
            finally:
                with self.db() as db:db.execute("UPDATE channel_connectors SET enabled=0,revision=revision+1 WHERE owner=? AND id=?",
                                               (self.owner,connector_id))
        else:
            with self.db() as db:db.execute("UPDATE channel_connectors SET enabled=0,revision=revision+1 WHERE owner=? AND id=?",
                                           (self.owner,connector_id))
        if action=="delete":
            with self.db() as db:
                db.execute("UPDATE channel_inbox SET payload=?,state='DELETED' WHERE owner=? AND connector=?",(_encode({}),self.owner,connector_id))
                db.execute("UPDATE channel_outbox SET content=? WHERE owner=? AND connector=?",(_encode(None),self.owner,connector_id))
            return {"deleted":True,"tombstones_retained":True,"remote_token_revoked":False}
        # The caller can rotate/revoke secrets in the central vault. A disabled
        # connector is never temporarily re-enabled for a remote cleanup call.
        return {"revoked":True,"remote_token_revoked":remote_revoked,"remote_revoke_required":not remote_revoked,
                "fallback":"owner provider-console token revocation" if not remote_revoked else None}

    async def close(self):
        if self.http is not None:await self.http.aclose();self.http=None
