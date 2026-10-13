"""Bounded UFO application-command vocabulary over authoritative semantic UIA.

Adapts the app/control receiver pattern, without importing UFO's unrestricted
method dispatcher, focus changes, pyautogui fallback or independent planner.
Each observation and action is a separately admitted central Operation.
"""
from __future__ import annotations

import hashlib
import inspect

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
