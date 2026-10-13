from contextlib import closing
import pytest
from sentra_core.conversations import _decode
from test_shell_dot_features import shell, dot


def test_native_image_is_one_explicit_web_turn_without_a_fake_attachment(shell, monkeypatch):
    app,server,scope,call = shell
    actor=dot(call,'Native image owner')
    cid=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    runtime=app._shell_runtime
    monkeypatch.setattr(runtime,'_execute',lambda _:None)
    monkeypatch.setattr(runtime.web,'_configuration',lambda:{'models':[actor['model']]})
    sent=call('message_send',conversation_id=cid,content='Uma fotografia de um cachorro',native_generation='image')
    with closing(runtime.control.store.connect('shell')) as db:
        row=db.execute('SELECT protected_input FROM canvas_shell_queue WHERE operation_id=?',(sent['operation_id'],)).fetchone()
    queued=_decode(row['protected_input'])['message']
    assert queued['native_generation']=='image' and queued['attachments']==[]
    assert queued['content']=='Uma fotografia de um cachorro'
    work=runtime.control.work_item_info(sent['work_item_id'],runtime.owner)
    assert 'web:send' in work['required_capabilities']
    assert 'web:attach' not in work['required_capabilities']


def test_existing_cli_history_cannot_be_silently_forked_for_image_generation(shell,monkeypatch):
    app,server,scope,call=shell
    actor=dot(call,'Existing CLI owner')
    cid=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    runtime=app._shell_runtime
    monkeypatch.setattr(runtime.web,'_configuration',lambda:{'models':[actor['model']]})
    runtime.conversations.open(app.store.workspace(scope['project_id'])['path'],session_id=cid)
    runtime.conversations.begin_turn(cid,'Existing canonical message')
    from sentra_canvas.store import Denied
    with pytest.raises(Denied,match='continuidade Web'):
        runtime.message_capabilities(scope['project_id'],runtime.owner,actor,
            {'conversation_id':cid,'native_generation':'image'},[])
