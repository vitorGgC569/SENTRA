"""Real owner HTTP/ConPTY receipts, with explicit post-effect fault injection."""
import hashlib
import json
import os
import time
import uuid
from contextlib import closing
from http.client import RemoteDisconnected
from threading import Thread
import pytest
from test_sentra_runtime_canvas_center_http import running_canvas,request


def fingerprint(terminal,target,data):
    payload={'terminal_id':terminal,'data':data,'input_target':target}
    return hashlib.sha256(json.dumps(['terminal_input',payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()


@pytest.fixture
def terminal(tmp_path):
    if os.name!='nt':pytest.skip('real Windows ConPTY')
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace('InputReceipts')['id']
        row=app.create_terminal(ws,'ReceiptTerminal','cmd')
        code,frame=request(server,f'/api/terminal/output?ws={ws}&id={row["id"]}&cursor=0')
        assert code==200 and frame['input_protocol_version']==1 and frame['input_target']
        def post(data,key=None,target=None):
            key=key or uuid.uuid4().hex;target=target or frame['input_target']
            payload={'ws':ws,'id':row['id'],'data':data,'request_key':key,'input_target':target}
            return request(server,'/api/terminal/input',json_body=payload)
        def status(key,data,target=None,other=None,host=None):
            target=target or frame['input_target'];fp=fingerprint(row['id'],target,data)
            return request(host or server,f'/api/terminal/input-status?ws={ws}&id={other or row["id"]}&request_key={key}&fingerprint={fp}')
        yield app,server,ws,row,frame,post,status


def test_delivered_input_is_protected_deduplicated_and_not_task_completion(terminal):
    app,server,ws,row,frame,post,status=terminal
    key=uuid.uuid4().hex;data='echo SECRET_INPUT_MARKER\r';calls=[]
    process=app._sessions[row['id']].pty;original=process.write
    def counted(raw):calls.append(raw);return original(raw)
    process.write=counted
    code,value=post(data,key);assert code==200 and value['delivery_stage']=='delivered_to_process'
    assert value['task_completion_verified'] is False and value['bytes']==len(data.encode())
    assert post(data,key)[0]==200 and calls==[data.encode()]
    code,observed=status(key,data);assert code==200 and observed['resolved'] and not observed['automatic_retry']
    control=app._shell_service()
    with closing(control.store.connect('shell')) as db:
        record=db.execute('SELECT protected_intent FROM canvas_shell_host_requests WHERE request_key=?',(key,)).fetchone()
    assert record['protected_intent'].startswith(('dpapi:','keyring:')) and 'SECRET_INPUT_MARKER' not in record['protected_intent']
    fp=fingerprint(row['id'],frame['input_target'],data)
    code,ack=request(server,'/api/terminal/input-ack',json_body={'ws':ws,'id':row['id'],'request_key':key,'fingerprint':fp})
    assert code==200 and ack['acknowledged'] and not app.terminal_output(ws,row['id'])['input_pending']
    assert post('different',key)[0]!=200 and calls==[data.encode()]


def test_lost_http_reply_is_restored_from_host_after_port_change_without_input_replay(terminal,monkeypatch):
    app,server,ws,row,frame,post,status=terminal
    key=uuid.uuid4().hex;data='echo once>> input-effect.txt\r';calls=[]
    original=app.terminal_input
    def lost_reply(*args,**kwargs):
        value=original(*args,**kwargs)
        if kwargs.get('request_key')==key:calls.append(key);raise ConnectionResetError('injected after delivered input')
        return value
    monkeypatch.setattr(app,'terminal_input',lost_reply)
    with pytest.raises(RemoteDisconnected):post(data,key)
    root=app.store.workspace(ws)['path'];effect=__import__('pathlib').Path(root)/'input-effect.txt'
    deadline=time.monotonic()+5
    while not effect.exists() and time.monotonic()<deadline:time.sleep(.03)
    assert effect.read_text().splitlines()==['once']
    from sentra_canvas.__main__ import CanvasServer
    second=CanvasServer(app,0);thread=Thread(target=second.serve_forever,daemon=True);thread.start()
    try:
        code,recovered=request(second,f'/api/terminal/output?ws={ws}&id={row["id"]}&cursor=0')
        assert code==200 and recovered['input_scope']==frame['input_scope']
        assert recovered['input_pending'][0]['request_key']==key and 'data' not in recovered['input_pending'][0]
        code,value=status(key,data,host=second)
        assert code==200 and value['resolved'] and value['result']['status']=='delivered' and calls==[key]
        assert effect.read_text().splitlines()==['once']
    finally:second.shutdown();second.server_close();thread.join(timeout=5)


def test_error_after_possible_write_stays_uncertain_and_cannot_be_replayed_or_acknowledged(terminal,monkeypatch):
    app,server,ws,row,frame,post,status=terminal
    key=uuid.uuid4().hex;data='echo uncertain\r';calls=[]
    process=app._sessions[row['id']].pty;original=process.write
    def lost_delivery(raw):calls.append(raw);original(raw);raise OSError('injected lost PTY write acknowledgement')
    monkeypatch.setattr(process,'write',lost_delivery)
    assert post(data,key)[0]==500
    code,value=status(key,data);assert code==200 and not value['resolved'] and value['result']['phase']=='after_possible_effect'
    code,again=post(data,key);assert code==200 and again['status']=='uncertain' and calls==[data.encode()]
    code,ack=request(server,'/api/terminal/input-ack',json_body={'ws':ws,'id':row['id'],'request_key':key,'fingerprint':fingerprint(row['id'],frame['input_target'],data)})
    assert code==200 and not ack['acknowledged'] and app.terminal_output(ws,row['id'])['input_pending']
    monkeypatch.setattr(process,'write',original)


def test_old_session_incarnation_is_rejected_before_effect_and_has_a_confirmed_refusal(terminal):
    app,_,_,row,frame,post,status=terminal
    session=app._sessions[row['id']];session.input_instance_id=uuid.uuid4().hex
    key=uuid.uuid4().hex;data='must not send\r';calls=[]
    original=session.pty.write
    session.pty.write=lambda raw:calls.append(raw)
    try:
        assert post(data,key)[0]==403 and not calls
        code,value=status(key,data)
        assert code==200 and value['resolved'] and value['result']['status']=='admission_failed'
        assert value['result']['phase']=='before_admission'
    finally:session.pty.write=original


def test_receipt_cannot_cross_terminal_or_unauthenticated_scope(terminal):
    app,server,ws,row,_,post,status=terminal
    key=uuid.uuid4().hex;data='echo scoped\r';assert post(data,key)[0]==200
    other=app.store.create_terminal(ws,'OtherHistory','cmd')
    assert status(key,data,other=other['id'])[0]==403
    code,_=request(server,f'/api/terminal/input-status?ws={ws}&id={row["id"]}&request_key={key}&fingerprint={"a"*64}',authorized=False)
    assert code==401


def test_bad_selector_and_oversized_packet_cannot_dispatch(terminal):
    app,server,ws,row,frame,post,_=terminal
    process=app._sessions[row['id']].pty;original=process.write;calls=[];process.write=lambda data:calls.append(data)
    try:
        assert post('🦊'*1025)[0]==400
        assert post('text',target='not-a-session')[0]==400
        code,_=request(server,'/api/terminal/input',json_body={'ws':ws,'id':row['id'],'data':'text','request_key':None,'input_target':None})
        assert code==400 and not calls
    finally:process.write=original
