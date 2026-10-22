"""Actual Python supervisor, encrypted Node client and two production Canvas brokers."""
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest
from test_shell_dot_features import shell,dot
from test_mobile_canvas_lan_real import line_from
from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas
from sentra_canvas.broker import publish_endpoint,remove_endpoint
from sentra_canvas.mobile_devices import owner_control
from sentra_canvas.mobile_network import host_status


def await_state(state, expected):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        value=host_status(state)
        if value['available'] and value['status']==expected:return value
        time.sleep(.1)
    pytest.fail('owned LAN gateway did not reach '+expected)


@pytest.mark.skipif(os.environ.get('SENTRA_MOBILE_ACCEPTANCE')!='1',reason='explicit real sidecar restart acceptance')
def test_mobile_login_survives_real_broker_restart_without_new_pairing(shell):
    app,server,scope,call=shell
    actor=dot(call,'Durable mobile login');conversation=call('conversation_create',dot_id=actor['dot_id'])
    state=app.state_dir;publish_endpoint(server)
    root=Path(__file__).resolve().parents[2];transport=root/'integrations/orca-mobile/transport'
    node=shutil.which('node');assert node
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    sidecar=subprocess.Popen([sys.executable,'-m','sentra_canvas.mobile_host','--state',str(state),
        '--bind','127.0.0.1','--port',str(port),'--node',node],cwd=root,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    phone=None;new_app=None;new_server=None;new_thread=None
    try:
        ready=queue.Queue(1)
        threading.Thread(target=lambda:ready.put(sidecar.stdout.readline()),daemon=True).start()
        assert 'LAN ready' in ready.get(timeout=12)
        original=await_state(state,'ready')
        offer=owner_control(app,{'action':'invite'})
        phone=subprocess.Popen([node,str(transport/'node_modules/tsx/dist/cli.mjs'),
            str(transport/'test/paired-canvas-driver.ts')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        phone.stdin.write(json.dumps({'offer':offer,'restart':True})+'\n');phone.stdin.flush()
        pending=line_from(phone)
        owner_control(app,{'action':'approve','device_id':pending['device_id'],'scope':{**scope,
            'dot_id':actor['dot_id'],'actions':['workspace_inventory','conversation_list']}})
        phone.stdin.write('approved\n');phone.stdin.flush()
        assert line_from(phone)['conversations']==[conversation['conversation_id']]
        remove_endpoint(server);server.shutdown();server.server_close();app.shutdown()
        await_state(state,'broker_restarting')
        new_app=Canvas(app.project_dir,principal='local-owner',state_dir=state)
        new_server=CanvasServer(new_app,0)
        new_thread=threading.Thread(target=new_server.serve_forever,daemon=True);new_thread.start()
        publish_endpoint(new_server)
        assert new_server.runtime_id!=server.runtime_id
        recovered=await_state(state,'ready')
        assert recovered['public_key']==original['public_key'] and recovered['endpoint']==original['endpoint']
        phone.stdin.write('restart\n');phone.stdin.flush()
        assert line_from(phone)=={'phase':'restarted','protocol':1,'conversations':[conversation['conversation_id']]}
        assert len(owner_control(new_app,{'action':'list'}))==1
        owner_control(new_app,{'action':'revoke','device_id':pending['device_id']})
        phone.stdin.write('revoked\n');phone.stdin.flush()
        assert line_from(phone)=={'phase':'revoked','refused':True}
        phone.wait(timeout=5);assert phone.returncode==0
    finally:
        if phone and phone.poll() is None:phone.terminate();phone.wait(timeout=5)
        if sidecar.poll() is None:sidecar.terminate();sidecar.wait(timeout=5)
        if new_server:
            remove_endpoint(new_server);new_server.shutdown();new_server.server_close()
        if new_thread:new_thread.join(5)
        if new_app:new_app.shutdown()
