"""Owner-bound repair never launches a guest or fakes installation completion."""
import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_canvas import shell_vm_reconcile as repair
from sentra_core.conversations import _encode
from sentra_canvas.store import Denied
from sentra_executors.virtualbox_vm import VirtualBoxClient


def _scenario(tmp_path, monkeypatch):
    dbfile = tmp_path / "reconcile.sqlite3"
    conn = sqlite3.connect(dbfile)
    conn.execute('CREATE TABLE canvas_shell_host_requests('
                 'owner TEXT,project_id TEXT,request_key TEXT,fingerprint TEXT,'
                 'state TEXT,phase TEXT,operation_id TEXT,protected_result TEXT)')
    scope = {'dot_id': 'dot-1', 'space_id': 'space-1',
             'conversation_id': 'conversation-1'}
    key = 'existing-install-observation-key'
    conn.execute('INSERT INTO canvas_shell_host_requests VALUES(?,?,?,?,?,?,?,?)',
        ('canvas:owner', 'project-1', key,
         repair._original_request_fingerprint(scope), 'committed', None, None,
         _encode({'state':'UNCERTAIN', 'operation_id': 'op-1'})))
    conn.commit()
    conn.close()

    class Store:
        def get(self, pid, root):
            assert (pid, root)==('project-1','dot-1')
            return {'root_dot_id': 'dot-1','os_family':'windows', 'agent_id':'agent-1',
                    'work_items':{'conversation-1':'work-1'},
                    'machine_id':'machine-1','vm_id':'vm-1','marker':'SENTRA-DOT:vm-1',
                    'cpus':2,'memory_mb':4096}
        def connect(self, kind):
            assert kind == 'shell'
            db = sqlite3.connect(dbfile)
            db.row_factory = sqlite3.Row
            return db
    durable = SimpleNamespace()
    durable.lock = threading.RLock()
    durable.db = sqlite3.connect(':memory:')
    durable.db.row_factory = sqlite3.Row
    durable.db.execute('CREATE TABLE leases(resource_key TEXT, operation_id TEXT,'
                       'owner TEXT,fencing_token INTEGER,lease_until REAL)')
    durable.db.execute('INSERT INTO leases VALUES(?,?,?,?,?)',
        ('machine:machine-1','op-1','canvas:owner',5,time.time()-500))
    op = {
        'state':'UNCERTAIN','kind':'sentra.machine','run_id':'run-1',
        'resource_key':'machine:machine-1','fencing_token':5,
        'progress_json':json.dumps({
            'effect_started':True,'work_item_id':'work-1',
            'principal_id':'agent-1','machine_id':'machine-1',
            'capability_id':'vm:manage'}),
    }
    updates = []
    durable._operation_row = lambda oid, owner: op if (oid,owner)==('op-1','canvas:owner') else None
    durable.clock = time.time
    def update(*a, **kw):
        assert kw['state']=='FAILED'
        op['state']='FAILED'
        updates.append(kw)
    durable.update_operation = update
    durable.release_lease = lambda *a: {'released':True}
    authority = SimpleNamespace(
        receipt_for_operation=lambda oid,owner: SimpleNamespace(operation_id=oid),
        result_for_receipt=lambda receipt: SimpleNamespace(
            state='UNCERTAIN',error='physical_effect_error_requires_reconciliation'),
        late_return_for_receipt=lambda receipt: {
            'worker_returned':True,'operation_reconciled':False,
            'error_type':'ExecutorFailure','reported_return':None},
        _store_evidence=lambda receipt, result, payload: {
            'state':'FAILED','evidence_artifact_id':'artifact-failed-1',
            'evidence_artifact_sha256':'f'*64,'evidence_sha256':'e'*64},
    )
    monkeypatch.setattr(VirtualBoxClient, 'status',
        lambda self, binding: {'VMState':'poweroff','cpus':2,'memory':4096})
    factory = SimpleNamespace(policy=lambda request: SimpleNamespace(allowed=True))
    control = SimpleNamespace(store=Store(), durable=durable,
        work_item_info=lambda wid,owner: {
            'run_id':'run-1','assignee_agent_id':'agent-1'})
    host = SimpleNamespace(owner='canvas:owner',control=control,
        _factories={'machine-1':factory}, durable_intent_authority=authority)
    service = SimpleNamespace(store=Store(),host=host,
        canvas=SimpleNamespace(_runtime=lambda: SimpleNamespace(
            run=lambda pid: {'run_id':'run-1','state':'RUNNING'})),
        requests=SimpleNamespace(operation_id=lambda *args: 'op-1'))
    return service, scope, key, op, updates


def test_eligible_preview_does_not_change_journal(tmp_path, monkeypatch):
    service, scope, key, operation, updates = _scenario(tmp_path,monkeypatch)
    result=repair.reconcile_observational_windows_vm(
        service,'project-1','dot-1',dict(scope,agent_id='agent-1'),
        {'conversation_id':'conversation-1'},key,preview=True)
    assert result['status']=='eligible'
    assert result['automatic_retry'] is False
    assert operation['state']=='UNCERTAIN'
    assert updates==[]


def test_reconciliation_records_failure_not_installation_success(tmp_path, monkeypatch):
    service, scope, key, operation, updates = _scenario(tmp_path,monkeypatch)
    result=repair.reconcile_observational_windows_vm(
        service,'project-1','dot-1',dict(scope,agent_id='agent-1'),
        {'conversation_id':'conversation-1'},key)
    assert result['status']=='reconciled'
    assert result['state']=='FAILED'
    assert result['lease_released'] is True
    assert result['installation_verified'] is False
    assert result['physical_effects_performed'] is False
    assert operation['state']=='FAILED'
    assert updates[0]['event_type']=='VM_OBSERVATION_FAILURE_RECONCILED'


def test_wrong_request_is_rejected_without_ledger_write(tmp_path,monkeypatch):
    service, scope, key, operation, updates = _scenario(tmp_path,monkeypatch)
    with pytest.raises(Denied):
        repair.reconcile_observational_windows_vm(
            service,'project-1','dot-1',dict(scope,agent_id='agent-1'),
            {'conversation_id':'conversation-1'},'not-the-same-request')
    assert updates==[] and operation['state']=='UNCERTAIN'


def test_running_vm_is_not_administratively_reconciled(tmp_path,monkeypatch):
    service, scope, key, operation, updates = _scenario(tmp_path,monkeypatch)
    monkeypatch.setattr(VirtualBoxClient,'status',
        lambda self,binding:{'VMState':'running','cpus':2,'memory':4096})
    with pytest.raises(Denied,match='powered off'):
        repair.reconcile_observational_windows_vm(
            service,'project-1','dot-1',dict(scope,agent_id='agent-1'),
            {'conversation_id':'conversation-1'},key)
    assert updates==[]


def test_missing_late_worker_return_is_rejected(tmp_path,monkeypatch):
    service, scope, key, operation, updates = _scenario(tmp_path,monkeypatch)
    service.host.durable_intent_authority.late_return_for_receipt=lambda receipt: None
    with pytest.raises(Denied,match='protected failed worker'):
        repair.reconcile_observational_windows_vm(
            service,'project-1','dot-1',dict(scope,agent_id='agent-1'),
            {'conversation_id':'conversation-1'},key)
    assert updates==[]
