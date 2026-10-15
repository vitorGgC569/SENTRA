import hashlib
from contextlib import closing
import pytest

from test_shell_dot_features import shell, dot
from browser.streaming import StreamingLedger
from sentra_canvas.shell_web_preview import web_preview
from sentra_mcp.services.web_history_store import _protected


@pytest.mark.parametrize('text',['First [[wiki]] fragment', 'Long Unicode 🪐 [[wiki]] repeated\n'*10000],ids=['short','long-unicode'])
def test_preview_binds_original_work_actor_message_and_revision(shell, monkeypatch, text):
    app, server, scope, call = shell
    actor = dot(call, 'Streaming')
    cid = call('conversation_create', dot_id=actor['dot_id'])['conversation_id']
    runtime = app._shell_runtime
    monkeypatch.setattr(runtime, '_execute', lambda oid: None)
    sent = call('message_send', conversation_id=cid, content='preview test')
    control, owner, oid = runtime.control, runtime.owner, sent['operation_id']
    control.durable.update_operation(oid, owner, state='STARTING')
    control.durable.update_operation(oid, owner, state='RUNNING')
    with closing(control.store.connect('shell')) as db:
        queued = db.execute('SELECT * FROM canvas_shell_queue WHERE operation_id=?', (oid,)).fetchone()
        keys = call('message_list', conversation_id=cid)['items']
        assert keys[0]['request_key']
    assert web_preview(runtime, scope['project_id'], cid)['status'] == 'idle'
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute('CREATE TABLE web_send_intents(job_id TEXT,owner TEXT,run_id TEXT,work_item_id TEXT,principal_id TEXT,created REAL,send_fence INTEGER,worker TEXT,answer_message_id TEXT,answer_revision INTEGER,workspace TEXT,operation_id TEXT)')
        db.execute('CREATE TABLE authenticated_web_receipts(job_id TEXT,owner TEXT,run_id TEXT,browser_principal TEXT,conversation_id TEXT,message_id TEXT,identity_epoch TEXT,worker TEXT)')
        run_id = app._runtime().run(scope['project_id'])['run_id']
        workspace = app.store.workspace(scope['project_id'])['path']
        db.execute('INSERT INTO web_send_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('job-original',owner,run_id,sent['work_item_id'],actor['agent_id'],queued['created_at']+1,1,'worker','assistant-current',2,workspace,oid))
        db.execute('INSERT INTO authenticated_web_receipts VALUES(?,?,?,?,?,?,?,?)',
            ('job-original',owner,run_id,'browser:test','remote-current','user-parent','epoch','worker'))
    with closing(control.store.connect('provider_content')) as db, db:
        db.execute('CREATE TABLE web_history_messages(owner TEXT,workspace TEXT,conversation_id TEXT,message_id TEXT,revision INTEGER,role TEXT,state TEXT,protected_body TEXT,body_sha256 TEXT,observed_at REAL)')
        db.execute('INSERT INTO web_history_messages VALUES(?,?,?,?,?,?,?,?,?,?)',
            (owner,workspace,'remote-current','assistant-current',2,'assistant','partial',_protected(text),hashlib.sha256(text.encode()).hexdigest(),queued['created_at']+2))
    ledger = StreamingLedger(control.store)
    ledger.record_frame(principal='browser:test',conversation_id='remote-current',message_id='assistant-current',revision=2,text=text)
    result = web_preview(runtime, scope['project_id'], cid)
    from sentra_canvas.shell_stream import content_window
    assert result['content'] == content_window(text) and result['operation_id'] == oid
    assert result['partial'] and not result['authoritative']
    full=web_preview(runtime,scope['project_id'],cid,include_full=True)
    assert full['content']==text and not full['truncated']
    runtime.stream.publish(scope['project_id'],scope['space_id'],cid,full)
    head=runtime.stream.head(scope['project_id'],cid)
    if head.get('content_ref'):
        from test_shell_stream_content import read_all
        assert read_all(runtime.stream,head['content_ref'],project=scope['project_id'],space=scope['space_id'],conversation=cid)==text
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute("UPDATE web_send_intents SET operation_id='unrelated-send'")
    assert web_preview(runtime, scope['project_id'], cid)['status'] == 'idle'
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute('UPDATE web_send_intents SET operation_id=?', (oid,))
    runtime.conversations.open(workspace, session_id=cid)
    turn, _ = runtime.conversations.begin_turn(cid, 'preview test')
    runtime.conversations.provider_state(cid, turn, 'gateway', 'native-turn-exact', 'submitted', context={
        'owner': owner, 'workspace': workspace, 'run_id': run_id, 'operation_id': oid,
        'work_item_id': sent['work_item_id'], 'agent_id': actor['agent_id']})
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute('CREATE TABLE gateway_bound_web_turns(owner TEXT,run_id TEXT,work_item_id TEXT,principal_id TEXT,turn_id TEXT,conversation_uri TEXT,operation_id TEXT)')
        db.execute('INSERT INTO gateway_bound_web_turns VALUES(?,?,?,?,?,?,?)',
            (owner,run_id,sent['work_item_id'],actor['agent_id'],'native-turn-exact',
             'conversation://sentra-cli/'+cid,'native-provider-operation'))
        db.execute("UPDATE web_send_intents SET operation_id='native-provider-operation'")
    assert web_preview(runtime, scope['project_id'], cid)['content'] == content_window(text)
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute("UPDATE gateway_bound_web_turns SET turn_id='different-native-turn'")
    assert web_preview(runtime, scope['project_id'], cid)['status'] == 'idle'
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute("UPDATE gateway_bound_web_turns SET turn_id='native-turn-exact'")
    assert web_preview(runtime, scope['project_id'], 'other-conversation')['status'] == 'idle'
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute("UPDATE web_send_intents SET answer_message_id='user-parent'")
    assert web_preview(runtime, scope['project_id'], cid)['content'] == ''
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute("UPDATE web_send_intents SET answer_message_id='assistant-current',answer_revision=3")
    assert web_preview(runtime, scope['project_id'], cid)['content'] == ''
    with closing(control.store.connect('session_checkpoint')) as db, db:
        db.execute("UPDATE web_send_intents SET principal_id='other-agent'")
    assert web_preview(runtime, scope['project_id'], cid)['status'] == 'idle'
