"""A missing read selector is 404; mutation uncertainty keeps its contract."""
from test_shell_dot_features import shell
from test_shell_conversation_get import setup
from test_sentra_runtime_canvas_center_http import request


def test_missing_conversation_read_is_explicit_without_disclosing_paths(shell):
    app, server, scope, call, conversation = setup(shell)
    status, result = request(server, '/api/shell/bridge', json_body={
        'action': 'conversation_get', **scope, 'conversation_id': 'missing-private-identity'})
    assert status == 404
    assert result == {'error': 'conversation unavailable in this scope'}


def test_file_error_during_mutation_is_not_reclassified_as_known_missing_read(shell, monkeypatch):
    app, server, scope, call, conversation = setup(shell)
    def interrupted(_payload):
        raise FileNotFoundError('private/path/not/for/client')
    monkeypatch.setattr(app, 'shell_bridge', interrupted)
    status, result = request(server, '/api/shell/bridge', json_body={
        'action': 'conversation_create', **scope, 'dot_id': conversation['dot_id'],
        'request_key': 'controlled-mutation-error-fixture'})
    assert status == 500
    assert result == {'error': 'FileNotFoundError: operation failed'}
