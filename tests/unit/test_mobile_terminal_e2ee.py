import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
import pytest
from test_shell_dot_features import shell
from test_terminal_observation_scope import configured
from test_mobile_canvas_lan_real import line_from
from sentra_canvas.mobile_devices import registry,owner_control


@pytest.mark.skipif(os.name!='nt' or os.environ.get('SENTRA_MOBILE_ACCEPTANCE')!='1',reason='explicit Windows ConPTY encrypted acceptance')
def test_mobile_terminal_recovers_a_lost_ack_without_repeating_physical_input(request,monkeypatch):
    monkeypatch.setenv('SENTRA_PTY_DAEMON','1')
    instance=request.getfixturevalue('shell')
    app,server,actor,foreign,terminal,control,grant,body=configured(instance,live=True)
    scope={k:body[k] for k in ('project_id','space_id','dot_id')};owner=app._runtime().owner
    control.authorization_grant(owner,principal_type='agent',principal_id=actor['agent_id'],
        capability='terminal:write',scope_type='work_item',scope_id=body['request']['work_item_id'])
    transport=Path(__file__).resolve().parents[2]/'integrations/orca-mobile/transport'
    node=shutil.which('node');tsx=transport/'node_modules/tsx/dist/cli.mjs'
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    gateway=subprocess.Popen([node,str(tsx),str(transport/'src/gateway.ts')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        text=True,encoding='utf-8',creationflags=flags)
    phone=None;client=app._pty_client
    effect=Path(app.store.workspace(scope['project_id'])['path'])/'mobile-terminal-once.txt'
    try:
        gateway.stdin.write(json.dumps({'bind':'127.0.0.1','port':port,'broker':f'http://127.0.0.1:{server.server_port}',
            'bearer':server.secret,'secret_key':base64.b64encode(secrets.token_bytes(32)).decode()}));gateway.stdin.close()
        ready=line_from(gateway);assert ready['ready']
        offer={**registry(app).invite(),'protocol_version':1,'endpoint':ready['endpoint'],'public_key':ready['public_key']}
        phone=subprocess.Popen([node,str(tsx),str(transport/'test/terminal-canvas-driver.ts')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=flags)
        config={**{k:body['request'][k] for k in ('machine_id','work_item_id','terminal_id')},'conversation_id':body['conversation_id'],
            'offer':offer,'key':'mobile-terminal-'+uuid.uuid4().hex,
            'command':"Add-Content -LiteralPath 'mobile-terminal-once.txt' -Value 'once'; Write-Output SENTRA_MOBILE_ONCE_DONE"}
        phone.stdin.write(json.dumps(config)+'\n');phone.stdin.flush()
        pending=line_from(phone);assert pending['phase']=='pending'
        owner_control(app,{'action':'approve','device_id':pending['device_id'],'scope':{**scope,
            'actions':['workspace_inventory','workspace_request_status','dot_computer_get','dot_computer_read','dot_computer_action']}})
        phone.stdin.write('approved\n');phone.stdin.flush()
        assert line_from(phone)=={'phase':'uncertain'}
        recovered=line_from(phone)
        assert recovered=={'phase':'recovered','resolved':True,'pending':0,'writes':1,'checkpoint':True}
        deadline=time.monotonic()+8
        while not effect.exists() and time.monotonic()<deadline:time.sleep(.05)
        assert effect.read_text(encoding='utf-8-sig').strip()=='once'
        control.authorization.revoke(grant['grant_id'],owner)
        phone.stdin.write('revoked\n');phone.stdin.flush()
        assert line_from(phone)=={'phase':'revoked','refused':True}
        phone.wait(timeout=8);assert phone.returncode==0,phone.stderr.read()[-3000:]
        assert effect.read_text(encoding='utf-8-sig').strip()=='once'
    finally:
        if phone and phone.poll() is None:phone.terminate();phone.wait(5)
        gateway.terminate();gateway.wait(5)
        app.terminal_close(scope['project_id'],terminal['id'])
        client.call('drain');client.call('stop_when_idle')
