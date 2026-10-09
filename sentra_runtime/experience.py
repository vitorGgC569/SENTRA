"""Scoped, provenance-bound experience suggestions. Knowledge grants no authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time

from sentra_core.conversations import _encode, _decode
from .central_authority import CentralDurableIntentAuthority


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def file_digest(path, limit=32*1024*1024):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>limit:
        raise ValueError("experience dependency unavailable")
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        count=0
        for block in iter(lambda:stream.read(1024*1024),b""):
            count+=len(block)
            if count>limit:raise ValueError("experience dependency exceeds bound")
            digest.update(block)
    return digest.hexdigest()


class ExperienceMemory:
    def __init__(self, control, *, owner, clock=time.time):
        self.control,self.owner,self.clock=control,owner,clock
        db=control.store.connect("experience_memory")
        try:
            with db:
                if db.execute("PRAGMA user_version").fetchone()[0]>1:raise RuntimeError("newer experience database")
                db.execute("CREATE TABLE IF NOT EXISTS experiences(owner TEXT NOT NULL,operation TEXT NOT NULL,"
                    "workspace TEXT NOT NULL,principal TEXT NOT NULL,machine TEXT NOT NULL,capability TEXT NOT NULL,"
                    "configuration TEXT NOT NULL,content TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,"
                    "PRIMARY KEY(owner,operation))")
                db.execute("PRAGMA user_version=1")
        finally:db.close()

    def record(self, request, *, workspace_id, configuration, ttl_seconds=7*86400):
        if type(ttl_seconds) is not int or not 1<=ttl_seconds<=90*86400:
            raise ValueError("invalid experience expiry")
        item=self.control.work_item_info(request.work_item_id,self.owner)
        row=self.control.durable.operation_status(request.operation_id,self.owner)
        if item.get("metadata",{}).get("workspace_id")!=workspace_id or row["run_id"]!=item["run_id"]:
            raise PermissionError("experience origin outside workspace")
        progress=row.get("progress") or {}
        expected={"principal_id":request.principal_id,"machine_id":request.machine_id,
                  "capability_id":request.capability_id,"work_item_id":request.work_item_id}
        if any(progress.get(key)!=value for key,value in expected.items()):
            raise PermissionError("experience origin identity mismatch")
        authority=CentralDurableIntentAuthority(self.control.durable)
        receipt=authority.receipt_for_operation(request.operation_id,self.owner)
        result=authority.result_for_receipt(receipt)
        if result is None or result.state not in {"SUCCEEDED","FAILED"}:
            return False  # Unknown effects are never recommended as reusable successes.
        dependencies={}
        input_path=request.arguments.get("input")
        input_digest=result.evidence.get("input_sha256")
        if input_path is not None:
            root=Path(configuration["workspace_root"]).resolve(strict=True)
            source=Path(input_path).resolve(strict=True)
            if not source.is_relative_to(root) or not isinstance(input_digest,str) or file_digest(source)!=input_digest:
                return False
            dependencies[str(source)]=input_digest
        content={"objective":item["objective"][:4000],"action":str(request.arguments.get("action",""))[:128],
            "result":result.state,"origin":{"operation_id":row["operation_id"],"work_item_id":request.work_item_id,
            "run_id":row["run_id"],"intent_sha256":receipt.intent_sha256},"dependencies":dependencies,
            "advice":"Revalidate current inputs, permissions and output verification before applying this experience.",
            "knowledge_only":True}
        protected=_encode(content)
        db=self.control.store.connect("experience_memory")
        try:
            with db:
                now=self.clock()
                db.execute("DELETE FROM experiences WHERE owner=? AND expires<=?",(self.owner,now))
                db.execute("INSERT INTO experiences VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(owner,operation) DO NOTHING",
                    (self.owner,request.operation_id,workspace_id,request.principal_id,request.machine_id,
                     request.capability_id,fingerprint(configuration),protected,now,now+ttl_seconds))
                db.execute("DELETE FROM experiences WHERE owner=? AND operation NOT IN "
                    "(SELECT operation FROM experiences WHERE owner=? ORDER BY created DESC LIMIT 2000)",
                    (self.owner,self.owner))
        finally:db.close()
        return True

    def retrieve(self, *, workspace_id, principal_id, configuration, query, capability_id=None, limit=5):
        if not isinstance(query,str) or not 1<=len(query)<=4000 or type(limit) is not int or not 1<=limit<=20:
            raise ValueError("bounded experience query required")
        db=self.control.store.connect("experience_memory")
        try:
            rows=list(db.execute("SELECT * FROM experiences WHERE owner=? AND workspace=? AND principal=? "
                "AND configuration=? AND expires>? ORDER BY created DESC LIMIT 500",
                (self.owner,workspace_id,principal_id,fingerprint(configuration),self.clock())))
        finally:db.close()
        words=lambda text:set(re.findall(r"[\w-]{2,}",text.casefold()))
        terms=words(query);matches=[]
        for row in rows:
            if capability_id is not None and row["capability"]!=capability_id:continue
            try:
                content=_decode(row["content"])
                if any(file_digest(path)!=digest for path,digest in content["dependencies"].items()):continue
                authority=CentralDurableIntentAuthority(self.control.durable)
                result=authority.result_for_receipt(authority.receipt_for_operation(row["operation"],self.owner))
                if result is None or result.state!=content["result"]:continue
            except (OSError,ValueError,RuntimeError,PermissionError):continue
            tokens=words(content["objective"]+" "+content["action"])
            score=len(terms&tokens)/max(1,len(terms|tokens))
            if score:
                matches.append({**content,"relevance":round(score,4),"expires_at":row["expires"]})
        return sorted(matches,key=lambda value:value["relevance"],reverse=True)[:limit]
