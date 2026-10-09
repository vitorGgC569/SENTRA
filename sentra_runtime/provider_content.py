"""Protected provider text, bound to one immutable central operation intent."""
import hashlib
import json
import time
import uuid

from sentra_core.conversations import _encode,_decode
from sentra_interop.gate import _fingerprint


def text_digest(text):
    return hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()


class ProviderContentStore:
    def __init__(self,store,owner):
        self.store,self.owner=store,owner
        db=store.connect("provider_content")
        try:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS provider_messages(owner TEXT NOT NULL,operation TEXT NOT NULL,"
                    "intent TEXT NOT NULL,content TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(owner,operation))")
                db.execute("CREATE TABLE IF NOT EXISTS provider_resource_ids(owner TEXT NOT NULL,machine TEXT NOT NULL,"
                    "work_item TEXT NOT NULL,local_id TEXT NOT NULL,remote_id TEXT NOT NULL UNIQUE,"
                    "PRIMARY KEY(owner,machine,work_item,local_id))")
        finally:db.close()
    def resource_id(self,*,machine_id,work_item_id,local_id):
        if not isinstance(local_id,str) or not 1<=len(local_id)<=256 or "\0" in local_id:
            raise ValueError("valid local provider resource identity required")
        db=self.store.connect("provider_content")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT remote_id FROM provider_resource_ids WHERE owner=? AND machine=? AND work_item=? AND local_id=?",
                               (self.owner,machine_id,work_item_id,local_id)).fetchone()
                if row:return row["remote_id"]
                remote=str(uuid.uuid4())
                db.execute("INSERT INTO provider_resource_ids VALUES(?,?,?,?,?)",
                           (self.owner,machine_id,work_item_id,local_id,remote))
                return remote
        finally:db.close()
    def prepare(self,request,text):
        if not isinstance(text,str) or not text or len(text.encode())>32768:raise ValueError("provider text must be 1..32768 bytes")
        self.prepare_value(request,text)

    def prepare_value(self,request,value):
        intent=_fingerprint(request);protected=_encode(value)
        db=self.store.connect("provider_content")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT * FROM provider_messages WHERE owner=? AND operation=?",
                               (self.owner,request.operation_id)).fetchone()
                if row:
                    if row["intent"]!=intent or text_digest(_decode(row["content"]))!=text_digest(value):
                        raise ValueError("provider content conflicts with recorded intent")
                    return
                db.execute("INSERT INTO provider_messages VALUES(?,?,?,?,?)",
                           (self.owner,request.operation_id,intent,protected,time.time()))
        finally:db.close()
    def resolve(self,request):
        key="text_sha256" if "text_sha256" in request.arguments else "initial_message_sha256"
        value=self.resolve_value(request,key)
        if not isinstance(value,str):raise PermissionError("provider message has invalid type")
        return value

    def resolve_value(self,request,hash_key):
        from .effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None or _fingerprint(context.request)!=_fingerprint(request):
            raise PermissionError("provider content outside active central scope")
        context.checkpoint()
        db=self.store.connect("provider_content")
        try:
            row=db.execute("SELECT * FROM provider_messages WHERE owner=? AND operation=?",
                           (self.owner,request.operation_id)).fetchone()
        finally:db.close()
        if row is None or row["intent"]!=_fingerprint(request):raise PermissionError("provider message intent missing")
        value=_decode(row["content"])
        if text_digest(value)!=request.arguments.get(hash_key):raise PermissionError("provider payload digest mismatch")
        return value
