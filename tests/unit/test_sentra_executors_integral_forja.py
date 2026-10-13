"""Prepared for the coordinated final validation phase; never run during implementation.

Real central SQLite tests cover input possession. Browser/UIA fixtures cover
recovery/publication contracts and make no claim about an external provider.
"""
import base64
from pathlib import Path

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.machine_host import MachineHost
from sentra_executors.input_control import InputControl, InputBoundPolicy, human_input_scope
from sentra_executors.integral import configure_executor, suggest_machines
from sentra_executors.browser_sessions import PersistentPlaywrightBackend
from sentra_executors.identity_sessions import SessionJournal
from sentra_executors.playwright_browser import PlaywrightBrowserBinding, NetworkProfile
from sentra_executors.rpa import AuthorizedPaths, ExecutorFailure
from sentra_executors.uia_semantic import SemanticUIABackend, SemanticUIABinding, DesktopIdentity, UIASelector
from sentra_executors.windows_identity import ProcessIdentity


@pytest.fixture
def central(tmp_path):
    root = tmp_path / 'central'; workspace = tmp_path / 'workspace'; workspace.mkdir()
    durable = DurableRunService(root)
    control = ControlPlaneService(durable, ContextBusService(root))
    owner, agent, run, work = 'owner-forja', 'agent-forja', 'run-forja', 'work-forja'
    control.durable.create_run(owner, run_id=run, workspace=str(workspace))
    control.ensure_agent(run, owner, agent_id=agent, role='worker')
    control.create_work_item(run, owner, work_item_id=work, objective='Scoped interactive input',
        assignee_agent_id=agent, required_capabilities=['uia:input'],
        metadata={'workspace_id': 'ws-forja', 'machine_id': 'machine-forja'})
    control.transition_work_item(work, owner, 'QUEUED')
    control.start_work_item_execution(work, owner, run_id=run, agent_id=agent)
    try:
        yield control, owner, agent, work, workspace
    finally:
        durable.close()


def test_input_possession_requires_real_grant_and_handoff_fences_original_epoch(central):
    control, owner, agent, work, _ = central
    request = OperationRequest('op-forja-input', agent, 'machine-forja', 'uia:input', work,
                               'key-forja-input', {'action': 'invoke'})
    lease = InputControl(control, owner=owner)
    arguments = dict(resource_id='desktop-forja', workspace_id='ws-forja', machine_id='machine-forja',
                     holder='agent', expected_epoch=0, request_key='acquire-1', request=request)
    with pytest.raises(PermissionError):
        lease.handoff(**arguments)
    grant = control.authorization.grant(owner, principal_type='agent', principal_id=agent,
        capability='uia:input', scope_type='work_item', scope_id=work)['grant_id']
    receipt = lease.handoff(**arguments)
    assert receipt['epoch'] == 1 and receipt['grant_created'] is False
    policy = InputBoundPolicy(BoundWorkItemPolicy(owner=owner, principal_type='agent',
        authorization=control.authorization, governance=control.governance),
        control=control, owner=owner, resources={'machine-forja': 'desktop-forja'})
    with policy.scope(request):
        assert policy(request).allowed is True
        lease.handoff(resource_id='desktop-forja', workspace_id='ws-forja', machine_id='machine-forja',
                      holder='human', expected_epoch=1, request_key='handoff-human')
        assert policy(request).allowed is False
        lease.handoff(**dict(arguments, expected_epoch=2, request_key='reacquire-3'))
        # Reacquisition cannot resurrect a worker holding the old epoch.
        assert policy(request).allowed is False
    with policy.scope(request):
        assert policy(request).allowed is True
        control.authorization.revoke(grant, owner)
        assert policy(request).allowed is False


def test_handoff_cas_idempotency_restart_expiry_and_workspace_redaction(central):
    control, owner, _, _, _ = central
    now = [100.0]
    lease = InputControl(control, owner=owner, clock=lambda: now[0])
    arguments = dict(resource_id='desktop-forja', workspace_id='ws-forja', machine_id='machine-forja',
        holder='human', expected_epoch=0, request_key='human-1', ttl_seconds=10)
    value = lease.handoff(**arguments)
    restarted = InputControl(control, owner=owner, clock=lambda: now[0])
    assert restarted.handoff(**arguments) == value
    with pytest.raises(ValueError, match='idempotency_conflict'):
        restarted.handoff(**dict(arguments, holder='none'))
    with pytest.raises(ValueError, match='revision_conflict'):
        restarted.handoff(**dict(arguments, request_key='stale-key'))
    other = restarted.status(resource_id='desktop-forja', workspace_id='ws-other')
    assert other['scope_visible'] is False and 'principal_id' not in other
    assert restarted.status(resource_id='desktop-forja', workspace_id='ws-forja')['live'] is True
    now[0] = 111
    assert restarted.status(resource_id='desktop-forja', workspace_id='ws-forja')['live'] is False
    moved = restarted.handoff(**dict(arguments, workspace_id='ws-other', expected_epoch=1, request_key='other-2'))
    assert moved['epoch'] == 2


