"""Durable requests for owner consent; recording a request NEVER grants authority."""
from contextlib import closing
import hashlib
import json
import time

from sentra_core.conversations import _encode, _decode


class CoordinatorApprovalInbox:
    def __init__(self, control, owner):
        self.control, self.owner = control, owner
        with closing(control.store.connect('shell')) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS shell_coordinator_approvals(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, approval_id TEXT NOT NULL,
                space_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                parent_operation_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, capability TEXT NOT NULL,
                intent_sha256 TEXT NOT NULL, protected_summary TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,approval_id))""")

    def record(self, *, project_id, space_id, conversation_id, parent_operation_id,
               work_item_id, agent_id, approval_id, capability, intent):
        if not approval_id.startswith('coordinator-') or not capability.startswith('canvas.coordinator.'):
            raise ValueError('canonical coordinator approval required')
        digest = hashlib.sha256(json.dumps(intent, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        # Only a concise label is exposed; the full intent stays with the live actor.
        summary = {'kind': intent.get('kind', ''), 'name': str(intent.get('name') or '')[:80]}
        identity = (self.owner, project_id, approval_id, space_id, conversation_id,
                    parent_operation_id, work_item_id, agent_id, capability, digest)
        now = time.time()
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""INSERT OR IGNORE INTO shell_coordinator_approvals
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", 
                (*identity, _encode(summary), 'pending', now, now))
            row = db.execute("""SELECT * FROM shell_coordinator_approvals
                WHERE owner=? AND project_id=? AND approval_id=?""",
                (self.owner, project_id, approval_id)).fetchone()
            if row is None or tuple(row[k] for k in (
                    'owner','project_id','approval_id','space_id','conversation_id',
                    'parent_operation_id','work_item_id','agent_id','capability','intent_sha256')) != identity:
                raise PermissionError('coordinator approval identity changed')

    def list(self, project_id, *, limit=30):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('bounded coordinator approval list')
        with closing(self.control.store.connect('shell')) as db:
            rows = db.execute("""SELECT * FROM shell_coordinator_approvals
                WHERE owner=? AND project_id=? AND state='pending'
                ORDER BY created_at DESC LIMIT ?""", (self.owner, project_id, limit)).fetchall()
        result = []
        for row in rows:
            status = 'expired'
            try:
                op = self.control.durable.operation_status(row['parent_operation_id'], self.owner)
                item = self.control.work_item_info(row['work_item_id'], self.owner)
                if op['state'] in {'STARTING','RUNNING','WAITING_EXTERNAL','QUEUED'} and item['state'] in {
                        'PENDING','QUEUED','BLOCKED','RUNNING'} and op['run_id'] == item['run_id']:
                    status = 'active'
            except (ValueError, KeyError, FileNotFoundError):
                pass
            result.append({'approval_id':row['approval_id'], 'project_id':project_id,
                'conversation_id':row['conversation_id'], 'space_id':row['space_id'],
                'work_item_id':row['work_item_id'], 'capability':row['capability'],
                'summary':_decode(row['protected_summary']), 'activity':status,
                'created_at':row['created_at'], 'automatic_execution':False})
        return {'items':result, 'automatic_approval':False}

    def get(self, project_id, approval_id):
        with closing(self.control.store.connect('shell')) as db:
            row = db.execute("""SELECT * FROM shell_coordinator_approvals
                WHERE owner=? AND project_id=? AND approval_id=?""",
                (self.owner, project_id, approval_id)).fetchone()
        if row is None:
            raise FileNotFoundError('approval does not belong to this project')
        return dict(row)

    def mark(self, project_id, approval_id, state):
        if state not in {'approved','rejected'}:
            raise ValueError('invalid coordinator approval decision')
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute("""UPDATE shell_coordinator_approvals SET state=?,updated_at=?
                WHERE owner=? AND project_id=? AND approval_id=? AND state='pending'""",
                (state, time.time(), self.owner, project_id, approval_id))
        return {'approval_id':approval_id, 'state':self.get(project_id, approval_id)['state'],
                'automatic_execution':False}
