"""Owner terminal-input receipts over the existing protected host request journal.

This wraps the existing authenticated owner input path. Agent/mobile input keeps
its central machine admission. A delivered receipt never verifies task completion.
"""
import hashlib
import json
import re
import time
import uuid
from contextlib import closing
from .shell_requests import ShellHostRequests


def journal(canvas):
    with canvas._lock:
        requests=getattr(canvas,'_terminal_input_requests',None)
        if requests is None:
            requests=ShellHostRequests(canvas._shell_service(),canvas._runtime().owner)
            with closing(requests.control.store.connect('shell')) as db,db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS canvas_terminal_input_pending('
                    'owner TEXT NOT NULL,project_id TEXT NOT NULL,request_key TEXT NOT NULL,terminal_id TEXT NOT NULL,'
                    'fingerprint TEXT NOT NULL,input_target TEXT NOT NULL,created_at INTEGER NOT NULL,'
                    'PRIMARY KEY(owner,project_id,request_key))')
                db.execute('CREATE TABLE IF NOT EXISTS canvas_terminal_input_revisions('
                    'owner TEXT NOT NULL,project_id TEXT NOT NULL,terminal_id TEXT NOT NULL,revision INTEGER NOT NULL,'
                    'PRIMARY KEY(owner,project_id,terminal_id))')
                for event, prefix in (('INSERT','NEW'),('DELETE','OLD')):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS canvas_terminal_pending_{event}
                        AFTER {event} ON canvas_terminal_input_pending BEGIN
                        INSERT INTO canvas_terminal_input_revisions VALUES({prefix}.owner,{prefix}.project_id,{prefix}.terminal_id,1)
                        ON CONFLICT(owner,project_id,terminal_id) DO UPDATE SET revision=revision+1; END''')
                db.execute('INSERT OR IGNORE INTO canvas_terminal_input_revisions '
                    'SELECT owner,project_id,terminal_id,1 FROM canvas_terminal_input_pending GROUP BY owner,project_id,terminal_id')
            canvas._terminal_input_requests=requests
        if not getattr(canvas,'_terminal_input_epoch',None):canvas._terminal_input_epoch=uuid.uuid4().hex
        return requests


def input_identity(canvas,ws,terminal,session):
    scope=hashlib.sha256(json.dumps([str(canvas.state_dir.resolve()),canvas.store.principal,ws,terminal],separators=(',',':')).encode()).hexdigest()
    requests=journal(canvas)
    with closing(requests.control.store.connect('shell')) as db:
        db.execute('BEGIN')
        rows=db.execute('SELECT request_key,fingerprint,input_target,created_at FROM canvas_terminal_input_pending '
            'WHERE owner=? AND project_id=? AND terminal_id=? ORDER BY created_at,request_key LIMIT 17',
            (requests.owner,ws,terminal)).fetchall()
        revision=_pending_revision(db,requests.owner,ws,terminal)
    return {'input_protocol_version':1,'input_scope':scope,
        'input_target':session.input_instance_id if session is not None else None,
        'input_pending':[dict(row) for row in rows[:16]],'input_pending_overflow':len(rows)>16,
        'input_pending_protocol_version':2,'input_pending_revision':revision,'input_pending_epoch':canvas._terminal_input_epoch}


def _pending_revision(db,owner,ws,terminal):
    row=db.execute('SELECT revision FROM canvas_terminal_input_revisions WHERE owner=? AND project_id=? AND terminal_id=?',
        (owner,ws,terminal)).fetchone()
    return row['revision'] if row else 0


def send(canvas,ws,terminal,data,key,target):
    if not isinstance(target,str) or not re.fullmatch(r'[0-9a-f]{32}',target):raise ValueError('exact terminal input target required')
    if len(data.encode('utf-8'))>4096:raise ValueError('terminal input packet exceeds 4096 bytes')
    requests=journal(canvas)
    payload={'terminal_id':terminal,'data':data,'input_target':target}
    fingerprint=hashlib.sha256(json.dumps(['terminal_input',payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def deliver():
        requests.note_before_admission(ws,key)
        canvas.store.resource('terminals',terminal,ws)
        session=canvas._sessions.get(terminal)
        if session is None or session.input_instance_id!=target:
            raise PermissionError('terminal input target changed; observe the session before new input')
        if session.pty is None:raise RuntimeError('terminal no longer attached')
        reference = None
        from .pty_client import DaemonPTY
        if isinstance(session.pty,DaemonPTY) and session.pty.client.capabilities.get('correlated_input_receipts') == 1:
            physical_key = 'host-input:' + hashlib.sha256(json.dumps([requests.owner,ws,terminal,key,target],separators=(',',':')).encode()).hexdigest()
            reference = session.pty.input_reference(physical_key,data.encode('utf-8'))
            requests.bind_terminal_input_effect(ws,key,fingerprint,reference)
        with closing(requests.control.store.connect('shell')) as db,db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute('SELECT COUNT(*) FROM canvas_terminal_input_pending WHERE owner=?',(requests.owner,)).fetchone()[0]
            if count>=1024:raise ValueError('pending terminal receipt budget reached')
            per_terminal=db.execute('SELECT COUNT(*) FROM canvas_terminal_input_pending WHERE owner=? AND project_id=? AND terminal_id=?',
                (requests.owner,ws,terminal)).fetchone()[0]
            if per_terminal>=16:raise ValueError('pending terminal receipt session budget reached')
            db.execute('INSERT OR IGNORE INTO canvas_terminal_input_pending VALUES(?,?,?,?,?,?,?)',
                (requests.owner,ws,key,terminal,fingerprint,target,int(time.time()*1000)))
        # Nothing after this mark claims safe replay if the transport disappears.
        requests.note_effect_possible(ws,key)
        if reference:session.pty.write_correlated(data.encode('utf-8'),reference)
        else:session.pty.write(data.encode('utf-8'))
        return {'ok':True,'status':'delivered','delivery_stage':'delivered_to_process',
            'request_key':key,'terminal_id':terminal,'input_target':target,
            'bytes':len(data.encode('utf-8')),'task_completion_verified':False,'automatic_retry':False}
    return requests.invoke(ws,'terminal_input',payload,key,deliver)


def inspect(canvas,ws,terminal,key,fingerprint):
    canvas.store.resource('terminals',terminal,ws)
    requests=journal(canvas)
    original=requests.intent(ws,key,fingerprint)
    if original is None:return {'found':False,'resolved':False,'request_key':key,'automatic_retry':False,'may_resend':False}
    if original.get('action')!='terminal_input' or original.get('payload',{}).get('terminal_id')!=terminal:
        raise PermissionError('input receipt belongs to another terminal')
    if original.get('payload_retired'):
        value=requests.inspect_retired_input(ws,key,fingerprint,terminal)
    else:
        value=requests.inspect(ws,'terminal_input',original['payload'],key)
        reference=original.get('terminal_effect')
        client=getattr(canvas,'_pty_client',None)
        if not value.get('resolved') and reference and client is not None and client.capabilities.get('correlated_input_receipts') == 1:
            # Observation only: no connect-or-start and no write fallback. A
            # missing/uncertain daemon receipt cannot license replay.
            physical=client.call('input_effect',reference)
            if physical.get('input_receipt_protocol_version') == 1 and physical.get('found') and physical.get('resolved'):
                requests.confirm_terminal_input_observation(ws,key,fingerprint,reference,physical.get('receipt'))
                value=requests.inspect(ws,'terminal_input',original['payload'],key)
    return {**value,'terminal_id':terminal,'input_target':original['payload']['input_target'],'task_completion_verified':False}


def acknowledge(canvas,ws,terminal,key,fingerprint):
    value=inspect(canvas,ws,terminal,key,fingerprint)
    if not value.get('resolved'):return {**value,'acknowledged':False}
    requests=journal(canvas)
    with closing(requests.control.store.connect('shell')) as db,db:
        db.execute('BEGIN IMMEDIATE')
        if not requests.acknowledge_terminal_input(db,ws,key,fingerprint):
            return {**value,'acknowledged':False}
        db.execute('DELETE FROM canvas_terminal_input_pending WHERE owner=? AND project_id=? AND terminal_id=? AND request_key=? AND fingerprint=?',
            (requests.owner,ws,terminal,key,fingerprint))
        revision=_pending_revision(db,requests.owner,ws,terminal)
    return {'acknowledged':True,'request_key':key,'terminal_id':terminal,'input_target':value['input_target'],
        'automatic_retry':False,'task_completion_verified':False,'input_pending_revision':revision,
        'input_pending_epoch':canvas._terminal_input_epoch}
