"""Real ConPTY in a separately owned, disposable daemon; never uses live state."""
import os
import subprocess
import sys
import time
import pytest
from sentra_canvas.pty_client import PtyDaemonClient,DaemonPTY

@pytest.mark.skipif(os.name!='nt',reason='Windows ConPTY')
def test_real_pty_survives_client_disconnect_without_double_execution(tmp_path):
    process=subprocess.Popen([sys.executable,'-m','sentra_canvas.pty_daemon',str(tmp_path)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)
    terminal=None
    try:
        client=None
        for _ in range(60):
            if process.poll() is not None:pytest.fail('daemon failed: '+process.stderr.read().decode(errors='replace'))
            try:client=PtyDaemonClient(tmp_path);break
            except (OSError,ValueError,KeyError,RuntimeError):time.sleep(.1)
        assert client is not None
        assert client.call('health')['coverage'] == 'handshake'
        assert client.call('self_test')['functional'] is True
        terminal=DaemonPTY.create(client,'workspace','terminal',
            ['cmd.exe','/d','/q'],tmp_path)
        command=b"<nul set /p =once >> effect.txt & echo SENTRA_DAEMON_OK\r"
        import base64
        fields=terminal.fields(data=base64.b64encode(command).decode())
        client.call('write',fields,'write:single-effect')
        # A new owner client reattaches by authenticated inventory, never PID.
        reconnected=PtyDaemonClient(tmp_path)
        assert reconnected.call('health')['runtime_id']==client.runtime_id
        reconnected.call('write',fields,'write:single-effect')
        for _ in range(80):
            output=terminal.output()
            if 'SENTRA_DAEMON_OK' in output['text'] and (tmp_path/'effect.txt').exists():break
            time.sleep(.1)
        assert (tmp_path/'effect.txt').exists(), repr(output)
        assert (tmp_path/'effect.txt').read_text().strip()=='once'
        assert 'SENTRA_DAEMON_OK' in output['text']
        assert terminal.poll() is None
        assert reconnected.call('inventory')[0]['terminal_id']=='terminal'
        assert reconnected.call('drain')['live_sessions'] == 1
        terminal.close()
        terminal = None
        reconnected.call('stop_when_idle')
        process.wait(timeout=5)
        assert process.returncode == 0
    finally:
        if terminal:
            try:terminal.close()
            except Exception:pass
        process.terminate();process.wait(timeout=10)


@pytest.mark.skipif(os.name!='nt',reason='Windows ConPTY')
def test_canvas_restart_reattaches_one_live_process(tmp_path,monkeypatch):
    from sentra_canvas.service import Canvas
    monkeypatch.setenv('SENTRA_PTY_DAEMON','1')
    root=tmp_path/'project';root.mkdir()
    state=tmp_path/'state'
    first=second=None;client=None
    try:
        first=Canvas(root,principal='test-owner',state_dir=state)
        ws=first.create_workspace('Durable')['id']
        terminal=first._start(ws,'Shell','cmd',['cmd.exe','/d','/q'])
        original=first._sessions[terminal['id']].pty
        first.terminal_input(ws,terminal['id'],'<nul set /p =once >> effect.txt & echo BROKER_RESTART_OK\r')
        effect=__import__('pathlib').Path(first.store.workspace(ws)['path'])/'effect.txt'
        for _ in range(60):
            if effect.exists() and effect.read_text().strip()=='once':break
            time.sleep(.1)
        assert effect.exists()
        client=first._pty_client
        runtime_id=client.runtime_id
        pid=original.pid
        first.shutdown();first=None
        # Actual Store recovery is involved, not a second PTY client alone.
        second=Canvas(root,principal='test-owner',state_dir=state)
        resumed=second._sessions[terminal['id']].pty
        assert resumed.pid==pid and resumed.runtime_id==runtime_id
        assert second.store.resource('terminals',terminal['id'],ws)['status']=='running'
        for _ in range(30):
            output=second.terminal_output(ws,terminal['id'])
            if 'BROKER_RESTART_OK' in output['text']:break
            time.sleep(.1)
        assert 'BROKER_RESTART_OK' in output['text']
        assert effect.read_text().strip()=='once'
        assert len(client.call('inventory'))==1
        second.terminal_close(ws,terminal['id'])
    finally:
        if first:first.shutdown()
        if second:second.shutdown()
        if client:
            for record in client.call('inventory'):
                if record['exit_code'] is None:
                    try:DaemonPTY(client,record['workspace_id'],record['terminal_id'],pid=record['pid'],runtime_id=record['runtime_id']).close()
                    except Exception:pass
            client.call('drain');client.call('stop_when_idle')
