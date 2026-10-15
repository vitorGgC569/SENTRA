"""Front 4 contract: capture, locate, mouse, keyboard, post-check, no uncertain replay.

The dispatch double is not a physical desktop. It proves Run, WorkItem, Operation
and Grant admission, and that an uncertain click is not dispatched again.
"""
import asyncio

import pytest

from sentra_executors.input_control import InputControl
from sentra_executors.rpa import AuthorizedPaths, ExecutorFailure
from sentra_executors.uia_semantic import (
    DesktopIdentity, SemanticUIABinding, SemanticUIAExecutor, UIASelector,
    keyboard_post_state, pointer_target)
from sentra_executors.uia_guest_worker import run_guest_request
from sentra_executors.ufo_actions import GraphicalComputerUse
from sentra_executors.windows_identity import ProcessIdentity
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import OperationRequest, PolicyDecision


OWNER, AGENT = 'owner-iris', 'agent-iris'
RUN, WORK = 'run-iris', 'work-iris'
WORKSPACE, MACHINE = 'ws-iris', 'machine-iris'
RESOURCE = 'desktop-iris'
CAP = 'desktop:computer-use'


@pytest.fixture
def central(tmp_path):
    root = tmp_path / 'central'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    durable = DurableRunService(root)
    control = ControlPlaneService(durable, ContextBusService(root))
    control.durable.create_run(OWNER, run_id=RUN, workspace=str(workspace))
    control.ensure_agent(RUN, OWNER, agent_id=AGENT, role='worker')
    control.create_work_item(RUN, OWNER, work_item_id=WORK, objective='Graphical computer use',
        assignee_agent_id=AGENT, required_capabilities=[CAP],
        metadata={'workspace_id': WORKSPACE, 'machine_id': MACHINE})
    control.transition_work_item(WORK, OWNER, 'QUEUED')
    control.start_work_item_execution(WORK, OWNER, run_id=RUN, agent_id=AGENT)
    try:
        yield control
    finally:
        durable.close()


def _cycle(control, dispatch):
    return GraphicalComputerUse(dispatch, control=control, owner=OWNER,
                                principal_id=AGENT, resource_id=RESOURCE)


def _grant_and_hold(control):
    control.authorization.grant(OWNER, principal_type='agent', principal_id=AGENT,
        capability=CAP, scope_type='work_item', scope_id=WORK)
    request = OperationRequest('op-iris-hold', AGENT, MACHINE, CAP, WORK, 'key-iris-hold',
                               {'action': 'input.mouse'})
    InputControl(control, owner=OWNER).handoff(
        resource_id=RESOURCE, workspace_id=WORKSPACE, machine_id=MACHINE, holder='agent',
        expected_epoch=0, request_key='iris-hold', request=request)


def _script(calls, mouse_state='SUCCEEDED'):
    async def dispatch(_ws, _work, _machine, _cap, operation_id, arguments, _key):
        calls.append(arguments['action'])
        if arguments['action'] == 'screenshot':
            return {'operation_id': operation_id, 'state': 'SUCCEEDED',
                    'evidence': {'width': 2, 'height': 2, 'sha256': 'ab'}}
        if arguments['action'] == 'observe':
            return {'operation_id': operation_id, 'state': 'SUCCEEDED', 'evidence': {
                'elements': [{'selector_key': 'note', 'reference': 'rev:note', 'value': 'iris-ok'}]}}
        if arguments['action'] == 'input.mouse':
            return {'operation_id': operation_id, 'state': mouse_state, 'evidence': {}}
        if arguments['action'] == 'input.key':
            assert arguments['text'] == 'iris-ok'
            return {'operation_id': operation_id, 'state': 'SUCCEEDED',
                    'evidence': {'effect_semantically_verified': True}}
        return {'operation_id': operation_id, 'state': 'FAILED', 'evidence': {}}
    return dispatch


def _run(control, dispatch, task_id):
    return asyncio.run(_cycle(control, dispatch).run(
        workspace_id=WORKSPACE, work_item_id=WORK, machine_id=MACHINE, capability_id=CAP,
        task_id=task_id, selector_key='note', text='iris-ok', expected={'value': 'iris-ok'},
        capture_output='C:/iris/capture.png'))


