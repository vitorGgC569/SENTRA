import json
from sentra_canvas.dot_tool_runner import build_dispatch_prompt, verify_receipt


def receipt(tool, text, info):
    return verify_receipt(tool, text, '', 0, info, 'own-operation', 'own-work', 'own-request')


def test_echoing_the_entire_dispatched_prompt_is_not_inference():
    prompt, info = build_dispatch_prompt('Sem arquivos, responda o desafio.', 'NONCE_5fc782a')
    assert info['reverse'] not in prompt and info['sha256'] not in prompt
    result = receipt('sentra-cli', prompt, info)
    assert result['verified'] is False and result['echo_only_detected'] is True


def test_opencode_user_event_cannot_impersonate_assistant_output():
    _, info = build_dispatch_prompt('Teste', 'NONCE_5fc782a')
    answer = 'REVERSE_NONCE=' + info['reverse']
    echoed = json.dumps({'type': 'user', 'part': {'type': 'text', 'text': answer}})
    assert receipt('opencode', echoed, info)['verified'] is False
    assistant = json.dumps({'type': 'text', 'part': {'type': 'text', 'text': answer}})
    assert receipt('opencode', assistant, info)['verified'] is True


def test_codex_uncompleted_agent_item_is_not_final_evidence():
    _, info = build_dispatch_prompt('Teste', 'NONCE_5fc782a')
    item = {'type': 'agent_message', 'text': 'REVERSE_NONCE=' + info['reverse']}
    assert receipt('codex', json.dumps({'type': 'item.started', 'item': item}), info)['verified'] is False
    assert receipt('codex', json.dumps({'type': 'item.completed', 'item': item}), info)['verified'] is True
