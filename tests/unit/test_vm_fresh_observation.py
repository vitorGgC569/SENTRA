import pytest
from sentra_core.conversations import ConversationStore


def test_new_provider_round_gets_fresh_frame_while_input_stays_deduplicated(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    store=ConversationStore(tmp_path/'state');cid=store.open(workspace)
    turn,_=store.begin_turn(cid,'Observe, send keyboard, observe again')
    def provider_round(native_id):
        store.provider_state(cid,turn,'gateway',native_id,'submitted')
        store.provider_state(cid,turn,'gateway',native_id,'completed')
        store.finish_response(cid,turn,'[[CANVAS|vm_frame]]')
        return ('gateway',native_id)
    first=provider_round('native-first')
    before,cached=store.start_tool(cid,turn,'CANVAS','vm_frame',observation_provider=first)
    assert cached is None
    store.finish_tool(cid,before,'desktop before input')
    assert store.start_tool(cid,turn,'CANVAS','vm_frame',observation_provider=first)==(before,'desktop before input')
    action='vm_input|{"action":"input.key","scancodes":[28,156]}'
    write,_=store.start_tool(cid,turn,'CANVAS',action)
    store.finish_tool(cid,write,'input sent once')
    second=provider_round('native-second')
    after,cached=store.start_tool(cid,turn,'CANVAS','vm_frame',observation_provider=second)
    assert after!=before and cached is None
    assert store.start_tool(cid,turn,'CANVAS',action)==(write,'input sent once')
    with pytest.raises(ValueError):
        store.start_tool(cid,turn,'CANVAS',action,observation_provider=second)
    with pytest.raises(PermissionError):
        store.start_tool(cid,turn,'CANVAS','vm_frame',observation_provider=('gateway','unknown-provider'))