def test_pointer_and_keyboard_post_state_are_bounded():
    assert pointer_target((0, 0, 10, 10), (0, 0, 20, 20)) == (5, 5)
    with pytest.raises(ExecutorFailure, match='outside_window'):
        pointer_target((0, 0, 4, 4), (10, 10, 20, 20))
    with pytest.raises(ExecutorFailure, match='rectangle_empty'):
        pointer_target((5, 5, 5, 8), (0, 0, 20, 20))
    assert keyboard_post_state(0, 'a', 'a') == 'not_sent'
    assert keyboard_post_state(2, 'iris-ok', 'iris-ok') == 'verified'
    assert keyboard_post_state(2, 'iris-ok', '') == 'uncertain'


def test_grant_is_required_before_any_dispatch(central):
    calls = []
    receipt = _run(central, _script(calls), 'task-denied')
    assert receipt['state'] == 'DENIED'
    assert calls == []
    assert receipt['mouse_dispatched'] == 0
    status = central.durable.operation_status('op-task-denied-capture', OWNER)
    assert status['run_id'] == RUN and status['state'] == 'FAILED'


def test_uncertain_mouse_is_not_dispatched_again(central):
    _grant_and_hold(central)
    calls = []
    first = _run(central, _script(calls, mouse_state='UNCERTAIN'), 'task-mouse')
    assert first['state'] == 'UNCERTAIN'
    assert calls == ['screenshot', 'observe', 'input.mouse']
    assert first['mouse_dispatched'] == 1 and first['keyboard_dispatched'] == 0
    mouse = central.durable.operation_status('op-task-mouse-mouse', OWNER)
    assert mouse['state'] == 'UNCERTAIN' and mouse['run_id'] == RUN
    assert InputControl(central, owner=OWNER).uncertain_effect(
        work_item_id=WORK, kind='mouse', selector_key='note')['automatic_resend'] is False
    second = _run(central, _script(calls, mouse_state='SUCCEEDED'), 'task-mouse')
    assert second['state'] == 'UNCERTAIN'
    assert second['mouse_dispatched'] == 0
    assert calls == ['screenshot', 'observe', 'input.mouse']


def test_successful_cycle_records_every_step_and_does_not_repeat_input(central):
    _grant_and_hold(central)
    calls = []
    receipt = _run(central, _script(calls), 'task-ok')
    assert receipt['state'] == 'SUCCEEDED'
    assert calls == ['screenshot', 'observe', 'input.mouse', 'observe', 'input.key', 'observe']
    assert receipt['mouse_dispatched'] == 1 and receipt['keyboard_dispatched'] == 1
    for name in ('capture', 'locate', 'mouse', 'relocate', 'keyboard', 'verify'):
        status = central.durable.operation_status(f'op-task-ok-{name}', OWNER)
        assert status['state'] == 'SUCCEEDED' and status['run_id'] == RUN
    again = _run(central, _script(calls), 'task-ok')
    assert again['state'] == 'SUCCEEDED'
    assert again['mouse_dispatched'] == 0 and again['keyboard_dispatched'] == 0
    assert calls.count('input.mouse') == 1 and calls.count('input.key') == 1


def test_executor_refuses_a_fenced_click_before_the_backend(central, tmp_path):
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    binding = SemanticUIABinding(
        'uia', ProcessIdentity(11, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1),
        (UIASelector('note', 'Note', 'Edit', actions=('read', 'input.mouse', 'input.key')),),
        paths, actions=('observe', 'screenshot', 'input.mouse', 'input.key'))

    class Recorder:
        def __init__(self):
            self.calls = 0
        def run(self, _binding, _args):
            self.calls += 1
            return {'ok': True}

    recorder = Recorder()
    executor = SemanticUIAExecutor(machine_id=MACHINE, owner_principal_id=AGENT,
        bindings=(binding,), backend=recorder, uncertain=InputControl(central, owner=OWNER))
    args = {'action': 'input.mouse', 'reference': 'rev:note', '_work_item_id': WORK}
    assert executor._run(binding, args)['ok'] is True
    InputControl(central, owner=OWNER).note_uncertain(
        work_item_id=WORK, kind='mouse', selector_key='note', operation_id='op-task-mouse-mouse')
    with pytest.raises(ExecutorFailure, match='uncertain_input_not_repeated') as raised:
        executor._run(binding, args)
    assert raised.value.uncertain is True
    assert recorder.calls == 1


