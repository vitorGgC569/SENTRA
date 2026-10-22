import hashlib,json,time,uuid
from pathlib import Path
import pytest
from test_shell_dot_features import shell,dot
from test_shell_access_profiles import execute
from test_workspace_request_recovery import selector
from test_sentra_runtime_canvas_center_http import request
from sentra_canvas.shell_access import AccessStore


def setup(shell):
    app,server,scope,call=shell;actor=dot(call,'Editor');cid=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    access=call('access_status',conversation_id=cid);path=Path(app.store.workspace(scope['project_id'])['path'])/'login.txt';oid='permission-flow-'+uuid.uuid4().hex
    args={'action':'write','path':str(path),'content':'verified','reason':'Preciso criar a proposta de login para sua revisão.'}
    with pytest.raises(PermissionError):execute(app,scope,access,'computer:file.write',args,oid)
    row=call('access_status',conversation_id=cid)['requests'][0]
    return app,server,scope,call,actor,cid,access,path,oid,args,row


def test_inline_permission_is_exact_timed_and_reconciled_without_second_effect(shell,monkeypatch):
    app,server,scope,call,actor,cid,access,path,oid,args,row=setup(shell)
    assert row['summary']['target']=='login.txt' and row['summary']['duration_seconds']==300
    assert row['summary']['reason']==args['reason'] and not path.exists()
    deadline=row['summary']['expires_at']
    with pytest.raises(PermissionError):execute(app,scope,access,'computer:file.write',args,oid)
    assert call('access_status',conversation_id=cid)['requests'][0]['summary']['expires_at']==deadline
    body={'action':'access_approve',**scope,'conversation_id':cid,'target_operation_id':oid,'expected_fingerprint':row['fingerprint'],'request_key':uuid.uuid4().hex}
    value=app.shell_bridge(body)['value'];assert path.read_text()=='verified' and value['result']['state']=='SUCCEEDED'
    assert value['panel_hint']=={'kind':'files','resourceId':'login.txt'}
    monkeypatch.setattr(app._machine_service(),'dispatch',lambda **_k:pytest.fail('receipt inspection repeated the physical action'))
    read=call('conversation_permission_status',conversation_id=cid,selector=selector(body))
    assert read['resolved'] and not read['automatic_retry'] and path.read_text()=='verified'
    foreign=dot(call,'Foreign');other=call('conversation_create',dot_id=foreign['dot_id'])['conversation_id']
    assert request(server,'/api/shell/bridge',json_body={'action':'conversation_permission_status',**scope,'conversation_id':other,'selector':selector(body)})[0]==403


def test_expired_and_modified_permissions_do_not_execute(shell):
    app,server,scope,call,actor,cid,access,path,oid,args,row=setup(shell)
    store=AccessStore(app._shell_service(),app._runtime().owner)
    store.save_request(cid,{**store.requests(cid)[0],'expires_at':time.time()-1})
    body={'action':'access_approve',**scope,'conversation_id':cid,'target_operation_id':oid,'expected_fingerprint':row['fingerprint'],'request_key':uuid.uuid4().hex}
    assert request(server,'/api/shell/bridge',json_body=body)[0]==403 and not path.exists()
    read=call('conversation_permission_status',conversation_id=cid,selector=selector(body))
    assert read['resolved'] and read['result']['status']=='admission_failed'
    with pytest.raises(PermissionError):execute(app,scope,access,'computer:file.write',{**args,'content':'changed'},oid)
    assert not path.exists()
