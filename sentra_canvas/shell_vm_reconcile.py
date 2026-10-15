"""Owner-scoped repair of one *observational* Windows VM request.

Never reconciles a VM boot, an installation launch, a provision, or arbitrary
UNCERTAIN effects. The original result and late-return artifacts are retained.
"""
from contextlib import closing
import hashlib
import json
import time

from sentra_core.conversations import _decode
from sentra_runtime.contracts import OperationResult
from .store import Denied


def _original_request_fingerprint(params):
    intent = {
        'dot_id': params['dot_id'], 'space_id': params['space_id'],
        'conversation_id': params['conversation_id'],
        'arguments': {'action': 'installation.advance', 'confirm_launch': False},
    }
    data = json.dumps(['dot_vm_execute', intent], sort_keys=True,
                      separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def _blocked_start_proof(service, pid, root, dot, cid, start_key):
    """Inspect a rejected start; never convert its journal to a success."""
    if start_key is None:
        return None
    if not isinstance(start_key, str) or not 8 <= len(start_key) <= 200:
        raise Denied('invalid start consultation key')
    payload = {
        'dot_id': root, 'space_id': dot['space_id'],
        'conversation_id': cid, 'arguments': {'action': 'start'},
    }
    fingerprint = hashlib.sha256(json.dumps(['dot_vm_execute', payload],
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    with closing(service.host.control.store.connect('shell')) as db:
        row = db.execute('SELECT fingerprint,state,phase,operation_id,protected_result '
            'FROM canvas_shell_host_requests WHERE owner=? AND project_id=? AND request_key=?',
            (service.host.owner, pid, start_key)).fetchone()
    if (row is None or row['fingerprint'] != fingerprint
            or row['state'] != 'uncertain' or row['phase'] is not None
            or row['operation_id'] is not None):
        raise Denied('start request lacks a matching blocked admission receipt')
    receipt = _decode(row['protected_result']) if row['protected_result'] else {}
    diagnosis = receipt.get('diagnosis') if isinstance(receipt, dict) else None
    if (not isinstance(diagnosis, dict) or receipt.get('status') != 'uncertain'
            or diagnosis.get('exception_class') != 'DuplicateOperation'
            or diagnosis.get('operation_id') is not None):
        raise Denied('start was not proven to have been rejected by admission')
    oid = service.requests.operation_id(pid, start_key, 'dot_vm_execute')
    with service.host.control.durable.lock:
        stored = service.host.control.durable.db.execute(
            'SELECT operation_id FROM operations WHERE operation_id=? OR '
            '(run_id=? AND idempotency_key=?)',
            (oid, service.canvas._runtime().run(pid)['run_id'], start_key)).fetchone()
    if stored is not None:
        raise Denied('start has a persisted effect intent; no local dismissal')
    return start_key


def reconcile_observational_windows_vm(service, pid, root, dot, conversation, original_key,
                                       blocked_start_key=None, *, preview=False):
    """One-way UNCERTAIN -> FAILED, proven error; never execute provider I/O."""
    if not isinstance(original_key, str) or not 8 <= len(original_key) <= 200:
        raise ValueError('valid original request key required')
    vm = service.store.get(pid, root)
    cid = conversation['conversation_id']
    if not vm or vm.get('os_family') != 'windows' or vm.get('root_dot_id') != root:
        raise Denied('only an owned Windows VM can use observational reconciliation')
    wid = (vm.get('work_items') or {}).get(cid)
    if not wid or vm.get('agent_id') != dot.get('agent_id'):
        raise Denied('VM conversation and WorkItem authority required')

    owner = service.host.owner
    control = service.host.control
    run = service.canvas._runtime().run(pid)
    work = control.work_item_info(wid, owner)
    if (run['state'] != 'RUNNING' or work['run_id'] != run['run_id']
            or work['assignee_agent_id'] != dot['agent_id']):
        raise Denied('work authority not active')
    expected = _original_request_fingerprint({
        'dot_id': root, 'space_id': dot['space_id'], 'conversation_id': cid})
    with closing(control.store.connect('shell')) as db:
        original = db.execute('SELECT fingerprint,state,protected_result FROM canvas_shell_host_requests '
            'WHERE owner=? AND project_id=? AND request_key=?',
            (owner, pid, original_key)).fetchone()
    if not original or original['fingerprint'] != expected:
        raise Denied('request is not this conversation observational installation check')
    projection = _decode(original['protected_result']) if original['protected_result'] else {}
    operation_id = service.requests.operation_id(pid, original_key, 'dot_vm_execute')
    if (not isinstance(projection, dict) or projection.get('state') != 'UNCERTAIN'
            or projection.get('operation_id') != operation_id):
        raise Denied('original request did not return matching uncertain operation')

    durable = control.durable
    auth = service.host._factories.get(vm['machine_id'])
    if auth is None:
        raise Denied('authorized physical VM not registered')
    factory = auth
    from sentra_runtime.contracts import OperationRequest
    requested = OperationRequest('reconcile-probe-' + original_key[:50],
        dot['agent_id'], vm['machine_id'], 'vm:manage', wid,
        'reconcile-probe-' + original_key[:50],
        {'action': 'installation.advance', 'confirm_launch': False})
    if factory.policy(requested).allowed is not True:
        raise Denied('live vm:manage Grant required')

    from sentra_executors.virtualbox_vm import VirtualBoxClient, VirtualBoxBinding
    client = VirtualBoxClient()
    binding = VirtualBoxBinding(vm['vm_id'], vm['marker'], None)
    # Read-only hypervisor identity/status; never call controlvm, startvm or guestcontrol.
    observed = client.status(binding)
    if (observed.get('VMState') != 'poweroff'
            or str(observed.get('cpus')) != str(vm.get('cpus'))
            or str(observed.get('memory')) != str(vm.get('memory_mb'))):
        raise Denied('VM must be powered off with verified existing hardware')
    # The failed Acordar click is an independent rejected admission.
    # Confirm its hash and absence of a reserved operation before dismissing
    # its local warning; retain its durable uncertain receipt unchanged.
    blocked_start = _blocked_start_proof(
        service, pid, root, dot, cid, blocked_start_key)
    resource = 'machine:' + vm['machine_id']
    with durable.lock:
        row = durable._operation_row(operation_id, owner)
        progress = json.loads(row['progress_json'])
        if (row['state'] != 'UNCERTAIN' or row['kind'] != 'sentra.machine'
                or row['run_id'] != run['run_id'] or row['resource_key'] != resource
                or progress.get('effect_started') is not True
                or progress.get('work_item_id') != wid
                or progress.get('principal_id') != dot['agent_id']
                or progress.get('capability_id') != 'vm:manage'
                or progress.get('machine_id') != vm['machine_id']):
            raise Denied('central machine operation does not match the original request')
        lease = durable.db.execute(
            'SELECT * FROM leases WHERE resource_key=?', (resource,)).fetchone()
        if (lease is None or lease['operation_id'] != operation_id
                or lease['owner'] != owner
                or lease['fencing_token'] != row['fencing_token']
                or float(lease['lease_until']) > durable.clock()):
            raise Denied('effect lease is active or belongs to another operation')
        # Both protected receipts must validate against the central intent.
        authority = getattr(service.host, 'durable_intent_authority', None)
        if authority is None:
            from sentra_runtime.central_authority import CentralDurableIntentAuthority
            authority = CentralDurableIntentAuthority(durable)
        receipt = authority.receipt_for_operation(operation_id, owner)
        recorded = authority.result_for_receipt(receipt)
        late = authority.late_return_for_receipt(receipt)
        if (recorded is None or recorded.state != 'UNCERTAIN'
                or recorded.error != 'physical_effect_error_requires_reconciliation'
                or not isinstance(late, dict)
                or late.get('worker_returned') is not True
                or late.get('operation_reconciled') is not False
                or late.get('error_type') != 'ExecutorFailure'
                or late.get('reported_return') is not None):
            raise Denied('protected failed worker receipt not verified')
        # This is safe for the authenticated status panel and QA preflight:
        # no artifacts, state transitions or leases are changed.
        if preview:
            return {
                'status': 'eligible', 'vm_state': observed['VMState'],
                'vm_id': vm['vm_id'], 'original_operation_id': operation_id,
                'original_request_key': original_key,
                'current_state': 'UNCERTAIN', 'worker_returned': True,
                'start_block_verified': blocked_start is not None,
                'blocked_start_request_key': blocked_start,
                'physical_effects_performed': False,
                'automatic_retry': False,
            }
        # Reconciliation is restricted to a Windows consultation with
        # confirm_launch=False, never the actual install/boot effect.
        evidence = {
            'reconciliation_kind': 'windows_installation_observation_failure',
            'original_action': 'installation.advance',
            'confirm_launch': False,
            'vm_id': vm['vm_id'], 'observed_vm_state': observed['VMState'],
            'worker_returned': True, 'worker_error_type': 'ExecutorFailure',
            'original_outcome': 'UNCERTAIN',
            'physical_boot_performed_by_reconciliation': False,
            'installation_verified': False, 'automatic_retry': False,
        }
        proof = authority._store_evidence(receipt, OperationResult(
            operation_id, 'FAILED', evidence,
            'observational_check_failed_and_reconciled'),
            json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')).encode())
        durable.update_operation(operation_id, owner, state='FAILED',
            event_type='VM_OBSERVATION_FAILURE_RECONCILED',
            progress={'reconciled_administratively': True,
                      'reconciled_observation_only': True,
                      'reconciliation_artifact_id': proof['evidence_artifact_id'],
                      'reconciled_at': time.time()},
            error={'error_type': 'observational_check_failed_and_reconciled'},
            result=proof)
        released = durable.release_lease(resource, owner, row['fencing_token'])
    return {'status': 'reconciled', 'original_operation_id': operation_id,
            'original_request_key': original_key,
            'state': 'FAILED', 'previous_state': 'UNCERTAIN',
            'receipt_artifact_id': proof['evidence_artifact_id'],
            'lease_released': released['released'],
            'vm_state': observed['VMState'],
            'vm_id': vm['vm_id'], 'installation_verified': False,
            'physical_effects_performed': False, 'automatic_retry': False,
            'verified_blocked_start_request_key': blocked_start,
            'start_journal_unchanged': True}
