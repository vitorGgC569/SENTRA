"""Native final selection uses one snapshot and one linked completed turn."""
import os
import sys

import pytest

from sentra_canvas.shell_runtime import CanvasShellRuntime
from sentra_core.conversations import ConversationStore


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
    return store, ident, runtime


def test_older_turn_completing_does_not_certify_running_response(journal):
    store, ident, runtime = journal
    old, _ = store.begin_turn(ident, 'old')
    baseline = runtime._native_journal_baseline(ident)
    new, _ = store.begin_turn(ident, 'new')
    store.end_turn(ident, old)
    store.finish_response(ident, new, 'intermediate')
    assert store.status(ident)['state'] == 'completed'
    assert runtime._native_journal_final(ident, baseline) is None
    store.end_turn(ident, new)
    assert runtime._native_journal_final(ident, baseline)['content'] == 'intermediate'


def test_multiple_new_turns_or_unlinked_response_are_rejected(journal):
    store, ident, runtime = journal
    baseline = runtime._native_journal_baseline(ident)
    first, _ = store.begin_turn(ident, 'first')
    store.finish_response(ident, first, 'one')
    store.end_turn(ident, first)
    assert runtime._native_journal_final(ident, baseline)['content'] == 'one'
    store.append(ident, 'assistant', 'legacy', kind='assistant_response')
    assert runtime._native_journal_final(ident, baseline) is None
    second, _ = store.begin_turn(ident, 'second')
    store.finish_response(ident, second, 'two')
    store.end_turn(ident, second)
    assert runtime._native_journal_final(ident, baseline) is None


def test_running_prior_turn_and_directive_are_rejected(journal):
    store, ident, runtime = journal
    prior, _ = store.begin_turn(ident, 'prior')
    baseline = runtime._native_journal_baseline(ident)
    new, _ = store.begin_turn(ident, 'new')
    store.finish_response(ident, new, '[[CANVAS|dispatch]]')
    store.end_turn(ident, new)
    assert runtime._native_journal_final(ident, baseline) is None
    store.end_turn(ident, prior)
    assert runtime._native_journal_final(ident, baseline) is None
