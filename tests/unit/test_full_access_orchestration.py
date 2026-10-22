import json,uuid
from pathlib import Path
import pytest
from test_shell_dot_features import shell
from test_shell_actor_children import _dot,_linked_node_ids,_prepare_parent_turn,_actor_for
from sentra_canvas.full_access import source,prepare_turn,prepare_resources
from sentra_canvas.shell_access import AccessStore


def setup(shell,monkeypatch):
    app,_,scope,call=shell
    monkeypatch.setattr(app._shell_runtime,'_execute',lambda _:None)
    root=_dot(call,'FullCoordinator')
    child=_dot(call,'FullWorker','worker',canvas_root_dot_id=root['dot_id'])
    parent=call('conversation_create',dot_id=root['dot_id'])
    convo=call('conversation_create',dot_id=child['dot_id'],parent_conversation_id=parent['conversation_id'])
    a,b=_linked_node_ids(app,scope['project_id'],{**root,**scope},{**child,**scope})
    app.graph_link(scope['project_id'],a,b)
    profile=call('access_set',conversation_id=parent['conversation_id'],mode='full')
    message=_prepare_parent_turn(app,call,{**root,**scope},parent['conversation_id'])
    actor,owner,_=_actor_for(app,message,root,monkeypatch)
    return app,scope,call,root,child,parent,convo,profile,message,actor,owner


def reply(data,content='Write the result'):
    app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    return actor.dispatch('unit-token',{'action':'child_reply','workspace':app.store.workspace(scope['project_id'])['path'],
        'value':json.dumps({'conversation_id':convo['conversation_id'],'content':content}),'request_key':uuid.uuid4().hex})


def test_full_mode_derives_own_child_scopes_and_revokes_every_descendant(shell,monkeypatch):
    data=setup(shell,monkeypatch)
    app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    result=reply(data)
    assert result['status']=='recorded',result
    control=app._shell_service()
    child_access=call('access_status',conversation_id=convo['conversation_id'])
    assert child_access['mode']=='full' and child_access['full_source']['work_item_id']==profile['work_item_id'],(child_access,result)
    grants=control.authorization.list_grants(owner,principal_type='agent',principal_id=child['agent_id'])['items']
    own=[g for g in grants if g.get('scope_id')==result['child']['work_item_id'] and not g['revoked']]
    assert [g['capability'] for g in own]==['model:invoke']
    path=Path(app.store.workspace(scope['project_id'])['path'])/'child-full.txt'
    op=uuid.uuid4().hex
    written=app.center_execute(scope['project_id'],child_access['work_item_id'],child_access['machine_id'],
        'computer:file.write',op,{'action':'write','path':str(path),'content':'derived'},op)
    assert written['state']=='SUCCEEDED' and path.read_text()=='derived'
    call('access_set',conversation_id=parent['conversation_id'],mode='ask')
    assert source(control,owner,convo['conversation_id']) is None
    assert call('access_status',conversation_id=convo['conversation_id'])['delegation_revoked']
    with pytest.raises(PermissionError):
        op=uuid.uuid4().hex
        app.center_execute(scope['project_id'],child_access['work_item_id'],child_access['machine_id'],
            'computer:file.write',op,{'action':'write','path':str(path),'content':'must not run'},op)
    assert path.read_text()=='derived'
    assert all(g['revoked'] for g in control.authorization.list_grants(owner,principal_type='agent',principal_id=child['agent_id'])['items'] if g['scope_id']==result['child']['work_item_id'])


def test_explicit_child_restriction_wins_and_full_does_not_escape_canvas(shell,monkeypatch):
    data=setup(shell,monkeypatch)
    app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    call('access_set',conversation_id=convo['conversation_id'],mode='ask')
    result=reply(data)
    assert result['child']['status']=='waiting_approval'
    assert call('access_status',conversation_id=convo['conversation_id'])['mode']=='ask'
    foreign=_dot(call,'OtherRoot')
    foreign_convo=call('conversation_create',dot_id=foreign['dot_id'],parent_conversation_id=parent['conversation_id'])
    data=list(data);data[6]=foreign_convo
    with pytest.raises(PermissionError):reply(data)


def test_full_selection_prepares_turn_without_manual_grants_and_never_replays(shell,monkeypatch):
    data=setup(shell,monkeypatch)
    app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    control=app._shell_service()
    grants=control.authorization.list_grants(owner,principal_type='agent',principal_id=root['agent_id'])['items']
    scoped=[g for g in grants if g.get('scope_id')==message['work_item_id'] and not g['revoked']]
    assert {'model:invoke','canvas.coordinator.dot_create','canvas.coordinator.handoff'} <= {g['capability'] for g in scoped}
    control.durable.update_operation(message['operation_id'],owner,state='UNCERTAIN')
    assert not prepare_turn(app._shell_runtime,message,root)
    assert control.durable.operation_status(message['operation_id'],owner)['state']=='UNCERTAIN'


def test_full_resource_preparation_does_not_start_terminal_and_is_revocable(shell,monkeypatch):
    data=setup(shell,monkeypatch)
    app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    before=len(app._sessions)
    prepare_resources(app._shell_runtime,message,root)
    assert len(app._sessions)==before
    catalog=app._machine_service().task_catalog(workspace_id=scope['project_id'],agent_ids={root['agent_id']},conversation_id=parent['conversation_id'])
    terminal=[w for w in catalog if 'terminal:start' in w['capabilities']]
    assert len(terminal)==1
    prepare_resources(app._shell_runtime,message,root)
    assert len(app._sessions)==before
    call('access_set',conversation_id=parent['conversation_id'],mode='ask')
    grants=app._shell_service().authorization.list_grants(owner,principal_type='agent',principal_id=root['agent_id'])['items']
    assert all(g['revoked'] for g in grants if g['scope_id']==terminal[0]['work_item_id'])
