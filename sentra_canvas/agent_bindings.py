"""Protected terminal capabilities restored only from a live daemon's exact proof."""
from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import time
import uuid

from sentra_cli.canvas_binding import signature,process_stamp
from sentra_remote.secrets import protect_secret,unprotect_secret
from .mobile_network import atomic_json


class AgentBindings:
    def __init__(self,state,owner):
        self.root=Path(state)/'agent-bindings';self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'bindings.sqlite3';self.owner=owner
        with self.db() as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version>1:raise RuntimeError('Canvas agent binding schema is newer than this application')
            db.execute('''CREATE TABLE IF NOT EXISTS bindings(owner TEXT,workspace TEXT,terminal TEXT,
                binding_id TEXT UNIQUE,protected_token TEXT,token_hash TEXT,state TEXT,daemon_runtime TEXT,
                pid INTEGER,updated REAL,PRIMARY KEY(owner,terminal))''')
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def reserve(self,workspace,terminal,token):
        if len(token)<32:raise ValueError('strong limited Canvas credential required')
        protected=protect_secret(token)
        if not protected.startswith(('dpapi:','keyring:')):raise RuntimeError('OS protected agent credential required')
        ident=uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO bindings VALUES(?,?,?,?,?,?,?,?,?,?)',
                (self.owner,workspace,terminal,ident,protected,hashlib.sha256(token.encode()).hexdigest(),
                 'reserved',None,None,time.time()))
        return self.root/(ident+'.json')

    def recover(self,proof):
        if proof.get('process_live') is not True:return None
        with self.db() as db:
            row=db.execute('SELECT * FROM bindings WHERE owner=? AND terminal=? AND workspace=?',
                (self.owner,proof['terminal_id'],proof['workspace_id'])).fetchone()
            if not row or row['state'] not in {'reserved','active'}:return None
            if not hmac.compare_digest(row['token_hash'],proof.get('agent_token_sha256') or ''):return None
            if row['state']=='active' and (row['daemon_runtime']!=proof['runtime_id'] or row['pid']!=proof['pid']):return None
            token=unprotect_secret(row['protected_token'])
            if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),row['token_hash']):
                raise PermissionError('Canvas credential storage identity mismatch')
            db.execute("UPDATE bindings SET state='active',daemon_runtime=?,pid=?,updated=? WHERE owner=? AND terminal=?",
                (proof['runtime_id'],proof['pid'],time.time(),self.owner,proof['terminal_id']))
            return token

    def publish(self,terminal,token,workspace_id,workspace,port,runtime_id):
        with self.db() as db:
            row=db.execute("SELECT * FROM bindings WHERE owner=? AND terminal=? AND state IN ('reserved','active')",
                (self.owner,terminal)).fetchone()
        if not row or row['workspace']!=workspace_id or not hmac.compare_digest(row['token_hash'],hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError('Canvas binding is not active for this terminal')
        value={'version':1,'binding_id':row['binding_id'],'terminal_id':terminal,'workspace':workspace,
            'port':port,'runtime_id':runtime_id,'broker_pid':os.getpid(),
            'process_stamp':process_stamp(os.getpid())}
        atomic_json(self.root/(row['binding_id']+'.json'),{**value,'signature':signature(value,token)})

    def revoke(self,terminal):
        with self.db() as db:
            row=db.execute('SELECT binding_id FROM bindings WHERE owner=? AND terminal=?',(self.owner,terminal)).fetchone()
            db.execute("UPDATE bindings SET state='revoked',protected_token=NULL WHERE owner=? AND terminal=?",(self.owner,terminal))
        if row:(self.root/(row['binding_id']+'.json')).unlink(missing_ok=True)
