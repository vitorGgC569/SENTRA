"""Bounded UFO application-command vocabulary over authoritative semantic UIA.

Adapts the app/control receiver pattern, without importing UFO's unrestricted
method dispatcher, focus changes, pyautogui fallback or independent planner.
Each observation and action is a separately admitted central Operation.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re

from .rpa import ExecutorFailure

UFO_SOURCE_REVISION = 'a795552d976c4c019d7c2f778a0effb5cef7de6b'
COMMANDS = {'click': 'invoke', 'set_text': 'set_value', 'toggle': 'toggle',
            'select': 'select', 'read': 'read'}


class UFOApplicationActions:
    """dispatch uses MachineHost._dispatch's positional, async signature."""
    def __init__(self, dispatch):
        if not callable(dispatch):
            raise ValueError('authoritative_machine_host_dispatch_required')
        self.dispatch = dispatch

    async def execute(self, *, workspace_id, work_item_id, machine_id, capability_id,
                      operation_id, request_key, command, selector_key, text=None):
        if (command not in COMMANDS or not isinstance(selector_key, str) or not selector_key or
                not isinstance(operation_id, str) or not operation_id or
                not isinstance(request_key, str) or not request_key):
            raise ValueError('bounded_ufo_application_command_required')
        if command == 'set_text':
            if not isinstance(text, str) or len(text) > 65536:
                raise ValueError('bounded_ufo_text_required')
        elif text is not None:
            raise ValueError('unexpected_ufo_command_text')
        fingerprint = hashlib.sha256((operation_id + '\0' + request_key).encode()).hexdigest()
        async def send(**fields):
            value = self.dispatch(workspace_id, work_item_id, machine_id, capability_id,
                                  fields['operation_id'], fields['arguments'], fields['idempotency_key'])
            if inspect.isawaitable(value):
                value = await value
            if not isinstance(value, dict) or value.get('state') != 'SUCCEEDED':
                # Pending/uncertain observations never authorize following input.
                raise ExecutorFailure('ufo_application_step_not_completed',
                    uncertain=isinstance(value, dict) and value.get('state') == 'UNCERTAIN',
                    evidence={'operation_id': value.get('operation_id') if isinstance(value, dict) else None,
                              'state': value.get('state') if isinstance(value, dict) else 'UNKNOWN'})
            return value

        observed = await send(operation_id='op-ufo-observe-' + fingerprint[:40],
            idempotency_key='ufo-observe-' + fingerprint, arguments={'action': 'observe'})
        elements = observed.get('evidence', {}).get('elements', [])
        matches = [item for item in elements if item.get('selector_key') == selector_key and item.get('reference')]
        if len(matches) != 1:
            raise ExecutorFailure('ufo_selector_missing_or_ambiguous')
        action = COMMANDS[command]
        arguments = {'action': action, 'reference': matches[0]['reference']}
        if command == 'set_text':
            arguments['value'] = text
        result = await send(operation_id=operation_id, idempotency_key=request_key, arguments=arguments)
        return {'operation_id': result['operation_id'], 'state': result['state'], 'value': result,
                'observation_operation_id': observed['operation_id'],
                'source_revision': UFO_SOURCE_REVISION, 'coordinate_input_used': False,
                'execution_authority': 'sentra_control_plane'}


_TASK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$')
_EXPECTED = {'text', 'value', 'enabled', 'visible'}


def _operation_id(task_id, name):
    text = f'op-{task_id}-{name}'
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', text):
        raise ValueError('bounded_task_id_required')
    return text


def _jsonable(value):
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return {'unserializable': True}


def _execution_surface_from_steps(steps):
    """Guest/host claims come from durable step evidence, never from dispatch alone."""
    for step in reversed(steps):
        if step.get('kind') != 'computer.verify':
            continue
        evidence = step.get('evidence')
        if not isinstance(evidence, dict):
            break
        surface = evidence.get('execution_surface')
        if not isinstance(surface, str) or not surface:
            break
        return {
            'execution_surface': surface,
            'claims_guest_execution': evidence.get('claims_guest_execution') is True,
            'host_subprocess': evidence.get('host_subprocess') is True,
        }
    return {}


