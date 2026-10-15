import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_cli.client import ModelClient, ProviderHTTPError
from sentra_cli.config import CLIConfig
from sentra_canvas.shell_live import ShellLivePreviews
from sentra_cli.shell_live_preview import LivePreviewWriter
from sentra_core.conversations import ConversationStore


def test_binary_relay_waits_past_three_minutes_and_renews_lease(monkeypatch):
    from sentra_canvas.shell_web import ShellWebRuntime
    now = [0.0]
    monkeypatch.setattr('sentra_canvas.shell_web.time.monotonic', lambda: now[0])
    stop = Mock()
    stop.is_set.return_value = False
    stop.wait.side_effect = lambda _: now.__setitem__(0, now[0] + 30)
    durable = Mock()
    durable.operation_status.return_value = {'state':'RUNNING'}
    durable.run_status.return_value = {'state':'RUNNING'}
    web = object.__new__(ShellWebRuntime)
    web.runtime = SimpleNamespace(_stop=stop)
    web.control = SimpleNamespace(durable=durable)
    web.owner = 'owner'
    web.observe = Mock(side_effect=lambda *_: {'content':'confirmed'} if now[0] >= 300 else None)
    relay = Mock()
    result = web._wait_for_answer({'operation_id':'op','run_id':'run'}, {}, relay, 'job', 'resource', {'fencing_token':1})
    assert result == {'content':'confirmed'}
    assert durable.renew_lease.call_count == 5
    relay.web_send.failure.assert_not_called()


def test_binary_relay_cancellation_stops_observation(monkeypatch):
    from sentra_canvas.shell_web import ShellWebRuntime
    web = object.__new__(ShellWebRuntime)
    web.runtime = SimpleNamespace(_stop=SimpleNamespace(is_set=lambda: False))
    durable = Mock()
    durable.operation_status.return_value = {'state':'CANCEL_REQUESTED'}
    durable.run_status.return_value = {'state':'RUNNING'}
    web.control, web.owner = SimpleNamespace(durable=durable), 'owner'
    web.observe = Mock()
    relay = Mock()
    assert web._wait_for_answer({'operation_id':'op','run_id':'run'}, {}, relay, 'job', 'resource', {'fencing_token':1}) is None
    web.observe.assert_not_called()
    relay.web_send.failure.assert_called_once()


def client_for(tmp_path, monkeypatch, events):
    client = ModelClient(CLIConfig(workspace=tmp_path, openai_api_key='none', model='sentra/chatgpt-web/gpt-6'))
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self):
            for event in events:
                if event == '[DONE]': yield b'data: [DONE]\n\n'
                else: yield ('data: ' + json.dumps(event) + '\n\n').encode()
    monkeypatch.setattr(client, '_provider_http', Mock(return_value=Response()))
    return client


def final(text):
    return {'type':'response.completed','response':{'status':'completed','output':[{'content':[{'type':'output_text','text':text}]}]}}


def test_large_stream_recovers_suffix_from_verified_final(tmp_path, monkeypatch):
    prefix, suffix = 'Olá 🌎\n' * 15000, 'Fim confirmado.'
    client = client_for(tmp_path, monkeypatch, [
        {'type':'response.output_text.delta','delta':prefix}, final(prefix+suffix)])
    assert ''.join(client._responses_stream([{'role':'user','content':'long'}], client.config.model)) == prefix+suffix
    assert client.last_delivery_state == 'completed'


@pytest.mark.parametrize('terminal', ['[DONE]', {'type':'response.incomplete'}, {'type':'response.cancelled'}])
def test_partial_never_becomes_success_from_close_marker(tmp_path, monkeypatch, terminal):
    client = client_for(tmp_path, monkeypatch, [{'type':'response.output_text.delta','delta':'parcial'}, terminal])
    output = []
    with pytest.raises(ProviderHTTPError):
        for part in client._responses_stream([{'role':'user','content':'long'}], client.config.model): output.append(part)
    assert output == ['parcial']
    assert client.last_delivery_state == 'uncertain'
    assert client._provider_http.call_count == 1


def test_terminal_does_not_wait_for_socket_or_repeat_output(tmp_path, monkeypatch):
    def events():
        yield final('Tudo confirmado')
        raise AssertionError('must not await EOF after verified completion')
    client = client_for(tmp_path, monkeypatch, events())
    assert ''.join(client._responses_stream([{'role':'user','content':'test'}], client.config.model)) == 'Tudo confirmado'


def test_large_unicode_fragment_and_next_round_keep_preview(tmp_path, monkeypatch):
    previews = ShellLivePreviews(tmp_path)
    turn = previews.begin(project_id='p', conversation_id='c', operation_id='o')
    for key,value in previews.environment(turn).items(): monkeypatch.setenv(key,value)
    writer = LivePreviewWriter()
    text = '🟦Olá!\n' * 15000
    writer.send(text)
    while turn['offset'] < turn['path'].stat().st_size: previews.update(turn)
    assert previews.view('p','c')['content'] == text
    writer.activity('provider_submitted')
    assert previews.view('p','c')['content'] == text
    writer.send('Próxima rodada')
    assert previews.view('p','c')['content'] == 'Próxima rodada'
    previews.close(turn)


def test_checkpoint_survives_reopen_but_never_enters_history_or_other_owner(tmp_path):
    store = ConversationStore(tmp_path, principal='alice')
    session = store.open(tmp_path)
    turn, _ = store.begin_turn(session, 'teste')
    text = 'RESPOSTA PRIVADA ' * 6000
    store.checkpoint_response(session, turn, text)
    reopened = ConversationStore(tmp_path, principal='alice')
    assert reopened.response_draft(session)['content'] == text
    assert all(message['role'] != 'assistant' for message in reopened.messages(session))
    assert b'RESPOSTA PRIVADA' not in store.path.read_bytes()
    with pytest.raises(PermissionError):
        ConversationStore(tmp_path, principal='bob').response_draft(session)
    reopened.finish_response(session, turn, text)
    reopened.end_turn(session, turn)
    assert reopened.response_draft(session) is None
    assert reopened.messages(session)[-1]['content'] == text


def test_desktop_starts_bundled_web_models_when_enabled(tmp_path, monkeypatch):
    from sentra_remote.desktop import SentraDesktop
    desktop = object.__new__(SentraDesktop)
    desktop.paths = SimpleNamespace(state_dir=tmp_path)
    desktop.runtime = SimpleNamespace(start_all=Mock())
    desktop.start_web_models = Mock()
    monkeypatch.setattr('sentra_remote.desktop.threading.Thread', Mock())
    desktop._autostart()
    desktop.start_web_models.assert_not_called()
    (tmp_path/'web-models-enabled').write_text('enabled')
    desktop._autostart()
    desktop.start_web_models.assert_called_once_with(hidden=True)


def test_installer_needs_web_catalog_and_turn_readiness():
    from sentra_remote.installer import _installation_ready
    status={'mcp':{'ok':True},'tunnel':{'ok':True},'web_models':{'payload_complete':True,'ready':True,'catalog_ready':False,'turn_ready':True}}
    verification={'core_ready':True,'chatgpt_onboarding':{'ready':True},'status':status,'web_models_required':True}
    assert not _installation_ready(verification)
    status['web_models']['catalog_ready']=True
    assert _installation_ready(verification)
