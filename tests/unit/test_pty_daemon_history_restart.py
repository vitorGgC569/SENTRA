import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import base64
import zlib
import threading
import urllib.request

import pytest
from sentra_canvas.service import Canvas
from sentra_canvas.pty_client import PtyDaemonClient
from sentra_canvas.__main__ import CanvasServer


def http_checkpoint(app,ws,terminal):
    server=CanvasServer(app,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/api/terminal/checkpoint?ws={ws}&id={terminal}'
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:urllib.request.urlopen(url,timeout=4)
        assert denied.value.code==401
        headers={'Authorization':'Bearer '+server.secret}
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=5) as response:
            value=json.load(response)
        other=app.create_workspace('Other'+str(server.server_port))['id']
        foreign=url.replace('ws='+ws,'ws='+other)
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(urllib.request.Request(foreign,headers=headers),timeout=4)
        assert denied.value.code==403
        return value
    finally:server.shutdown();server.server_close();thread.join(5)


def start_daemon(state):
    process=subprocess.Popen([sys.executable,'-m','sentra_canvas.pty_daemon',str(state)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if process.poll() is not None:pytest.fail('owned daemon exited: '+process.stderr.read().decode(errors='replace'))
            try:
                client=PtyDaemonClient(state)
                if client.call('health')['pid']==process.pid:return process,client
            except (OSError,ValueError,KeyError,RuntimeError):pass
            time.sleep(.05)
        pytest.fail('owned daemon startup timed out')
    except BaseException:
        process.terminate();process.wait(5);raise


@pytest.mark.skipif(os.name!='nt',reason='real ConPTY and DPAPI restart')
def test_daemon_death_restores_only_protected_history_and_never_respawns(tmp_path,monkeypatch):
    monkeypatch.setenv('SENTRA_PTY_DAEMON','1')
    root=tmp_path/'root';root.mkdir();state=tmp_path/'state';daemon_state=state/'pty-host'
    process,client=start_daemon(daemon_state);app=None
    try:
        app=Canvas(root,principal='owner',state_dir=state)
        ws=app.create_workspace('History')['id'];work=Path(app.store.workspace(ws)['path'])
        command=[sys.executable,'-u','-c',
            "from pathlib import Path;import time;Path('once.txt').open('a').write('once');print('\\x1b[32mDURABLE_OUTPUT_95721\\x1b[0m',flush=True);time.sleep(90)"]
        terminal=app._start(ws,'Transcript','cmd',command)
        old_runtime=client.runtime_id
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            value=app.terminal_output(ws,terminal['id'])
            if 'DURABLE_OUTPUT_95721' in value['text'] and value['persisted'] and (work/'once.txt').exists():break
            time.sleep(.05)
        assert value['persisted'] and 'DURABLE_OUTPUT_95721' in value['text']
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            checkpoint=app.terminal_checkpoint(ws,terminal['id'])
            if checkpoint['available']:
                frame=json.loads(zlib.decompress(base64.b64decode(checkpoint['checkpoint']['data'])))
                if 'DURABLE_OUTPUT_95721' in frame['snapshotAnsi']:break
            time.sleep(.05)
        assert checkpoint['available'] and 'DURABLE_OUTPUT_95721' in frame['snapshotAnsi']
        assert http_checkpoint(app,ws,terminal['id'])['available']
        app.shutdown();app=None
        # This daemon and all its ConPTY jobs were created by this test alone.
        process.terminate();process.wait(5)
        process,client=start_daemon(daemon_state)
        assert client.runtime_id!=old_runtime
        rows=client.call('inventory',{'include_history':True})
        assert len(rows)==1 and rows[0]['process_state']=='history_restored'
        assert rows[0]['process_live'] is False
        app=Canvas(root,principal='owner',state_dir=state)
        value=app.terminal_output(ws,terminal['id'])
        assert 'DURABLE_OUTPUT_95721' in value['text'] and value['persisted']
        assert value['status']=='history_restored' and value['recoverable'] is False
        assert terminal['id'] not in app._sessions
        checkpoint=app.terminal_checkpoint(ws,terminal['id'])
        assert checkpoint['available'] and checkpoint['restoration_creates_process'] is False
        archived=json.loads(zlib.decompress(base64.b64decode(checkpoint['checkpoint']['data'])))
        assert 'DURABLE_OUTPUT_95721' in archived['snapshotAnsi']
        assert http_checkpoint(app,ws,terminal['id'])['available']
        with pytest.raises(Exception):app.terminal_input(ws,terminal['id'],'effect-again\r')
        with pytest.raises(urllib.error.HTTPError) as error:
            client.call('create',{'workspace_id':ws,'terminal_id':terminal['id'],'argv':command,'cwd':str(work)},'create:'+terminal['id'])
        assert error.value.code==409
        assert client.call('inventory')==[] and (work/'once.txt').read_text()=='once'
    finally:
        if app:app.shutdown()
        if process.poll() is None:
            try:client.call('drain');client.call('stop_when_idle');process.wait(5)
            finally:
                if process.poll() is None:process.terminate();process.wait(5)
