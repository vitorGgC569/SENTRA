"""Real CanvasBridge in a ConPTY child, scoped credential and broker restart."""
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest
from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.pty_client import DaemonPTY


DRIVER='''import json,os,sys,time,urllib.request,urllib.error
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from sentra_cli.canvas import CanvasBridge
root=Path(sys.argv[2]);gate=root/'continue';effect=root/'once.txt'
effect.write_text(effect.read_text()+'once' if effect.exists() else 'once')
bridge=CanvasBridge(SimpleNamespace(workspace=str(root),model=None))
try:
    first=bridge.working_context()
    (root/'first.json').write_text(json.dumps({'pid':os.getpid(),'parent_pid':os.getppid(),'port':bridge.port,'context':isinstance(first,dict)}))
    for _ in range(400):
        if gate.exists():break
        time.sleep(.05)
    else:raise RuntimeError('restart gate timed out')
    second=bridge.working_context()
    request=urllib.request.Request('http://127.0.0.1:'+str(bridge.port)+'/api/runtime/shutdown',
        data=b'{}',headers={'Authorization':'Bearer '+bridge._token,'Content-Type':'application/json'})
    denied=False
    try:urllib.request.urlopen(request,timeout=3)
    except urllib.error.HTTPError as error:denied=error.code==401
    (root/'second.json').write_text(json.dumps({'pid':os.getpid(),'parent_pid':os.getppid(),'port':bridge.port,
        'context':isinstance(second,dict),'owner_route_denied':denied}))
    for _ in range(400):time.sleep(.05)
except BaseException as error:
    (root/'error.json').write_text(json.dumps({'error':type(error).__name__,'detail':str(error)}))
    raise
'''


def wait_json(path,error):
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        if error.exists():pytest.fail(error.read_text())
        if path.exists():return json.loads(path.read_text())
        time.sleep(.05)
    pytest.fail('owned CLI bridge acceptance timed out')


@pytest.mark.skipif(os.name!='nt',reason='Windows ConPTY and DPAPI')
def test_running_cli_rebinds_broker_without_duplicate_process_or_owner_authority(tmp_path,monkeypatch):
    monkeypatch.setenv('SENTRA_PTY_DAEMON','1')
    root=tmp_path/'root';root.mkdir();state=tmp_path/'state';source=Path(__file__).resolve().parents[2]
    driver=tmp_path/'driver.py';driver.write_text(DRIVER)
    first=None;second=None;server=None;thread=None;client=None
    try:
        first=Canvas(root,principal='owner',state_dir=state)
        server=CanvasServer(first,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        ws=first.create_workspace('BoundCLI')['id'];work=Path(first.store.workspace(ws)['path'])
        terminal=first._start(ws,'CLI','sentra-cli',[sys.executable,'-u',str(driver),str(source),str(work)])
        client=first._pty_client;pid=first._sessions[terminal['id']].pty.pid
        before=wait_json(work/'first.json',work/'error.json')
        assert before['context'] and before['port']==server.server_port
        # Windows venv python.exe redirects to an interpreter child. Keep the
        # owned ConPTY root and actual driver identity distinct and stable.
        assert before['pid']>0 and (before['pid']==pid or before['parent_pid']==pid)
        token=next(token for token,binding in first._agent_tokens.items() if binding==(ws,terminal['id']))
        old_runtime=server.runtime_id
        server.shutdown();server.server_close();thread.join(5);server=None
        first.shutdown();first=None
        second=Canvas(root,principal='owner',state_dir=state)
        assert second._agent_tokens[token]==(ws,terminal['id'])
        assert second._sessions[terminal['id']].pty.pid==pid
        server=CanvasServer(second,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        assert server.runtime_id!=old_runtime
        (work/'continue').write_text('continue')
        after=wait_json(work/'second.json',work/'error.json')
        assert after['context'] and after['port']==server.server_port
        assert after['pid']==before['pid'] and after['parent_pid']==before['parent_pid']
        assert after['owner_route_denied']
        assert (work/'once.txt').read_text()=='once'
        assert len(client.call('inventory'))==1
        second.terminal_close(ws,terminal['id'])
        assert token not in second._agent_tokens
    finally:
        if server:server.shutdown();server.server_close()
        if thread:thread.join(5)
        if first:first.shutdown()
        if second:second.shutdown()
        if client:
            for row in client.call('inventory'):
                if row['process_live']:
                    DaemonPTY(client,row['workspace_id'],row['terminal_id'],pid=row['pid'],runtime_id=row['runtime_id']).close()
            client.call('drain');client.call('stop_when_idle')
