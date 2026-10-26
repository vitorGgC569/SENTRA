"""Intermediate CLI rounds cannot become confirmed Canvas answers."""
import pytest

from sentra_canvas.shell_runtime import _native_final_candidate


@pytest.mark.parametrize('state,kind,content,tail', [
    ('limit_reached', 'assistant_response', '[[CANVAS|do-work]]', []),
    ('completed', 'assistant_response', '[[CANVAS|dispatch]]', [
        {'seq': 3, 'role': 'user', 'kind': 'tool_result', 'content': 'queued'}]),
    ('completed', 'assistant_response', '[[CANVAS|dispatch]]', []),
    ('completed', 'message', 'not a proven final', []),
    ('interrupted', 'assistant_response', 'partial answer', []),
])
def test_intermediate_or_unconfirmed_turn_is_not_publishable(state, kind, content, tail):
    messages = [{'seq': 2, 'role': 'assistant', 'kind': kind, 'content': content}, *tail]
    assert _native_final_candidate({'state': state, 'uncertain_calls': []}, messages, 1) is None


def test_completed_final_answer_requires_new_sequence_and_no_uncertain_calls():
    final = {'seq': 2, 'role': 'assistant', 'kind': 'assistant_response', 'content': 'Resultado final'}
    assert _native_final_candidate({'state': 'completed', 'uncertain_calls': []}, [final], 1) is final
    assert _native_final_candidate({'state': 'completed', 'uncertain_calls': []}, [final], 2) is None
    assert _native_final_candidate({'state': 'completed', 'uncertain_calls': ['pending']}, [final], 1) is None
