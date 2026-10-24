import pytest
from sentra_canvas.terminal_frames import bounded_output,MAX_FRAME_CHARS


def test_large_legacy_frame_advances_only_after_the_returned_prefix():
    text='🦊'*40000
    first=bounded_output({'text':text,'cursor':45000,'status':'exited','recoverable':False})
    assert len(first['text'])==MAX_FRAME_CHARS and first['cursor']==5000+MAX_FRAME_CHARS
    assert first['head']==45000 and first['has_more'] and not first['recoverable']
    second=bounded_output({'text':text[MAX_FRAME_CHARS:],'cursor':45000})
    third=bounded_output({'text':text[2*MAX_FRAME_CHARS:],'cursor':45000})
    assert first['text']+second['text']+third['text']==text and third['cursor']==45000 and not third['has_more']


def test_daemon_bounded_frame_keeps_head_gap_and_process_identity():
    value={'text':'abc','cursor':13,'head':20,'truncated':True,'runtime_id':'host','process_live':True}
    result=bounded_output(value)
    assert result['text']=='abc' and result['cursor']==13 and result['has_more'] and result['head']==20
    assert result['truncated'] and result['runtime_id']=='host' and result['process_live']


@pytest.mark.parametrize('change',[{'cursor':True},{'cursor':-1},{'cursor':1},{'head':1},{'head':10**13},{'text':None}])
def test_malformed_frames_are_rejected(change):
    with pytest.raises(RuntimeError):bounded_output({'text':'abc','cursor':3}|change)


def test_authenticated_canvas_history_pages_without_skips_or_starting_a_process(tmp_path):
    from test_sentra_runtime_canvas_center_http import running_canvas,request
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace('BoundedHistory')['id']
        terminal=app.store.create_terminal(ws,'HistoryOnly','cmd')['id']
        quiet=app.store.create_terminal(ws,'QuietHistory','cmd')['id']
        text='🦊'*40000
        for offset in range(0,len(text),8192):app.store.append_terminal_output(ws,terminal,text[offset:offset+8192])
        app.store.append_terminal_output(ws,quiet,'quiet')
        app.store.terminal_state(ws,terminal,'interrupted')
        app.store.terminal_state(ws,quiet,'interrupted')
        cursor=0;pieces=[]
        for _ in range(3):
            code,frame=request(server,f'/api/terminal/output?ws={ws}&id={terminal}&cursor={cursor}')
            assert code==200 and len(frame['text'])<=MAX_FRAME_CHARS and frame['head']==40000
            assert not frame['recoverable'];pieces.append(frame['text']);cursor=frame['cursor']
        assert ''.join(pieces)==text and cursor==40000 and not frame['has_more']
        code,frame=request(server,f'/api/terminal/output?ws={ws}&id={quiet}&cursor=0')
        assert code==200 and frame['text']=='quiet' and not frame['has_more']
        assert not app._sessions  # Metadata/history retrieval never creates a PTY.
        code,_=request(server,f'/api/terminal/output?ws={ws}&id={terminal}&cursor=0',authorized=False)
        assert code==401


def test_owner_http_output_uses_integer_cursors_for_real_durable_terminal(tmp_path,monkeypatch):
    import os
    from urllib.parse import quote
    if os.name!='nt':pytest.skip('actual Windows ConPTY daemon')
    from test_sentra_runtime_canvas_center_http import running_canvas,request
    from sentra_canvas.pty_client import DaemonPTY
    monkeypatch.setenv('SENTRA_PTY_DAEMON','1')
    with running_canvas(tmp_path) as (app,server):
        client=None;terminal=None
        try:
            ws=app.create_workspace('HttpDaemonCursor')['id']
            terminal=app.create_terminal(ws,'CursorFixture','cmd')['id']
            client=app._pty_client
            assert isinstance(app._sessions[terminal].pty,DaemonPTY)
            pid=app._sessions[terminal].pty.pid
            base=f'/api/terminal/output?ws={ws}&id={terminal}'
            for suffix in ('','&cursor=0','&cursor=1'):
                code,frame=request(server,base+suffix)
                assert code==200,frame
                assert frame['process_live'] and type(frame['cursor']) is int
                assert app._sessions[terminal].pty.pid==pid
            for cursor in ('-1','1.5','true','1000000000001','9'*100,'١'):
                assert request(server,base+'&cursor='+quote(cursor))[0]==400
            assert request(server,base+'&cursor=0&cursor=1')[0]==400
            assert request(server,base,authorized=False)[0]==401
        finally:
            if terminal is not None:app.terminal_close(ws,terminal)
            if client is not None:
                client.call('drain');client.call('stop_when_idle')
