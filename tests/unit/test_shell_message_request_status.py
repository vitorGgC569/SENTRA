"""Inspect a lost send ACK without replaying a prompt or creating an intent."""
import uuid
import pytest
from sentra_core.conversations import _encode
from test_shell_dot_features import shell, dot
from test_sentra_runtime_canvas_center_http import request


def setup_scope(shell, monkeypatch, delivery='queued'):
    app, server, scope, call = shell
    actor = dot(call, 'Message status QA')
    conversation = call('conversation_create', dot_id=actor['dot_id'])['conversation_id']
    scope = {**scope, 'conversation_id': conversation}
    sends = []
    def dispatch(*arguments):
        sends.append(arguments)
        return {'status': delivery, 'receipt_id': None}
    monkeypatch.setattr(app._shell_runtime, 'dispatch_message', dispatch)
    return app, server, scope, sends


def snapshot(app):
    with app._shell_runtime.control.store.connect('shell') as db:
        return {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
            for table in ('shell_requests', 'shell_messages', 'shell_message_requests', 'shell_events', 'shell_receipts')}


def test_missing_send_request_is_read_only_and_never_becomes_a_send(shell, monkeypatch):
    app, server, scope, sends = setup_scope(shell, monkeypatch)
    key = 'missing-' + uuid.uuid4().hex
    before = snapshot(app)
    for _ in range(2):
        code, result = request(server, '/api/shell/bridge', json_body={
            'action': 'message_request_status', **scope, 'request_key': key})
        assert code == 200
        value = result['value']
        assert value == {'status': 'unverified', 'request_key': key, 'confirmed': False,
                         'found': False, 'automatic_retry': False, 'resent': False}
    assert snapshot(app) == before and sends == []


def test_lost_ack_reads_exact_stored_message_without_dispatch_or_runtime_reconcile(shell, monkeypatch):
    app, server, scope, sends = setup_scope(shell, monkeypatch)
    key = 'acked-' + uuid.uuid4().hex
    original = app.shell_bridge({'action': 'message_send', **scope, 'request_key': key, 'content': 'Do not repeat this prompt'})['value']
    assert len(sends) == 1
    def forbidden(*_args, **_kwargs):
        pytest.fail('Status inspection must not dispatch or reconcile a runtime effect')
    monkeypatch.setattr(app._shell_runtime, 'dispatch_message', forbidden)
    monkeypatch.setattr(app._shell_runtime, 'reconcile_message', forbidden)
    before = snapshot(app)
    for _ in range(2):
        result = app.shell_bridge({'action': 'message_request_status', **scope, 'request_key': key})['value']
        assert result['confirmed'] is True and result['status'] == 'confirmed'
        assert result['confirmation_kind'] == 'stored_message'
        assert result['automatic_retry'] is False and result['resent'] is False
        message = result['message']
        assert message['message_id'] == original['message_id'] and message['request_key'] == key
        assert message['conversation_id'] == scope['conversation_id']
        assert message['status'] == 'queued'  # acceptance does not certify model completion
    assert snapshot(app) == before and len(sends) == 1


def test_uncertain_or_unacknowledged_request_stays_uncertain_without_side_effect(shell, monkeypatch):
    app, server, scope, sends = setup_scope(shell, monkeypatch, delivery='uncertain')
    key = 'uncertain-' + uuid.uuid4().hex
    app.shell_bridge({'action': 'message_send', **scope, 'request_key': key, 'content': 'Keep uncertain'})
    before = snapshot(app)
    value = app.shell_bridge({'action': 'message_request_status', **scope, 'request_key': key})['value']
    assert value['status'] == 'uncertain' and value['confirmed'] is False
    assert snapshot(app) == before and len(sends) == 1
    with app._shell_runtime.control.store.connect('shell') as db:
        db.execute("UPDATE shell_requests SET state='dispatching',protected_result=NULL WHERE request_key=?", (key,))
    before = snapshot(app)
    value = app.shell_bridge({'action': 'message_request_status', **scope, 'request_key': key})['value']
    assert value['status'] == 'uncertain' and value['confirmed'] is False
    assert snapshot(app) == before and len(sends) == 1


def test_request_inspection_enforces_conversation_space_action_and_exact_read_payload(shell, monkeypatch):
    app, server, scope, sends = setup_scope(shell, monkeypatch)
    key = 'scoped-' + uuid.uuid4().hex
    app.shell_bridge({'action': 'message_send', **scope, 'request_key': key, 'content': 'Private original'})
    _, _, _, call = shell
    actor = dot(call, 'Other status QA')
    other = call('conversation_create', dot_id=actor['dot_id'])['conversation_id']
    with pytest.raises(PermissionError):
        app.shell_bridge({'action': 'message_request_status', **scope, 'conversation_id': other, 'request_key': key})
    with pytest.raises(PermissionError):
        app.shell_bridge({'action': 'message_request_status', **scope, 'space_id': 'other-space', 'request_key': key})
    with pytest.raises(ValueError):
        app.shell_bridge({'action': 'message_request_status', **scope, 'request_key': key, 'content': 'must never be accepted'})
    with pytest.raises(ValueError):
        app.shell_bridge({'action': 'message_request_status', **scope})
    with app._shell_runtime.control.store.connect('shell') as db:
        another_action = db.execute("SELECT request_key FROM shell_requests WHERE action='dot_create' LIMIT 1").fetchone()['request_key']
    with pytest.raises(PermissionError):
        app.shell_bridge({'action': 'message_request_status', **scope, 'request_key': another_action})
    code, _ = request(server, '/api/shell/bridge', authorized=False,
        json_body={'action': 'message_request_status', **scope, 'request_key': key})
    assert code == 401 and len(sends) == 1


def test_forged_or_missing_ack_cannot_confirm_a_stored_message(shell, monkeypatch):
    app, server, scope, sends = setup_scope(shell, monkeypatch)
    key = 'forged-' + uuid.uuid4().hex
    app.shell_bridge({'action': 'message_send', **scope, 'request_key': key, 'content': 'An existing message is not a forged ACK'})
    with app._shell_runtime.control.store.connect('shell') as db:
        db.execute("UPDATE shell_requests SET protected_result=? WHERE request_key=?", (
            _encode({'ok': True, 'value': {'message_id': 'different-message', 'conversation_id': scope['conversation_id']}}), key))
    before = snapshot(app)
    value = app.shell_bridge({'action': 'message_request_status', **scope, 'request_key': key})['value']
    assert value['status'] == 'uncertain' and value['confirmed'] is False
    assert snapshot(app) == before and len(sends) == 1