class _GuestDouble:
    """Stand-in for the guest engine. process_id is the only admission to run."""

    def __init__(self, process_id=5151, mouse_state='SUCCEEDED'):
        self.process_id = process_id
        self.mouse_state = mouse_state
        self.calls = []
        self.seen_process = []

    def __call__(self, _profile, arguments, _checkpoint):
        self.calls.append(arguments['action'])
        if arguments['action'] in {'input.mouse', 'input.key'}:
            self.seen_process.append(arguments.get('_process_id'))
        if arguments['action'] == 'input.mouse' and self.mouse_state == 'UNCERTAIN':
            raise ExecutorFailure('uia_mouse_dispatch_failed', uncertain=True)
        if arguments['action'] == 'screenshot':
            return {'width': 2, 'height': 2}
        if arguments['action'] == 'observe':
            return {'elements': [{'selector_key': 'note', 'reference': 'rev:note', 'value': 'iris-ok'}]}
        if arguments['action'] == 'input.key':
            return {'effect_semantically_verified': True}
        return {}


def _guest_document(task_id, pid=5151):
    profile = {'window_title': 'guest-double'}
    if pid is not None:
        profile['identity'] = {'pid': pid}
    return {'job_id': 'b' * 32, 'profile': profile, 'task': {
        'workspace_id': WORKSPACE, 'work_item_id': WORK, 'machine_id': MACHINE,
        'capability_id': CAP, 'task_id': task_id, 'selector_key': 'note', 'text': 'iris-ok',
        'expected': {'value': 'iris-ok'}, 'capture_output': 'C:/iris/guest-capture.png'}}


def _guest(document, directory, perform, control):
    lines = []
    ran = run_guest_request(document, directory=directory, perform=perform, emit=lines.append,
                            checkpoint=lambda: None, control=control, owner=OWNER,
                            principal_id=AGENT, resource_id=RESOURCE)
    return ran, lines[-1]


def test_guest_cycle_does_not_reach_the_engine_without_a_grant(central, tmp_path):
    engine = _GuestDouble()
    ran, result = _guest(_guest_document('task-nogrant'), tmp_path, engine, central)
    assert ran is False and result['state'] == 'DENIED'
    assert result['dispatched'] is False and engine.calls == []


def test_guest_refuses_before_the_engine_without_a_process_id(central, tmp_path):
    _grant_and_hold(central)
    engine = _GuestDouble(process_id=5151)
    _ran, result = _guest(_guest_document('task-nopid', pid=None), tmp_path, engine, central)
    assert result['code'] == 'guest_process_id_required'
    assert result['dispatched'] is False and result['automatic_resend'] is False
    assert engine.calls == []


def test_guest_first_request_runs_the_cycle_and_reads_the_value(central, tmp_path):
    _grant_and_hold(central)
    engine = _GuestDouble()
    ran, result = _guest(_guest_document('task-read'), tmp_path, engine, central)
    assert ran is True and result['state'] == 'SUCCEEDED'
    assert result['value'] == 'iris-ok' and result['process_id'] == 5151
    assert engine.calls == ['screenshot', 'observe', 'input.mouse', 'observe', 'input.key', 'observe']
    assert engine.seen_process == [5151, 5151]
    mouse = central.durable.operation_status('op-task-read-mouse', OWNER)
    assert mouse['state'] == 'SUCCEEDED' and mouse['run_id'] == RUN


