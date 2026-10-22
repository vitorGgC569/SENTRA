"""Read real protected intents through HTTP; reconciliation cannot replay them."""
from contextlib import closing
import hashlib
import json
import pytest
from test_shell_dot_features import shell,dot
from test_sentra_runtime_canvas_center_http import request
from sentra_canvas.shell_requests import ShellHostRequests


def selector(original):
    payload={k:v for k,v in original.items() if k not in {'action','project_id','request_key'}}
    return {'action':original['action'],'request_key':original['request_key'],
            'fingerprint':hashlib.sha256(json.dumps([original['action'],payload],sort_keys=True,
                separators=(',',':'),allow_nan=False).encode()).hexdigest()}


def move(app,scope,call,actor):
    graph=call('dot_canvas_get',dot_id=actor['dot_id'])
    return {'action':'dot_canvas_move',**scope,'dot_id':actor['dot_id'],
            'request_key':'original-move-key','id':graph['nodes'][0]['id'],'x':17,'y':29}


def test_read_original_intent_after_reopening_journal_never_replays(shell,monkeypatch):
    app,server,scope,call=shell
    actor=dot(call,'Recover');original=move(app,scope,call,actor)
    assert app.shell_bridge(original)['value']['status']=='applied'
    monkeypatch.setattr(app,'graph_move',lambda *_a,**_k:pytest.fail('read replayed a physical action'))
    for _ in range(2):
        ShellHostRequests(app._shell_service(),app._runtime().owner)
        value=call('workspace_request_status',dot_id=actor['dot_id'],selector=selector(original))
        assert value['found'] and value['resolved'] and value['automatic_retry'] is False
        assert value['result']['status']=='applied'
        assert 'original' not in value and 'intent' not in value
    with closing(app._shell_service().store.connect('shell')) as db:
        assert db.execute('SELECT COUNT(*) FROM canvas_shell_host_requests WHERE request_key=?',
                          (original['request_key'],)).fetchone()[0]==1


def test_scope_and_payload_changes_are_rejected(shell):
    app,server,scope,call=shell
    first,second=dot(call,'First'),dot(call,'Second')
    original=move(app,scope,call,first);app.shell_bridge(original)
    for actor,selection in [(second,selector(original)),(first,{**selector(original),'fingerprint':'0'*64})]:
        code,body=request(server,'/api/shell/bridge',json_body={'action':'workspace_request_status',
            **scope,'dot_id':actor['dot_id'],'selector':selection})
        assert code!=200
        assert 'protected_intent' not in str(body)


def test_absent_and_uncertain_requests_do_not_reserve_or_reexecute(shell):
    app,server,scope,call=shell
    actor=dot(call,'Unknown');original=move(app,scope,call,actor)
    value=call('workspace_request_status',dot_id=actor['dot_id'],selector=selector(original))
    assert not value['found'] and not value['resolved'] and not value['automatic_retry']
    journal=ShellHostRequests(app._shell_service(),app._runtime().owner)
    seen=[]
    def effect():
        seen.append('effect');raise RuntimeError('confirmation lost')
    payload={k:v for k,v in original.items() if k not in {'action','project_id','request_key'}}
    with pytest.raises(RuntimeError):journal.invoke(scope['project_id'],original['action'],payload,original['request_key'],effect)
    value=call('workspace_request_status',dot_id=actor['dot_id'],selector=selector(original))
    assert value['found'] and not value['resolved'] and value['receipt']['stage']=='uncertain'
    assert seen==['effect']


def test_inventory_uses_delivery_projection_in_production_route(shell):
    _app,_server,_scope,call=shell
    actor=dot(call,'Inventory')
    value=call('workspace_inventory',dot_id=actor['dot_id'])
    assert value['receipts']==[] and value['restoration_creates_resources'] is False


def test_request_schema_migration_and_future_version_are_explicit(shell):
    app,_server,_scope,_call=shell
    control=app._shell_service();owner=app._runtime().owner
    ShellHostRequests(control,owner)
    with closing(control.store.connect('shell')) as db,db:
        assert db.execute('SELECT version FROM canvas_shell_request_schema WHERE id=1').fetchone()[0]==2
        assert 'protected_intent' in {r[1] for r in db.execute('PRAGMA table_info(canvas_shell_host_requests)')}
        db.execute('UPDATE canvas_shell_request_schema SET version=999')
    try:
        with pytest.raises(RuntimeError,match='newer'):ShellHostRequests(control,owner)
    finally:
        with closing(control.store.connect('shell')) as db,db:db.execute('UPDATE canvas_shell_request_schema SET version=2')


@pytest.mark.parametrize('state',['UNCERTAIN','RUNNING','WAITING_EXTERNAL','RESERVED','FUTURE_UNKNOWN_STATE'])
def test_recorded_host_response_does_not_resolve_open_physical_operation(shell,state):
    app,_server,scope,call=shell
    actor=dot(call,'Open operation');original=move(app,scope,call,actor)
    journal=ShellHostRequests(app._shell_service(),app._runtime().owner)
    payload={k:v for k,v in original.items() if k not in {'action','project_id','request_key'}}
    journal.invoke(scope['project_id'],original['action'],payload,original['request_key'],lambda:{'state':state})
    value=call('workspace_request_status',dot_id=actor['dot_id'],selector=selector(original))
    assert value['found'] and value['resolved'] is False
