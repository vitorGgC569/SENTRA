from types import SimpleNamespace

import pytest

from sentra_canvas import pty_client


def test_cold_start_waits_for_one_owner_without_spawning_fallback(tmp_path, monkeypatch):
    clock=[0.0]
    starts=[]
    monkeypatch.setattr(pty_client,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    monkeypatch.setattr(pty_client.subprocess,'Popen',lambda *args,**kwargs:starts.append(args) or SimpleNamespace(poll=lambda:None))
    class ColdClient(pty_client.PtyDaemonClient):
        def __init__(self,state):
            if clock[0]<6:raise FileNotFoundError('cold owner not ready')
            self.state=state
    result=ColdClient.connect_or_start(tmp_path)
    assert result.state==tmp_path.resolve()
    assert len(starts)==1
    assert 6<=clock[0]<30


def test_failed_start_reports_exit_without_second_spawn(tmp_path, monkeypatch):
    starts=[]
    monkeypatch.setattr(pty_client.subprocess,'Popen',lambda *args,**kwargs:starts.append(args) or SimpleNamespace(poll=lambda:1))
    class ExitedClient(pty_client.PtyDaemonClient):
        def __init__(self,state):raise FileNotFoundError('not ready')
    with pytest.raises(pty_client.TerminalError,match='exited during startup; no fallback'):
        ExitedClient.connect_or_start(tmp_path)
    assert len(starts)==1
