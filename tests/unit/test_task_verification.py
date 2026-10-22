import json,uuid
from pathlib import Path
import pytest
from test_shell_dot_features import shell
from test_full_access_orchestration import setup
from sentra_canvas.task_verification import confirm_for_publish,recorded


def execute(data,cap,args):
    app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    oid='op-verify-unit-'+uuid.uuid4().hex
    value=app.center_execute(scope['project_id'],profile['work_item_id'],profile['machine_id'],cap,oid,args,oid)
    assert value['state']=='SUCCEEDED'
    return oid


def test_verification_uses_real_read_receipts_and_rechecks_before_publication(shell,monkeypatch):
    data=setup(shell,monkeypatch);app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    path=Path(app.store.workspace(scope['project_id'])['path'])/'evidence.txt'
    execute(data,'computer:file.write',{'action':'write','path':str(path),'content':'result'})
    read=execute(data,'computer:file.read',{'action':'read','path':str(path)})
    payload={'action':'verify_result','workspace':str(path.parent),'value':json.dumps({'operation_ids':[read]}),'request_key':uuid.uuid4().hex}
    result=actor.dispatch('test',payload)
    assert result['status']=='verified' and result['verification']['semantic_correctness_claimed'] is False
    same=actor.dispatch('test',payload)
    assert same['verification']['receipt_id']==result['verification']['receipt_id']
    proof=confirm_for_publish(app._shell_runtime,message)
    assert proof['verified'] and proof['finalized'] and proof['files'][0]['final_observation_operation_id']
    assert recorded(app._shell_service(),owner,message['work_item_id'])==proof
    app._shell_service().durable.update_operation(message['operation_id'],owner,state='SUCCEEDED')
    from sentra_canvas.task_presentation import decorate_messages
    rows=decorate_messages(app._shell_service(),owner,scope['project_id'],scope['space_id'],parent['conversation_id'],
        [{'role':'user','operation_id':message['operation_id']},{'role':'assistant','operation_id':message['operation_id']}])
    assert rows[0]['task_lifecycle']['stage']=='verified'
    assert 'task_lifecycle' not in rows[1]


def test_changed_file_or_foreign_evidence_cannot_be_verified(shell,monkeypatch):
    data=setup(shell,monkeypatch);app,scope,call,root,child,parent,convo,profile,message,actor,owner=data
    path=Path(app.store.workspace(scope['project_id'])['path'])/'changed.txt'
    write=execute(data,'computer:file.write',{'action':'write','path':str(path),'content':'before'})
    read=execute(data,'computer:file.read',{'action':'read','path':str(path)})
    result=actor.dispatch('test',{'action':'verify_result','workspace':str(path.parent),
        'value':json.dumps({'operation_ids':[read]}),'request_key':uuid.uuid4().hex})
    assert result['status']=='verified'
    with pytest.raises(PermissionError):
        actor.dispatch('test',{'action':'verify_result','workspace':str(path.parent),
            'value':json.dumps({'operation_ids':[write]}),'request_key':uuid.uuid4().hex})
    execute(data,'computer:file.write',{'action':'edit','path':str(path),'content':'after'})
    assert confirm_for_publish(app._shell_runtime,message)['verified'] is False


def test_native_pause_resume_uses_central_runtime_control_method(shell):
    app,_,scope,_=shell
    assert app.run_control(scope['project_id'],'pause')['state']=='PAUSED'
    assert app.run_control(scope['project_id'],'resume')['state']=='RUNNING'
