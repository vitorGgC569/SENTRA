from sentra_interop.acp_dialects import normalize_update


def test_opencode_metadata_is_normalized_without_inventing_success():
    event={'sessionUpdate':'tool_call_update','toolCallId':'command','status':'in_progress',
        'rawOutput':{'metadata':{'exit':0,'output':'hello'}}}
    normalized=normalize_update('opencode',event)
    assert normalized['rawOutput']['stdout']=='hello'
    assert normalized['rawOutput']['exitCode']==0
    assert normalized['status']=='in_progress'
    assert 'stdout' not in event['rawOutput']
    explicit={**event,'rawOutput':{'stdout':'existing','exitCode':2,'metadata':{'exit':0,'output':'other'}}}
    assert normalize_update('opencode',explicit)==explicit
    assert normalize_update('other',event) is event
