"""Native final selection uses one snapshot and one linked completed turn."""
import os
import sys
from types import SimpleNamespace

import pytest

from sentra_canvas.shell_runtime import CanvasShellRuntime
from sentra_core.conversations import ConversationStore, _encode


@pytest.fixture(autouse=True)
def local_keyring(monkeypatch):
    if os.name != 'nt':
        from types import SimpleNamespace
        values = {}
        monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(
            set_password=lambda service, key, value: values.__setitem__((service, key), value),
            get_password=lambda service, key: values.get((service, key))))


@pytest.fixture
def journal(tmp_path):
    store = ConversationStore(tmp_path / 'state', principal='owner')
    ident = store.open(tmp_path)
    runtime = object.__new__(CanvasShellRuntime)
    runtime.conversations = store
    runtime.owner = 'canvas:owner'
    runtime.canvas = SimpleNamespace(store=SimpleNamespace(principal='owner'))
    return store, ident, runtime


def identity(store, ident):
    workspace = store.status(ident)['workspace']
    message = {'conversation_id':ident, 'project_id':'project', 'space_id':'space',
               'run_id':'run', 'work_item_id':'work', 'operation_id':'operation'}
    dot = {'agent_id':'agent'}
    scope = {**message, 'owner':'canvas:owner', 'principal':'owner', 'workspace':workspace,
             'agent_id':dot['agent_id']}
    return message, dot, workspace, scope


def test_older_turn_completing_does_not_certify_running_response(journal):
    store, ident, runtime = journal
    message, dot, workspace, scope = identity(store, ident)
    old, _ = store.begin_turn(ident, 'old')
    baseline = runtime._native_journal_baseline(ident)
    new, _ = store.begin_canvas_turn(ident, 'new', scope)
    store.end_turn(ident, old)
    store.finish_response(ident, new, 'intermediate')
    assert store.status(ident)['state'] == 'completed'
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None
    store.end_turn(ident, new)
    assert runtime._native_journal_final(message, dot, workspace, baseline)['content'] == 'intermediate'


def test_multiple_new_turns_or_unlinked_response_are_rejected(journal):
    store, ident, runtime = journal
    message, dot, workspace, scope = identity(store, ident)
    baseline = runtime._native_journal_baseline(ident)
    first, _ = store.begin_canvas_turn(ident, 'first', scope)
    store.finish_response(ident, first, 'one')
    store.end_turn(ident, first)
    assert runtime._native_journal_final(message, dot, workspace, baseline)['content'] == 'one'
    store.append(ident, 'assistant', 'legacy', kind='assistant_response')
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None
    second, _ = store.begin_turn(ident, 'second')
    store.finish_response(ident, second, 'two')
    store.end_turn(ident, second)
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None


def test_running_prior_turn_and_directive_are_rejected(journal):
    store, ident, runtime = journal
    message, dot, workspace, scope = identity(store, ident)
    prior, _ = store.begin_turn(ident, 'prior')
    baseline = runtime._native_journal_baseline(ident)
    new, _ = store.begin_canvas_turn(ident, 'new', scope)
    store.finish_response(ident, new, '[[CANVAS|dispatch]]')
    store.end_turn(ident, new)
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None
    store.end_turn(ident, prior)
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None


def test_binding_rejects_swapped_operation_turn_and_protected_scope(journal):
    store, ident, runtime = journal
    message, dot, workspace, scope = identity(store, ident)
    old, _ = store.begin_turn(ident, 'older')
    store.end_turn(ident, old)
    baseline = runtime._native_journal_baseline(ident)
    turn, _ = store.begin_canvas_turn(ident, 'prompt', scope)
    store.finish_response(ident, turn, 'answer')
    store.end_turn(ident, turn)
    assert runtime._native_journal_final(message, dot, workspace, baseline)['content'] == 'answer'
    assert runtime._native_journal_final({**message, 'operation_id':'other'}, dot, workspace, baseline) is None
    assert runtime._native_journal_final({**message, 'work_item_id':'other'}, dot, workspace, baseline) is None
    assert runtime._native_journal_final(message, {'agent_id':'other'}, workspace, baseline) is None
    with store._tx() as db:
        db.execute('UPDATE canvas_native_turn_bindings SET turn_id=? WHERE operation_id=?',
                   (old, message['operation_id']))
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None
    with store._tx() as db:
        db.execute('UPDATE canvas_native_turn_bindings SET turn_id=?,protected_scope=? WHERE operation_id=?',
                   (turn, _encode({**scope, 'space_id':'foreign'}), message['operation_id']))
    assert runtime._native_journal_final(message, dot, workspace, baseline) is None
