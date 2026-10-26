"""Real scoped stream and encrypted client; never installed accounts or phones."""
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import urllib.request

import pytest

from test_shell_dot_features import shell, dot
from test_mobile_canvas_lan_real import line_from
from test_sentra_runtime_canvas_center_http import request
from sentra_canvas.mobile_devices import registry, presentation_scope
from test_shell_stream_journal import _frame


def paired(app, scope, actor, actions=None):
    devices=registry(app);offer=devices.invite();key=base64.b64encode(secrets.token_bytes(32)).decode()
    pending=devices.pair(offer['invite_id'],offer['invite'],key,'Read-only phone')
    devices.approve(pending['device_id'],{**scope,'dot_id':actor['dot_id'],'actions':actions or ['message_list']})
    claim=devices.claim(pending['device_id'],key)
    return {'device_id':claim['device_id'],'credential':claim['credential'],'public_key':key}


def test_mobile_presentation_reuses_live_read_scope_and_never_accepts_foreign_dot(shell):
    app,server,scope,call=shell
    actor,other=dot(call,'Reader'),dot(call,'Other')
    own=call('conversation_create',dot_id=actor['dot_id'])
    foreign=call('conversation_create',dot_id=other['dot_id'])
    auth=paired(app,scope,actor)
    selected={**scope,'dot_id':actor['dot_id'],'conversation_id':own['conversation_id']}
    assert presentation_scope(app,{**auth,'request':selected})==selected
    for mutation in ({'conversation_id':foreign['conversation_id']},{'dot_id':other['dot_id']},
                     {'space_id':'foreign'},{'project_id':'foreign'}):
        body={**auth,'method':'presentation_head','request':{**selected,**mutation}}
        status,_=request(server,'/api/mobile/rpc',json_body=body)
        assert status==403
    unreadable=paired(app,scope,actor,['workspace_inventory'])
    with pytest.raises(PermissionError):presentation_scope(app,{**unreadable,'request':selected})
    registry(app).revoke(auth['device_id'])
    with pytest.raises(PermissionError):presentation_scope(app,{**auth,'request':selected})


def test_stream_epoch_persists_per_owner_and_changes_with_replaced_journal(tmp_path):
    from sentra_canvas.shell_stream import ShellStreamJournal
    from sentra_mcp.services.control_store import create_control_plane_store
    store=create_control_plane_store(tmp_path/'one')
    first=ShellStreamJournal(store,'owner')
    assert ShellStreamJournal(store,'owner').epoch==first.epoch
    assert ShellStreamJournal(store,'other').epoch!=first.epoch
    assert ShellStreamJournal(create_control_plane_store(tmp_path/'two'),'owner').epoch!=first.epoch
    assert first.read('project')['epoch']==first.epoch


def test_epoch_mismatch_resets_a_matching_cursor_on_real_canvas_http(shell,monkeypatch):
    app,server,scope,call=shell
    actor=dot(call,'Restored observer')
    conversation=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    monkeypatch.setattr(app._shell_runtime,'_execute',lambda _:None)
    operation=call('message_send',conversation_id=conversation,content='Synthetic observation')['operation_id']
    journal=app._shell_runtime.stream
    sequence=journal.publish(scope['project_id'],scope['space_id'],conversation,{
        'operation_id':operation,'status':'generating','content':'Persisted preview'})
    assert sequence is not None
    url=f'http://127.0.0.1:{server.server_port}/api/shell/stream?project_id={scope["project_id"]}&after={sequence}&epoch='+'0'*32
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+server.secret}),timeout=4) as response:
        frame=_frame(response)
        assert frame['event']=='snapshot' and frame['data']['reset'] is True
        assert frame['data']['cursor']==sequence and frame['data']['epoch']==journal.epoch
        assert frame['data']['protocol_version']==1


