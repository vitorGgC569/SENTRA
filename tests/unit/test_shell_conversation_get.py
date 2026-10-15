"""Restore exact current conversation identity without depending on list pages."""
import time
import uuid
import urllib.error
import urllib.request
import pytest
from sentra_core.conversations import _encode

from test_shell_dot_features import shell, dot
from test_sentra_runtime_canvas_center_http import request


def setup(shell):
    app, server, scope, call = shell
    actor = dot(call, 'Conversation lookup QA')
    conversation = call('conversation_create', dot_id=actor['dot_id'])
    return app, server, scope, call, conversation


def snapshot(app):
    with app._shell_runtime.control.store.connect('shell') as db:
        return {table: [tuple(row) for row in db.execute('SELECT * FROM '+table)]
            for table in ('shell_entities','shell_requests','shell_events','shell_receipts','shell_messages')}


def test_exact_conversation_get_restores_an_entity_outside_home_and_first_list_page(shell, monkeypatch):
    app, server, scope, call, conversation = setup(shell)
    coordinator, owner = app._shell_runtime.control.shell, app._shell_runtime.owner
    # Only the pagination fixture is seeded directly; target creation and
    # retrieval use the real authenticated Canvas/Control Plane paths.
    with coordinator.store.connect('shell') as db:
        target = coordinator._entity(db, owner, scope['project_id'], 'conversation', conversation['conversation_id'])
        for index in range(55):
            value = {**target,'conversation_id':'conversation-page-'+uuid.uuid4().hex,
                'created_at':time.time()+index+1,'updated_at':time.time()+index+1,'revision':1}
            coordinator._put(db, owner, scope['project_id'], 'conversation', value)
    first = call('conversation_list', limit=50)
    assert first['page']['total'] == 56 and first['page']['next_offset'] == 50
    assert conversation['conversation_id'] not in {item['conversation_id'] for item in first['items']}
    home = call('home')
    assert conversation['conversation_id'] not in {item['conversation_id'] for item in home['conversations']}
    def no_migration(*_args, **_kwargs):
        pytest.fail('Exact conversation lookup must not migrate entities or consult list pages')
    monkeypatch.setattr(coordinator, '_migrate', no_migration)
    monkeypatch.setattr(coordinator, '_list', no_migration)
    before = snapshot(app)
    code, result = request(server, '/api/shell/bridge', json_body={
        'action':'conversation_get', **scope,'conversation_id':conversation['conversation_id']})
    assert code == 200
    assert result['value'] == target
    assert snapshot(app) == before


def test_conversation_get_rejects_nonexistent_wrong_space_and_extra_selectors(shell):
    app, server, scope, call, conversation = setup(shell)
    with pytest.raises(FileNotFoundError):
        app.shell_bridge({'action':'conversation_get',**scope,'conversation_id':'conversation-missing'})
    other_space = call('space_create',name='Other lookup Space')['space_id']
    with pytest.raises(PermissionError):
        app.shell_bridge({'action':'conversation_get',**scope,'space_id':other_space,
                          'conversation_id':conversation['conversation_id']})
    for extra in ({'limit':1},{'content':'must not become a send'},{'dot_id':conversation['dot_id']}):
        with pytest.raises(ValueError):
            app.shell_bridge({'action':'conversation_get',**scope,'conversation_id':conversation['conversation_id'],**extra})
    with pytest.raises(ValueError):
        app.shell_bridge({'action':'conversation_get','project_id':scope['project_id'],
                          'conversation_id':conversation['conversation_id']})
    code,_ = request(server,'/api/shell/bridge',authorized=False,json_body={
        'action':'conversation_get',**scope,'conversation_id':conversation['conversation_id']})
    assert code == 401


def test_conversation_get_does_not_cross_owner_or_project_scope(shell):
    app, server, scope, call, conversation = setup(shell)
    coordinator, owner = app._shell_runtime.control.shell, app._shell_runtime.owner
    with coordinator.store.connect('shell') as db:
        target = coordinator._entity(db,owner,scope['project_id'],'conversation',conversation['conversation_id'])
        coordinator._put(db,'another-owner',scope['project_id'],'conversation',{
            **target,'conversation_id':'conversation-private-other-owner','title':'not disclosed'})
    with pytest.raises(FileNotFoundError):
        app.shell_bridge({'action':'conversation_get',**scope,'conversation_id':'conversation-private-other-owner'})
    with pytest.raises(PermissionError):
        coordinator.dispatch('another-owner',project_id=scope['project_id'],action='conversation_get',
                             payload={'space_id':scope['space_id'],'conversation_id':conversation['conversation_id']})
    other_project = app.create_workspace('Different_lookup_project')['id']
    other_home = app.shell_bridge({'action':'home','project_id':other_project})['value']
    with pytest.raises(FileNotFoundError):
        app.shell_bridge({'action':'conversation_get','project_id':other_project,
                          'space_id':other_home['space']['space_id'],'conversation_id':conversation['conversation_id']})
    assert app.shell_bridge({'action':'conversation_get',**scope,'conversation_id':conversation['conversation_id']})['value'] == target


def test_conversation_get_observes_current_entity_revision_and_removal(shell):
    app, server, scope, call, conversation = setup(shell)
    coordinator,owner = app._shell_runtime.control.shell,app._shell_runtime.owner
    selectors={'action':'conversation_get',**scope,'conversation_id':conversation['conversation_id']}
    first = app.shell_bridge(selectors)['value']
    with coordinator.store.connect('shell') as db:
        current={**first,'title':'Current canonical title','revision':first['revision']+1,'updated_at':time.time()}
        coordinator._put(db,owner,scope['project_id'],'conversation',current)
    assert app.shell_bridge(selectors)['value'] == current
    with coordinator.store.connect('shell') as db:
        db.execute("DELETE FROM shell_entities WHERE owner=? AND project_id=? AND kind='conversation' AND entity_id=?",
            (owner,scope['project_id'],conversation['conversation_id']))
    before=snapshot(app)
    with pytest.raises(FileNotFoundError):app.shell_bridge(selectors)
    assert snapshot(app)==before


def test_conversation_get_revalidates_current_bearer_after_session_revocation(shell):
    app,server,scope,call,conversation=setup(shell)
    selectors={'action':'conversation_get',**scope,'conversation_id':conversation['conversation_id']}
    assert app.shell_bridge(selectors)['value']['conversation_id']==conversation['conversation_id']
    import json
    old_secret=server.secret
    server.secret='rotated-lookup-session-'+uuid.uuid4().hex
    before=snapshot(app)
    req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/shell/bridge',
        data=json.dumps(selectors).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+old_secret})
    with pytest.raises(urllib.error.HTTPError) as expired:urllib.request.urlopen(req,timeout=5)
    assert expired.value.code==401
    expired.value.close()
    assert snapshot(app)==before
    assert request(server,'/api/shell/bridge',json_body=selectors)[0]==200


def test_conversation_get_refuses_inconsistent_stored_identity(shell):
    app,server,scope,call,conversation=setup(shell)
    selectors={'action':'conversation_get',**scope,'conversation_id':conversation['conversation_id']}
    for forged in ({'project_id':'another-project'},{'conversation_id':'conversation-different-identity'}):
        with app._shell_runtime.control.store.connect('shell') as db:
            db.execute("UPDATE shell_entities SET body=? WHERE owner=? AND project_id=? AND kind='conversation' AND entity_id=?",
                (_encode({**conversation,**forged}),app._shell_runtime.owner,scope['project_id'],conversation['conversation_id']))
        before=snapshot(app)
        with pytest.raises(PermissionError):app.shell_bridge(selectors)
        assert snapshot(app)==before
