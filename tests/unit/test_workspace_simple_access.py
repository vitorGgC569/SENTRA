import uuid
import pytest
from test_shell_dot_features import shell,dot
from test_sentra_runtime_canvas_center_http import request
from test_workspace_request_recovery import selector


def recipe(scope,actor,cid,profile='read',**fields):
    return {'action':'dot_canvas_access',**scope,'dot_id':actor['dot_id'],'member_dot_id':actor['dot_id'],
        'conversation_id':cid,'profile':profile,'approved':True,'request_key':'recipe-'+uuid.uuid4().hex,**fields}


def test_simple_recipe_prepares_central_task_and_minimal_grants_once(shell,monkeypatch):
    app,server,scope,call=shell;actor=dot(call,'Simple')
    convo=call('conversation_create',dot_id=actor['dot_id'])
    body=recipe(scope,actor,convo['conversation_id'])
    value=app.shell_bridge(body)['value'];assert value['status']=='configured'
    access=value['access'];control=app._shell_service();owner=app._runtime().owner
    item=control.work_item_info(access['work_item_id'],owner)
    assert item['state']=='RUNNING' and item['assignee_agent_id']==actor['agent_id']
    assert item['required_capabilities']==['computer:file.read']
    assert item['metadata']['conversation_id']==convo['conversation_id']
    grants=control.authorization.list_grants(owner,principal_type='agent',principal_id=actor['agent_id'])['items']
    scoped=[g for g in grants if g['scope_id']==item['work_item_id']]
    assert len(scoped)==1 and scoped[0]['capability']=='computer:file.read' and scoped[0]['scope_type']=='work_item'
    from pathlib import Path
    path=Path(app.store.workspace(scope['project_id'])['path'])/'recipe-read.txt';path.write_text('permitted')
    from test_shell_access_profiles import execute
    observed_read=execute(app,scope,access,'computer:file.read',{'action':'read','path':str(path)})
    assert observed_read['state']=='SUCCEEDED' and observed_read['evidence']['content']=='permitted'
    with pytest.raises(PermissionError):execute(app,scope,access,'computer:file.delete',{'action':'delete','path':str(path)})
    with pytest.raises(PermissionError):execute(app,scope,access,'computer:execute',{'command':'Write-Output forbidden'})
    assert path.read_text()=='permitted'
    monkeypatch.setattr(control,'authorization_grant',lambda *_a,**_k:pytest.fail('duplicated grant'))
    assert app.shell_bridge(body)['value']==value
    observed=call('workspace_request_status',dot_id=actor['dot_id'],selector=selector(body))
    assert observed['resolved'] and not observed['automatic_retry'] and observed['result']==value
    assert not value['external_completion_claimed']


@pytest.mark.parametrize('change',[{'approved':False},{'approved':'true'},{'profile':'full'},{'permissions':['*']},{'profile':'auto'}])
def test_recipe_refuses_unconfirmed_or_broadened_authority(shell,change):
    app,server,scope,call=shell;actor=dot(call,'Limited');cid=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    before=call('access_status',conversation_id=cid)
    body=recipe(scope,actor,cid,**change)
    assert request(server,'/api/shell/bridge',json_body=body)[0] in {400,403}
    assert call('access_status',conversation_id=cid)==before


def test_recipes_refuse_foreign_dot_and_conversation_and_unauthenticated_caller(shell):
    app,server,scope,call=shell;actor=dot(call,'One');other=dot(call,'Two')
    cid=call('conversation_create',dot_id=other['dot_id'])['conversation_id']
    assert request(server,'/api/shell/bridge',json_body=recipe(scope,actor,cid))[0]==403
    assert request(server,'/api/shell/bridge',json_body=recipe(scope,actor,cid,member_dot_id=other['dot_id']))[0]==403
    assert request(server,'/api/shell/bridge',json_body=recipe(scope,other,cid),authorized=False)[0]==401


def test_downgrade_revokes_previous_recipe_grants_without_touching_other_conversations(shell):
    app,server,scope,call=shell;actor=dot(call,'Downgrade')
    first=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    other=dot(call,'Independent');second=call('conversation_create',dot_id=other['dot_id'])['conversation_id']
    independent=app.shell_bridge(recipe(scope,other,second))['value']['access']
    broad=app.shell_bridge(recipe(scope,actor,first,'ask'))['value']['access']
    assert broad['scope']=='workspace' and broad['approval']=='ask'
    narrow=app.shell_bridge(recipe(scope,actor,first,'none'))['value']['access']
    assert narrow['capabilities']==[]
    control=app._shell_service();owner=app._runtime().owner
    assert control.work_item_info(broad['work_item_id'],owner)['state']=='CANCELLED'
    grants=control.authorization.list_grants(owner,principal_type='agent',principal_id=actor['agent_id'])['items']
    assert not any(g['scope_id']==broad['work_item_id'] for g in grants)
    assert control.work_item_info(independent['work_item_id'],owner)['state']=='RUNNING'
