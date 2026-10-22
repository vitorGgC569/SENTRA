import copy
import pytest
from test_shell_dot_features import shell,dot
from test_sentra_runtime_canvas_center_http import request


def profile():return {'version':1,'layouts':{'simple':{'version':1,'tree':{'type':'leaf','groupId':'main'},'panes':{'main':{'tabs':[{'id':'files:a','kind':'files','resourceId':'a.txt'}],'active':'files:a'}},'focused':'main'}},'recent':[{'id':'files:a','kind':'files','resourceId':'a.txt'}],'sessionNames':{'session-a':'Revisando login'},'started':True,'focusPanels':True}


def test_host_presentation_survives_new_service_and_does_not_start_resources(shell,monkeypatch):
    app,server,scope,call=shell;actor=dot(call,'Resume');params={'dot_id':actor['dot_id']}
    first=call('workspace_presentation_get',**params);assert first['revision']==0 and first['profile'] is None
    monkeypatch.setattr(app,'create_terminal',lambda *_a,**_k:pytest.fail('restoration started a terminal'))
    saved=call('workspace_presentation_save',**params,profile=profile(),expected_revision=0)
    assert saved['saved'] and saved['revision']==1
    from sentra_canvas.workspace_presentation import dispatch_presentation
    restored=dispatch_presentation(app,scope['project_id'],'workspace_presentation_get',{'space_id':scope['space_id'],**params})
    assert restored['profile']==profile() and not restored['restoration_creates_resources']
    other=dot(call,'Other');assert call('workspace_presentation_get',dot_id=other['dot_id'])['profile'] is None
    assert call('workspace_presentation_save',**params,profile=profile(),expected_revision=0)['revision']==1
    changed=copy.deepcopy(profile());changed['sessionNames']['session-a']='Executando servidor'
    conflict=call('workspace_presentation_save',**params,profile=changed,expected_revision=0)
    assert not conflict['saved'] and conflict['conflict']
    assert call('workspace_presentation_get',**params)['profile']==profile()


@pytest.mark.parametrize('damage',['cycle','deep','authority','bad-mode','large-name','bad-resource'])
def test_host_presentation_rejects_invalid_or_executable_state(shell,damage):
    app,server,scope,call=shell;actor=dot(call,'Validate');value=profile()
    if damage=='cycle':value['layouts']['simple']['tree']={'type':'split','direction':'horizontal','ratio':.5,'first':value['layouts']['simple']['tree'],'second':value['layouts']['simple']['tree']}
    elif damage=='deep':value['recent']*=13
    elif damage=='authority':value['grants']=['*']
    elif damage=='bad-mode':value['layouts']['full']=value['layouts']['simple']
    elif damage=='large-name':value['sessionNames']['a']='x'*81
    else:value['layouts']['simple']['panes']['main']['tabs'][0]['kind']='execute'
    body={'action':'workspace_presentation_save',**scope,'dot_id':actor['dot_id'],'profile':value,'expected_revision':0}
    assert request(server,'/api/shell/bridge',json_body=body)[0]==400
