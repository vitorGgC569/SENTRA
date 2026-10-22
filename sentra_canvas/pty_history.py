"""Bounded OS-protected PTY history; persistence never owns process execution.

The reader thread only enqueues bounded output. Encryption and SQLite work run
on a fair background queue. A missing suffix is explicit, never a claim that a
process or its uncommitted output survived a daemon/Windows restart.
"""
from __future__ import annotations
from collections import OrderedDict, deque
import math
import json
from pathlib import Path
import sqlite3
import threading
import time

DISK_LIMIT = 16 * 1024 * 1024
QUEUE_LIMIT = 4 * 1024 * 1024
SESSION_QUEUE_LIMIT = 512 * 1024
CHUNK_OVERHEAD = 256
OUTPUT_CHARS = 16000


class PtyHistory:
    def __init__(self, state_dir, *, disk_limit=DISK_LIMIT, queue_limit=QUEUE_LIMIT,
                 session_queue_limit=SESSION_QUEUE_LIMIT, protect=None, unprotect=None,
                 snapshots_enabled=True):
        from sentra_remote.secrets import protect_secret, unprotect_secret
        if any(type(n) is not int or n <= CHUNK_OVERHEAD for n in
               (disk_limit, queue_limit, session_queue_limit)):
            raise ValueError('positive bounded history limits required')
        self.protect = protect or protect_secret
        self.unprotect = unprotect or unprotect_secret
        self.disk_limit, self.queue_limit = disk_limit, queue_limit
        self.session_limit = min(session_queue_limit, queue_limit)
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        self.path = Path(state_dir) / 'pty-history.sqlite3'
        self.db_lock = threading.RLock()
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.sizes, self.heads, self.durable, self.gaps = {}, {}, {}, {}
        self.geometries = {}
        self.sequences={};self.mirrors=set();self.snapshot_dirty=set();self.snapshot_errors={}
        self.snapshot_invalid=set();self.snapshot_force=False;self.snapshot_at={}
        self.restore_lock=threading.RLock()
        self.retire_mirrors=set();self.retired_mirrors=set()
        self.dirty_heads = {}
        self.queued_bytes = self.dropped_chars = 0
        self.error = None
        self.inflight = False
        self.inflight_bytes = 0
        self.inflight_terminal = None
        self.inflight_start = 0
        self.stopping = False
        self.closed = False
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        try:
            with self.db:
                self.db.execute('PRAGMA journal_mode=DELETE')
                self.db.execute('PRAGMA synchronous=FULL')
                self.db.execute('PRAGMA secure_delete=ON')
                size = self.db.execute('PRAGMA page_size').fetchone()[0]
                self.db.execute('PRAGMA max_page_count=' + str(math.ceil((disk_limit + 8 * 1024 * 1024) / size)))
                self.db.execute('BEGIN IMMEDIATE')
                version = self.db.execute('PRAGMA user_version').fetchone()[0]
                if version > 2:
                    raise RuntimeError('PTY history schema is newer than this application')
                self.db.execute('''CREATE TABLE IF NOT EXISTS sessions(
                    terminal_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,
                    origin_runtime_id TEXT NOT NULL,pid INTEGER,exit_code INTEGER,
                    state TEXT NOT NULL,head INTEGER NOT NULL DEFAULT 0,
                    updated REAL NOT NULL,tail_uncertain INTEGER NOT NULL DEFAULT 1)''')
                self.db.execute('''CREATE TABLE IF NOT EXISTS chunks(
                    terminal_id TEXT NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,
                    protected TEXT NOT NULL,bytes INTEGER NOT NULL,created REAL NOT NULL,
                    PRIMARY KEY(terminal_id,start))''')
                self.db.execute('CREATE INDEX IF NOT EXISTS history_age ON chunks(created)')
                columns={row[1] for row in self.db.execute('PRAGMA table_info(sessions)')}
                for name,default in (('sequence',0),('geometry_sequence',0),('cols',100),('rows',28),('snapshot_supported',0)):
                    if name not in columns:self.db.execute(f'ALTER TABLE sessions ADD COLUMN {name} INTEGER NOT NULL DEFAULT {default}')
                if 'sequence' not in {row[1] for row in self.db.execute('PRAGMA table_info(chunks)')}:
                    self.db.execute('ALTER TABLE chunks ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0')
                self.db.execute('''CREATE TABLE IF NOT EXISTS checkpoints(terminal_id TEXT PRIMARY KEY,
                    sequence INTEGER,cursor INTEGER,protected TEXT,bytes INTEGER,updated REAL)''')
                self.db.execute('''CREATE TABLE IF NOT EXISTS geometry(terminal_id TEXT,sequence INTEGER,
                    cursor INTEGER,cols INTEGER,rows INTEGER,PRIMARY KEY(terminal_id,sequence))''')
                # Account for row/index overhead as well as ciphertext. Tiny
                # ConPTY frames otherwise exhaust SQLite pages below the quota.
                # Transactional triggers keep this O(1), including rollback and
                # replacement, instead of summing the whole transcript per byte.
                self.db.execute('CREATE TABLE IF NOT EXISTS history_budget(id INTEGER PRIMARY KEY CHECK(id=1),used INTEGER NOT NULL)')
                self.db.execute('''INSERT OR REPLACE INTO history_budget VALUES(1,
                    (SELECT COALESCE(SUM(bytes+256),0) FROM chunks)+
                    (SELECT COALESCE(SUM(bytes+256),0) FROM checkpoints))''')
                for table in ('chunks', 'checkpoints'):
                    for event, delta in (('INSERT', 'NEW.bytes+256'),
                                         ('DELETE', '-OLD.bytes-256'),
                                         ('UPDATE', 'NEW.bytes-OLD.bytes')):
                        self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS budget_{table}_{event}
                            AFTER {event} ON {table} BEGIN
                            UPDATE history_budget SET used=used+({delta}) WHERE id=1; END''')
                # Do not reattach an OS PID or recreate a process after host loss.
                self.db.execute("UPDATE sessions SET state='history_restored',tail_uncertain=1 WHERE state='live'")
                self.db.execute('PRAGMA user_version=2')
                self.checkpoint_known={row[0] for row in self.db.execute('SELECT terminal_id FROM checkpoints')}
                self._trim()
                self.geometries = {row['terminal_id']: {key: row[key] for key in ('cols','rows','geometry_sequence')}
                    for row in self.db.execute('SELECT terminal_id,cols,rows,geometry_sequence FROM sessions')}
        except BaseException:
            self.db.close()
            raise
        from .terminal_snapshots import TerminalSnapshots
        self.snapshots=TerminalSnapshots() if snapshots_enabled else None
        self.worker = threading.Thread(target=self._worker, name='sentra-pty-history', daemon=True)
        self.worker.start()

    def register(self, workspace_id, terminal_id, runtime_id):
        with self.db_lock, self.db:
            if self.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] >= 512:
                raise ValueError('PTY history session quota exhausted')
            self.db.execute('INSERT INTO sessions(terminal_id,workspace_id,origin_runtime_id,state,updated,snapshot_supported) VALUES(?,?,?,?,?,?)',
                            (terminal_id, workspace_id, runtime_id, 'reserved', time.time(),1))
        with self.condition:
            self.heads[terminal_id] = self.durable[terminal_id] = 0
            self.geometries[terminal_id] = {'cols':100,'rows':28,'geometry_sequence':0}
            self.sequences[terminal_id]=0
            if self.snapshots and self.snapshots.available:
                if self.queued_bytes+self.inflight_bytes+CHUNK_OVERHEAD<=self.queue_limit:
                    self.pending[terminal_id]=deque([(0,'',CHUNK_OVERHEAD,0,'init',None)])
                    self.sizes[terminal_id]=CHUNK_OVERHEAD;self.queued_bytes+=CHUNK_OVERHEAD
                    self.condition.notify_all()
                else:self.snapshot_invalid.add(terminal_id)

    def bind(self, terminal_id, pid):
        with self.db_lock, self.db:
            self.db.execute("UPDATE sessions SET pid=?,state='live',updated=? WHERE terminal_id=?", (pid, time.time(), terminal_id))

    def ended(self, terminal_id, code, *, drained=False):
        with self.db_lock, self.db:
            self.db.execute("UPDATE sessions SET state='ended',exit_code=?,updated=? WHERE terminal_id=?",
                            (code, time.time(), terminal_id))
        if drained:
            with self.condition:
                self.retire_mirrors.add(terminal_id)
                if terminal_id in self.mirrors:self.snapshot_dirty.add(terminal_id)
                self.snapshot_force=True;self.condition.notify_all()

    def _gap(self, terminal_id, start, end):
        if end <= start:
            return
        self.dropped_chars += end - start
        intervals = sorted([*self.gaps.get(terminal_id, []), (start, end)])
        merged = []
        for left, right in intervals:
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        # Conservatively merge old gaps rather than grow metadata indefinitely.
        if len(merged) > 64:
            merged = [(merged[0][0], merged[-64][1]), *merged[-63:]]
        self.gaps[terminal_id] = merged

    def _evict(self, terminal_id):
        queue = self.pending[terminal_id]
        start, text, size, *_ = queue.popleft()
        self.sizes[terminal_id] -= size
        self.queued_bytes -= size
        self._gap(terminal_id, start, start + len(text))
        self.snapshot_invalid.add(terminal_id)
        if not queue:
            del self.pending[terminal_id]

    def append(self, terminal_id, start, text):
        """Nonblocking with respect to disk, crypto and consumers."""
        if not text:
            return
        raw = text.encode('utf-8')
        with self.condition:
            if self.stopping or terminal_id not in self.heads:
                self.error = self.error or 'history_not_available'
                return
            original_end = start + len(text)
            self.sequences[terminal_id]+=1
            sequence=self.sequences[terminal_id]
            self.heads[terminal_id] = max(self.heads[terminal_id], original_end)
            self.dirty_heads[terminal_id] = self.heads[terminal_id]
            inflight = self.inflight_bytes if self.inflight_terminal == terminal_id else 0
            allowance = max(0, self.session_limit - inflight - CHUNK_OVERHEAD)
            if len(raw) > allowance:
                tail = raw[-allowance:].decode('utf-8', 'ignore') if allowance else ''
                removed = len(text) - len(tail)
                self._gap(terminal_id, start, start + removed)
                self.snapshot_invalid.add(terminal_id)
                start += removed
                text = tail
            if not text:
                self.condition.notify_all()
                return
            size = len(text.encode('utf-8')) + CHUNK_OVERHEAD
            while terminal_id in self.pending and self.sizes.get(terminal_id, 0) + inflight + size > self.session_limit:
                self._evict(terminal_id)
            while self.pending and self.queued_bytes + self.inflight_bytes + size > self.queue_limit:
                # An output flood evicts from the largest backlog, preserving
                # small quiet sessions instead of punishing their consumers.
                largest = max(self.pending, key=lambda key: self.sizes[key])
                self._evict(largest)
            available = self.queue_limit - self.inflight_bytes - CHUNK_OVERHEAD
            if len(text.encode('utf-8')) > available:
                tail = text.encode('utf-8')[-max(0, available):].decode('utf-8', 'ignore') if available > 0 else ''
                removed = len(text) - len(tail)
                self._gap(terminal_id, start, start + removed)
                self.snapshot_invalid.add(terminal_id)
                start += removed
                text = tail
                size = len(text.encode('utf-8')) + CHUNK_OVERHEAD
                if not text:
                    self.condition.notify_all()
                    return
            self.pending.setdefault(terminal_id, deque()).append((start, text, size, sequence, 'output', None))
            self.sizes[terminal_id] = self.sizes.get(terminal_id, 0) + size
            self.queued_bytes += size
            self.condition.notify_all()

    def resize(self,terminal_id,cols,rows):
        with self.condition:
            if terminal_id not in self.heads or self.stopping:return
            self.sequences[terminal_id]+=1
            size=CHUNK_OVERHEAD
            inflight=self.inflight_bytes if self.inflight_terminal==terminal_id else 0
            while terminal_id in self.pending and self.sizes.get(terminal_id,0)+inflight+size>self.session_limit:
                self._evict(terminal_id)
            while self.pending and self.queued_bytes+self.inflight_bytes+size>self.queue_limit:
                self._evict(max(self.pending,key=lambda key:self.sizes[key]))
            if (self.queued_bytes+self.inflight_bytes+size>self.queue_limit or
                    self.sizes.get(terminal_id,0)+inflight+size>self.session_limit):
                self.snapshot_invalid.add(terminal_id);return
            event=(self.heads[terminal_id],'',size,self.sequences[terminal_id],'resize',{'cols':cols,'rows':rows})
            self.pending.setdefault(terminal_id,deque()).append(event)
            self.sizes[terminal_id]=self.sizes.get(terminal_id,0)+size;self.queued_bytes+=size
            self.condition.notify_all()

    def invalidate_checkpoint(self,terminal_id):
        with self.condition:self.snapshot_invalid.add(terminal_id)
        with self.db_lock,self.db:
            self.db.execute('UPDATE sessions SET snapshot_supported=0 WHERE terminal_id=?',(terminal_id,))

    def _snapshot_apply_batch(self,ident,batch):
        if not self.snapshots or not self.snapshots.available:return
        if ident in self.retired_mirrors:self.snapshot_invalid.add(ident)
        if ident in self.snapshot_invalid or ident in self.snapshot_errors:return
        try:
            if ident not in self.mirrors:
                self.snapshots.call('create',ident,cols=100,rows=28)
                self.mirrors.add(ident)
            events=[]
            for start,text,size,sequence,kind,geometry in batch:
                if kind=='init':continue
                event={'kind':kind,'sequence':sequence,'start':start}
                event.update({'text':text} if kind=='output' else geometry)
                events.append(event)
            if events:self.snapshots.call('batch',ident,events=events)
            with self.condition:self.snapshot_dirty.add(ident)
        except Exception as exc:self.snapshot_errors[ident]=type(exc).__name__

    def _trim(self):
        used=self.db.execute('SELECT used FROM history_budget WHERE id=1').fetchone()[0]
        pruned=[]
        # A little headroom avoids repeated single-row eviction under a flood.
        target=int(self.disk_limit*.9) if used>self.disk_limit else self.disk_limit
        while used>target:
            # Bound scans per batch. Without this, migrating a large legacy
            # transcript with no usable checkpoints scans it once per row.
            rows=[]
            if self.db.execute('SELECT 1 FROM checkpoints LIMIT 1').fetchone():
                rows=self.db.execute('''SELECT c.terminal_id,c.start,c.bytes,c.end FROM chunks c JOIN checkpoints p
                    ON c.terminal_id=p.terminal_id WHERE c.sequence<=p.sequence
                    ORDER BY c.created,c.terminal_id,c.start LIMIT 256''').fetchall()
            if rows:
                for row in rows:
                    self.db.execute('DELETE FROM chunks WHERE terminal_id=? AND start=?',(row[0],row[1]))
                    used-=row[2]+CHUNK_OVERHEAD;pruned.append((row[0],row[1],row[3]))
                    if used<=target:break
                continue
            row=self.db.execute('''SELECT p.terminal_id,p.bytes FROM checkpoints p JOIN sessions s ON s.terminal_id=p.terminal_id
                WHERE p.sequence<s.sequence ORDER BY p.updated LIMIT 1''').fetchone()
            if not row:
                chunks=self.db.execute('SELECT terminal_id,start,bytes,end FROM chunks ORDER BY created,terminal_id,start LIMIT 256').fetchall()
                if chunks:
                    for chunk in chunks:
                        self.db.execute('DELETE FROM chunks WHERE terminal_id=? AND start=?',(chunk[0],chunk[1]))
                        used-=chunk[2]+CHUNK_OVERHEAD;pruned.append((chunk[0],chunk[1],chunk[3]))
                        if used<=target:break
                    continue
                row=self.db.execute('SELECT terminal_id,bytes FROM checkpoints ORDER BY updated LIMIT 1').fetchone()
            if not row:break
            self.db.execute('DELETE FROM checkpoints WHERE terminal_id=?',(row[0],))
            self.checkpoint_known.discard(row[0]);used-=row[1]+CHUNK_OVERHEAD
        return pruned

    def _save_checkpoint(self,ident,frame):
        raw=json.dumps(frame,ensure_ascii=False,separators=(',',':'))
        protected=self.protect(raw)
        if not isinstance(protected,str) or not protected.startswith(('dpapi:','keyring:')):
            raise RuntimeError('OS protected checkpoint required')
        if len(protected.encode('utf-8'))>self.disk_limit:
            raise RuntimeError('Checkpoint exceeds history quota; transcript retained')
        with self.db_lock,self.db:
            self.db.execute('''INSERT INTO checkpoints VALUES(?,?,?,?,?,?)
                ON CONFLICT(terminal_id) DO UPDATE SET sequence=excluded.sequence,cursor=excluded.cursor,
                protected=excluded.protected,bytes=excluded.bytes,updated=excluded.updated
                WHERE checkpoints.sequence<=excluded.sequence''',
                (ident,frame['sequence'],frame['cursor'],protected,len(protected.encode('utf-8')),time.time()))
            self.db.execute('DELETE FROM geometry WHERE terminal_id=? AND sequence<=?',(ident,frame['sequence']))
            self.checkpoint_known.add(ident)
            pruned=self._trim()
        with self.condition:
            for terminal,left,right in pruned:self._gap(terminal,left,right)

    def _capture(self,ident):
        self.snapshot_at[ident]=time.monotonic()
        try:
            if ident in self.snapshot_invalid or ident in self.snapshot_errors:return
            if not self.snapshots or not self.snapshots.available:return
            self._save_checkpoint(ident,self.snapshots.call('capture',ident))
        except Exception as exc:self.snapshot_errors[ident]=type(exc).__name__
        finally:
            if ident in self.retire_mirrors and ident not in self.pending and ident in self.mirrors:
                if self.snapshots and self.snapshots.available:
                    try:self.snapshots.call('dispose',ident)
                    except Exception as exc:self.snapshot_errors[ident]=type(exc).__name__
                self.mirrors.discard(ident);self.retired_mirrors.add(ident)

    def _worker(self):
        try:
            while True:
                with self.condition:
                    def due():
                        return [key for key in self.snapshot_dirty if time.monotonic()-self.snapshot_at.get(key,0)>=1
                            or ((self.snapshot_force or self.stopping) and key not in self.pending)]
                    while not self.pending and not self.dirty_heads and not due() and not self.stopping:
                        self.condition.wait(.2 if self.snapshot_dirty else None)
                    capture=next(iter(due()),None)
                    if not self.pending and not self.dirty_heads and not self.snapshot_dirty and self.stopping:return
                    ident=None;batch=[];size=0;start=0;chars=0
                    if capture is not None:self.snapshot_dirty.discard(capture)
                    elif self.pending:
                        ident,queue=self.pending.popitem(last=False)
                        # Fair, bounded transactions and mirror RPCs. ConPTY
                        # emits tiny fragments; a disk fsync/pipe roundtrip for
                        # each fragment cannot keep up with ordinary TUI output.
                        while queue and len(batch)<64:
                            event=queue[0]
                            if batch and chars+len(event[1])>OUTPUT_CHARS:break
                            batch.append(queue.popleft());size+=event[2];chars+=len(event[1])
                        start=batch[0][0]
                        if queue:self.pending[ident]=queue
                        self.sizes[ident]-=size;self.queued_bytes-=size
                    heads={}
                    if capture is None:heads,self.dirty_heads=self.dirty_heads,{}
                    self.inflight=True;self.inflight_bytes=size;self.inflight_terminal=ident;self.inflight_start=start
                try:
                    if capture is not None:
                        self._capture(capture)
                    else:
                        protected_batch=[]
                        geometry_updates={}
                        for event in batch:
                            text=event[1];protected=self.protect(text) if text else None
                            if text and (not isinstance(protected,str) or not protected.startswith(('dpapi:','keyring:'))):
                                raise RuntimeError('OS protected history required')
                            protected_batch.append((event,protected))
                        with self.db_lock,self.db:
                            for (start,text,_,sequence,kind,geometry),protected in protected_batch:
                                if text:self.db.execute('''INSERT INTO chunks(terminal_id,start,end,protected,bytes,created,sequence) VALUES(?,?,?,?,?,?,?)
                                    ON CONFLICT(terminal_id,start) DO UPDATE SET end=excluded.end,protected=excluded.protected,
                                    bytes=excluded.bytes,created=excluded.created,sequence=excluded.sequence''',
                                    (ident,start,start+len(text),protected,len(protected.encode('utf-8')),time.time(),sequence))
                                self.db.execute('UPDATE sessions SET sequence=?,head=MAX(head,?) WHERE terminal_id=?',(sequence,start+len(text),ident))
                                if kind=='resize':
                                    self.db.execute('INSERT INTO geometry VALUES(?,?,?,?,?)',(ident,sequence,start,geometry['cols'],geometry['rows']))
                                    self.db.execute('UPDATE sessions SET cols=?,rows=?,geometry_sequence=? WHERE terminal_id=?',
                                        (geometry['cols'],geometry['rows'],sequence,ident))
                                    self.db.execute('DELETE FROM geometry WHERE terminal_id=? AND sequence NOT IN (SELECT sequence FROM geometry WHERE terminal_id=? ORDER BY sequence DESC LIMIT 128)',(ident,ident))
                                    geometry_updates[ident]={'cols':geometry['cols'],'rows':geometry['rows'],'geometry_sequence':sequence}
                            for terminal_id,head in heads.items():
                                self.db.execute('UPDATE sessions SET head=MAX(head,?),updated=? WHERE terminal_id=?',(head,time.time(),terminal_id))
                            pruned=self._trim()
                        with self.condition:
                            self.geometries.update(geometry_updates)
                            for terminal,left,right in pruned:self._gap(terminal,left,right)
                            for start,text,*_ in batch:
                                if text:self.durable[ident]=max(self.durable.get(ident,0),start+len(text))
                        if ident is not None:self._snapshot_apply_batch(ident,batch)
                except Exception as exc:
                    with self.condition:
                        self.error=type(exc).__name__
                        for start,text,*_ in batch:
                            if text:self._gap(ident,start,start+len(text))
                        if ident is not None:self.snapshot_invalid.add(ident)
                finally:
                    with self.condition:
                        self.inflight=False;self.inflight_bytes=0;self.inflight_terminal=None
                        if not self.pending and not self.snapshot_dirty:self.snapshot_force=False
                        self.condition.notify_all()
        finally:
            if self.snapshots:self.snapshots.close()
            with self.db_lock:self.db.close()
            self.closed=True


    def flush(self, timeout=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            self.snapshot_force=True;self.condition.notify_all()
            while self.pending or self.dirty_heads or self.inflight or self.snapshot_dirty:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return self.error is None

    def status(self, terminal_id=None, start=0, end=0):
        with self.condition:
            durable = self.durable.get(terminal_id, 0)
            lost = any(left < end and right > start for left, right in self.gaps.get(terminal_id, []))
            state = 'failed' if self.error else 'gap' if lost else 'saved' if end <= durable else 'pending'
            return {'persisted': self.error is None and end <= durable and not lost,
                    'persistence_state': state,
                    'persisted_cursor': durable, 'persistence_gap': lost,
                    'persistence_error': self.error, 'queued_bytes': self.queued_bytes,
                    'inflight_bytes': self.inflight_bytes,
                    'buffered_bytes': self.queued_bytes + self.inflight_bytes,
                    'queue_limit': self.queue_limit, 'session_queue_limit': self.session_limit,
                    'disk_limit': self.disk_limit, 'dropped_chars': self.dropped_chars}

    def inventory(self):
        with self.db_lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM sessions ORDER BY updated DESC')]

    def checkpoint_supported(self,terminal_id):
        return terminal_id in self.checkpoint_known or bool(self.snapshots and self.snapshots.available)

    def geometry(self,terminal_id):
        # Live output must not wait on a history fsync/trim. Publish only the
        # geometry from a committed transaction; restored sessions seed this
        # bounded (at most 512 sessions) projection at startup.
        with self.condition:return dict(self.geometries.get(terminal_id,{}))

    def checkpoint(self,workspace_id,terminal_id):
        with self.restore_lock:return self._checkpoint(workspace_id,terminal_id)

    def _checkpoint(self,workspace_id,terminal_id):
        from .terminal_snapshots import SnapshotUnavailable,encode_checkpoint
        with self.db_lock:
            meta=self.db.execute('SELECT * FROM sessions WHERE terminal_id=? AND workspace_id=?',(terminal_id,workspace_id)).fetchone()
            if meta is None:raise PermissionError('PTY checkpoint not in this workspace')
            saved=self.db.execute('SELECT * FROM checkpoints WHERE terminal_id=?',(terminal_id,)).fetchone()
        if not meta['snapshot_supported']:
            return {'available':False,'retryable':False,'reason':'legacy_history_without_ordered_geometry'}
        if terminal_id in self.snapshot_invalid or terminal_id in self.snapshot_errors:
            return {'available':False,'retryable':False,'reason':'checkpoint_coverage_unavailable'}
        frame=json.loads(self.unprotect(saved['protected'])) if saved else None
        if terminal_id in self.heads:
            with self.condition:self.snapshot_force=True;self.condition.notify_all()
            if not frame or frame['sequence']<meta['geometry_sequence']:
                return {'available':False,'retryable':bool(self.snapshots and self.snapshots.available),'reason':'checkpoint_pending'}
        elif not frame or frame['sequence']<meta['sequence']:
            if not self.snapshots or not self.snapshots.available:
                if not frame or frame['sequence']<meta['geometry_sequence']:
                    return {'available':False,'retryable':False,'reason':'snapshot_runtime_unavailable'}
            else:
                # Archived resources have no producer. Rebuild their committed
                # tail in an observation-only mirror, never respawn the PTY.
                try:
                    self.snapshots.call('create',terminal_id,cols=frame['cols'] if frame else 100,
                        rows=frame['rows'] if frame else 28,seed=frame)
                    sequence=frame['sequence'] if frame else 0
                    deadline=time.monotonic()+2
                    while sequence<meta['sequence']:
                        with self.db_lock:
                            row=self.db.execute('''SELECT sequence,start AS cursor,protected,NULL AS cols,NULL AS rows
                                FROM chunks WHERE terminal_id=? AND sequence>? AND sequence<=?
                                UNION ALL SELECT sequence,cursor,NULL AS protected,cols,rows FROM geometry
                                WHERE terminal_id=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT 1''',
                                (terminal_id,sequence,meta['sequence'],terminal_id,sequence,meta['sequence'])).fetchone()
                        if row is None or row['sequence']!=sequence+1:raise SnapshotUnavailable('checkpoint_event_gap')
                        event={'sequence':row['sequence'],'start':row['cursor']}
                        if row['protected'] is None:event.update(kind='resize',cols=row['cols'],rows=row['rows'])
                        else:event.update(kind='output',text=self.unprotect(row['protected']))
                        self.snapshots.call('apply',terminal_id,event=event);sequence=row['sequence']
                        if time.monotonic()>deadline:break
                    frame=self.snapshots.call('capture',terminal_id)
                    self._save_checkpoint(terminal_id,frame)
                    if frame['sequence']<meta['geometry_sequence']:
                        return {'available':False,'retryable':True,'reason':'checkpoint_reconstruction_pending'}
                except (SnapshotUnavailable,RuntimeError,ValueError):
                    return {'available':False,'retryable':False,'reason':'checkpoint_event_gap_or_runtime_limit'}
                finally:
                    if self.snapshots.available:
                        try:self.snapshots.call('dispose',terminal_id)
                        except SnapshotUnavailable:pass
        if frame is None:return {'available':False,'retryable':False,'reason':'checkpoint_unavailable'}
        packet=encode_checkpoint(frame)
        return {'available':True,'checkpoint':packet,'geometry_sequence':meta['geometry_sequence'],
                'cols':frame['cols'],'rows':frame['rows'],'tail_uncertain':bool(meta['tail_uncertain']),
                'restoration_creates_process':False}

    def read(self, workspace_id, terminal_id, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise ValueError('invalid history cursor')
        # Pending output is not a gap: advancing past it would lose late commits.
        with self.db_lock:
            row = self.db.execute('SELECT * FROM sessions WHERE terminal_id=? AND workspace_id=?',
                                  (terminal_id, workspace_id)).fetchone()
            if row is None:
                raise PermissionError('PTY history not in this workspace')
            chunks = self.db.execute('SELECT start,end,protected FROM chunks WHERE terminal_id=? AND end>? ORDER BY start LIMIT 8',
                                     (terminal_id, cursor)).fetchall()
            base = self.db.execute('SELECT MIN(start) FROM chunks WHERE terminal_id=?', (terminal_id,)).fetchone()[0]
        # Do not hold the producer condition while waiting for disk. The older
        # committed head bounds this read even if producers advance meanwhile.
        with self.condition:
            pending_starts = [item[0] for item in self.pending.get(terminal_id, [])]
            if self.inflight_terminal == terminal_id:
                pending_starts.append(self.inflight_start)
            head = min([row['head'], *pending_starts])
            chunks = [chunk for chunk in chunks if chunk['start'] < head]
        base = head if base is None else base
        position = min(head, cursor)
        gaps, parts, length = [], [], 0
        for chunk in chunks:
            if chunk['start'] > position:
                gaps.append({'from': position, 'to': chunk['start']})
                position = chunk['start']
            text = self.unprotect(chunk['protected'])
            if len(text) != chunk['end'] - chunk['start']:
                raise RuntimeError('history chunk identity mismatch')
            part = text[max(0, position - chunk['start']):max(0, head - chunk['start'])][:OUTPUT_CHARS - length]
            parts.append(part)
            position += len(part)
            length += len(part)
            if length >= OUTPUT_CHARS:
                break
        if length < OUTPUT_CHARS and position < head and len(chunks) < 8:
            gaps.append({'from': position, 'to': head})
            position = head
        return {'text': ''.join(parts), 'cursor': position, 'head': head, 'base': base,
                'truncated': cursor < base or cursor > head or bool(gaps), 'gaps': gaps,
                'persisted': True, 'process_live': False, 'process_state': 'history_restored',
                'persistence_state': 'gap' if gaps else 'saved', 'persistence_gap': bool(gaps),
                'exit_code': row['exit_code'], 'tail_uncertain': bool(row['tail_uncertain']),
                'origin_runtime_id': row['origin_runtime_id'], 'restoration_creates_process': False}

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        self.worker.join(timeout=8)
        return not self.worker.is_alive()
