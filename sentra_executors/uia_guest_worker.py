"""Owned one-request UIA worker; also installable INSIDE an interactive guest."""
import hashlib
import json
import sys
import os
import threading
import time
from pathlib import Path
from .uia_semantic import UIAProbeEngine
from .rpa import ExecutorFailure

_INPUT_ACTIONS = {'input.mouse', 'input.key'}
_FENCE_NAME = 'input-uncertain.json'


def guest_input_digest(document):
    """Identity of one guest click or typing. The typed text is not stored."""
    arguments = document.get('arguments') if isinstance(document, dict) else None
    if not isinstance(arguments, dict):
        return None
    action = arguments.get('action')
    if action not in _INPUT_ACTIONS:
        return None
    selector = arguments.get('_selector_key')
    runtime = arguments.get('_expected_runtime_id')
    if not isinstance(selector, str) or not selector or not isinstance(runtime, list) or not runtime:
        raise ExecutorFailure('uia_input_fence_identity_required')
    material = [action, selector, runtime]
    if action == 'input.key':
        text = arguments.get('text')
        if not isinstance(text, str) or not text:
            raise ExecutorFailure('uia_keyboard_text_rejected')
        material.append(hashlib.sha256(text.encode()).hexdigest())
    return hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()


def load_input_fence(directory):
    path = Path(directory) / _FENCE_NAME
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ExecutorFailure('guest_input_fence_unreadable')
    if not isinstance(loaded, dict):
        raise ExecutorFailure('guest_input_fence_unreadable')
    return loaded


def guest_task_digest(document):
    """Mouse effect of one guest cycle. The typed text is not part of the digest."""
    task = document.get('task') if isinstance(document, dict) else None
    if not isinstance(task, dict):
        return None
    selector = task.get('selector_key')
    if not isinstance(selector, str) or not selector or len(selector) > 200:
        return None
    return hashlib.sha256(json.dumps(['mouse', selector], separators=(',', ':')).encode()).hexdigest()


def remember_uncertain_input(directory, document, digest, action='input.mouse'):
    """Record an uncertain guest input. Does not send mouse or keyboard."""
    path = Path(directory) / _FENCE_NAME
    fence = load_input_fence(directory)
    prior = fence.get(digest)
    if isinstance(prior, dict):
        return prior
    if not isinstance(action, str) or action not in _INPUT_ACTIONS:
        action = 'input.mouse'
    fence[digest] = {'job_id': document.get('job_id'), 'action': action, 'automatic_resend': False}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(fence, sort_keys=True), encoding='utf-8')
    temporary.replace(path)
    return fence[digest]


def authorized_process_id(document):
    """Process id placed by the authorized executor in the guest profile."""
    profile = document.get('profile') if isinstance(document, dict) else None
    identity = profile.get('identity') if isinstance(profile, dict) else None
    pid = identity.get('pid') if isinstance(identity, dict) else None
    if type(pid) is not int or pid <= 0:
        return None
    return pid


def _read_back(receipt, selector_key):
    for step in receipt.get('steps') or ():
        if step.get('kind') != 'computer.verify':
            continue
        for element in (step.get('evidence') or {}).get('elements') or []:
            if isinstance(element, dict) and element.get('selector_key') == selector_key:
                return element.get('value')
    return None


def _invoke_guest(perform, profile, arguments, checkpoint):
    """Call a proven guest executor, or the supplied engine without claiming proof."""
    from sentra_executors.guest_execution import is_proven_guest_executor
    if is_proven_guest_executor(perform):
        produced = perform.execute({
            'profile': profile, 'arguments': arguments, 'placement': 'guest'})
        if not isinstance(produced, dict):
            raise ExecutorFailure('guest_executor_result_invalid', uncertain=True)
        return produced
    return perform(profile, arguments, checkpoint)


def _surface_for(perform):
    from sentra_executors.guest_execution import is_proven_guest_executor
    proven = is_proven_guest_executor(perform)
    return {
        'execution_surface': 'guest' if proven else 'unproven',
        'claims_guest_execution': proven,
        'host_subprocess': False,
    }


