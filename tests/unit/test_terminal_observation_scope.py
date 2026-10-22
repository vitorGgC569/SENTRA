import os
import time
import uuid
import pytest
from test_shell_dot_features import shell,dot
from test_sentra_runtime_canvas_center_http import request
from sentra_executors.conpty_sessions import PersistentConPTYLedger


def configured(shell,*,live=False):
    app,server,scope,call=shell
    actor=dot(call,'Terminal owner');foreign=dot(call,'Foreign owner')
    conversation=call('conversation_create',dot_id=actor['dot_id'])
    control=app._shell_service();owner=app._runtime().owner;run=app._runtime().run(scope['project_id'])
    machine=app._machine_service().configure_terminal(workspace_id=scope['project_id'],
        workspace_root=app.store.workspace(scope['project_id'])['path'],agent_id=actor['agent_id'],canvas=app)
    work='terminal-read-'+uuid.uuid4().hex
    control.create_work_item(run['run_id'],owner,work_item_id=work,objective='Observe existing terminal',
        assignee_agent_id=actor['agent_id'],required_capabilities=['terminal:read','terminal:write'],
        metadata={'workspace_id':scope['project_id'],'machine_id':machine['machine_id'],
            'conversation_id':conversation['conversation_id']})
    grant=control.authorization_grant(owner,principal_type='agent',principal_id=actor['agent_id'],
        capability='terminal:read',scope_type='work_item',scope_id=work)
    control.transition_work_item(work,owner,'RUNNING')
    terminal=(app.create_terminal if live else app.store.create_terminal)(scope['project_id'],'Observed','powershell')
    PersistentConPTYLedger(control).register(owner,workspace_id=scope['project_id'],terminal_id=terminal['id'],
        run_id=run['run_id'],work_item_id=work,principal_id=actor['agent_id'],name='Observed',shell='powershell')
    envelope={'action':'dot_computer_read',**scope,'dot_id':actor['dot_id'],'conversation_id':conversation['conversation_id'],
        'request':{'action':'terminal_output','machine_id':machine['machine_id'],'work_item_id':work,
            'capability_id':'terminal:read','terminal_id':terminal['id'],'cursor':0}}
    return app,server,actor,foreign,terminal,control,grant,envelope


def test_terminal_frames_are_bounded_unicode_safe_and_scope_checked(shell):
    app,server,actor,foreign,terminal,control,grant,body=configured(shell)
    text='🐋abc'*6000
    for offset in range(0,len(text),8192):app.store.append_terminal_output(body['project_id'],terminal['id'],text[offset:offset+8192])
    code,result=request(server,'/api/shell/bridge',json_body=body)
    assert code==200,result
    frame=result['value'];assert frame['start']==0 and frame['cursor']==16000 and frame['text']==text[:16000]
    assert frame['read_only'] and not frame['automatic_input_replay']
    second={**body,'request':{**body['request'],'cursor':16000}}
    code,result=request(server,'/api/shell/bridge',json_body=second)
    assert code==200 and result['value']['text']==text[16000:]
    assert request(server,'/api/shell/bridge',json_body={**body,'dot_id':foreign['dot_id']})[0]==403
    assert request(server,'/api/shell/bridge',json_body=body,authorized=False)[0]==401
    other=app.store.create_terminal(body['project_id'],'Unbound','powershell')
    forged={**body,'request':{**body['request'],'terminal_id':other['id']}}
    assert request(server,'/api/shell/bridge',json_body=forged)[0]==403
    control.authorization.revoke(grant['grant_id'],app._runtime().owner)
    assert request(server,'/api/shell/bridge',json_body=second)[0]==403


def test_terminal_checkpoint_and_cursor_refuse_foreign_authority(shell):
    app,server,actor,foreign,terminal,control,grant,body=configured(shell)
    for value in [True,-1,10**12+1,'0']:
        code,_=request(server,'/api/shell/bridge',json_body={**body,'request':{**body['request'],'cursor':value}})
        assert code==400
    checkpoint={**body,'request':{k:v for k,v in body['request'].items() if k!='cursor'}}
    checkpoint['request']['action']='terminal_checkpoint'
    code,result=request(server,'/api/shell/bridge',json_body=checkpoint)
    assert code==200 and result['value']['available'] is False
    control.transition_work_item(body['request']['work_item_id'],app._runtime().owner,'BLOCKED')
    assert request(server,'/api/shell/bridge',json_body=body)[0]==403


@pytest.mark.skipif(os.name!='nt',reason='actual Windows ConPTY observation')
def test_terminal_observation_reads_real_existing_conpty_without_input(shell):
    app,server,actor,foreign,terminal,control,grant,body=configured(shell,live=True)
    try:
        app.terminal_input(body['project_id'],terminal['id'],'Write-Output SENTRA_MOBILE_TERMINAL_READ_6248\r')
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            code,result=request(server,'/api/shell/bridge',json_body=body)
            assert code==200,result
            if 'SENTRA_MOBILE_TERMINAL_READ_6248' in result['value']['text']:break
            time.sleep(.05)
        assert 'SENTRA_MOBILE_TERMINAL_READ_6248' in result['value']['text']
        assert len(app._sessions)==1 and result['value']['read_only']
    finally:app.terminal_close(body['project_id'],terminal['id'])