class GraphicalComputerUse:
    """Capture, locate, click, type, then read the result back.

    Each step is its own durable operation under the live WorkItem grant.
    An uncertain mouse or keyboard effect is fenced and is not dispatched again.
    """

    def __init__(self, dispatch, *, control, owner, principal_id, resource_id):
        if not callable(dispatch):
            raise ValueError('authoritative_machine_host_dispatch_required')
        if not resource_id or not owner or not principal_id:
            raise ValueError('computer_use_scope_required')
        self.dispatch = dispatch
        self.control = control
        self.owner = owner
        self.principal_id = principal_id
        self.resource_id = resource_id

    def _policy(self):
        from sentra_runtime.authority_bridge import BoundWorkItemPolicy
        return BoundWorkItemPolicy(owner=self.owner, principal_type='agent',
            authorization=self.control.authorization, governance=self.control.governance,
            trusted_context=lambda _request: {'actual_cost': 0.0})

    def _request(self, *, operation_id, machine_id, capability_id, work_item_id,
                 idempotency_key, arguments):
        from sentra_runtime.contracts import OperationRequest
        return OperationRequest(operation_id, self.principal_id, machine_id, capability_id,
                                work_item_id, idempotency_key, arguments)

    async def _finish(self, operation_id, state, *, evidence=None, error=None):
        self.control.durable.update_operation(operation_id, self.owner, state=state,
            result={'evidence': _jsonable(evidence or {}), 'automatic_resend': False},
            error=error)

    async def _effect(self, *, run_id, task_id, name, kind, workspace_id, work_item_id,
                      machine_id, capability_id, arguments, input_kind=None,
                      selector_key=None, text=None):
        from sentra_executors.input_control import InputControl
        from sentra_runtime.executor import AuthorizationRequired
        operation_id = _operation_id(task_id, name)
        info = self.control.durable.create_operation(run_id, self.owner, kind=kind,
            idempotency_key=operation_id, operation_id=operation_id)
        stored = (info.get('result') or {}).get('evidence') or {}
        if info.get('idempotent_replay') and info['state'] != 'QUEUED':
            if info['state'] in {'SUCCEEDED', 'FAILED', 'UNCERTAIN', 'CANCELLED'}:
                return {'operation_id': operation_id, 'kind': kind, 'state': info['state'],
                        'dispatched': False, 'evidence': stored, 'automatic_resend': False}
            if input_kind:
                InputControl(self.control, owner=self.owner).note_uncertain(
                    work_item_id=work_item_id, kind=input_kind, selector_key=selector_key,
                    operation_id=operation_id, text=text)
            if info['state'] in {'RUNNING', 'STARTING', 'WAITING_EXTERNAL', 'CANCEL_REQUESTED'}:
                self.control.durable.update_operation(operation_id, self.owner, state='UNCERTAIN',
                    error={'code': 'in_flight_input_not_repeated', 'automatic_resend': False})
            return {'operation_id': operation_id, 'kind': kind, 'state': 'UNCERTAIN',
                    'dispatched': False, 'evidence': stored, 'automatic_resend': False}
        request = self._request(operation_id=operation_id, machine_id=machine_id,
            capability_id=capability_id, work_item_id=work_item_id,
            idempotency_key=operation_id, arguments=arguments)
        decision = self._policy()(request)
        if not isinstance(decision, object) or getattr(decision, 'allowed', None) is not True:
            self._finish_denied(operation_id, getattr(decision, 'reason', 'grant_denied'))
            return {'operation_id': operation_id, 'kind': kind, 'state': 'DENIED',
                    'dispatched': False, 'evidence': {}, 'automatic_resend': False}
        lease = InputControl(self.control, owner=self.owner)
        if input_kind:
            fenced = lease.uncertain_effect(work_item_id=work_item_id, kind=input_kind,
                                            selector_key=selector_key, text=text)
            if fenced is not None:
                self.control.durable.update_operation(operation_id, self.owner, state='RUNNING')
                await self._finish(operation_id, 'UNCERTAIN',
                                   error={'code': 'uncertain_input_not_repeated', 'automatic_resend': False})
                return {'operation_id': operation_id, 'kind': kind, 'state': 'UNCERTAIN',
                        'dispatched': False, 'evidence': {'fenced_by': fenced['operation_id']},
                        'automatic_resend': False}
            try:
                lease.check(request, self.resource_id)
            except (AuthorizationRequired, PermissionError, ValueError, KeyError):
                self._finish_denied(operation_id, 'input_possession_required')
                return {'operation_id': operation_id, 'kind': kind, 'state': 'DENIED',
                        'dispatched': False, 'evidence': {}, 'automatic_resend': False}
        self.control.durable.update_operation(operation_id, self.owner, state='RUNNING')
        try:
            value = self.dispatch(workspace_id, work_item_id, machine_id, capability_id,
                                  operation_id, arguments, operation_id)
            if inspect.isawaitable(value):
                value = await value
        except Exception:
            if input_kind:
                lease.note_uncertain(work_item_id=work_item_id, kind=input_kind,
                                     selector_key=selector_key, operation_id=operation_id, text=text)
                await self._finish(operation_id, 'UNCERTAIN',
                                   error={'code': 'input_dispatch_failed', 'automatic_resend': False})
                return {'operation_id': operation_id, 'kind': kind, 'state': 'UNCERTAIN',
                        'dispatched': True, 'evidence': {}, 'automatic_resend': False}
            await self._finish(operation_id, 'FAILED', error={'code': 'dispatch_failed'})
            return {'operation_id': operation_id, 'kind': kind, 'state': 'FAILED',
                    'dispatched': True, 'evidence': {}, 'automatic_resend': False}
        if not isinstance(value, dict):
            state, evidence = 'UNCERTAIN' if input_kind else 'FAILED', {}
        else:
            state = value.get('state')
            evidence = value.get('evidence') if isinstance(value.get('evidence'), dict) else {}
            if state not in {'SUCCEEDED', 'FAILED', 'UNCERTAIN'}:
                state = 'UNCERTAIN' if input_kind else 'FAILED'
        if input_kind and state == 'UNCERTAIN':
            lease.note_uncertain(work_item_id=work_item_id, kind=input_kind,
                                 selector_key=selector_key, operation_id=operation_id, text=text)
        await self._finish(operation_id, 'UNCERTAIN' if state == 'DENIED' else state,
                           evidence=evidence,
                           error=None if state == 'SUCCEEDED' else {'code': state, 'automatic_resend': False})
        return {'operation_id': operation_id, 'kind': kind, 'state': state,
                'dispatched': True, 'evidence': evidence, 'automatic_resend': False}

    def _finish_denied(self, operation_id, reason):
        self.control.durable.update_operation(operation_id, self.owner, state='FAILED',
            error={'code': 'DENIED', 'reason': str(reason)[:200], 'automatic_resend': False})

    def _element(self, evidence, selector_key):
        elements = evidence.get('elements') if isinstance(evidence, dict) else None
        if not isinstance(elements, list):
            return None
        matches = [item for item in elements
                   if isinstance(item, dict) and item.get('selector_key') == selector_key and item.get('reference')]
        if len(matches) != 1:
            return None
        return matches[0]

    async def run(self, *, workspace_id, work_item_id, machine_id, capability_id, task_id,
                  selector_key, text, expected, capture_output):
        if not _TASK.fullmatch(str(task_id or '')) or not isinstance(selector_key, str) or not selector_key:
            raise ValueError('bounded_graphical_task_required')
        if not isinstance(text, str) or not text or len(text) > 65536:
            raise ValueError('bounded_keyboard_text_required')
        if not isinstance(expected, dict) or not expected or set(expected) - _EXPECTED:
            raise ValueError('bounded_post_action_expected')
        if not isinstance(capture_output, str) or not capture_output:
            raise ValueError('capture_output_required')
        from sentra_runtime.executor import AuthorizationRequired
        item = self.control.work_item_info(work_item_id, self.owner)
        if (item.get('metadata', {}).get('workspace_id') != workspace_id or
                item.get('metadata', {}).get('machine_id') != machine_id or
                item.get('state') != 'RUNNING'):
            raise AuthorizationRequired('computer use outside the running machine task')
        run_id = item['run_id']
        common = dict(run_id=run_id, task_id=task_id, workspace_id=workspace_id,
                      work_item_id=work_item_id, machine_id=machine_id, capability_id=capability_id)
        steps = []

        async def stop(state):
            receipt = {'task_id': task_id, 'run_id': run_id, 'work_item_id': work_item_id,
                       'state': state, 'automatic_resend': False, 'steps': tuple(steps),
                       'mouse_dispatched': sum(1 for step in steps if step['kind'] == 'computer.mouse' and step['dispatched']),
                       'keyboard_dispatched': sum(1 for step in steps if step['kind'] == 'computer.keyboard' and step['dispatched']),
                       'execution_authority': 'sentra_control_plane'}
            receipt.update(_execution_surface_from_steps(steps))
            return receipt

        capture = await self._effect(**common, name='capture', kind='computer.capture',
                                      arguments={'action': 'screenshot', 'output': capture_output})
        steps.append(capture)
        if capture['state'] != 'SUCCEEDED':
            return await stop('DENIED' if capture['state'] == 'DENIED' else capture['state'])
        located = await self._effect(**common, name='locate', kind='computer.locate',
                                      arguments={'action': 'observe'})
        steps.append(located)
        element = self._element(located['evidence'], selector_key) if located['state'] == 'SUCCEEDED' else None
        if located['state'] != 'SUCCEEDED' or element is None:
            return await stop(located['state'] if located['state'] != 'SUCCEEDED' else 'FAILED')
        mouse = await self._effect(**common, name='mouse', kind='computer.mouse', input_kind='mouse',
                                    selector_key=selector_key,
                                    arguments={'action': 'input.mouse', 'reference': element['reference']})
        steps.append(mouse)
        if mouse['state'] != 'SUCCEEDED':
            return await stop('DENIED' if mouse['state'] == 'DENIED' else mouse['state'])
        relocated = await self._effect(**common, name='relocate', kind='computer.relocate',
                                        arguments={'action': 'observe'})
        steps.append(relocated)
        fresh = self._element(relocated['evidence'], selector_key) if relocated['state'] == 'SUCCEEDED' else None
        if relocated['state'] != 'SUCCEEDED' or fresh is None:
            return await stop(relocated['state'] if relocated['state'] != 'SUCCEEDED' else 'FAILED')
        typed = await self._effect(**common, name='keyboard', kind='computer.keyboard', input_kind='keyboard',
                                    selector_key=selector_key, text=text,
                                    arguments={'action': 'input.key', 'reference': fresh['reference'], 'text': text})
        steps.append(typed)
        if typed['state'] != 'SUCCEEDED':
            return await stop('DENIED' if typed['state'] == 'DENIED' else typed['state'])
        verified = await self._effect(**common, name='verify', kind='computer.verify',
                                       arguments={'action': 'observe'})
        steps.append(verified)
        found = self._element(verified['evidence'], selector_key) if verified['state'] == 'SUCCEEDED' else None
        if verified['state'] != 'SUCCEEDED' or found is None:
            return await stop(verified['state'] if verified['state'] != 'SUCCEEDED' else 'FAILED')
        if any(found.get(key) != value for key, value in expected.items()):
            return await stop('FAILED')
        return await stop('SUCCEEDED')