class BrowserFixture:
    def __init__(self):
        self.calls = []; self._sessions = {}

    def run(self, binding, arguments):
        self.calls.append(dict(arguments))
        if arguments['action'] == 'open':
            self._sessions['provider-page'] = object()
            return {'session_id': 'provider-page', 'page_id': 'page', 'profile': 'offline'}
        if arguments['action'] == 'observe':
            return {'elements': [{'name': 'fixture-observation'}]}
        return {'action': arguments['action']}

    def shutdown(self):
        self._sessions.clear()


def test_browser_restart_exposes_lost_and_retained_evidence_without_launch_or_input(tmp_path):
    root = tmp_path.resolve(); paths = AuthorizedPaths((str(root),), (str(root),))
    journal = SessionJournal(str(root / 'browser.sqlite3'), paths)
    binding = PlaywrightBrowserBinding('browser:operate', (NetworkProfile('offline'),), artifact_paths=paths)
    backend = BrowserFixture(); wrapper = PersistentPlaywrightBackend(backend, journal)
    arguments = {'action': 'open', 'profile': 'offline', '_scope': 'owned-work', '_operation_id': 'op-open'}
    opened = wrapper.run(binding, arguments); session = opened['session_id']
    assert wrapper.run(binding, arguments) == opened and len(backend.calls) == 1
    wrapper.run(binding, {'action': 'observe', 'session_id': session, '_scope': 'owned-work', '_operation_id': 'op-observe'})
    fresh = BrowserFixture(); recovered = PersistentPlaywrightBackend(fresh, journal)
    context = {'session_id': session, '_scope': 'owned-work', '_operation_id': 'op-status'}
    status = recovered.run(binding, dict(context, action='session.status'))
    assert status['state'] == 'LOST' and status['replay_allowed'] is False
    events = recovered.run(binding, dict(context, action='session.events'))
    assert len(events['events']) == 2 and fresh.calls == []
    with pytest.raises(ExecutorFailure, match='no_automatic_replay'):
        recovered.run(binding, dict(context, action='click'))
    with pytest.raises(ExecutorFailure, match='scope_mismatch'):
        recovered.run(binding, dict(context, action='session.status', _scope='foreign-work'))