def run_authorized_guest_step(document, *, directory, perform, emit, checkpoint):
    """One production guest step. The engine runs only after an authorized pid."""
    if authorized_process_id(document) is None:
        emit({'event': 'result', 'ok': False, 'code': 'guest_process_id_required',
              'uncertain': False, 'dispatched': False, 'automatic_resend': False})
        return False
    try:
        digest = guest_input_digest(document)
    except ExecutorFailure as exc:
        emit({'event': 'result', 'ok': False, 'code': exc.code, 'uncertain': False,
              'dispatched': False, 'automatic_resend': False})
        return False
    if digest is not None and digest in load_input_fence(directory):
        emit({'event': 'result', 'ok': False, 'code': 'uncertain_input_not_repeated',
              'uncertain': True, 'dispatched': False, 'automatic_resend': False})
        return False
    try:
        evidence = _invoke_guest(perform, document['profile'], document['arguments'], checkpoint)
    except ExecutorFailure as exc:
        if exc.uncertain and digest is not None:
            remember_uncertain_input(directory, document, digest, action=document['arguments']['action'])
        emit({'event': 'result', 'ok': False, 'code': exc.code, 'uncertain': exc.uncertain,
              'dispatched': True, 'automatic_resend': False})
        return False
    emit({'event': 'result', 'ok': True, 'evidence': evidence, 'dispatched': True,
          'automatic_resend': False, **_surface_for(perform)})
    return True


def run_guest_request(document, *, directory, perform, emit, checkpoint, control=None,
                      owner=None, principal_id=None, resource_id=None):
    """First guest effect goes through GraphicalComputerUse. No process id, no engine."""
    import asyncio
    from sentra_executors.ufo_actions import GraphicalComputerUse
    from sentra_runtime.executor import AuthorizationRequired

    process_id = authorized_process_id(document)
    if process_id is None:
        emit({'event': 'result', 'ok': False, 'code': 'guest_process_id_required',
              'uncertain': False, 'dispatched': False, 'automatic_resend': False,
              'execution_surface': 'blocked', 'claims_guest_execution': False,
              'host_subprocess': False})
        return False
    digest = guest_task_digest(document)
    if digest is not None and digest in load_input_fence(directory):
        emit({'event': 'result', 'ok': False, 'code': 'uncertain_input_not_repeated',
              'uncertain': True, 'dispatched': False, 'automatic_resend': False})
        return False
    if control is None or not owner or not principal_id or not resource_id:
        emit({'event': 'result', 'ok': False, 'code': 'guest_cycle_required',
              'uncertain': False, 'dispatched': False, 'automatic_resend': False})
        return False
    profile = document.get('profile') if isinstance(document.get('profile'), dict) else {}

    async def dispatch(_workspace, _work, _machine, _capability, operation_id, arguments, _key):
        step = dict(arguments)
        if step.get('action') in _INPUT_ACTIONS:
            step['_process_id'] = process_id
        try:
            evidence = _invoke_guest(perform, profile, step, checkpoint)
        except ExecutorFailure as exc:
            return {'operation_id': operation_id,
                    'state': 'UNCERTAIN' if exc.uncertain else 'FAILED',
                    'evidence': {'code': exc.code, 'uncertain': exc.uncertain}}
        if not isinstance(evidence, dict):
            evidence = {}
        return {'operation_id': operation_id, 'state': 'SUCCEEDED', 'evidence': evidence}

    task = document.get('task') if isinstance(document, dict) else None
    if not isinstance(task, dict):
        emit({'event': 'result', 'ok': False, 'code': 'guest_cycle_required',
              'uncertain': False, 'dispatched': False, 'automatic_resend': False})
        return False
    cycle = GraphicalComputerUse(dispatch, control=control, owner=owner,
                                 principal_id=principal_id, resource_id=resource_id)
    try:
        receipt = asyncio.run(cycle.run(
            workspace_id=task['workspace_id'], work_item_id=task['work_item_id'],
            machine_id=task['machine_id'], capability_id=task['capability_id'],
            task_id=task['task_id'], selector_key=task['selector_key'], text=task['text'],
            expected=task['expected'], capture_output=task['capture_output']))
    except (AuthorizationRequired, ValueError, KeyError):
        emit({'event': 'result', 'ok': False, 'code': 'guest_cycle_refused',
              'uncertain': False, 'dispatched': False, 'automatic_resend': False})
        return False
    if receipt.get('state') == 'UNCERTAIN' and digest is not None:
        remember_uncertain_input(directory, document, digest, action='input.mouse')
    value = _read_back(receipt, task.get('selector_key'))
    entered = any(step.get('dispatched') for step in receipt.get('steps') or ())
    emit({'event': 'result', 'ok': receipt.get('state') == 'SUCCEEDED', 'state': receipt.get('state'),
          'value': value, 'process_id': process_id, 'uncertain': receipt.get('state') == 'UNCERTAIN',
          'dispatched': entered, 'automatic_resend': False,
          'mouse_dispatched': receipt.get('mouse_dispatched'),
          'keyboard_dispatched': receipt.get('keyboard_dispatched'),
          **_surface_for(perform)})
    return receipt.get('state') == 'SUCCEEDED'


