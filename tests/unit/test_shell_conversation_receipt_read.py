"""The status button must inspect a durable creation without repeating it."""
import uuid
import pytest
from test_shell_dot_features import shell, dot


def test_conversation_status_reads_exact_key_without_mutation(shell):
    app, server, scope, call = shell
    actor = dot(call, 'Test receipt dot')
    key = 'inspect-' + uuid.uuid4().hex
    payload = {'action':'conversation_create', **scope, 'dot_id':actor['dot_id'],
               'request_key':key}
    original = app.shell_bridge(payload)['value']
    with app._shell_runtime.control.store.connect('shell') as db:
        before = db.execute("SELECT action,state,protected_result FROM shell_requests "
          "WHERE owner=? AND project_id=? AND request_key=?", (
          app._shell_runtime.owner,scope['project_id'],key)).fetchone()
        count_before = db.execute("SELECT COUNT(*) FROM shell_requests").fetchone()[0]
    assert before['action'] == 'conversation_create'
    result = app.shell_bridge({
        'action':'conversation_request_status', **scope, 'dot_id':actor['dot_id'],
        'request_key':key
    })['value']
    assert result['status'] == 'confirmed'
    assert result['confirmed'] is True
    assert result['automatic_retry'] is False
    assert result['conversation']['conversation_id'] == original['conversation_id']
    assert result['conversation']['project_id'] == scope['project_id']
    assert 'instructions' not in result['conversation']
    with app._shell_runtime.control.store.connect('shell') as db:
        after = db.execute("SELECT action,state,protected_result FROM shell_requests "
          "WHERE owner=? AND project_id=? AND request_key=?", (
          app._shell_runtime.owner,scope['project_id'],key)).fetchone()
        count_after = db.execute("SELECT COUNT(*) FROM shell_requests").fetchone()[0]
    assert tuple(after) == tuple(before)
    assert count_after == count_before


def test_missing_or_wrong_scope_is_never_claimed_as_confirmed(shell):
    app, server, scope, call = shell
    first = dot(call,'First receipt dot')
    second = dot(call,'Second receipt dot')
    key = 'inspect-' + uuid.uuid4().hex
    unverified = app.shell_bridge({
      'action':'conversation_request_status',**scope,
      'dot_id':first['dot_id'], 'request_key':key
    })['value']
    assert unverified['status'] == 'unverified'
    assert unverified['automatic_retry'] is False
    app.shell_bridge({'action':'conversation_create', **scope,
      'dot_id':first['dot_id'],'request_key':key})
    bad_scope = app.shell_bridge({'action':'conversation_request_status', **scope,
      'dot_id':second['dot_id'],'request_key':key})['value']
    assert bad_scope['confirmed'] is False
    with pytest.raises(ValueError):
        app.shell_bridge({'action':'conversation_request_status',**scope,
          'dot_id':first['dot_id']})
    with pytest.raises(ValueError):
        app.shell_bridge({'action':'conversation_request_status',**scope,
          'dot_id':first['dot_id'],'request_key':key,'extra':'bad'})