class HybridFixture:
    def __init__(self, changed=False):
        self.observations = 0; self.changed = changed

    def invoke(self, *_, input_document, **__):
        arguments = input_document['arguments']
        if arguments['action'] == 'screenshot':
            Path(arguments['_temporary_output']).write_bytes(base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jW1QAAAAASUVORK5CYII='))
            return {'width': 1, 'height': 1, 'window_rectangle': [0, 0, 1, 1]}
        self.observations += 1
        return {'elements': [{'selector_key': 'input', 'runtime_id': [1, 2],
            'value': 'changed' if self.changed and self.observations == 2 else 'stable'}]}


def test_hybrid_observation_publishes_one_consistent_artifact_or_preserves_output(tmp_path):
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    binding = SemanticUIABinding('uia', ProcessIdentity(11, 22, 33, '0' * 64), 'fixture',
        DesktopIdentity('fixture-machine', 1), (UIASelector('input', 'Input', 'Edit'),), paths,
        actions=('observe', 'observe.hybrid'))
    output = tmp_path / 'hybrid.png'
    result = SemanticUIABackend(HybridFixture()).run(binding,
        {'action': 'observe.hybrid', 'output': str(output), '_scope': 'work-one'})
    assert result['observation_mode'] == 'uia_and_window_image'
    assert result['artifact']['sha256'] and result['elements'][0]['reference']
    failed = tmp_path / 'inconsistent.png'
    with pytest.raises(ExecutorFailure, match='changed_during_hybrid'):
        SemanticUIABackend(HybridFixture(changed=True)).run(binding,
            {'action': 'observe.hybrid', 'output': str(failed), '_scope': 'work-one'})
    assert not failed.exists()


def test_host_configuration_persists_provider_without_invoking_uia_or_creating_grant(central):
    control, owner, agent, _, root = central
    host = MachineHost(control, owner=owner)
    config = {'enabled': True, 'bindings': [{'capability_id': 'uia:input', 'window_title': 'fixture',
        'identity': {'pid': 11, 'hwnd': 22, 'creation_filetime': 33, 'executable_sha256': '0' * 64},
        'desktop': {'machine_guid': 'fixture-machine', 'session_id': 1},
        'selectors': [{'key': 'input', 'automation_id': 'Input', 'control_type': 'Edit'}]}]}
    try:
        inventory = configure_executor(host, workspace_id='ws-forja', workspace_root=str(root),
            agent_id=agent, kind='windows_uia_semantic', provider_config=config)
        assert inventory['grant_created'] is False and inventory['provider_verified'] is False
        stored = host.configurations.entries()
        assert stored[0]['configuration']['provider_config'] == config
        assert host._factories[inventory['machine_id']]._declarations[inventory['machine_id']].adapter._records == {}
    finally:
        host.close()


def test_device_suggestion_requires_all_capabilities_and_observed_load():
    candidates = [{'machine_id': 'busy', 'capabilities': ['desktop']},
                  {'machine_id': 'idle', 'capabilities': ['desktop']},
                  {'machine_id': 'unknown', 'capabilities': ['desktop']},
                  {'machine_id': 'wrong', 'capabilities': ['shell']}]
    result = suggest_machines(candidates, required_capabilities=['desktop'],
                              load_by_machine={'busy': 2, 'idle': 0})
    assert [row['machine_id'] for row in result] == ['idle', 'busy', 'unknown']
    assert all(row['suggestion_only'] and not row['grant_created'] for row in result)


def test_human_possession_does_not_authorize_agent_and_requires_authenticated_exact_epoch(central):
    control, owner, agent, work, _ = central
    request = OperationRequest('op-human-forja', agent, 'machine-forja', 'uia:input', work,
                               'key-human-forja', {'action': 'invoke'})
    control.authorization.grant(owner, principal_type='agent', principal_id=agent,
        capability='uia:input', scope_type='work_item', scope_id=work)
    input_control = InputControl(control, owner=owner)
    input_control.handoff(resource_id='desktop-forja', workspace_id='ws-forja', machine_id='machine-forja',
                          holder='human', expected_epoch=0, request_key='human-possession')
    policy = InputBoundPolicy(BoundWorkItemPolicy(owner=owner, principal_type='agent',
        authorization=control.authorization, governance=control.governance),
        control=control, owner=owner, resources={'machine-forja': 'desktop-forja'})
    assert policy(request).allowed is False
    with pytest.raises(PermissionError):
        with human_input_scope(control, owner=owner, workspace_id='ws-forja',
            machine_id='machine-forja', resource_id='desktop-forja', expected_epoch=2):
            pass
    with human_input_scope(control, owner=owner, workspace_id='ws-forja',
            machine_id='machine-forja', resource_id='desktop-forja', expected_epoch=1):
        with policy.scope(request):
            assert policy(request).allowed is True
            input_control.handoff(resource_id='desktop-forja', workspace_id='ws-forja', machine_id='machine-forja',
                                  holder='none', expected_epoch=1, request_key='release-human')
            assert policy(request).allowed is False


def test_readonly_tunnel_rejects_raw_input_and_revoke_retains_scope_for_idempotent_close():
    from types import SimpleNamespace
    from sentra_executors.remote_guacamole_tunnel import GuacamoleTunnelServer
    from sentra_executors.remote_guacamole import encode_instruction
    calls = []
    def dispatch(ticket, arguments):
        calls.append(arguments)
        return {'state': 'SUCCEEDED', 'evidence': {'events': [], 'gap': False}}
    server = GuacamoleTunnelServer(dispatch=dispatch, allowed_origins=('http://127.0.0.1:8888',))
    ticket = server.issue(session_id='session', machine_id='machine', principal_id='agent',
        capability_id='remote:view', work_item_id='work', run_id='run', workspace_id='workspace')
    class Socket:
        request = SimpleNamespace(path=ticket['url'].split(':8766',1)[1])
        def send(self, value):
            pass
        def recv(self, timeout):
            return encode_instruction('key','65','1').decode()
        def close(self, **kwargs):
            self.closed = kwargs
    socket = Socket()
    server.handle(socket)
    assert socket.closed['code'] == 1008
    assert not any(call.get('opcode') == 'key' for call in calls)
    assert server.viewer_scope(ticket['viewer_id']).workspace_id == 'workspace'
    assert server.revoke(ticket['viewer_id'])['closed'] is True


def test_ephemeral_tunnel_port_requires_real_bound_listener_before_issue():
    from sentra_executors.remote_guacamole_tunnel import GuacamoleTunnelServer
    server=GuacamoleTunnelServer(dispatch=lambda *_:None,port=0,
                                 allowed_origins=('http://127.0.0.1:8888',))
    with pytest.raises(ExecutorFailure,match='bind_before_ticket'):
        server.issue(session_id='session',machine_id='machine',principal_id='agent',
                     capability_id='remote:view',work_item_id='work',run_id='run')