def main():
    def checkpoint():
        print(json.dumps({'event':'checkpoint','phase':'uia'}),flush=True)
        if sys.stdin.readline().strip()!='CONTINUE':raise ExecutorFailure('uia_parent_checkpoint_not_authorized')
    try:
        document=json.loads(sys.stdin.readline(2*1024*1024))
        result=UIAProbeEngine().perform(document['profile'],document['arguments'],checkpoint)
        print(json.dumps({'event':'result','ok':True,'evidence':result},allow_nan=False),flush=True)
    except Exception as exc:
        print(json.dumps({'event':'result','ok':False,'code':exc.code if isinstance(exc,ExecutorFailure) else 'uia_provider_error',
                          'uncertain':isinstance(exc,ExecutorFailure) and exc.uncertain}),flush=True)


def file_main(root):
    """Task Scheduler InteractiveToken mode INSIDE guest; no network protocol.

    Files are a protected local IPC spool for the host's PowerShell Direct
    session. Every physical step awaits a fresh parent ACK. No generic code API.
    """
    directory=Path(root).resolve(strict=True)
    request=directory/'pending.json';response=directory/'response.jsonl';ack=directory/'ack.json'
    document=json.loads(request.read_text(encoding='utf-8-sig'));job=document['job_id'];deadline=document['deadline_unix']
    if not isinstance(job,str) or len(job)!=32 or time.time()>=deadline or deadline-time.time()>300:
        with response.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'event':'result','ok':False,'code':'guest_clock_skew_or_expired_job','job_id':job})+'\n')
        return
    def watchdog():
        while time.time()<deadline:time.sleep(.1)
        os._exit(94)
    threading.Thread(target=watchdog,daemon=True).start()
    counter=0
    def emit(value):
        value['job_id']=job
        with response.open('a',encoding='utf-8') as stream:stream.write(json.dumps(value,allow_nan=False)+'\n');stream.flush()
    def checkpoint():
        nonlocal counter;counter+=1
        emit({'event':'checkpoint','phase':'uia','sequence':counter})
        limit=min(deadline,time.time()+5)
        while time.time()<limit:
            try:
                value=json.loads(ack.read_text(encoding='utf-8-sig'))
                if value.get('job_id')==job and value.get('sequence')==counter and time.time()<value.get('expires_unix',0):return
            except (FileNotFoundError,ValueError):pass
            time.sleep(.05)
        raise ExecutorFailure('guest_parent_checkpoint_expired')
    def perform(profile, arguments, checkpoint):
        return UIAProbeEngine().perform(profile, arguments, checkpoint)
    try:
        run_authorized_guest_step(document, directory=directory, perform=perform, emit=emit,
                                  checkpoint=checkpoint)
    except ExecutorFailure as exc:
        emit({'event':'result','ok':False,'code':exc.code,'uncertain':exc.uncertain,
              'dispatched':False,'automatic_resend':False})
    except Exception as exc:
        emit({'event':'result','ok':False,'code':exc.code if isinstance(exc,ExecutorFailure) else 'guest_uia_provider_error',
              'uncertain':isinstance(exc,ExecutorFailure) and exc.uncertain,'automatic_resend':False})


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--request-dir':file_main(sys.argv[2])
    elif len(sys.argv)==1:main()
    else:raise SystemExit('configured UIA worker arguments required')
