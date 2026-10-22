"""Real Node gateway + encrypted client + authenticated production Canvas HTTP."""
import base64
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import threading
import pytest
from test_shell_dot_features import shell,dot
from sentra_canvas.mobile_devices import registry,owner_control


def line_from(process):
    result=queue.Queue(1)
    threading.Thread(target=lambda:result.put(process.stdout.readline()),daemon=True).start()
    try:value=result.get(timeout=12)
    except queue.Empty:pytest.fail('isolated mobile acceptance timed out')
    if not value:pytest.fail('isolated mobile child exited before completing the protocol')
    return json.loads(value)


@pytest.mark.skipif(os.environ.get('SENTRA_MOBILE_ACCEPTANCE')!='1',reason='explicit installed Node transport acceptance')
def test_encrypted_mobile_canvas_pairing_scope_and_revocation(shell):
    app,server,scope,call=shell
    first,other=dot(call,'Paired phone'),dot(call,'Other Dot')
    own=call('conversation_create',dot_id=first['dot_id'])
    call('conversation_create',dot_id=other['dot_id'])
    transport=Path(__file__).resolve().parents[2]/'integrations/orca-mobile/transport'
    node=shutil.which('node');assert node
    tsx=transport/'node_modules/tsx/dist/cli.mjs';assert tsx.is_file()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    gateway=subprocess.Popen([node,str(tsx),str(transport/'src/gateway.ts')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,creationflags=flags)
    phone=None
    try:
        gateway.stdin.write(json.dumps({'bind':'127.0.0.1','port':port,'broker':'http://127.0.0.1:'+str(server.server_port),
            'bearer':server.secret,'secret_key':base64.b64encode(secrets.token_bytes(32)).decode()}));gateway.stdin.close()
        ready=line_from(gateway);assert ready['ready']
        invite=registry(app).invite()
        offer={**invite,'protocol_version':1,'endpoint':f'ws://127.0.0.1:{port}/sentra/mobile/v1','public_key':ready['public_key']}
        phone=subprocess.Popen([node,str(tsx),str(transport/'test/paired-canvas-driver.ts')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,creationflags=flags)
        phone.stdin.write(json.dumps({'offer':offer})+'\n');phone.stdin.flush()
        paired=line_from(phone);assert paired['phase']=='pending'
        owner_control(app,{'action':'approve','device_id':paired['device_id'],'scope':{**scope,'dot_id':first['dot_id'],
            'actions':['workspace_inventory','conversation_list']}})
        phone.stdin.write('approved\n');phone.stdin.flush()
        scoped=line_from(phone)
        assert scoped=={'phase':'scoped','protocol':1,'conversations':[own['conversation_id']]}
        owner_control(app,{'action':'revoke','device_id':paired['device_id']})
        phone.stdin.write('revoked\n');phone.stdin.flush()
        assert line_from(phone)=={'phase':'revoked','refused':True}
        phone.wait(timeout=5);assert phone.returncode==0
    finally:
        if phone and phone.poll() is None:phone.terminate();phone.wait(timeout=5)
        gateway.terminate();gateway.wait(timeout=5)