def test_guest_uncertain_effect_is_not_sent_to_the_engine_again(central, tmp_path):
    _grant_and_hold(central)
    engine = _GuestDouble(mouse_state='UNCERTAIN')
    document = _guest_document('task-fence')
    _ran, first = _guest(document, tmp_path, engine, central)
    assert first['state'] == 'UNCERTAIN' and first['value'] is None
    assert engine.calls == ['screenshot', 'observe', 'input.mouse']
    _ran, second = _guest(document, tmp_path, engine, central)
    assert second['code'] == 'uncertain_input_not_repeated'
    assert second['dispatched'] is False and second['automatic_resend'] is False
    assert engine.calls == ['screenshot', 'observe', 'input.mouse']


def test_authorized_executor_supplies_the_process_and_reads_the_backend(central, tmp_path):
    """The binding pid, not a double attribute, is what reaches the engine."""
    _grant_and_hold(central)
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    binding = SemanticUIABinding(
        CAP, ProcessIdentity(4242, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1),
        (UIASelector('note', 'Note', 'Edit', actions=('read', 'input.mouse', 'input.key')),),
        paths, actions=('observe', 'screenshot', 'input.mouse', 'input.key'))

    class Backend:
        def __init__(self):
            self.calls = []
        def run(self, _binding, args):
            self.calls.append((args['action'], args.get('_process_id')))
            if args['action'] == 'screenshot':
                return {'width': 2, 'height': 2}
            if args['action'] == 'observe':
                return {'elements': [{'selector_key': 'note', 'reference': 'rev:note', 'value': 'from-executor'}]}
            return {}

    backend = Backend()
    executor = SemanticUIAExecutor(
        machine_id=MACHINE, owner_principal_id=AGENT, bindings=(binding,),
        backend=backend, uncertain=InputControl(central, owner=OWNER),
        policy=lambda _request: PolicyDecision(True, 'work item grant already checked'))

    async def dispatch(_ws, _work, _machine, _cap, operation_id, arguments, _key):
        request = OperationRequest(operation_id, AGENT, MACHINE, CAP, WORK, operation_id, arguments)
        result = await executor.start(request)
        return {'operation_id': result.operation_id, 'state': result.state,
                'evidence': dict(result.evidence or {}), 'error': result.error}

    receipt = asyncio.run(GraphicalComputerUse(
        dispatch, control=central, owner=OWNER, principal_id=AGENT, resource_id=RESOURCE).run(
        workspace_id=WORKSPACE, work_item_id=WORK, machine_id=MACHINE, capability_id=CAP,
        task_id='task-exec', selector_key='note', text='iris-ok', expected={'value': 'from-executor'},
        capture_output=str(tmp_path / 'executor-capture.png')))
    assert receipt['state'] == 'SUCCEEDED'
    assert backend.calls == [
        ('screenshot', None), ('observe', None), ('input.mouse', 4242),
        ('observe', None), ('input.key', 4242), ('observe', None)]
    verify = next(step for step in receipt['steps'] if step['kind'] == 'computer.verify')
    assert verify['evidence']['elements'][0]['value'] == 'from-executor'
    assert verify['evidence']['execution_surface'] == 'host'
    assert verify['evidence']['claims_guest_execution'] is False


def test_guest_placement_does_not_call_the_host_backend(central, tmp_path):
    binding = SemanticUIABinding(
        CAP, ProcessIdentity(4242, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1),
        (UIASelector('note', 'Note', 'Edit', actions=('read', 'input.mouse')),),
        AuthorizedPaths((str(tmp_path),), (str(tmp_path),)), actions=('observe', 'input.mouse'))

    class Backend:
        def run(self, _binding, _args):
            raise AssertionError('host backend ran for guest placement')

    executor = SemanticUIAExecutor(
        machine_id=MACHINE, owner_principal_id=AGENT, bindings=(binding,),
        backend=Backend(), placement='guest')
    with pytest.raises(ExecutorFailure, match='guest_executor_unproven') as raised:
        executor._run(binding, {'action': 'observe'})
    assert raised.value.uncertain is True


def _guest_executor_dispatch(executor):
    async def dispatch(_ws, _work, _machine, _cap, operation_id, arguments, _key):
        request = OperationRequest(operation_id, AGENT, MACHINE, CAP, WORK, operation_id, arguments)
        result = await executor.start(request)
        state = result.state.upper() if isinstance(result.state, str) else 'FAILED'
        return {'operation_id': result.operation_id, 'state': state,
                'evidence': dict(result.evidence or {}), 'error': result.error}
    return dispatch


