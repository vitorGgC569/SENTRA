"""The legacy protected-draft fallback must preserve literal bracket prose."""
import pytest
from sentra_canvas.shell_stream import content_window
from test_sentra_runtime_canvas_center_http import running_canvas
from test_shell_stream_journal import _scope


@pytest.mark.parametrize('kind',['short','long'])
def test_idle_draft_keeps_legitimate_brackets_but_masks_structured_tool_arguments(tmp_path,monkeypatch,kind):
    with running_canvas(tmp_path) as (app,server):
        project,space,conversation,operation=_scope(app,monkeypatch)
        runtime=app._shell_runtime
        runtime._stop.set()
        for thread in runtime._threads:thread.join(timeout=3)
        workspace=app.store.workspace(project)['path']
        runtime.conversations.open(workspace,session_id=conversation)
        turn,_=runtime.conversations.begin_turn(conversation,'synthetic interrupted draft')
        visible='Unicode 🪐 [[wiki]] [[ação]] repeated '+('[[wiki]] 🪐 '*15000 if kind=='long' else '')
        runtime.conversations.checkpoint_response(conversation,turn,visible+'[[CANVAS|machine_execute|private arguments]]')
        view=app.shell_live_preview(project,space,conversation)
        assert view['status']=='interrupted' and view['persisted']
        assert view['content']==content_window(visible)
        assert view['truncated']==(view['content']!=visible)
        assert view['content_offset']==len(visible)-len(view['content'])
        assert '[[wiki]]' in view['content'] and 'private arguments' not in view['content']
        assert not view['authoritative'] and not view['closes_trio']
