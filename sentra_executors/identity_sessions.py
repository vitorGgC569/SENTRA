"""Provider resource ownership and cursor journal, NOT a grant/lease authority."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ._base import GuardedExecutor
from .rpa import ExecutorFailure, effect_checkpoint, atomic_output, AuthorizedPaths


@dataclass(frozen=True)
class SessionScope:
    machine_id: str
    principal_id: str
    capability_id: str
    work_item_id: str

    @classmethod
    def from_request(cls, request):
        return cls(request.machine_id,request.principal_id,request.capability_id,request.work_item_id)

    @property
    def key(self):
        return hashlib.sha256(json.dumps([self.machine_id,self.principal_id,self.capability_id,
            self.work_item_id],separators=(',',':')).encode()).hexdigest()


class SessionJournal:
    """SQLite mapping and bounded received data; never fabricates remote status.

    A cursor is local durable ingress sequence, not a remote transport offset.
    A restarted/reconnected provider must identify any loss explicitly.
    """
    def __init__(self, path: str, paths: AuthorizedPaths, *, max_bytes=16*1024*1024):
        self.path=paths.resolve(path,write=True)
        if not 1024<=max_bytes<=256*1024*1024: raise ValueError('invalid_session_journal_budget')
        self.max_bytes=max_bytes
        self.lock=threading.RLock()
        effect_checkpoint()
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS provider_sessions(
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, provider TEXT NOT NULL,
                binding TEXT NOT NULL, remote_id TEXT NOT NULL, state TEXT NOT NULL,
                metadata TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 0,
                next_sequence INTEGER NOT NULL DEFAULT 1, retained_bytes INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS provider_events(
                session_id TEXT NOT NULL, sequence INTEGER NOT NULL, time_ns INTEGER NOT NULL,
                channel TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(session_id,sequence));
            CREATE TABLE IF NOT EXISTS provider_intents(
                operation_id TEXT PRIMARY KEY, scope TEXT NOT NULL, digest TEXT NOT NULL,
                state TEXT NOT NULL, result TEXT);
            ''')

    def _db(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        return db

    def reserve_effect(self, operation_id, scope, intent):
        fingerprint=hashlib.sha256(json.dumps(intent,sort_keys=True,allow_nan=False).encode()).hexdigest()
        effect_checkpoint()
        with self.lock,self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM provider_intents WHERE operation_id=?',(operation_id,)).fetchone()
            if old:
                if old['scope']!=scope or old['digest']!=fingerprint:
                    raise ExecutorFailure('provider_intent_conflict')
                if old['state']=='COMPLETE': return json.loads(old['result'])
                raise ExecutorFailure('provider_effect_requires_reconciliation',uncertain=True)
            db.execute('INSERT INTO provider_intents VALUES(?,?,?,?,NULL)',(operation_id,scope,fingerprint,'RESERVED'))
        return None

    def complete_effect(self,operation_id,result):
        effect_checkpoint()
        with self.lock,self._db() as db:
            db.execute('UPDATE provider_intents SET state=?,result=? WHERE operation_id=?',
                ('COMPLETE',json.dumps(result,allow_nan=False),operation_id))

    def create(self,scope,provider,binding,remote_id,metadata,*,state='CREATING',max_sessions=64):
        if not 1<=max_sessions<=64:raise ValueError('invalid_provider_session_budget')
        sid=uuid.uuid4().hex
        effect_checkpoint()
        with self.lock,self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute("SELECT count(*) FROM provider_sessions WHERE scope=? AND provider=? AND binding=? AND state NOT IN ('CLOSED','TERMINATED','DELETED')",
                (scope,provider,binding)).fetchone()[0]
            if count>=max_sessions:raise ExecutorFailure('provider_active_session_limit')
            db.execute('INSERT INTO provider_sessions(id,scope,provider,binding,remote_id,state,metadata) VALUES(?,?,?,?,?,?,?)',
                (sid,scope,provider,binding,remote_id,state,json.dumps(metadata,allow_nan=False)))
        return self.get(sid,scope,provider,binding)

    def get(self,sid,scope,provider,binding):
        with self.lock,self._db() as db:
            row=db.execute('SELECT * FROM provider_sessions WHERE id=?',(sid,)).fetchone()
        if row is None or row['scope']!=scope or row['provider']!=provider or row['binding']!=binding:
            raise ExecutorFailure('provider_session_scope_mismatch')
        result=dict(row); result['metadata']=json.loads(result['metadata'])
        return result

    def list(self,scope,provider,binding,*,limit=64):
        """Recover owned local IDs only; cached state is not live provider state."""
        if type(limit) is not int or not 1<=limit<=100:raise ExecutorFailure('invalid_session_list_limit')
        effect_checkpoint()
        with self.lock,self._db() as db:
            rows=db.execute('SELECT id,remote_id,state,epoch FROM provider_sessions WHERE scope=? AND provider=? AND binding=? ORDER BY rowid DESC LIMIT ?',
                (scope,provider,binding,limit+1)).fetchall()
        return {'sessions':[dict(r) for r in rows[:limit]],'more':len(rows)>limit,'live_status_asserted':False}

    def update(self,row,*,state=None,remote_id=None,metadata=None,new_epoch=False):
        effect_checkpoint()
        with self.lock,self._db() as db:
            db.execute('UPDATE provider_sessions SET state=?,remote_id=?,metadata=?,epoch=epoch+? WHERE id=? AND scope=?',
                (state or row['state'],remote_id or row['remote_id'],
                 json.dumps(metadata if metadata is not None else row['metadata']),int(new_epoch),row['id'],row['scope']))
        if state is not None:row['state']=state
        if remote_id is not None:row['remote_id']=remote_id
        if metadata is not None:row['metadata']=metadata
        if new_epoch:row['epoch']+=1

    def append(self,row,channel,data:bytes):
        if type(data) is not bytes or len(data)>self.max_bytes:
            raise ExecutorFailure('provider_event_byte_limit')
        effect_checkpoint()
        with self.lock,self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT next_sequence,retained_bytes FROM provider_sessions WHERE id=?',(row['id'],)).fetchone()
            seq=current['next_sequence']; retained=current['retained_bytes']+len(data)
            db.execute('INSERT INTO provider_events VALUES(?,?,?,?,?)',(row['id'],seq,time.time_ns(),channel,data))
            # Sequence is monotonic even when old bytes are evicted. A client
            # must notice the returned first_sequence/gap, not assume replay.
            while retained>self.max_bytes:
                old=db.execute('SELECT sequence,length(data) size FROM provider_events WHERE session_id=? ORDER BY sequence LIMIT 1',
                    (row['id'],)).fetchone()
                db.execute('DELETE FROM provider_events WHERE session_id=? AND sequence=?',(row['id'],old['sequence']))
                retained-=old['size']
            # Empty/control records must not create an unbounded row journal.
            count=db.execute('SELECT count(*) FROM provider_events WHERE session_id=?',(row['id'],)).fetchone()[0]
            while count>10000:
                old=db.execute('SELECT sequence,length(data) size FROM provider_events WHERE session_id=? ORDER BY sequence LIMIT 1',
                    (row['id'],)).fetchone()
                db.execute('DELETE FROM provider_events WHERE session_id=? AND sequence=?',(row['id'],old['sequence']))
                retained-=old['size'];count-=1
            db.execute('UPDATE provider_sessions SET next_sequence=?,retained_bytes=? WHERE id=?',(seq+1,retained,row['id']))
        return seq

    def read(self,row,*,after=0,max_events=100,max_bytes=65536):
        if type(after) is not int or after<0 or not 1<=max_events<=1000 or not 1<=max_bytes<=1024*1024:
            raise ExecutorFailure('invalid_provider_cursor')
        with self.lock,self._db() as db:
            current=db.execute('SELECT epoch,next_sequence FROM provider_sessions WHERE id=?',(row['id'],)).fetchone()
            if after>=current['next_sequence']:raise ExecutorFailure('provider_cursor_ahead_of_journal')
            first=db.execute('SELECT min(sequence) seq FROM provider_events WHERE session_id=?',(row['id'],)).fetchone()['seq']
            events=db.execute('SELECT * FROM provider_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?',
                (row['id'],after,max_events)).fetchall()
        result=[]; used=0
        for event in events:
            if used+len(event['data'])>max_bytes: break
            used+=len(event['data'])
            result.append({'sequence':event['sequence'],'time_ns':event['time_ns'],'channel':event['channel'],
                'data_base64':base64.b64encode(event['data']).decode(),
                'sha256':hashlib.sha256(event['data']).hexdigest()})
        return {'session_id':row['id'],'epoch':current['epoch'],'events':result,'bytes':used,
            'cursor':result[-1]['sequence'] if result else after,'first_sequence':first,
            'gap':first is not None and after<first-1,'more':len(result)<len(events) or len(events)==max_events}

    def export(self,row,paths,output):
        with self.lock,self._db() as db:
            events=db.execute('SELECT * FROM provider_events WHERE session_id=? ORDER BY sequence',(row['id'],)).fetchall()
        # Export is bounded by the journal's retention budget, not an unlimited log.
        body=json.dumps({'session_id':row['id'],'provider':row['provider'],'remote_id':row['remote_id'],
            'scope_sha256':row['scope'],'epoch':row['epoch'],'state':row['state'],
            'metadata':row['metadata'],'completeness_asserted':False,
            'events':[{'sequence':e['sequence'],'time_ns':e['time_ns'],'channel':e['channel'],
                'data_base64':base64.b64encode(e['data']).decode(),
                'sha256':hashlib.sha256(e['data']).hexdigest()} for e in events]},ensure_ascii=False).encode()
        return atomic_output(paths,output,lambda p:p.write_bytes(body),
            lambda p:json.loads(p.read_text(encoding='utf-8')),max_output_bytes=min(512*1024*1024,self.max_bytes*2+1024*1024))


class SessionExecutor(GuardedExecutor):
    """Current OperationRequest gate plus precise, conservative provider errors."""
    def __init__(self,**kwargs):
        super().__init__(**kwargs); self._failures={}; self._failure_lock=threading.Lock()

    def _execute(self,binding,arguments):
        try:return self._run(binding,arguments)
        except ExecutorFailure as exc:
            with self._failure_lock:self._failures[arguments['_operation_id']]=exc
            raise

    async def start(self,request):
        result=await super().start(request)
        if result.error in {'backend_error','physical_effect_error_requires_reconciliation'}:
            with self._failure_lock:failure=self._failures.get(request.operation_id)
            if failure is not None:
                async with self._lock:
                    record=self._records[request.operation_id]
                    # Never downgrade central uncertainty or cancellation.
                    if failure.uncertain:record.state='uncertain'
                    record.error=failure.code
                    record.evidence={} if record.cancel_requested else dict(failure.evidence)
                    return self._snapshot(request.operation_id,record)
        return result


def declare_session_machine(executor,bindings,description):
    from sentra_runtime.contracts import Capability,Machine
    from .discovery import MachineDeclaration
    return MachineDeclaration(Machine(executor.machine_id,executor.kind,executor.owner_principal_id,
        tuple(Capability(b.capability_id,description,'high') for b in bindings)),executor)
