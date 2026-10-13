"""Frequent admission reads preserve live authority without heavy context I/O."""
import pytest
from types import SimpleNamespace
from sentra_canvas.shell_actor import ShellActorService
from sentra_canvas.store import Denied
from sentra_cli.canvas import CanvasBridge


def test_checkpoint_checks_subject_each_time_and_never_builds_graph(monkeypatch):
    message = dict(project_id='p', space_id='s', conversation_id='c', run_id='r',
        work_item_id='w', operation_id='o')
    dot = dict(dot_id='d', agent_id='a')
    actor = ShellActorService(SimpleNamespace(canvas=object(), control=object(), owner='owner'))
    calls = []
    def subject(token, payload):
        calls.append(token)
        if len(calls) > 1:
            raise Denied('shell turn authority was revoked')
        return {'message': message, 'dot': dot}
    monkeypatch.setattr(actor, 'subject', subject)
    payload = {'action': 'checkpoint', 'workspace': 'workspace'}
    assert actor.dispatch('live-token', payload) == {'shell_scope': dict(
        project_id='p', space_id='s', conversation_id='c', dot_id='d', agent_id='a',
        run_id='r', work_item_id='w', parent_operation_id='o')}
    with pytest.raises(Denied):
        actor.dispatch('live-token', payload)
    assert calls == ['live-token', 'live-token']


def test_checkpoint_cannot_select_another_conversation():
    actor = ShellActorService(SimpleNamespace(canvas=object(), control=object(), owner='owner'))
    with pytest.raises(Denied):
        actor.dispatch('token', {'action': 'checkpoint', 'workspace': 'w', 'conversation_id': 'other'})


def test_cli_checkpoint_requests_only_live_binding(monkeypatch):
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN', 'x' * 40)
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT', '12345')
    bridge = CanvasBridge(SimpleNamespace(workspace='w'))
    bodies = []
    monkeypatch.setattr(bridge, '_request', lambda body: bodies.append(body) or {'shell_scope': {}})
    assert bridge.authority_checkpoint() == {'shell_scope': {}}
    assert bodies == [{'action': 'checkpoint', 'workspace': 'w'}]


def test_vm_frame_accepts_bounded_real_desktop_envelope_but_controls_stay_small(monkeypatch):
    import io, json, urllib.request
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN', 'x' * 40)
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT', '12345')
    bridge = CanvasBridge(SimpleNamespace(workspace='w'))
    envelope = {'state': 'SUCCEEDED', 'evidence': {'image_base64': 'x' * 100000}}
    class Opener:
        def open(self, request, **kwargs):
            return io.BytesIO(json.dumps(envelope).encode())
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    assert bridge._request({'action': 'vm_frame'}) == envelope
    with pytest.raises(RuntimeError, match='exceeded limit'):
        bridge._request({'action': 'checkpoint'})
    envelope['evidence']['image_base64'] = 'x' * 2100001
    with pytest.raises(RuntimeError, match='exceeded limit'):
        bridge._request({'action': 'vm_frame'})