@pytest.mark.skipif(os.environ.get('SENTRA_MOBILE_ACCEPTANCE')!='1',reason='explicit real encrypted Canvas presentation acceptance')
def test_encrypted_presentation_reconnects_by_cursor_filters_dot_and_stops_on_revocation(shell,monkeypatch):
    app,server,scope,call=shell
    actor,other=dot(call,'Stream reader'),dot(call,'Other')
    own=call('conversation_create',dot_id=actor['dot_id'])
    foreign=call('conversation_create',dot_id=other['dot_id'])
    transport=Path(__file__).resolve().parents[2]/'integrations/orca-mobile/transport'
    node=shutil.which('node');assert node
    tsx=transport/'node_modules/tsx/dist/cli.mjs';assert tsx.is_file()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    gateway=subprocess.Popen([node,str(tsx),str(transport/'src/gateway.ts')],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,text=True,encoding='utf-8',creationflags=flags)
    phone=None
    from sentra_canvas.__main__ import CanvasHandler
    opened=[]
    original_stream=CanvasHandler._shell_stream
    def record_stream(handler,project_id,after,**options):
        if options.get('validate_scope'):
            opened.append((after,options.get('epoch')))
        return original_stream(handler,project_id,after,**options)
    monkeypatch.setattr(CanvasHandler,'_shell_stream',record_stream)
    try:
        target={'broker':'http://127.0.0.1:'+str(server.server_port),'bearer':server.secret,'runtime_id':'initial'}
        gateway.stdin.write(json.dumps({'bind':'127.0.0.1','port':port,**target,'supervised':True,
            'secret_key':base64.b64encode(secrets.token_bytes(32)).decode()})+'\n');gateway.stdin.flush()
        ready=line_from(gateway);assert ready['ready']
        offer={**registry(app).invite(),'protocol_version':1,'endpoint':ready['endpoint'],'public_key':ready['public_key']}
        phone=subprocess.Popen([node,str(tsx),str(transport/'test/presentation-canvas-driver.ts')],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,text=True,encoding='utf-8',creationflags=flags)
        phone.stdin.write(json.dumps({'offer':offer,'conversation_id':own['conversation_id']})+'\n');phone.stdin.flush()
        pending=line_from(phone);assert pending['phase']=='pending'
        registry(app).approve(pending['device_id'],{**scope,'dot_id':actor['dot_id'],'actions':['message_list']})
        monkeypatch.setattr(app._shell_runtime,'_execute',lambda _:None)
        operations={c['conversation_id']:call('message_send',conversation_id=c['conversation_id'],content='Synthetic feed observation')['operation_id'] for c in (own,foreign)}
        journal=app._shell_runtime.stream
        def publish(conversation,text):
            assert journal.publish(scope['project_id'],scope['space_id'],conversation,{
                'operation_id':operations[conversation],'status':'generating','content_revision':0,'content':text}) is not None
        publish(own['conversation_id'],'OWN-PRIVATE one 🪐')
        publish(foreign['conversation_id'],'FOREIGN-PRIVATE must never cross scope')
        before_cursor=journal.read(scope['project_id'])['cursor']
        phone.stdin.write('approved\n');phone.stdin.flush()
        initial=[line_from(phone),line_from(phone)]
        assert {'phase':'ready'} in initial
        assert {'phase':'preview','content':'OWN-PRIVATE one 🪐'} in initial
        gateway.stdin.write(json.dumps({'type':'broker_update','available':False})+'\n');gateway.stdin.flush()
        assert line_from(gateway)['broker_updated']
        publish(own['conversation_id'],'OWN-PRIVATE one 🪐 two')
        gateway.stdin.write(json.dumps({'type':'broker_update',**target,'runtime_id':'reopened'})+'\n');gateway.stdin.flush()
        assert line_from(gateway)['runtime_id']=='reopened'
        assert line_from(phone)=={'phase':'preview','content':'OWN-PRIVATE one 🪐 two'}
        assert opened[0]==(None,None)
        assert any(after==before_cursor and epoch==journal.epoch for after,epoch in opened[1:]),opened
        # Revocation is checked even when the selected conversation is idle.
        registry(app).revoke(pending['device_id'])
        assert line_from(phone)=={'phase':'revoked','paired':False}
        phone.stdin.write('finish\n');phone.stdin.flush()
        assert line_from(phone)=={'phase':'finished','seen':2,'encrypted':True}
        phone.wait(timeout=5);assert phone.returncode==0
    finally:
        if phone and phone.poll() is None:phone.terminate();phone.wait(timeout=5)
        gateway.terminate();gateway.wait(timeout=5)
