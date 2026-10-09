"""Protected identity session projections; no Run/Operation/grant authority."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sentra_core.conversations import _encode, _decode


def identity_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()).hexdigest()


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal_id: str
    issuer: str
    subject: str
    kind: str
    expires_at: int


def principal_id(issuer,subject,*,kind="oidc"):
    if kind not in {"oidc","spiffe"} or not all(isinstance(v,str) and v and len(v)<=2048 for v in (issuer,subject)):
        raise ValueError("invalid authenticated principal origin")
    return kind+"-"+identity_digest({"issuer":issuer,"subject":subject})


class IdentityStateConflict(PermissionError): pass


class ProtectedIdentityStore:
    def __init__(self,database,*,workspace,namespace):
        self.path,root=Path(database).resolve(),Path(workspace).resolve()
        if self.path==root or not self.path.is_relative_to(root) or not isinstance(namespace,str) or not namespace:
            raise ValueError("identity projection must be workspace-scoped")
        self.namespace=namespace; self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS identity_records(namespace TEXT,key TEXT,revision INTEGER,protected_value TEXT,sha256 TEXT,PRIMARY KEY(namespace,key))")
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def get(self,key):
        with self.db() as db: row=db.execute("SELECT * FROM identity_records WHERE namespace=? AND key=?",(self.namespace,key)).fetchone()
        if row is None: return None
        value=_decode(row["protected_value"])
        if identity_digest(value)!=row["sha256"]: raise IdentityStateConflict("identity state digest mismatch")
        return {"revision":row["revision"],"value":value}
    def put(self,key,value,*,expected_revision=None):
        encrypted,sha=_encode(value),identity_digest(value)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT revision FROM identity_records WHERE namespace=? AND key=?",(self.namespace,key)).fetchone()
            if (row[0] if row else None)!=expected_revision: raise IdentityStateConflict("identity state CAS conflict")
            revision=0 if row is None else row[0]+1
            db.execute("INSERT INTO identity_records VALUES(?,?,?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET revision=excluded.revision,protected_value=excluded.protected_value,sha256=excluded.sha256",
                       (self.namespace,key,revision,encrypted,sha))
        return revision
    def records(self,prefix):
        with self.db() as db: keys=[r[0] for r in db.execute("SELECT key FROM identity_records WHERE namespace=?",(self.namespace,)) if r[0].startswith(prefix)]
        return [(key,self.get(key)) for key in keys]
