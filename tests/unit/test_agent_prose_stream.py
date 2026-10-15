"""Exercise the actual CLI stream, transcript and directive boundary."""
from unittest.mock import Mock

import pytest

from test_conversation_persistence import config
from sentra_cli.agent import SentraAgent


@pytest.mark.parametrize('fragments', [
    ['Wiki [[wiki]] e [[ação🦉]] repetido [[wiki]].'],
    ['Wiki [', '[C', 'an', 'vas]] e [', '[ação🦉]] literal ['],
    list('Wiki [[wiki]] e [[Canvas]] fim.'),
])
def test_literal_brackets_survive_fragmentation_without_directive_execution(tmp_path, fragments):
    agent = SentraAgent(config(tmp_path))
    agent.client.chat_stream = Mock(return_value=iter(fragments))
    agent._execute_directive = Mock(side_effect=AssertionError('literal prose executed'))
    output = ''.join(agent.step_stream('Show bracket prose'))
    assert output == ''.join(fragments)
    assert agent.store.messages(agent.session_id)[-1]['content'] == ''.join(fragments)
    assert agent.store.status(agent.session_id)['state'] == 'completed'
    agent._execute_directive.assert_not_called()


@pytest.mark.parametrize('failed', [False, True])
def test_unfinished_formal_arguments_never_leak_on_completion_or_provider_error(tmp_path, failed):
    agent = SentraAgent(config(tmp_path))
    fragments = ['Visible [[', 'CAN', 'VAS|private-tool-argument']
    agent.client.chat_stream = Mock(return_value=iter(fragments))
    agent._execute_directive = Mock(side_effect=AssertionError('unfinished directive executed'))
    if failed:
        agent.client.last_error = 'synthetic provider error'
        agent.client.last_delivery_state = 'uncertain'
    output = ''.join(agent.step_stream('Show partial prose'))
    assert 'private-tool-argument' not in output and '[[CANVAS' not in output
    assert output.rstrip() == 'Visible'
    assert agent.store.messages(agent.session_id)[-1]['content'] == ''.join(fragments)
    agent._execute_directive.assert_not_called()


def test_complete_directive_is_executed_once_after_prose_without_exposing_arguments(tmp_path):
    agent = SentraAgent(config(tmp_path))
    response = 'Before [[wiki]] [[CANVAS|private-tool-argument]] After'
    agent.client.chat_stream = Mock(side_effect=[iter(list(response)), iter(['Done.'])])
    agent._execute_directive = Mock(return_value='synthetic tool result')
    output = ''.join(agent.step_stream('Use a tool'))
    assert 'Before [[wiki]]' in output and 'After' in output and 'Done.' in output
    assert 'private-tool-argument' not in output
    agent._execute_directive.assert_called_once_with('CANVAS', 'private-tool-argument')