def test_guest_placement_graphical_cycle_blocks_without_proven_executor(central, tmp_path):
    """Capture must not reach SemanticUIABackend when placement is guest and executor is missing."""
    _grant_and_hold(central)
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    binding = SemanticUIABinding(
        CAP, ProcessIdentity(5151, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1),
        (UIASelector('note', 'Note', 'Edit', actions=('read', 'input.mouse', 'input.key')),),
        paths, actions=('observe', 'screenshot', 'input.mouse', 'input.key'))

    class Backend:
        def run(self, _binding, _args):
            raise AssertionError('host backend ran for guest placement')

    executor = SemanticUIAExecutor(
        machine_id=MACHINE, owner_principal_id=AGENT, bindings=(binding,),
        backend=Backend(), uncertain=InputControl(central, owner=OWNER), placement='guest',
        policy=lambda _request: PolicyDecision(True, 'work item grant already checked'))
    receipt = asyncio.run(GraphicalComputerUse(
        _guest_executor_dispatch(executor), control=central, owner=OWNER,
        principal_id=AGENT, resource_id=RESOURCE).run(
        workspace_id=WORKSPACE, work_item_id=WORK, machine_id=MACHINE, capability_id=CAP,
        task_id='task-guest-blocked', selector_key='note', text='iris-ok',
        expected={'value': 'iris-ok'}, capture_output=str(tmp_path / 'blocked.png')))
    assert receipt['state'] == 'UNCERTAIN'
    assert receipt['mouse_dispatched'] == 0 and receipt['keyboard_dispatched'] == 0
    capture = central.durable.operation_status('op-task-guest-blocked-capture', OWNER)
    assert capture['state'] == 'UNCERTAIN'
    assert (capture.get('result') or {}).get('automatic_resend') is False
    assert InputControl(central, owner=OWNER).uncertain_effect(
        work_item_id=WORK, kind='mouse', selector_key='note') is None


