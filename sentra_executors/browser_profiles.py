"""Owner-local protected browser login state; never returned to a renderer.

Network policy, machine/principal/capability and binding revision identify the
opted-in login. Each use still requires the current WorkItem's central grant;
the cache confers no authority to open a browser or issue input.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time

from sentra_core.conversations import _encode, _decode


class BrowserProfiles:
    def __init__(self, directory):
        self.path=Path(directory)/'protected-logins.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.RLock()
        with closing(sqlite3.connect(self.path)) as db,db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version>1:raise ValueError('browser login schema requires newer SENTRA')
            db.execute('CREATE TABLE IF NOT EXISTS logins(identity TEXT PRIMARY KEY,protected TEXT NOT NULL,updated REAL NOT NULL)')
            db.execute('PRAGMA user_version=1')

    @staticmethod
    def identity(scope,binding,profile):
        parts=json.loads(scope)
        if not isinstance(parts,list) or len(parts)!=4 or any(not isinstance(p,str) or not p for p in parts):
            raise ValueError('host-derived browser session scope required')
        return hashlib.sha256(json.dumps([parts[:3],binding,profile],sort_keys=True).encode()).hexdigest()

    def load(self,scope,binding,profile):
        identity=self.identity(scope,binding,profile)
        with self.lock,closing(sqlite3.connect(self.path)) as db:
            row=db.execute('SELECT protected FROM logins WHERE identity=?',(identity,)).fetchone()
        if not row:return None
        value=_decode(row[0])
        if value.get('identity')!=identity or value.get('schema')!=1:
            raise PermissionError('browser login identity mismatch')
        state=value['state']
        if not isinstance(state,dict) or set(state)-{'cookies','origins'}:
            raise ValueError('invalid protected browser login state')
        return state

    def save(self,scope,binding,profile,state):
        if not isinstance(state,dict) or set(state)-{'cookies','origins'} or len(json.dumps(state).encode())>512*1024:
            raise ValueError('browser login state exceeds bounded format')
        identity=self.identity(scope,binding,profile)
        protected=_encode({'schema':1,'identity':identity,'state':state})
        with self.lock,closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            count,used=db.execute('SELECT count(*),coalesce(sum(length(protected)),0) FROM logins WHERE identity<>?',(identity,)).fetchone()
            if count>=128 or used+len(protected)>16*1024*1024:
                raise ValueError('browser protected login quota exhausted')
            db.execute('INSERT INTO logins VALUES(?,?,?) ON CONFLICT(identity) DO UPDATE SET protected=excluded.protected,updated=excluded.updated',
                (identity,protected,time.time()))

    def forget(self,scope,binding,profile):
        with self.lock,closing(sqlite3.connect(self.path)) as db,db:
            db.execute('DELETE FROM logins WHERE identity=?',(self.identity(scope,binding,profile),))