def test_guest_semantic_executor_cycle_marks_guest_on_receipt(central, tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor
    _grant_and_hold(central)
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    binding = SemanticUIABinding(
        CAP, ProcessIdentity(5151, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1),
        (UIASelector('note', 'Note', 'Edit', actions=('read', 'input.mouse', 'input.key')),),
        paths, actions=('observe', 'screenshot', 'input.mouse', 'input.key'))

    class Backend:
        def run(self, _binding, _args):
            raise AssertionError('host backend ran for guest placement')

    def answer(request):
        action = request.get('action') or request['arguments']['action']
        args = request['arguments']
        if action == 'screenshot':
            return {'width': 2, 'height': 2}
        if action == 'observe':
            return {'elements': [{'selector_key': 'note', 'reference': 'rev:note', 'value': 'iris-ok'}]}
        if action == 'input.key':
            return {'effect_semantically_verified': True}
        assert args.get('_process_id') == 5151
        return {}

    guest = InjectableGuestExecutor(answer)
    executor = SemanticUIAExecutor(
        machine_id=MACHINE, owner_principal_id=AGENT, bindings=(binding,),
        backend=Backend(), uncertain=InputControl(central, owner=OWNER),
        placement='guest', guest_executor=guest,
        policy=lambda _request: PolicyDecision(True, 'work item grant already checked'))
    receipt = asyncio.run(GraphicalComputerUse(
        _guest_executor_dispatch(executor), control=central, owner=OWNER,
        principal_id=AGENT, resource_id=RESOURCE).run(
        workspace_id=WORKSPACE, work_item_id=WORK, machine_id=MACHINE, capability_id=CAP,
        task_id='task-guest-exec', selector_key='note', text='iris-ok',
        expected={'value': 'iris-ok'}, capture_output=str(tmp_path / 'guest-exec.png')))
    assert receipt['state'] == 'SUCCEEDED'
    assert receipt['execution_surface'] == 'guest'
    assert receipt['claims_guest_execution'] is True
    assert receipt['host_subprocess'] is False
    verify = next(step for step in receipt['steps'] if step['kind'] == 'computer.verify')
    assert verify['evidence']['execution_surface'] == 'guest'
    assert [call.get('action') or call['arguments']['action'] for call in guest.calls] == [
        'screenshot', 'observe', 'input.mouse', 'observe', 'input.key', 'observe']


def test_uncertain_guest_click_is_not_confirmed_or_followed_by_a_key(central, tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor
    _grant_and_hold(central)
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    binding = SemanticUIABinding(
        CAP, ProcessIdentity(5151, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1),
        (UIASelector('note', 'Note', 'Edit', actions=('read', 'input.mouse', 'input.key')),),
        paths, actions=('observe', 'screenshot', 'input.mouse', 'input.key'))

    class Backend:
        def run(self, _binding, _args):
            raise AssertionError('host backend ran for guest placement')

    def answer(request):
        action = request.get('action') or request['arguments']['action']
        if action == 'screenshot':
            return {'width': 2, 'height': 2}
        if action == 'observe':
            return {'elements': [{'selector_key': 'note', 'reference': 'rev:note', 'value': 'iris-ok'}]}
        if action == 'input.mouse':
            return {
                'execution_uncertain': True, 'claims_guest_execution': True,
                'exit_code': 0, 'execution_surface': 'guest',
            }
        raise AssertionError('key was sent after an uncertain click')

    guest = InjectableGuestExecutor(answer)
    computer = GraphicalComputerUse(
        _guest_executor_dispatch(SemanticUIAExecutor(
            machine_id=MACHINE, owner_principal_id=AGENT, bindings=(binding,),
            backend=Backend(), uncertain=InputControl(central, owner=OWNER),
            placement='guest', guest_executor=guest,
            policy=lambda _request: PolicyDecision(True, 'work item grant already checked'))),
        control=central, owner=OWNER, principal_id=AGENT, resource_id=RESOURCE)
    receipt = asyncio.run(computer.run(
        workspace_id=WORKSPACE, work_item_id=WORK, machine_id=MACHINE, capability_id=CAP,
        task_id='task-guest-uncertain-click', selector_key='note', text='iris-ok',
        expected={'value': 'iris-ok'}, capture_output=str(tmp_path / 'guest-uncertain.png')))
    assert receipt['state'] == 'UNCERTAIN'
    assert receipt['automatic_resend'] is False
    assert receipt.get('claims_guest_execution') is not True
    actions = [call.get('action') or call['arguments']['action'] for call in guest.calls]
    assert actions.count('input.mouse') == 1
    assert 'input.key' not in actions
    again = asyncio.run(computer.run(
        workspace_id=WORKSPACE, work_item_id=WORK, machine_id=MACHINE, capability_id=CAP,
        task_id='task-guest-uncertain-click', selector_key='note', text='iris-ok',
        expected={'value': 'iris-ok'}, capture_output=str(tmp_path / 'guest-uncertain.png')))
    assert again['state'] == 'UNCERTAIN'
    assert again['automatic_resend'] is False
    assert [call.get('action') or call['arguments']['action'] for call in guest.calls].count('input.mouse') == 1


def test_guest_computer_use_calls_the_injected_executor(central, tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor
    _grant_and_hold(central)

    def answer(request):
        action = request['arguments']['action']
        if action == 'screenshot':
            return {'width': 2, 'height': 2}
        if action == 'observe':
            return {'elements': [{'selector_key': 'note', 'reference': 'rev:note', 'value': 'iris-ok'}]}
        if action == 'input.key':
            return {'effect_semantically_verified': True}
        assert request['arguments'].get('_process_id') == 5151
        return {}

    guest = InjectableGuestExecutor(answer)
    ran, result = _guest(_guest_document('task-proven'), tmp_path, guest, central)
    assert ran is True and result['state'] == 'SUCCEEDED'
    assert result['execution_surface'] == 'guest'
    assert result['claims_guest_execution'] is True
    assert result['host_subprocess'] is False
    assert result['value'] == 'iris-ok'
    assert [call['arguments']['action'] for call in guest.calls] == [
        'screenshot', 'observe', 'input.mouse', 'observe', 'input.key', 'observe']
